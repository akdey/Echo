import os
import json
import logging
import time
import datetime
import pyotp
import requests
import threading
from typing import Dict, Any, Optional, List

try:
    from SmartApi import SmartConnect
    HAS_SMART_API = True
except ImportError:
    HAS_SMART_API = False
    logging.getLogger(__name__).warning("smartapi-python library is not installed or import failed.")

logger = logging.getLogger(__name__)

class AngelDataGateway:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AngelDataGateway, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.api_key = os.environ.get("ANGEL_API_KEY", "").strip()
        self.client_id = os.environ.get("ANGEL_CLIENT_ID", "").strip()
        self.pin = os.environ.get("ANGEL_PIN", "").strip()
        self.totp_secret = os.environ.get("ANGEL_TOTP_SECRET", "").strip()
        
        self.is_configured = bool(self.api_key and self.client_id and self.pin and self.totp_secret)
        self.smart_api = None
        self.jwt_token = None
        self.session_expiry = 0
        self.token_map = {}
        self.map_lock = threading.Lock()
        
        if not self.is_configured:
            logger.warning("[AngelData] Credentials not fully configured. Gateway will run in OFFLINE / FALLBACK mode.")
        else:
            logger.info("[AngelData] Gateway configured. Client ID: %s", self.client_id)
            
        self._initialized = True

    def _login(self) -> bool:
        if not self.is_configured:
            return False
        
        if self.smart_api and self.jwt_token and (time.time() < self.session_expiry):
            return True
            
        if not HAS_SMART_API:
            logger.error("[AngelData] Cannot log in: smartapi-python SDK is missing.")
            return False

        logger.info("[AngelData] Authenticating with SmartAPI...")
        try:
            totp = pyotp.TOTP(self.totp_secret)
            current_totp = totp.now()
            
            self.smart_api = SmartConnect(api_key=self.api_key)
            session_data = self.smart_api.generateSession(self.client_id, self.pin, current_totp)
            
            if session_data and session_data.get("status"):
                self.jwt_token = session_data["data"]["jwtToken"]
                self.session_expiry = time.time() + (18 * 3600)
                logger.info("[AngelData] Session generated successfully. JWT Token loaded.")
                return True
            else:
                msg = session_data.get("message", "Unknown error") if session_data else "No response"
                logger.error("[AngelData] Login failed: %s", msg)
                self.smart_api = None
                return False
        except Exception as e:
            logger.error("[AngelData] Login exception: %s", e, exc_info=True)
            self.smart_api = None
            return False

    def ensure_instruments_loaded(self) -> bool:
        with self.map_lock:
            if self.token_map:
                return True

            services_dir = os.path.dirname(os.path.abspath(__file__))
            backend_dir = os.path.dirname(services_dir)
            storage_dir = os.environ.get("PERSISTENT_STORAGE_DIR")
            if not storage_dir:
                storage_dir = os.path.join(backend_dir, "data_store")
            else:
                storage_dir = os.path.abspath(storage_dir)
                
            os.makedirs(storage_dir, exist_ok=True)
            cache_file = os.path.join(storage_dir, "angel_scrip_master.json")
            
            if os.path.exists(cache_file):
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < 24 * 3600:
                    try:
                        logger.info("[AngelData] Loading scrip master from local cache file: %s", cache_file)
                        with open(cache_file, "r") as f:
                            self.token_map = json.load(f)
                        if self.token_map:
                            return True
                    except Exception as fe:
                        logger.warning("[AngelData] Failed to read cached scrip master: %s. Re-downloading...", fe)

            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            logger.info("[AngelData] Downloading fresh instruments list from %s...", url)
            try:
                resp = requests.get(url, timeout=20)
                if resp.status_code == 200:
                    raw_list = resp.json()
                    temp_map = {}
                    for item in raw_list:
                        exch = item.get("exch_seg")
                        symbol = item.get("symbol", "")
                        # We only need standard NSE Cash Market equities and Nifty Indices
                        is_eq = (exch == "NSE" and (symbol.endswith("-EQ") or item.get("instrumenttype") == ""))
                        is_index = (exch == "NSE" and symbol in ("Nifty 50", "Nifty Midcap 150", "NIFTY", "CNXMDCP"))
                        if is_eq or is_index:
                            name = item.get("name", "").strip().upper()
                            token = item.get("token")
                            tick_size_str = item.get("tick_size", "5.000000")
                            try:
                                tick_size = float(tick_size_str) / 100.0
                            except Exception:
                                tick_size = 0.05
                                
                            payload = {
                                "token": token,
                                "tradingsymbol": symbol,
                                "exch_seg": exch,
                                "tick_size": tick_size
                            }
                            temp_map[name] = payload
                            temp_map[f"{name}.NS"] = payload
                            temp_map[symbol] = payload
                            
                    with open(cache_file, "w") as f:
                        json.dump(temp_map, f)
                    self.token_map = temp_map
                    logger.info("[AngelData] Loaded and cached %d symbols from ScripMaster.", len(self.token_map))
                    return True
                else:
                    logger.error("[AngelData] Scrip master fetch failed: %d", resp.status_code)
                    return False
            except Exception as e:
                logger.error("[AngelData] Exception fetching scrip master: %s", e)
                return False

    def lookup_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        self.ensure_instruments_loaded()
        clean = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
        
        info = self.token_map.get(clean) or self.token_map.get(symbol.strip().upper())
        if info:
            return info
            
        bare = clean.split("-")[0]
        info = self.token_map.get(bare)
        if info:
            return info
            
        return None

    def get_live_ltp(self, symbol: str, fallback_price: Optional[float] = None) -> float:
        """Fetches the live Last Traded Price (LTP) from Angel One."""
        if not self._login() or not self.smart_api:
            return fallback_price or 0.0
            
        info = self.lookup_symbol(symbol)
        if not info:
            logger.warning("[AngelData] Symbol not found in instrument list: %s", symbol)
            return fallback_price or 0.0
            
        try:
            resp = self.smart_api.ltpData(info["exch_seg"], info["tradingsymbol"], info["token"])
            if resp and resp.get("status"):
                return float(resp["data"]["ltp"])
            else:
                msg = resp.get("message", "Unknown error") if resp else "No response"
                logger.error("[AngelData] LTP query failed for %s: %s", symbol, msg)
                return fallback_price or 0.0
        except Exception as e:
            logger.error("[AngelData] LTP query exception for %s: %s", symbol, e)
            return fallback_price or 0.0

    def get_historical_data(
        self,
        symbol: str,
        interval: str = "ONE_DAY",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches historical daily candle data from Angel One SmartAPI.
        Format of returned items: [{"timestamp": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]
        """
        if not self._login() or not self.smart_api:
            logger.warning("[AngelData] Historical request failed: not authenticated.")
            return []

        info = self.lookup_symbol(symbol)
        if not info:
            logger.warning("[AngelData] Symbol not found for historical lookup: %s", symbol)
            return []

        # Map interval standard values
        interval_map = {
            "1d": "ONE_DAY",
            "ONE_DAY": "ONE_DAY",
            "1h": "ONE_HOUR",
            "ONE_HOUR": "ONE_HOUR",
            "15m": "FIFTEEN_MINUTE",
            "FIFTEEN_MINUTE": "FIFTEEN_MINUTE",
            "1m": "ONE_MINUTE",
            "ONE_MINUTE": "ONE_MINUTE"
        }
        mapped_interval = interval_map.get(interval, "ONE_DAY")

        # Set default date ranges if not provided
        if not from_date:
            # 180 days ago
            from_dt = datetime.datetime.now() - datetime.timedelta(days=180)
            from_date = from_dt.strftime("%Y-%m-%d 09:15")
        if not to_date:
            to_date = datetime.datetime.now().strftime("%Y-%m-%d 15:30")

        # Validate format (ensure HH:MM exists)
        if len(from_date) <= 10:
            from_date += " 09:15"
        if len(to_date) <= 10:
            to_date += " 15:30"

        params = {
            "exchange": info["exch_seg"],
            "symboltoken": info["token"],
            "interval": mapped_interval,
            "fromdate": from_date,
            "todate": to_date
        }

        try:
            logger.info("[AngelData] Fetching candles for %s: %s", symbol, params)
            resp = self.smart_api.getCandleData(params)
            
            candles = []
            if resp and resp.get("status") and isinstance(resp.get("data"), list):
                for row in resp["data"]:
                    # row is [timestamp, open, high, low, close, volume]
                    if len(row) >= 6:
                        try:
                            ts_str = row[0]
                            candles.append({
                                "timestamp": ts_str,
                                "open": float(row[1]),
                                "high": float(row[2]),
                                "low": float(row[3]),
                                "close": float(row[4]),
                                "volume": float(row[5]),
                                "amount": float(row[4]) * float(row[5])
                            })
                        except (TypeError, ValueError) as val_err:
                            logger.debug("[AngelData] Error parsing candle row %s: %s", row, val_err)
                logger.info("[AngelData] Successfully fetched %d candles for %s.", len(candles), symbol)
                return candles
            else:
                msg = resp.get("message", "Unknown error") if resp else "No response"
                logger.error("[AngelData] Historical candles API failed for %s: %s", symbol, msg)
                return []
        except Exception as e:
            logger.error("[AngelData] Exception fetching historical candles for %s: %s", symbol, e)
            return []
