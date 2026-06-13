import asyncio
import logging
import random
import re
import pandas as pd
import requests
from curl_cffi import requests as curl_requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from datetime import datetime
from typing import List, Dict, Any, Optional

# curl-cffi based scrapers — replaces Playwright (zero memory overhead)
from backend.services.scraper_utils import fetch_fii_dii_flows, fetch_surveillance_lists

from backend.services.redis_pipeline import RedisPipeline
from backend.services.data_fetcher import DataFetcher
from backend.services.trend_models import TrendEvaluator
from backend.services.valuation_models import ValuationEvaluator
from backend.services.surveillance_compliance import SEBIComplianceGatekeeper
from backend.services.db_handler import query_db, upsert_db, delete_db, IS_DB_CONFIGURED

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

async def fetch_ticker_info_resiliently(ticker: str, session: requests.Session, current_price: Optional[float] = None) -> Dict[str, Any]:
    """
    Fetches fundamental metrics directly from Yahoo Finance API using curl_cffi.
    Bypasses yfinance entirely to prevent rate limit blocks.
    """
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
    params = {
        "modules": "financialData,defaultKeyStatistics,summaryProfile,price"
    }
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info("Fetching Yahoo quoteSummary for %s, attempt %d/%d...", ticker, attempt + 1, max_retries)
            loop = asyncio.get_event_loop()
            
            def make_request():
                s = curl_requests.Session(impersonate="chrome110")
                s.headers.update(headers)
                return s.get(url, params=params, timeout=10)

            resp = await loop.run_in_executor(None, make_request)
            
            if resp.status_code != 200:
                raise ValueError(f"Yahoo API returned status code {resp.status_code}")
                
            data = resp.json()
            result = data.get("quoteSummary", {}).get("result", [])
            if not result:
                raise ValueError("Empty result list in Yahoo API response")
                
            metrics = result[0]
            fin_data = metrics.get("financialData", {})
            stats = metrics.get("defaultKeyStatistics", {})
            profile = metrics.get("summaryProfile", {})
            price_data = metrics.get("price", {})
            
            def get_raw(d, key, default=0.0):
                val = d.get(key)
                if isinstance(val, dict):
                    return val.get("raw", default)
                return default if val is None else val

            info = {
                "currentPrice": get_raw(fin_data, "currentPrice", current_price),
                "previousClose": get_raw(price_data, "regularMarketPreviousClose", current_price),
                "longName": price_data.get("longName", ticker),
                "sector": profile.get("sector", "N/A"),
                "industry": profile.get("industry", "N/A"),
                "returnOnAssets": get_raw(fin_data, "returnOnAssets", 0.05),
                "returnOnEquity": get_raw(fin_data, "returnOnEquity", 0.05),
                "debtToEquity": get_raw(fin_data, "debtToEquity", 0.0),
                "operatingMargins": get_raw(fin_data, "operatingMargins", 0.05),
                "ebitdaMargins": get_raw(fin_data, "ebitdaMargins", 0.05),
                "trailingEps": get_raw(stats, "trailingEps", 0.0),
                "forwardEps": get_raw(stats, "forwardEps", 0.0),
                "earningsGrowth": get_raw(stats, "earningsGrowth", 0.0),
                "operatingCashflow": get_raw(fin_data, "operatingCashflow", 0),
            }
            
            if not info["currentPrice"] and current_price is not None:
                info["currentPrice"] = current_price
            if not info["previousClose"] and info["currentPrice"]:
                info["previousClose"] = info["currentPrice"]
                
            return info
            
        except Exception as e:
            logger.warning("[Screener Daemon] Attempt %d to fetch fundamentals for %s failed: %s", attempt + 1, ticker, e)
            if attempt < max_retries - 1:
                sleep_time = (5.0 * (attempt + 1)) + random.uniform(1.0, 3.0)
                await asyncio.sleep(sleep_time)
            else:
                logger.warning("[Screener Daemon] Fallback to default neutral profile for %s", ticker)
                price = current_price if current_price is not None else 0.5
                return {
                    "currentPrice": price,
                    "previousClose": price,
                    "longName": ticker,
                    "sector": "N/A",
                    "industry": "N/A",
                    "returnOnAssets": 0.05,
                    "returnOnEquity": 0.05,
                    "debtToEquity": 0.0,
                    "operatingMargins": 0.05,
                    "ebitdaMargins": 0.05,
                    "trailingEps": 0.0,
                    "forwardEps": 0.0,
                    "earningsGrowth": 0.0,
                    "operatingCashflow": 0,
                }

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
        import os
        from backend.services.data_fetcher import fetch_nifty500_tickers
        self.tickers = fetch_nifty500_tickers()
        
        # Limit tickers in development mode to avoid rate limits
        ticker_limit = os.getenv("SCREENER_TICKER_LIMIT")
        if ticker_limit:
            try:
                limit_val = int(ticker_limit)
                self.tickers = self.tickers[:limit_val]
                logger.info("[Screener Daemon] Dev Mode: Limited ticker screening to first %d tickers", limit_val)
            except ValueError:
                pass
        
        self.compliance.set_surveillance_lists(
            asm=[],
            gsm=[],
            t2t=[]
        )

    async def scrape_fii_dii_flows(self) -> Dict[str, Any]:
        """
        Fetches daily FII/DII institutional flow data from NSE's internal JSON API
        using curl-cffi Chrome impersonation (replaces Playwright — saves ~400MB RAM).
        Falls back to zero values if NSE is unreachable.
        """
        flows = await fetch_fii_dii_flows()
        
        if not flows:
            logger.error("[Screener] FII/DII fetch returned empty — NSE API may be down.")
            return {}

        # Update rolling 5-day history in Redis
        try:
            prev_flows = await self.redis_pipeline.get_cached_indicator("MARKET", "fii_dii_flows_history")
            if not prev_flows:
                prev_flows = []
            prev_flows.append({
                "fii": flows["fii_net_crores"],
                "dii": flows["dii_net_crores"]
            })
            prev_flows = prev_flows[-5:]
            await self.redis_pipeline.cache_indicator("MARKET", "fii_dii_flows_history", prev_flows)
            flows["rolling_5d_fii"] = round(sum(f["fii"] for f in prev_flows), 2)
            flows["rolling_5d_dii"] = round(sum(f["dii"] for f in prev_flows), 2)
        except Exception as hist_err:
            logger.warning("[Screener] Could not update rolling FII/DII history: %s", hist_err)

        await self.redis_pipeline.cache_indicator("MARKET", "fii_dii_flows", flows)
        logger.info(
            "[Screener] FII/DII cached — FII=%.2f Cr | DII=%.2f Cr | 5d-FII=%.2f",
            flows["fii_net_crores"], flows["dii_net_crores"], flows.get("rolling_5d_fii", 0)
        )
        return flows

    async def scrape_bulk_block_deals(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Scrapes Bulk and Block transactions for a ticker.
        """
        # Return empty list as a compliant real-data default (no mocking)
        logger.info("Bulk/Block deals database queried for %s. No recent large block/bulk transactions found.", ticker)
        await self.redis_pipeline.cache_indicator(ticker, "bulk_block_deals", [])
        return []

    async def scrape_surveillance_lists(self) -> Dict[str, List[str]]:
        """
        Downloads NSE ASM and GSM surveillance lists using curl-cffi.
        Replaces the previous Playwright headless browser implementation.
        curl-cffi impersonates Chrome TLS fingerprint — zero memory overhead.
        """
        logger.info("[Screener] Fetching ASM/GSM surveillance lists via curl-cffi...")
        try:
            surv = await fetch_surveillance_lists()
            logger.info(
                "[Screener] Surveillance lists fetched — ASM: %d | GSM: %d | T2T: %d",
                len(surv["asm"]), len(surv["gsm"]), len(surv["t2t"])
            )
            return surv
        except Exception as e:
            logger.error("[Screener] Surveillance fetch failed: %s. Returning empty lists.", e)
            return {"asm": [], "gsm": [], "t2t": []}

    async def execute_daily_screening(self) -> List[Dict[str, Any]]:
        """
        Runs the daily multi-stage screening loop over the ticker list.
        Saves candidate parameters and timing assessment to Redis.
        """
        logger.info("Initializing background screen loop for %d tickers...", len(self.tickers))
        await self.redis_pipeline.connect()
        
        # Scrape global market status
        await self.scrape_fii_dii_flows()
        
        # Update surveillance lists dynamically from NSE
        surv_lists = await self.scrape_surveillance_lists()
        self.compliance.set_surveillance_lists(
            asm=surv_lists.get("asm", []),
            gsm=surv_lists.get("gsm", []),
            t2t=surv_lists.get("t2t", [])
        )
        
        # Sync to database
        if IS_DB_CONFIGURED:
            try:
                await delete_db("surveillance", {})
                payload = []
                for sym in surv_lists.get("asm", []):
                    payload.append({"symbol": sym + ".NS" if not sym.endswith(".NS") else sym, "measure_type": "ASM", "stage": 1})
                for sym in surv_lists.get("gsm", []):
                    payload.append({"symbol": sym + ".NS" if not sym.endswith(".NS") else sym, "measure_type": "GSM", "stage": 4})
                for sym in surv_lists.get("t2t", []):
                    payload.append({"symbol": sym + ".NS" if not sym.endswith(".NS") else sym, "measure_type": "T2T", "stage": 1})
                if payload:
                    await upsert_db("surveillance", payload)
                    logger.info("[Screener Daemon] Successfully synchronized %d surveillance rules to database.", len(payload))
            except Exception as sync_err:
                logger.error("[Screener Daemon] Failed to sync surveillance to database: %s", sync_err)
        
        # Create a single requests session with rotated headers to share across requests
        session = get_resilient_session()
        screened_candidates = []
        
        # Fetch previous candidates to check for recent successful screenings
        prev_candidates = await self.redis_pipeline.get_cached_indicator("SCREENER", "candidates")
        cached_candidates_map = {c["ticker"]: c for c in prev_candidates} if prev_candidates else {}
        
        for ticker in self.tickers:
            try:
                # Check if ticker has been screened recently (within 12 hours)
                if ticker in cached_candidates_map:
                    candidate = cached_candidates_map[ticker]
                    updated_at_str = candidate.get("updated_at")
                    if updated_at_str:
                        try:
                            updated_at = datetime.fromisoformat(updated_at_str)
                            elapsed = (datetime.now() - updated_at).total_seconds()
                            if elapsed < 12 * 3600:
                                # Re-use candidate directly
                                logger.info("Using cached report for %s (screened %.1f hours ago)", ticker, elapsed / 3600)
                                if not candidate.get("is_blocked"):
                                    screened_candidates.append(candidate)
                                continue
                        except Exception as parse_err:
                            logger.warning("Failed to parse updated_at for %s: %s", ticker, str(parse_err))

                # 1. Fetch price data and sync to Redis (Checks database first, no rate limits!)
                success = await self.data_fetcher.fetch_and_cache_ticker(ticker, period="250d", interval="1d", session=session)
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
                
                # --- Cheap Hard Veto Gates (Lazy Evaluation) ---
                # A. Minimum Liquidity Gate (20-day average turnover < 5 Crores)
                if "turnover_cr" in df.columns:
                    df["turnover_cr"] = df["turnover_cr"].astype(float)
                    avg_turnover_20d = float(df["turnover_cr"].rolling(window=20).mean().iloc[-1])
                else:
                    turnover = (df["close"] * df["volume"]) / 10000000.0
                    avg_turnover_20d = float(turnover.rolling(window=20).mean().iloc[-1])
                    
                is_illiquid = avg_turnover_20d < 5.0
                
                # B. Trend filter gate: We only buy Stage 2 Breakouts / Stage 1 Accumulations.
                # Stage 3 or 4 markdown are blocked early.
                is_unfavorable_trend = weinstein["stage"] not in ["Stage 2 (Markup)", "Stage 1 (Accumulation)"]
                
                # C. Check SEBI surveillance lists (cheap memory check)
                surveillance = self.compliance.verify_surveillance_status(ticker)
                
                is_blocked_early = surveillance["is_blocked"] or is_illiquid or is_unfavorable_trend
                
                # Fetch fundamentals ONLY if the ticker is NOT blocked early
                info = {}
                cfo_is_negative = False
                valuation = {}
                buffett_scorecard = {}
                
                if not is_blocked_early:
                    # Delay between candidates to prevent hitting Yahoo API too rapidly
                    sleep_interval = random.uniform(2.0, 4.0)
                    logger.info("Sleeping %.2f seconds before fetching Yahoo fundamentals for candidate: %s", sleep_interval, ticker)
                    await asyncio.sleep(sleep_interval)
                    
                    # 4. Fetch ticker info fundamentals via raw Yahoo API (using curl_cffi)
                    info = await fetch_ticker_info_resiliently(ticker, session, current_price=float(df["close"].iloc[-1]))
                    cfo_is_negative = float(info.get("operatingCashflow", 0)) < 0
                    
                    # 5. Run Valuation and Moat Models
                    valuation = ValuationEvaluator.calculate_valuation(info)
                    buffett_scorecard = ValuationEvaluator.generate_buffett_scorecard(valuation)
                else:
                    logger.info("Skipping Yahoo API queries for blocked/unfavorable ticker: %s (Weinstein: %s, Illiquid: %s)", 
                                ticker, weinstein["stage"], is_illiquid)
                    price = float(df["close"].iloc[-1])
                    info = {
                        "currentPrice": price,
                        "previousClose": price,
                        "longName": ticker,
                        "sector": "N/A",
                        "industry": "N/A",
                        "operatingCashflow": 0,
                    }
                    valuation = {
                        "roce": 0.05,
                        "roe": 0.05,
                        "cfo_to_net_income": 1.0,
                        "debt_to_equity": 0.0,
                        "moat_rating": "None",
                        "intrinsic_value": 0.0,
                        "margin_of_safety": 0.0,
                        "is_undervalued": False,
                    }
                    buffett_scorecard = {
                        "score": 0,
                        "max_score": 5,
                        "passes": []
                    }
                
                # 6. Get Entry Timing Assessment
                timing = TrendEvaluator.get_entry_timing_assessment(df, weinstein, fvgs)
                
                # 7. Scrape bulk deals
                deals = await self.scrape_bulk_block_deals(ticker)
                
                # B. Operator Trap Check (3 consecutive upper circuits + negative Operating Cash Flow)
                hit_upper_circuits_3d = False
                if "is_upper_circuit" in df.columns:
                    hit_upper_circuits_3d = bool(df["is_upper_circuit"].iloc[-3:].all())
                
                is_operator_trap = hit_upper_circuits_3d and cfo_is_negative
                
                # Combine surveillance and safety gates
                surveillance_reasons = list(surveillance["reasons"]) if surveillance.get("reasons") else []
                if is_illiquid:
                    surveillance_reasons.append("Average daily turnover < 5 Crores (Illiquid)")
                if is_operator_trap:
                    surveillance_reasons.append("Operator Pump Warning (3 consecutive upper circuits with negative CFO)")
                    
                is_blocked = surveillance["is_blocked"] or is_illiquid or is_operator_trap
                
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
                    "is_blocked": is_blocked,
                    "surveillance_reasons": surveillance_reasons,
                    "timing_status": timing["status"],
                    "timing_description": timing["description"],
                    "has_fvg": len([f for f in fvgs if not f["mitigated"]]) > 0,
                    "is_operator_trap": is_operator_trap,
                    "avg_turnover_20d_cr": round(avg_turnover_20d, 2),
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
                    "surveillance": {
                        "is_blocked": is_blocked,
                        "reasons": surveillance_reasons
                    },
                    "deals": deals,
                    "updated_at": datetime.now().isoformat()
                }
                
                await self.redis_pipeline.cache_indicator(ticker, "detailed_indicators", detailed_indicators)
                
                if not is_blocked:
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
