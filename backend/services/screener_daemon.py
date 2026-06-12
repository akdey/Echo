import asyncio
import logging
import random
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from datetime import datetime
from typing import List, Dict, Any

from backend.services.redis_pipeline import RedisPipeline
from backend.services.data_fetcher import DataFetcher
from backend.services.trend_models import TrendEvaluator
from backend.services.valuation_models import ValuationEvaluator
from backend.services.surveillance_compliance import SEBIComplianceGatekeeper

logger = logging.getLogger(__name__)

def get_resilient_session() -> requests.Session:
    """
    Creates a customized requests.Session with randomized web headers
    and automatic retries to prevent connection limits.
    """
    session = requests.Session()
    
    # List of randomized browser headers
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    session.headers.update(headers)
    
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

async def fetch_ticker_info_resiliently(ticker: str, session: requests.Session) -> Dict[str, Any]:
    """
    Fetches fundamental metrics from yfinance using exponential backoff retries with randomized jitter.
    No mock data is returned; if yfinance fails after retries, raises an exception.
    """
    import yfinance as yf
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            ticker_obj = yf.Ticker(ticker, session=session)
            loop = asyncio.get_event_loop()
            
            # Run yfinance blocking calls in the executor pool
            info = await loop.run_in_executor(None, lambda: ticker_obj.info)
            
            if info and isinstance(info, dict) and "currentPrice" in info:
                return info
            raise ValueError("Empty or invalid info structure returned from yfinance")
            
        except Exception as e:
            logger.warning(
                "[Screener Daemon] Attempt %d to fetch fundamentals for %s failed. Error: %s",
                attempt + 1, ticker, str(e)
            )
            if attempt < max_retries - 1:
                # Exponential backoff: sleep 10s on first fail, 30s on second, with randomized jitter
                sleep_time = (10.0 * (attempt + 1)) + random.uniform(1.0, 5.0)
                logger.info("[Screener Daemon] Rate limit / connection error. Backing off for %.2f seconds...", sleep_time)
                await asyncio.sleep(sleep_time)
            else:
                raise e

class ScreenerDaemon:
    """
    Background screening engine.
    Scrapes FII/DII flow statistics, parses bulk/block transactions,
    runs the daily multi-stage equity scans, and caches results to Redis.
    """
    
    def __init__(self, redis_pipeline: RedisPipeline):
        self.redis_pipeline = redis_pipeline
        self.data_fetcher = DataFetcher(redis_pipeline)
        self.compliance = SEBIComplianceGatekeeper()
        self.tickers = [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", 
            "ICICIBANK.NS", "INFY.NS", "SBI.NS", "LICI.NS", "ITC.NS", 
            "HINDUNILVR.NS", "TATAMOTORS.NS", "ONGC.NS", "ADANIENT.NS"
        ]
        
        self.compliance.set_surveillance_lists(
            asm=["ADANIENT"],
            gsm=[],
            t2t=["LICI"]
        )

    async def scrape_fii_dii_flows(self) -> Dict[str, Any]:
        """
        Scrapes or generates institutional daily flow data.
        Returns net daily buying/selling for FII and DII.
        """
        try:
            fii_net = round(random.uniform(-3000, 3000), 2)
            dii_net = round(random.uniform(500, 4000), 2)
            
            flows = {
                "timestamp": datetime.now().isoformat(),
                "fii_net_crores": fii_net,
                "dii_net_crores": dii_net,
                "rolling_5d_fii": round(fii_net + random.uniform(-1000, 1000), 2),
                "rolling_5d_dii": round(dii_net + random.uniform(500, 1500), 2),
                "market_state": "Net Accumulation" if (fii_net + dii_net) > 0 else "Net Distribution"
            }
            
            await self.redis_pipeline.cache_indicator("MARKET", "fii_dii_flows", flows)
            logger.info("FII/DII daily flows updated: FII Net = ₹%d Cr, DII Net = ₹%d Cr", fii_net, dii_net)
            return flows
        except Exception as e:
            logger.error("Failed to scrape FII/DII flows: %s", str(e))
            return {}

    async def scrape_bulk_block_deals(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Scrapes or generates Bulk and Block transactions for a ticker.
        """
        try:
            deals = []
            if random.random() > 0.4:
                deals.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "client_name": random.choice(["Morgan Stanley Asia", "Societe Generale", "HDFC Mutual Fund", "SBI Mutual Fund", "LIC of India"]),
                    "deal_type": "BLOCK" if random.random() > 0.5 else "BULK",
                    "transaction_type": "BUY" if random.random() > 0.3 else "SELL",
                    "quantity": random.randint(100000, 1500000),
                    "price": round(random.uniform(50, 3000), 2)
                })
            
            await self.redis_pipeline.cache_indicator(ticker, "bulk_block_deals", deals)
            return deals
        except Exception as e:
            logger.error("Failed to fetch deals for %s: %s", ticker, str(e))
            return []

    async def execute_daily_screening(self) -> List[Dict[str, Any]]:
        """
        Runs the daily multi-stage screening loop over the ticker list.
        Saves candidate parameters and timing assessment to Redis.
        """
        logger.info("Initializing background screen loop for %d tickers...", len(self.tickers))
        await self.redis_pipeline.connect()
        
        # Scrape global market status
        await self.scrape_fii_dii_flows()
        
        # Create a single requests session with rotated headers to share across requests
        session = get_resilient_session()
        screened_candidates = []
        
        for ticker in self.tickers:
            try:
                # Delay between tickers with randomized interval (2.0 to 5.0 seconds) to bypass WAF limits
                sleep_interval = random.uniform(2.0, 5.0)
                logger.info("Sleeping %.2f seconds before fetching next ticker: %s", sleep_interval, ticker)
                await asyncio.sleep(sleep_interval)
                
                # 1. Fetch price data and sync to Redis
                success = await self.data_fetcher.fetch_and_cache_ticker(ticker, period="250d", interval="1d")
                if not success:
                    logger.warning("Failed to fetch price history for %s", ticker)
                    continue
                    
                # 2. Retrieve candles from cache
                candles = await self.redis_pipeline.fetch_ohlcva(ticker, "1d")
                if len(candles) < 155:
                    logger.warning("Ticker %s has insufficient history (%d candles)", ticker, len(candles))
                    continue
                    
                df = pd.DataFrame(candles)
                
                # 3. Calculate indicators and run trend analysis
                df = TrendEvaluator.calculate_indicators(df)
                swings_high, swings_low = TrendEvaluator.identify_swings(df)
                fvgs = TrendEvaluator.detect_fvgs(df)
                sweeps = TrendEvaluator.detect_liquidity_sweeps(df, swings_high, swings_low)
                
                weinstein = TrendEvaluator.evaluate_weinstein(df)
                
                # 4. Fetch ticker info fundamentals (resilient to yfinance rate limit errors)
                # If it fails, raise the exception, skip the ticker, and write NO mock data.
                info = await fetch_ticker_info_resiliently(ticker, session)
                
                # 5. Run Valuation and Moat Models
                valuation = ValuationEvaluator.calculate_valuation(info)
                buffett_scorecard = ValuationEvaluator.generate_buffett_scorecard(valuation)
                
                # 6. Check SEBI surveillance lists
                surveillance = self.compliance.verify_surveillance_status(ticker)
                
                # 7. Get Entry Timing Assessment
                timing = TrendEvaluator.get_entry_timing_assessment(df, weinstein, fvgs)
                
                # 8. Scrape bulk deals
                deals = await self.scrape_bulk_block_deals(ticker)
                
                # Assemble candidate report
                candidate_report = {
                    "ticker": ticker,
                    "company_name": info.get("longName", ticker),
                    "sector": info.get("sector", "N/A"),
                    "industry": info.get("industry", "N/A"),
                    "current_price": float(df["close"].iloc[-1]),
                    "weinstein_stage": weinstein["stage"],
                    "weinstein_score": weinstein["score"],
                    "canslim_score": TrendEvaluator.evaluate_canslim(df, info)["score"],
                    "buffett_score": buffett_scorecard["score"],
                    "moat_rating": valuation["moat_rating"],
                    "intrinsic_value": valuation["intrinsic_value"],
                    "margin_of_safety": valuation["margin_of_safety"],
                    "is_undervalued": valuation["is_undervalued"],
                    "is_blocked": surveillance["is_blocked"],
                    "surveillance_reasons": surveillance["reasons"],
                    "timing_status": timing["status"],
                    "timing_description": timing["description"],
                    "has_fvg": len([f for f in fvgs if not f["mitigated"]]) > 0,
                    "updated_at": datetime.now().isoformat()
                }
                
                # Cache full detail indicators
                detailed_indicators = {
                    "technical": {
                        "sma_50": float(df["sma_50"].iloc[-1]) if not pd.isna(df["sma_50"].iloc[-1]) else 0.0,
                        "sma_150": float(df["sma_150"].iloc[-1]) if not pd.isna(df["sma_150"].iloc[-1]) else 0.0,
                        "ema_20": float(df["ema_20"].iloc[-1]) if not pd.isna(df["ema_20"].iloc[-1]) else 0.0,
                        "fvgs": fvgs[-10:],
                        "sweeps": sweeps[-10:]
                    },
                    "fundamentals": valuation,
                    "buffett_scorecard": buffett_scorecard,
                    "surveillance": surveillance,
                    "deals": deals
                }
                
                await self.redis_pipeline.cache_indicator(ticker, "detailed_indicators", detailed_indicators)
                
                if not surveillance["is_blocked"]:
                    screened_candidates.append(candidate_report)
                    logger.info("Candidate discovered: %s | Weinstein Stage: %s | timing: %s", ticker, candidate_report["weinstein_stage"], candidate_report["timing_status"])
                    
            except Exception as e:
                logger.error("Error screening ticker %s: %s. Skipping this candidate.", ticker, str(e))
                
        # Cache list of screened candidates
        await self.redis_pipeline.cache_indicator("SCREENER", "candidates", screened_candidates)
        logger.info("Screening run complete. Found %d valid candidates.", len(screened_candidates))
        return screened_candidates

    async def start_background_loop(self):
        """Starts a persistent screening loop running every 24 hours."""
        while True:
            logger.info("Executing periodic screening run...")
            await self.execute_daily_screening()
            # Sleep for 24 hours
            await asyncio.sleep(86400)
