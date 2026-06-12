import asyncio
import logging
import urllib.request
import csv
import io
from datetime import datetime
from typing import List, Dict, Any, Optional
import yfinance as yf

from backend.services.redis_pipeline import RedisPipeline

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

class DataFetcher:
    """
    Data Ingestion Service responsible for pulling market data from APIs
    and synchronizing it to the Redis caching layer.
    """
    def __init__(self, redis_pipeline: RedisPipeline):
        self.redis_pipeline = redis_pipeline

    async def fetch_and_cache_ticker(self, ticker: str, period: str = "60d", interval: str = "1d") -> bool:
        """
        Fetch daily/hourly OHLCVA candles for a ticker using yfinance, calculate amount,
        and cache the structured tensor in Redis.
        """
        try:
            logger.info("Fetching data for %s (period=%s, interval=%s)...", ticker, period, interval)
            # Run blocking yfinance fetch in a thread pool to avoid blocking the async event loop
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None, 
                lambda: yf.Ticker(ticker).history(period=period, interval=interval)
            )

            if df.empty:
                logger.warning("No data returned for ticker %s", ticker)
                return False

            candles = []
            for idx, row in df.iterrows():
                # Format timestamp as string
                if isinstance(idx, datetime):
                    timestamp = idx.isoformat()
                else:
                    timestamp = str(idx)

                # Calculate Amount (Close * Volume) as a fallback/standard metric
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

            # Save to Redis
            success = await self.redis_pipeline.store_ohlcva(ticker, interval, candles)
            return success

        except Exception as e:
            logger.error("Error fetching/caching data for %s: %s", ticker, str(e), exc_info=True)
            return False

    async def sync_shortlist(self, tickers: List[str] = None, period: str = "60d", interval: str = "1d") -> Dict[str, bool]:
        """
        Synchronize multiple tickers concurrently to update the local Redis twin states.
        """
        if tickers is None:
            tickers = fetch_nifty500_tickers()
            
        tasks = [self.fetch_and_cache_ticker(ticker, period, interval) for ticker in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        sync_status = {}
        for ticker, result in zip(tickers, results):
            if isinstance(result, Exception):
                logger.error("Sync task for %s failed with exception: %s", ticker, str(result))
                sync_status[ticker] = False
            else:
                sync_status[ticker] = bool(result)
                
        return sync_status
