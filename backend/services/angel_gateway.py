import os
import json
import logging
import time
import requests
import pyotp
import threading
from typing import Dict, Any, Optional

try:
    from SmartApi import SmartConnect
    HAS_SMART_API = True
except ImportError:
    HAS_SMART_API = False
    logging.getLogger(__name__).warning("smartapi-python library is not installed or import failed.")

logger = logging.getLogger(__name__)

class AngelOneGateway:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AngelOneGateway, cls).__new__(cls)
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
        self.feed_token = None
        self.jwt_token = None
        self.session_expiry = 0
        self.token_map = {}  # Maps symbol string -> token info payload dict
        self.map_lock = threading.Lock()
        
        if not self.is_configured:
            logger.warning("[AngelOne] Credentials not fully configured. Gateway will run in OFFLINE / SIMULATION fallback mode.")
        else:
            logger.info("[AngelOne] Gateway configured. Client ID: %s", self.client_id)
            
        self._initialized = True

    def _login(self) -> bool:
        if not self.is_configured:
            return False
        
        # Check if session is still valid (sessions usually last 24h, we renew if older than 18h)
        if self.smart_api and self.jwt_token and (time.time() < self.session_expiry):
            return True
            
        if not HAS_SMART_API:
            logger.error("[AngelOne] Cannot log in: smartapi-python SDK is missing.")
            return False

        logger.info("[AngelOne] Authenticating with SmartAPI...")
        try:
            # Generate TOTP
            totp = pyotp.TOTP(self.totp_secret)
            current_totp = totp.now()
            
            # Initialize SmartConnect
            self.smart_api = SmartConnect(api_key=self.api_key)
            session_data = self.smart_api.generateSession(self.client_id, self.pin, current_totp)
            
            if session_data and session_data.get("status"):
                self.jwt_token = session_data["data"]["jwtToken"]
                self.feed_token = session_data["data"].get("feedToken")
                # Set expiry to 18 hours from now
                self.session_expiry = time.time() + (18 * 3600)
                logger.info("[AngelOne] Session generated successfully. JWT Token loaded.")
                return True
            else:
                msg = session_data.get("message", "Unknown error") if session_data else "No response payload"
                logger.error("[AngelOne] Login failed: %s", msg)
                self.smart_api = None
                return False
        except Exception as e:
            logger.error("[AngelOne] Login exception: %s", e, exc_info=True)
            self.smart_api = None
            return False

    def ensure_instruments_loaded(self) -> bool:
        """Loads and parses the Angel One instrument scrip master list, caching it on disk."""
        with self.map_lock:
            if self.token_map:
                return True

            # Define path to local JSON cache in data store
            services_dir = os.path.dirname(os.path.abspath(__file__))
            backend_dir = os.path.dirname(services_dir)
            storage_dir = os.environ.get("PERSISTENT_STORAGE_DIR")
            if not storage_dir:
                storage_dir = os.path.join(backend_dir, "data_store")
            else:
                storage_dir = os.path.abspath(storage_dir)
                
            os.makedirs(storage_dir, exist_ok=True)
            cache_file = os.path.join(storage_dir, "angel_scrip_master.json")
            
            # Load from disk if it exists and is less than 24 hours old
            if os.path.exists(cache_file):
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < 24 * 3600:
                    try:
                        logger.info("[AngelOne] Loading scrip master from local cache file: %s", cache_file)
                        with open(cache_file, "r") as f:
                            self.token_map = json.load(f)
                        if self.token_map:
                            return True
                    except Exception as fe:
                        logger.warning("[AngelOne] Failed to read cached scrip master: %s. Re-downloading...", fe)

            # Download fresh scrip master from margincalculator
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            logger.info("[AngelOne] Downloading fresh instruments list from %s...", url)
            try:
                resp = requests.get(url, timeout=20)
                if resp.status_code == 200:
                    raw_list = resp.json()
                    temp_map = {}
                    # We parse and only map NSE EQ instruments to keep memory foot-print tiny
                    for item in raw_list:
                        exch = item.get("exch_seg")
                        symbol = item.get("symbol", "")
                        # We only need standard NSE Cash Market equities (symbol ending with -EQ or normal equity)
                        if exch == "NSE" and (symbol.endswith("-EQ") or item.get("instrumenttype") == ""):
                            # Map clean name (e.g. RELIANCE) and standard suffix name (e.g. RELIANCE.NS)
                            name = item.get("name", "").strip().upper()
                            token = item.get("token")
                            tick_size_str = item.get("tick_size", "5.000000")
                            try:
                                tick_size = float(tick_size_str) / 100.0  # Convert to rupees e.g. 5.0 -> 0.05
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
                            
                    # Save to cache file
                    with open(cache_file, "w") as f:
                        json.dump(temp_map, f)
                    self.token_map = temp_map
                    logger.info("[AngelOne] Loaded and cached %d symbols from ScripMaster.", len(self.token_map))
                    return True
                else:
                    logger.error("[AngelOne] Scrip master fetch failed with HTTP status: %d", resp.status_code)
                    return False
            except Exception as e:
                logger.error("[AngelOne] Exception fetching scrip master: %s", e)
                return False

    def lookup_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Maps any symbol (e.g. RELIANCE, RELIANCE.NS, RELIANCE-EQ) to the token info payload."""
        self.ensure_instruments_loaded()
        clean = symbol.replace(".NS", "").replace(".BO", "").strip().upper()
        
        # Try direct lookups
        info = self.token_map.get(clean) or self.token_map.get(symbol.strip().upper())
        if info:
            return info
            
        # Try finding as starts-with or matching name
        # Remove suffixes like -EQ
        bare = clean.split("-")[0]
        info = self.token_map.get(bare)
        if info:
            return info
            
        return None

    def get_ltp(self, symbol: str, fallback_price: Optional[float] = None) -> float:
        """Fetches the live Last Traded Price (LTP) from Angel One."""
        if not self._login() or not self.smart_api:
            # Fallback if offline / failed login
            return fallback_price or 0.0
            
        info = self.lookup_symbol(symbol)
        if not info:
            logger.warning("[AngelOne] Symbol not found in instrument list: %s", symbol)
            return fallback_price or 0.0
            
        try:
            logger.info("[AngelOne] Querying LTP for %s (%s, token: %s)...", symbol, info["tradingsymbol"], info["token"])
            resp = self.smart_api.ltpData(info["exch_seg"], info["tradingsymbol"], info["token"])
            
            if resp and resp.get("status"):
                ltp = float(resp["data"]["ltp"])
                logger.info("[AngelOne] Live LTP for %s is ₹%.2f", symbol, ltp)
                return ltp
            else:
                msg = resp.get("message", "Unknown error") if resp else "No response"
                logger.error("[AngelOne] LTP query failed for %s: %s", symbol, msg)
                return fallback_price or 0.0
        except Exception as e:
            logger.error("[AngelOne] LTP query exception for %s: %s", symbol, e)
            return fallback_price or 0.0
