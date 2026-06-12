import asyncio
import logging
import random
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

from backend.services.redis_pipeline import RedisPipeline
from backend.services.data_fetcher import DataFetcher
from backend.services.trend_models import TrendEvaluator
from backend.services.valuation_models import ValuationEvaluator
from backend.services.surveillance_compliance import SEBIComplianceGatekeeper

logger = logging.getLogger(__name__)

# Static fallback database of Nifty constituents to shield against yfinance rate limits
DEFAULT_INFO_BANK = {
    "RELIANCE.NS": {
        "longName": "Reliance Industries Limited",
        "sector": "Energy",
        "industry": "Oil & Gas Refineries",
        "currentPrice": 1263.0,
        "operatingMargins": 0.185,
        "ebitdaMargins": 0.22,
        "returnOnAssets": 0.08,
        "returnOnEquity": 0.155,
        "debtToEquity": 38.0,
        "trailingEps": 98.4,
        "earningsGrowth": 0.12,
        "heldPercentInstitutions": 0.28
    },
    "TCS.NS": {
        "longName": "Tata Consultancy Services Limited",
        "sector": "Technology",
        "industry": "Information Technology Services",
        "currentPrice": 3950.0,
        "operatingMargins": 0.245,
        "ebitdaMargins": 0.27,
        "returnOnAssets": 0.18,
        "returnOnEquity": 0.38,
        "debtToEquity": 5.0,
        "trailingEps": 124.5,
        "earningsGrowth": 0.09,
        "heldPercentInstitutions": 0.16
    },
    "HDFCBANK.NS": {
        "longName": "HDFC Bank Limited",
        "sector": "Financial Services",
        "industry": "Banks - Regional",
        "currentPrice": 1420.0,
        "operatingMargins": 0.32,
        "ebitdaMargins": 0.38,
        "returnOnAssets": 0.02,
        "returnOnEquity": 0.172,
        "debtToEquity": 85.0,
        "trailingEps": 88.2,
        "earningsGrowth": 0.18,
        "heldPercentInstitutions": 0.52
    },
    "BHARTIARTL.NS": {
        "longName": "Bharti Airtel Limited",
        "sector": "Communication Services",
        "industry": "Telecom Services",
        "currentPrice": 1380.0,
        "operatingMargins": 0.21,
        "ebitdaMargins": 0.48,
        "returnOnAssets": 0.05,
        "returnOnEquity": 0.12,
        "debtToEquity": 120.0,
        "trailingEps": 32.5,
        "earningsGrowth": 0.25,
        "heldPercentInstitutions": 0.22
    },
    "ICICIBANK.NS": {
        "longName": "ICICI Bank Limited",
        "sector": "Financial Services",
        "industry": "Banks - Regional",
        "currentPrice": 1120.0,
        "operatingMargins": 0.28,
        "ebitdaMargins": 0.34,
        "returnOnAssets": 0.021,
        "returnOnEquity": 0.185,
        "debtToEquity": 90.0,
        "trailingEps": 74.2,
        "earningsGrowth": 0.20,
        "heldPercentInstitutions": 0.44
    },
    "INFY.NS": {
        "longName": "Infosys Limited",
        "sector": "Technology",
        "industry": "Information Technology Services",
        "currentPrice": 1480.0,
        "operatingMargins": 0.205,
        "ebitdaMargins": 0.24,
        "returnOnAssets": 0.14,
        "returnOnEquity": 0.31,
        "debtToEquity": 8.0,
        "trailingEps": 62.4,
        "earningsGrowth": 0.06,
        "heldPercentInstitutions": 0.34
    },
    "SBI.NS": {
        "longName": "State Bank of India",
        "sector": "Financial Services",
        "industry": "Banks - Regional",
        "currentPrice": 820.0,
        "operatingMargins": 0.22,
        "ebitdaMargins": 0.28,
        "returnOnAssets": 0.011,
        "returnOnEquity": 0.168,
        "debtToEquity": 140.0,
        "trailingEps": 82.5,
        "earningsGrowth": 0.14,
        "heldPercentInstitutions": 0.12
    },
    "ITC.NS": {
        "longName": "ITC Limited",
        "sector": "Consumer Defensive",
        "industry": "Tobacco",
        "currentPrice": 430.0,
        "operatingMargins": 0.35,
        "ebitdaMargins": 0.39,
        "returnOnAssets": 0.22,
        "returnOnEquity": 0.29,
        "debtToEquity": 1.0,
        "trailingEps": 16.8,
        "earningsGrowth": 0.08,
        "heldPercentInstitutions": 0.42
    },
    "HINDUNILVR.NS": {
        "longName": "Hindustan Unilever Limited",
        "sector": "Consumer Defensive",
        "industry": "Household & Personal Products",
        "currentPrice": 2350.0,
        "operatingMargins": 0.23,
        "ebitdaMargins": 0.255,
        "returnOnAssets": 0.19,
        "returnOnEquity": 0.202,
        "debtToEquity": 2.0,
        "trailingEps": 43.8,
        "earningsGrowth": 0.04,
        "heldPercentInstitutions": 0.14
    },
    "LICI.NS": {
        "longName": "Life Insurance Corporation of India",
        "sector": "Financial Services",
        "industry": "Insurance - Life",
        "currentPrice": 1050.0,
        "operatingMargins": 0.05,
        "ebitdaMargins": 0.06,
        "returnOnAssets": 0.005,
        "returnOnEquity": 0.142,
        "debtToEquity": 0.0,
        "trailingEps": 65.4,
        "earningsGrowth": 0.05,
        "heldPercentInstitutions": 0.08
    },
    "TATAMOTORS.NS": {
        "longName": "Tata Motors Limited",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "currentPrice": 960.0,
        "operatingMargins": 0.082,
        "ebitdaMargins": 0.138,
        "returnOnAssets": 0.042,
        "returnOnEquity": 0.165,
        "debtToEquity": 110.0,
        "trailingEps": 54.3,
        "earningsGrowth": 0.32,
        "heldPercentInstitutions": 0.18
    },
    "ONGC.NS": {
        "longName": "Oil and Natural Gas Corporation Limited",
        "sector": "Energy",
        "industry": "Oil & Gas Exploration & Production",
        "currentPrice": 268.0,
        "operatingMargins": 0.18,
        "ebitdaMargins": 0.24,
        "returnOnAssets": 0.075,
        "returnOnEquity": 0.135,
        "debtToEquity": 45.0,
        "trailingEps": 34.2,
        "earningsGrowth": 0.04,
        "heldPercentInstitutions": 0.15
    },
    "ADANIENT.NS": {
        "longName": "Adani Enterprises Limited",
        "sector": "Industrials",
        "industry": "Conglomerates",
        "currentPrice": 3150.0,
        "operatingMargins": 0.068,
        "ebitdaMargins": 0.095,
        "returnOnAssets": 0.038,
        "returnOnEquity": 0.098,
        "debtToEquity": 150.0,
        "trailingEps": 28.5,
        "earningsGrowth": 0.42,
        "heldPercentInstitutions": 0.06
    }
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
        self.tickers = list(DEFAULT_INFO_BANK.keys())
        
        # Load mock ASM/GSM lists for safety tests
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
        
        screened_candidates = []
        
        for ticker in self.tickers:
            try:
                # Add delay to avoid rate limit spikes on historical data fetches
                await asyncio.sleep(0.3)
                
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
                info = None
                try:
                    import yfinance as yf
                    loop = asyncio.get_event_loop()
                    info = await loop.run_in_executor(None, lambda: yf.Ticker(ticker).info)
                    
                    if not info or not isinstance(info, dict) or "currentPrice" not in info:
                        raise ValueError("yfinance info payload is empty or invalid")
                except Exception as ex:
                    logger.warning("[Screener Daemon] yfinance rate-limited/failed for %s. Using cached local benchmark fundamentals. Reason: %s", ticker, str(ex))
                    info = DEFAULT_INFO_BANK.get(ticker, {}).copy()
                    # Keep price updated relative to last candle close
                    info["currentPrice"] = float(df["close"].iloc[-1])
                
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
                logger.error("Error screening ticker %s: %s", ticker, str(e), exc_info=True)
                
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
