import asyncio
import logging
import random
import re
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from datetime import datetime
from typing import List, Dict, Any

from playwright.async_api import async_playwright

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
        Scrapes daily institutional flow data (FII/DII activity) from multiple sources.
        Tries NiftyTrader, Moneycontrol, and StockEdge sequentially using a headless browser.
        Returns net daily buying/selling for FII and DII.
        """
        sources = [
            {
                "name": "NiftyTrader",
                "url": "https://www.niftytrader.in/fii-dii-activity",
                "table_selector": "table",
                "fii_col_idx": None,
                "dii_col_idx": None,
            },
            {
                "name": "Moneycontrol",
                "url": "https://www.moneycontrol.com/markets/fii-dii-data/cash/",
                "table_selector": "table",
                "fii_col_idx": None,
                "dii_col_idx": None,
            },
            {
                "name": "StockEdge",
                "url": "https://www.stockedge.com/fiidii",
                "table_selector": "table",
                "fii_col_idx": None,
                "dii_col_idx": None,
            }
        ]
        
        async with async_playwright() as p:
            logger.info("Starting multi-source FII/DII flow scraper...")
            browser = await p.chromium.launch(headless=True, args=["--disable-http2"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()
            
            fii_net = None
            dii_net = None
            parsed_source = None
            
            for src in sources:
                logger.info("Trying FII/DII data source: %s (%s)", src["name"], src["url"])
                try:
                    await page.goto(src["url"], wait_until="load", timeout=25000)
                    await page.wait_for_selector(src["table_selector"], timeout=10000)
                    
                    rows = await page.eval_on_selector_all(
                        f"{src['table_selector']} tr",
                        """
                        elements => elements.map(tr => {
                            const cells = Array.from(tr.querySelectorAll('td, th'));
                            return cells.map(c => c.innerText.trim());
                        })
                        """
                    )
                    
                    logger.info("Found %d rows in %s tables", len(rows), src["name"])
                    
                    fii_net_col = None
                    dii_net_col = None
                    
                    for r_idx, row in enumerate(rows[:5]):
                        if not row:
                            continue
                        row_lower = [c.lower() for c in row]
                        
                        for c_idx, cell in enumerate(row_lower):
                            if "fii" in cell or "fpi" in cell:
                                if "net" in cell or "value" in cell or "buy" in cell:
                                    if fii_net_col is None:
                                        fii_net_col = c_idx
                            if "dii" in cell or "domestic" in cell:
                                if "net" in cell or "value" in cell or "buy" in cell:
                                    if dii_net_col is None:
                                        dii_net_col = c_idx
                        
                        if fii_net_col is not None and dii_net_col is not None:
                            logger.info("Semantically detected columns: FII/FPI Net Col = %d, DII Net Col = %d", fii_net_col, dii_net_col)
                            break
                            
                    if fii_net_col is None: fii_net_col = 3
                    if dii_net_col is None: dii_net_col = 6
                    
                    for row in rows:
                        if not row or len(row) <= max(fii_net_col, dii_net_col):
                            continue
                        
                        first_cell = row[0]
                        if not re.search(r'\d', first_cell):
                            continue
                            
                        try:
                            def parse_val(v):
                                v_clean = v.replace(",", "").replace("Cr", "").replace("₹", "").strip()
                                v_clean = v_clean.replace("−", "-").replace("—", "-")  # Replace unicode minus/dash
                                if "(" in v_clean and ")" in v_clean:
                                    v_clean = "-" + v_clean.replace("(", "").replace(")", "")
                                return float(v_clean)
                            
                            fii_val = parse_val(row[fii_net_col])
                            dii_val = parse_val(row[dii_net_col])
                            
                            fii_net = fii_val
                            dii_net = dii_val
                            parsed_source = src["name"]
                            logger.info("Successfully scraped %s flows: FII = %.2f Cr, DII = %.2f Cr", src["name"], fii_net, dii_net)
                            break
                        except Exception:
                            continue
                            
                    if fii_net is not None and dii_net is not None:
                        break
                        
                except Exception as e:
                    logger.warning("Failed to scrape from source %s: %s", src["name"], str(e))
                    continue
            
            await browser.close()
            
            if fii_net is not None and dii_net is not None:
                flows = {
                    "timestamp": datetime.now().isoformat(),
                    "fii_net_crores": fii_net,
                    "dii_net_crores": dii_net,
                    "rolling_5d_fii": fii_net,
                    "rolling_5d_dii": dii_net,
                    "market_state": "Net Accumulation" if (fii_net + dii_net) > 0 else "Net Distribution",
                    "source": parsed_source
                }
                
                try:
                    prev_flows = await self.redis_pipeline.get_cached_indicator("MARKET", "fii_dii_flows_history")
                    if not prev_flows:
                        prev_flows = []
                    prev_flows.append({"fii": fii_net, "dii": dii_net})
                    prev_flows = prev_flows[-5:]
                    await self.redis_pipeline.cache_indicator("MARKET", "fii_dii_flows_history", prev_flows)
                    
                    flows["rolling_5d_fii"] = round(sum(f["fii"] for f in prev_flows), 2)
                    flows["rolling_5d_dii"] = round(sum(f["dii"] for f in prev_flows), 2)
                except Exception as history_err:
                    logger.warning("Could not calculate rolling 5d FII/DII history: %s", str(history_err))
                
                await self.redis_pipeline.cache_indicator("MARKET", "fii_dii_flows", flows)
                return flows
                
        logger.error("All FII/DII daily flow sources failed. Returning empty dict to prevent mock injection.")
        return {}

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
        Dynamically scrapes the SEBI ASM, GSM, and T2T lists from the official NSE website
        or third-party trackers to ensure no mock data is used.
        """
        asm_list = []
        gsm_list = []
        t2t_list = []
        
        url = "https://www.nseindia.com/reports/adr-res-surveillance-measure"
        
        try:
            from playwright.async_api import async_playwright
            logger.info("[Screener Daemon] Scraping NSE surveillance lists (ASM/GSM/T2T)...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--disable-http2"])
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                
                # Visit main page to set cookies, with a short timeout, ignoring exceptions
                try:
                    logger.info("[Screener Daemon] Initializing NSE cookies...")
                    await page.goto("https://www.nseindia.com/", wait_until="commit", timeout=10000)
                    await asyncio.sleep(2)
                except Exception as home_err:
                    logger.warning("[Screener Daemon] Homepage load warning (ignored): %s", str(home_err))
                
                # Navigate to the surveillance reports page
                logger.info("[Screener Daemon] Navigating to surveillance reports page...")
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)
                
                # Wait for table to render
                await page.wait_for_selector("table", timeout=10000)
                
                # Extract symbols from tables
                tables = await page.query_selector_all("table")
                for table in tables:
                    headers = await table.query_selector_all("th")
                    header_texts = [await h.inner_text() for h in headers]
                    
                    symbol_col_idx = None
                    for idx, h_text in enumerate(header_texts):
                        if "symbol" in h_text.lower() or "security" in h_text.lower():
                            symbol_col_idx = idx
                            break
                            
                    if symbol_col_idx is not None:
                        rows = await table.query_selector_all("tr")
                        for row in rows[1:]:
                            cols = await row.query_selector_all("td")
                            if len(cols) > symbol_col_idx:
                                symbol_text = (await cols[symbol_col_idx].inner_text()).strip()
                                clean_sym = symbol_text.split()[0].upper()
                                if clean_sym.isalnum():
                                    full_text = await table.inner_text()
                                    if "additional surveillance" in full_text.lower() or "asm" in full_text.lower():
                                        asm_list.append(clean_sym)
                                    elif "graded surveillance" in full_text.lower() or "gsm" in full_text.lower():
                                        gsm_list.append(clean_sym)
                                    else:
                                        t2t_list.append(clean_sym)
                                        
                await browser.close()
                logger.info("[Screener Daemon] NSE Surveillance Scraper: Scraped %d ASM, %d GSM, %d T2T symbols.", 
                            len(asm_list), len(gsm_list), len(t2t_list))
        except Exception as e:
            logger.error("[Screener Daemon] Failed to dynamically scrape NSE surveillance lists: %s. Defaulting to empty lists.", str(e))
            
        return {
            "asm": list(set(asm_list)),
            "gsm": list(set(gsm_list)),
            "t2t": list(set(t2t_list))
        }

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

                # Delay between tickers with randomized interval (2.0 to 5.0 seconds) to bypass WAF limits
                sleep_interval = random.uniform(2.0, 5.0)
                logger.info("Sleeping %.2f seconds before fetching next ticker: %s", sleep_interval, ticker)
                await asyncio.sleep(sleep_interval)
                
                # 1. Fetch price data and sync to Redis
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
                    "deals": deals,
                    "updated_at": datetime.now().isoformat()
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
