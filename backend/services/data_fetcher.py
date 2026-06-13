import asyncio
import logging
import urllib.request
import csv
import io
import re
import random
import datetime
import requests
import yfinance as yf
from typing import List, Dict, Any, Optional
from curl_cffi import requests as curl_requests

from backend.services.redis_pipeline import RedisPipeline
from backend.services.db_handler import query_db, upsert_db, delete_db, IS_DB_CONFIGURED
from backend.services.embeddings import generate_embedding
from backend.services.angel_data_gateway import AngelDataGateway

logger = logging.getLogger(__name__)


def fetch_nifty500_tickers() -> List[str]:
    """
    Fetches the official Nifty 500 constituents from the NSE archives.
    Returns yfinance-compatible ticker symbols (e.g. RELIANCE.NS).
    """
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode('utf-8')
        
        reader = csv.DictReader(io.StringIO(content))
        tickers = []
        for row in reader:
            symbol = row.get('Symbol')
            if symbol:
                tickers.append(symbol.strip() + ".NS")
        if tickers:
            logger.info("Successfully fetched %d tickers from NSE Nifty 500 list", len(tickers))
            return tickers
    except Exception as e:
        logger.error("Failed to fetch official Nifty 500 list: %s. Falling back to active benchmark list.", str(e))
    
    # Active institutional benchmark fallback list
    return [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS",
        "INFY.NS", "SBI.NS", "LICI.NS", "ITC.NS", "HINDUNILVR.NS", "TATAMOTORS.NS",
        "ONGC.NS", "ADANIENT.NS", "AXISBANK.NS", "LT.NS", "KOTAKBANK.NS",
        "BAJFINANCE.NS", "MARUTI.NS", "SUNPHARMA.NS", "NTPC.NS"
    ]

def fetch_nifty500_metadata() -> List[Dict[str, str]]:
    """
    Fetches official Nifty 500 constituents with names and industry details.
    """
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode('utf-8')
        
        reader = csv.DictReader(io.StringIO(content))
        metadata = []
        for row in reader:
            symbol = row.get('Symbol')
            company_name = row.get('Company Name')
            industry = row.get('Industry')
            if symbol and company_name:
                metadata.append({
                    "symbol": symbol.strip() + ".NS",
                    "name": company_name.strip(),
                    "industry": industry.strip() if industry else ""
                })
        if metadata:
            logger.info("Successfully fetched metadata for %d Nifty 500 constituents", len(metadata))
            return metadata
    except Exception as e:
        logger.error("Failed to fetch official Nifty 500 metadata: %s", str(e))
    
    # Fallback default metadata list
    fallbacks = [
        ("RELIANCE.NS", "Reliance Industries Ltd", "Oil Gas & Fuels"),
        ("TCS.NS", "Tata Consultancy Services Ltd", "IT Services"),
        ("HDFCBANK.NS", "HDFC Bank Ltd", "Financial Services"),
        ("BHARTIARTL.NS", "Bharti Airtel Ltd", "Telecommunication Services"),
        ("ICICIBANK.NS", "ICICI Bank Ltd", "Financial Services"),
        ("INFY.NS", "Infosys Ltd", "IT Services"),
        ("SBI.NS", "State Bank of India", "Financial Services"),
        ("ITC.NS", "ITC Ltd", "FMCG"),
        ("HINDUNILVR.NS", "Hindustan Unilever Ltd", "FMCG"),
        ("TATAMOTORS.NS", "Tata Motors Ltd", "Automobile")
    ]
    return [{"symbol": s, "name": n, "industry": i} for s, n, i in fallbacks]

class DataFetcher:
    """
    Data Ingestion Service responsible for pulling market data from APIs,
    parsing daily Bhavcopies, and synchronizing it to Supabase / Redis.
    """
    def __init__(self, redis_pipeline: RedisPipeline):
        self.redis_pipeline = redis_pipeline

    async def fetch_and_cache_ticker(self, ticker: str, period: str = "60d", interval: str = "1d", session: Optional[Any] = None) -> bool:
        """
        Fetch daily/hourly OHLCVA candles for a ticker. Checks local database (daily_bhavcopy)
        first for daily interval, and falls back to yfinance if data is missing or hourly interval is requested.
        """
        try:
            # 1. Try to load daily data from the local database
            if interval == "1d" and IS_DB_CONFIGURED:
                try:
                    logger.info("Checking database for historical candles of %s...", ticker)
                    rows = await query_db("daily_bhavcopy", {
                        "symbol": f"eq.{ticker}",
                        "order": "trade_date.asc"
                    })
                    if rows and len(rows) >= 150:
                        logger.info("Successfully loaded %d candles from database for %s. Caching in Redis.", len(rows), ticker)
                        candles = []
                        for row in rows:
                            close_price = float(row.get("close", 0.0))
                            volume = float(row.get("volume", 0.0))
                            trade_date_str = row.get("trade_date")
                            try:
                                dt = datetime.datetime.strptime(trade_date_str, "%Y-%m-%d")
                                timestamp = dt.isoformat()
                            except Exception:
                                timestamp = trade_date_str

                            candles.append({
                                "timestamp": timestamp,
                                "open": float(row.get("open", 0.0)),
                                "high": float(row.get("high", 0.0)),
                                "low": float(row.get("low", 0.0)),
                                "close": close_price,
                                "volume": volume,
                                "amount": close_price * volume
                            })
                        success = await self.redis_pipeline.store_ohlcva(ticker, interval, candles)
                        if success:
                            return True
                    else:
                        logger.info("Insufficient database history for %s (%d records). Falling back.", ticker, len(rows) if rows else 0)
                except Exception as db_err:
                    logger.warning("Failed to fetch historical candles from database for %s: %s", ticker, db_err)

            # 2. Try fetching from AngelDataGateway
            gateway = AngelDataGateway()
            if gateway.is_configured:
                try:
                    days_map = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825, "max": 1825}
                    days = days_map.get(period, 180)
                    from_dt = datetime.datetime.now() - datetime.timedelta(days=days)
                    from_date = from_dt.strftime("%Y-%m-%d 09:15")
                    to_date = datetime.datetime.now().strftime("%Y-%m-%d 15:30")
                    
                    logger.info("Fetching data for %s (period=%s, interval=%s) from AngelDataGateway...", ticker, period, interval)
                    candles = gateway.get_historical_data(ticker, interval=interval, from_date=from_date, to_date=to_date)
                    if candles:
                        success = await self.redis_pipeline.store_ohlcva(ticker, interval, candles)
                        if success:
                            logger.info("Successfully fetched and cached %d candles from AngelDataGateway for %s", len(candles), ticker)
                            return True
                except Exception as gateway_err:
                    logger.warning("AngelDataGateway fetch failed for %s: %s. Reverting to yfinance.", ticker, gateway_err)

            # 3. Fallback to yfinance
            max_retries = 3
            df = None
            for attempt in range(max_retries):
                try:
                    logger.info("Fetching data for %s (period=%s, interval=%s) from yfinance, attempt %d/%d...", 
                                ticker, period, interval, attempt + 1, max_retries)
                    ticker_obj = yf.Ticker(ticker, session=session)
                    loop = asyncio.get_event_loop()
                    df = await loop.run_in_executor(
                        None, 
                        lambda: ticker_obj.history(period=period, interval=interval)
                    )
                    break
                except Exception as e:
                    logger.warning("Attempt %d to fetch history for %s from yfinance failed. Error: %s", attempt + 1, ticker, str(e))
                    if attempt < max_retries - 1:
                        sleep_time = (5.0 * (attempt + 1)) + random.uniform(1.0, 3.0)
                        logger.info("Rate limit / connection error. Backing off for %.2f seconds...", sleep_time)
                        await asyncio.sleep(sleep_time)
                    else:
                        raise e

            if df is None or df.empty:
                logger.warning("No yfinance data returned for ticker %s", ticker)
                return False

            candles = []
            for idx, row in df.iterrows():
                if isinstance(idx, datetime.datetime):
                    timestamp = idx.isoformat()
                else:
                    timestamp = str(idx)

                close_price = float(row["Close"])
                volume = float(row["Volume"])
                amount = close_price * volume

                candles.append({
                    "timestamp": timestamp,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": close_price,
                    "volume": volume,
                    "amount": amount
                })

            success = await self.redis_pipeline.store_ohlcva(ticker, interval, candles)
            return success

        except Exception as e:
            logger.error("Error fetching/caching data for %s: %s", ticker, str(e), exc_info=True)
            return False

    async def sync_shortlist(self, tickers: List[str] = None, period: str = "60d", interval: str = "1d", session: Optional[Any] = None) -> Dict[str, bool]:
        """
        Synchronize multiple tickers concurrently to update the local Redis twin states.
        """
        if tickers is None:
            tickers = fetch_nifty500_tickers()
            
        tasks = [self.fetch_and_cache_ticker(ticker, period, interval, session=session) for ticker in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        sync_status = {}
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                logger.error("Sync task for %s failed with exception: %s", ticker, str(result))
                sync_status[ticker] = False
            else:
                sync_status[ticker] = bool(result)
                
        return sync_status

    async def download_and_parse_bhavcopy(self, trade_date: datetime.date) -> List[Dict[str, Any]]:
        """
        Downloads NSE's EOD Deliverable Positions Bhavcopy for a given date using curl_cffi,
        parses the CSV, and extracts pricing and deliverable volume metrics.
        """
        # Format: https://archives.nseindia.com/products/content/sec_bhavdata_full_ddmmyyyy.csv
        date_str = trade_date.strftime("%d%m%Y")
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Referer": "https://www.nseindia.com/"
        }
        
        try:
            logger.info("Downloading EOD Bhavcopy from NSE for date %s using curl_cffi...", trade_date.isoformat())
            loop = asyncio.get_event_loop()
            
            def fetch_url():
                session = curl_requests.Session(impersonate="chrome110")
                session.headers.update(headers)
                try:
                    session.get("https://www.nseindia.com/", timeout=10)
                except Exception as e:
                    logger.debug("NSE home session initialization failed: %s", e)
                
                resp = session.get(url, timeout=15)
                if resp.status_code != 200:
                    logger.warning("Bhavcopy request returned status code: %d", resp.status_code)
                    return None
                return resp.text

            content = await loop.run_in_executor(None, fetch_url)
            if not content:
                return []
            
            # Clean header spaces and parse CSV
            f = io.StringIO(content)
            # NSE files sometimes have leading/trailing whitespaces in headers
            raw_reader = csv.reader(f)
            headers_raw = next(raw_reader)
            headers_cleaned = [h.strip().upper() for h in headers_raw]
            
            rows = []
            for row in raw_reader:
                if not row or len(row) < len(headers_cleaned):
                    continue
                row_dict = {headers_cleaned[i]: row[i].strip() for i in range(len(headers_cleaned))}
                
                # Filter for EQ series (standard equity cash market)
                if row_dict.get("SERIES") != "EQ":
                    continue
                    
                symbol = row_dict.get("SYMBOL")
                if not symbol:
                    continue
                    
                try:
                    close_val = float(row_dict.get("CLOSE_PRICE", 0.0))
                    prev_close_val = float(row_dict.get("PREV_CLOSE", 0.0))
                    high_val = float(row_dict.get("HIGH_PRICE", 0.0))
                    low_val = float(row_dict.get("LOW_PRICE", 0.0))
                    vol_val = int(row_dict.get("TTL_TRD_QTY", 0))
                    deliv_val = int(row_dict.get("DELIV_QTY", 0))
                    
                    # Clean percentage and handle '-' values
                    deliv_per_str = row_dict.get("DELIV_PER", "0.0").replace("-", "0.0")
                    deliv_per = float(deliv_per_str)
                    
                    turnover_lacs = float(row_dict.get("TURNOVER_LACS", 0.0))
                    
                    # Calculations
                    turnover_cr = turnover_lacs / 100.0 # 1 Crore = 100 Lakhs
                    
                    # Circuit detection (Price band limit hit checks EOD proxy)
                    pct_change = (close_val - prev_close_val) / prev_close_val if prev_close_val > 0 else 0.0
                    is_upper = (close_val == high_val) and (pct_change >= 0.0195)
                    is_lower = (close_val == low_val) and (pct_change <= -0.0195)
                    is_circuit = is_upper or is_lower
                    
                    rows.append({
                        "symbol": symbol + ".NS",
                        "trade_date": trade_date.isoformat(),
                        "open": float(row_dict.get("OPEN_PRICE", 0.0)),
                        "high": high_val,
                        "low": low_val,
                        "close": close_val,
                        "prev_close": prev_close_val,
                        "volume": vol_val,
                        "delivery_volume": deliv_val,
                        "delivery_pct": deliv_per,
                        "turnover_cr": round(turnover_cr, 4),
                        "is_circuit_hit": is_circuit,
                        "is_upper_circuit": is_upper,
                        "is_lower_circuit": is_lower
                    })
                except Exception as parse_err:
                    logger.warning("Failed parsing Bhavcopy row for %s: %s", symbol, parse_err)
                    continue
                    
            logger.info("Successfully parsed %d equity rows from Bhavcopy.", len(rows))
            return rows
            
        except Exception as e:
            logger.warning("Bhavcopy not available or failed for date %s: %s", trade_date.isoformat(), e)
            return []

    async def ingest_latest_bhavcopy(self) -> Dict[str, Any]:
        """
        Crawls backward from today to find and ingest the latest available EOD Bhavcopy.
        Also registers new company symbols, lazy-loads descriptions/embeddings from yfinance.
        """
        if not IS_DB_CONFIGURED:
            logger.warning("Database not configured. Ingestion aborted.")
            return {"status": "error", "message": "Database not configured."}
            
        # 1. Scan backward to find latest available Bhavcopy
        target_date = datetime.date.today()
        bhav_rows = []
        for i in range(5): # Scan up to 5 days back (to bridge weekends/holidays)
            bhav_rows = await self.download_and_parse_bhavcopy(target_date)
            if bhav_rows:
                break
            target_date -= datetime.timedelta(days=1)
            
        if not bhav_rows:
            logger.error("Failed to find any active Bhavcopy in the last 5 days.")
            return {"status": "error", "message": "No Bhavcopy files available in archive."}
            
        logger.info("Ingesting Bhavcopy for date: %s", target_date.isoformat())
        
        # 2. Get existing companies to avoid duplicates
        existing = await query_db("companies", {"select": "symbol"})
        existing_symbols = {c["symbol"] for c in existing} if existing else set()
        
        # 3. Dynamic metadata resolution & Embedding generation
        nifty500_meta = fetch_nifty500_metadata()
        meta_map = {m["symbol"]: m for m in nifty500_meta}
        
        # We only ingest Nifty 500 constituents to keep Supabase footprint small
        nifty500_tickers = {m["symbol"] for m in nifty500_meta}
        
        companies_payload = []
        bhavcopy_payload = []
        
        # Clean session
        session = get_resilient_session = requests.Session()
        
        for row in bhav_rows:
            symbol = row["symbol"]
            if symbol not in nifty500_tickers:
                continue
                
            # A. Register new company metadata
            if symbol not in existing_symbols:
                meta = meta_map.get(symbol, {"name": symbol, "industry": "N/A"})
                
                # Fetch business summary from yfinance (lazy-load)
                description = ""
                try:
                    logger.info("Lazy-loading description for new ticker: %s", symbol)
                    t_info = yf.Ticker(symbol, session=session).info
                    description = t_info.get("longBusinessSummary", "")
                except Exception as yf_err:
                    logger.warning("Could not fetch yfinance description for %s: %s", symbol, yf_err)
                
                emb = generate_embedding(description) if description else [0.0] * 384
                
                companies_payload.append({
                    "symbol": symbol,
                    "name": meta["name"],
                    "sector": meta.get("industry", "N/A"), # map industry as sector/category
                    "industry": meta.get("industry", "N/A"),
                    "market_cap_cr": 0.0, # Will be filled, default zero
                    "description": description or "No description available.",
                    "description_embedding": emb
                })
                existing_symbols.add(symbol)
                
            bhavcopy_payload.append(row)
            
        # 4. Upsert companies
        if companies_payload:
            logger.info("Upserting %d new company metadata records into database...", len(companies_payload))
            await upsert_db("companies", companies_payload)
            
        # 5. Upsert Bhavcopy EOD prices/delivery
        if bhavcopy_payload:
            logger.info("Upserting %d Bhavcopy records into database...", len(bhavcopy_payload))
            await upsert_db("daily_bhavcopy", bhavcopy_payload)
            
        # 6. Apply Sliding Window Database Pruning (keep last 250 trading days)
        # We count historical dates and delete rows older than 250 days.
        try:
            # Fetch unique dates ordered descending
            db_dates = await query_db("daily_bhavcopy", {
                "select": "trade_date",
                "order": "trade_date.desc",
                "limit": 1000
            })
            unique_dates = sorted(list({d["trade_date"] for d in db_dates}), reverse=True)
            if len(unique_dates) > 250:
                cutoff_date = unique_dates[249]
                logger.info("Pruning daily_bhavcopy rows older than date: %s", cutoff_date)
                await delete_db("daily_bhavcopy", {"trade_date": f"lt.{cutoff_date}"})
        except Exception as prune_err:
            logger.warning("Failed to prune database: %s", prune_err)
            
        return {
            "status": "success",
            "date": target_date.isoformat(),
            "companies_added": len(companies_payload),
            "records_inserted": len(bhavcopy_payload)
        }


# ──────────────────────────────────────────────────────────────────────────────
# NSE Insider / Promoter Disclosure Crawler
# ──────────────────────────────────────────────────────────────────────────────

class InsiderDisclosureCrawler:
    """
    Crawls NSE's official Insider Trading Disclosure CSV archive.

    Source URL pattern:
      https://archives.nseindia.com/corporate/sasti/sasti_DDMMYYYY.csv

    The NSE filename uses the *disclosure date* (when the form was filed),
    not the *trade date*.  We scan backward from today to find the latest
    available file (up to 7 calendar days) and ingest all EQ-series rows.

    Duplicate protection: the `insider_disclosures` table has a UNIQUE constraint
    on (symbol, acquirer_name, trade_date, quantity, transaction_type) so
    repeated ingest runs are idempotent.
    """

    # Column name normalisation map (NSE CSV headers are inconsistent)
    _COL_ALIASES = {
        # NSE column → our canonical name
        "SYMBOL":               "symbol",
        "COMPANY":              "symbol",          # older file format
        "NAME_OF_PERSON":       "acquirer_name",
        "ACQUIRER_NAME":        "acquirer_name",
        "PERSON_NAME":          "acquirer_name",
        "CATEGORY":             "category_of_person",
        "CATEGORY_OF_PERSON":   "category_of_person",
        "TYPE":                 "transaction_type",
        "TRANSACTION_TYPE":     "transaction_type",
        "BUY_SELL":             "transaction_type",
        "NO_OF_SHARES":         "quantity",
        "QUANTITY":             "quantity",
        "VALUE":                "value_rs",
        "VALUE_OF_SHARES_RS":   "value_rs",
        "MODE":                 "mode_of_acquisition",
        "MODE_OF_ACQUISITION":  "mode_of_acquisition",
        "TRADE_DATE":           "trade_date",
        "DATE_OF_TRADE":        "trade_date",
        "INTIMATION_DATE":      "disclosure_date",
        "DISCLOSURE_DATE":      "disclosure_date",
        "DATE":                 "disclosure_date",
    }

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    def _build_url(self, date: datetime.date) -> str:
        """Returns the NSE SASTI archive URL for a given disclosure date."""
        date_str = date.strftime("%d%m%Y")
        return (
            f"https://archives.nseindia.com/corporate/sasti/sasti_{date_str}.csv"
        )

    def _normalise_headers(self, raw_headers: List[str]) -> List[str]:
        """Maps raw NSE CSV headers to canonical names."""
        return [
            self._COL_ALIASES.get(h.strip().upper().replace(" ", "_"), h.strip().lower())
            for h in raw_headers
        ]

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Attempts multiple date format parses; returns ISO string or None."""
        date_str = date_str.strip()
        for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.datetime.strptime(date_str, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def _parse_number(self, val: str) -> Optional[float]:
        """Cleans numeric strings with commas/spaces; returns float or None."""
        try:
            return float(re.sub(r"[^\d.\-]", "", val.strip()))
        except (ValueError, AttributeError):
            return None

    async def _download_csv(self, date: datetime.date) -> Optional[str]:
        """
        Downloads the NSE SASTI CSV for the given date.
        Returns raw CSV content string, or None if unavailable.
        """
        url = self._build_url(date)
        loop = asyncio.get_event_loop()
        try:
            content = await loop.run_in_executor(
                None,
                lambda: requests.get(url, headers=self._HEADERS, timeout=12).text
            )
            # NSE returns an HTML error page or tiny response when file is missing
            if len(content) < 200 or "<html" in content[:100].lower():
                return None
            return content
        except Exception as e:
            logger.debug("[InsiderCrawler] CSV not found for %s: %s", date.isoformat(), e)
            return None

    async def crawl_latest(self) -> Dict[str, Any]:
        """
        Scans backward from today (up to 7 days) to find the latest NSE
        SASTI insider disclosure CSV, parses it, and upserts rows to Supabase.

        Returns a summary dict with status and record counts.
        """
        if not IS_DB_CONFIGURED:
            return {"status": "error", "message": "Database not configured."}

        # Find latest available file
        target_date = datetime.date.today()
        content = None
        for _ in range(7):
            content = await self._download_csv(target_date)
            if content:
                break
            target_date -= datetime.timedelta(days=1)

        if not content:
            return {
                "status": "error",
                "message": "NSE SASTI CSV not available in last 7 days.",
            }

        logger.info(
            "[InsiderCrawler] Parsing NSE insider disclosures for %s...",
            target_date.isoformat()
        )

        # Parse CSV
        f = io.StringIO(content)
        raw_reader = csv.reader(f)
        try:
            raw_headers = next(raw_reader)
        except StopIteration:
            return {"status": "error", "message": "Empty CSV returned."}

        normalised_headers = self._normalise_headers(raw_headers)

        payload: List[Dict[str, Any]] = []

        for row in raw_reader:
            if not row or len(row) < 4:
                continue
            row_dict = {
                normalised_headers[i]: row[i].strip()
                for i in range(min(len(normalised_headers), len(row)))
            }

            # Extract and validate required fields
            raw_symbol = row_dict.get("symbol", "").strip().upper()
            if not raw_symbol:
                continue
            symbol = raw_symbol + ".NS" if not raw_symbol.endswith((".NS", ".BO")) else raw_symbol

            acquirer = row_dict.get("acquirer_name", "").strip()
            if not acquirer:
                continue

            tx_raw = row_dict.get("transaction_type", "").strip().upper()
            if "BUY" in tx_raw:
                tx_type = "Buy"
            elif "SELL" in tx_raw:
                tx_type = "Sell"
            else:
                # Skip ambiguous/unknown transaction types
                logger.debug("[InsiderCrawler] Skipping unknown tx_type '%s' for %s", tx_raw, symbol)
                continue

            qty_raw  = row_dict.get("quantity", "0")
            quantity = int(self._parse_number(qty_raw) or 0)
            if quantity <= 0:
                continue

            trade_date_iso = self._parse_date(row_dict.get("trade_date", ""))
            disc_date_iso  = self._parse_date(
                row_dict.get("disclosure_date", target_date.isoformat())
            )
            if not trade_date_iso:
                trade_date_iso = target_date.isoformat()
            if not disc_date_iso:
                disc_date_iso = target_date.isoformat()

            value_rs  = self._parse_number(row_dict.get("value_rs", ""))
            category  = row_dict.get("category_of_person", "").strip() or None
            mode      = row_dict.get("mode_of_acquisition", "").strip() or None

            payload.append({
                "symbol":              symbol,
                "acquirer_name":       acquirer,
                "category_of_person":  category,
                "transaction_type":    tx_type,
                "quantity":            quantity,
                "value_rs":            value_rs,
                "mode_of_acquisition": mode,
                "trade_date":          trade_date_iso,
                "disclosure_date":     disc_date_iso,
            })

        if not payload:
            return {
                "status": "success",
                "date": target_date.isoformat(),
                "records_inserted": 0,
                "message": "No valid insider disclosure rows found.",
            }

        # Upsert — conflict on UNIQUE constraint is silently ignored (merge-duplicates)
        logger.info(
            "[InsiderCrawler] Upserting %d insider disclosure records for %s...",
            len(payload), target_date.isoformat()
        )
        await upsert_db("insider_disclosures", payload)

        # Summary split by transaction type
        buys  = sum(1 for p in payload if p["transaction_type"] == "Buy")
        sells = sum(1 for p in payload if p["transaction_type"] == "Sell")

        return {
            "status":           "success",
            "date":             target_date.isoformat(),
            "records_inserted": len(payload),
            "promoter_buys":    buys,
            "promoter_sells":   sells,
        }
