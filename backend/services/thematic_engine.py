import logging
import asyncio
import re
import json
import pandas as pd
import numpy as np
import yfinance as yf
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

# Upgraded: query_llm_structured enforces Pydantic schema — no more regex JSON hacks
from backend.services.llm_gateway import query_llm, query_llm_structured
from backend.services.trend_models import TrendEvaluator
from backend.services.redis_pipeline import RedisPipeline
from backend.services.embeddings import generate_embedding
from backend.services.supabase_client import query_supabase, rpc_supabase, upsert_supabase, IS_SUPABASE_CONFIGURED

logger = logging.getLogger(__name__)


# ── Pydantic schema for structured LLM catalyst parsing ───────────────────────
class CatalystData(BaseModel):
    """
    Structured representation of a parsed financial catalyst.
    The LLM MUST produce output conforming to this schema.
    If validation fails, query_llm_structured retries automatically (up to 3x).
    """
    theme: str                                    # DEFENSE | RAILWAYS | RENEWABLE_ENERGY | SEMICONDUCTORS | OTHER
    products_or_materials: List[str]              # e.g. ["Titanium", "Carbon Fibre", "Radar systems"]
    estimated_budget_cr: Optional[float] = None  # Budget in Crore INR, or null


class ThematicCatalystAnalyzer:
    """
    Supabase pgvector RAG-backed thematic investing engine.
    Ingests unstructured budget/policy catalysts, vectorizes them,
    queries Supabase via pgvector semantic similarity to map suppliers,
    checks EOD deliverable volume spikes to verify institutional buying,
    and applies retail operator / exhaustion filters.
    """
    def __init__(self, redis_pipeline: RedisPipeline):
        self.redis_pipeline = redis_pipeline

    async def ingest_and_categorize(self, catalyst_text: str) -> Dict[str, Any]:
        """
        Uses query_llm_structured to parse unstructured policy text into a typed
        CatalystData object.  Automatic retry (up to 3x) ensures valid JSON output
        — replaces the previous fragile regex-based JSON extraction.
        """
        system_instruction = (
            "You are an expert thematic investing engine for Indian equity markets. "
            "Categorize the provided policy or budget catalyst into exactly one of these "
            "themes: DEFENSE, RAILWAYS, RENEWABLE_ENERGY, SEMICONDUCTORS, or OTHER. "
            "Identify key products or materials mentioned (be specific — e.g. 'Titanium sponge' "
            "not just 'metals'). Extract any budget allocation in Crore Rupees if stated."
        )

        prompt = (
            f'Catalyst text to classify: "{catalyst_text}"\n\n'
            "Classify into one theme and extract specific products/materials and budget."
        )

        result = await query_llm_structured(
            prompt=prompt,
            schema=CatalystData,
            system_instruction=system_instruction,
            max_retries=3,
        )

        if result:
            logger.info(
                "[ThematicEngine] Catalyst classified: theme=%s | products=%s | budget=%.0f Cr",
                result.theme,
                result.products_or_materials,
                result.estimated_budget_cr or 0,
            )
            return result.model_dump()

        # Graceful fallback if all LLM retries fail
        logger.warning("[ThematicEngine] LLM structured parse failed — using neutral fallback.")
        return {"theme": "OTHER", "products_or_materials": [], "estimated_budget_cr": None}

    async def analyze_thematic_chain(self, catalyst_text: str) -> Dict[str, Any]:
        """
        Executes a 4-stage RAG-backed thematic arbitrage search:
        1. Ingests unstructured policy news and parses keywords.
        2. Vectorizes the catalyst query and does pgvector semantic search to find supplier companies.
        3. Loads EOD Bhavcopy history to calculate delivery volume spikes and OBV accumulation.
        4. Applies operator upper circuit checks, liquidity gates, and catalyst exhaustion filters.
        """
        if not IS_SUPABASE_CONFIGURED:
            return {
                "status": "error",
                "reason": "Supabase credentials are not configured in environment."
            }

        # Stage 1: Ingestion
        ingestion_results = await self.ingest_and_categorize(catalyst_text)
        theme = ingestion_results.get("theme", "OTHER").upper()
        products_materials = ingestion_results.get("products_or_materials", [])
        budget_cr = ingestion_results.get("estimated_budget_cr")

        # Formulate search string (combine products and sector details)
        search_query = f"{' '.join(products_materials)} {theme} sector suppliers, manufacturing and raw materials"
        logger.info("Generating semantic search vector for query: %s", search_query)
        
        # Stage 2: Hybrid Search (BM25 keyword + pgvector semantic)
        # Hybrid search is more precise than pure semantic search — prevents
        # returning steel companies when searching for "titanium suppliers".
        query_vector = generate_embedding(search_query)

        matched_companies: List[Dict] = []

        # Try hybrid search first
        try:
            matched_companies = await rpc_supabase("match_companies_hybrid", {
                "query_embedding":   query_vector,
                "query_text":        search_query,
                "match_threshold":   0.15,
                "match_count":       10,
                "semantic_weight":   0.7,
                "bm25_weight":       0.3,
            })
            if matched_companies:
                logger.info(
                    "[ThematicEngine] Hybrid search returned %d companies.",
                    len(matched_companies)
                )
        except Exception as hybrid_err:
            logger.warning(
                "[ThematicEngine] Hybrid search RPC failed (%s). "
                "Falling back to pure semantic search.",
                hybrid_err
            )

        # Fallback: pure semantic search
        if not matched_companies:
            matched_companies = await rpc_supabase("match_companies", {
                "query_embedding":   query_vector,
                "match_threshold":   0.20,
                "match_count":       10,
            })
            if matched_companies:
                logger.info(
                    "[ThematicEngine] Semantic fallback returned %d companies.",
                    len(matched_companies)
                )
        
        if not matched_companies:
            logger.warning("No companies matched the catalyst query vector.")
            return {
                "status": "ignored",
                "reason": "No supply chain matches found in the vector database.",
                "ingestion": ingestion_results
            }

        logger.info("pgvector returned %d semantically matched suppliers.", len(matched_companies))
        arbitrage_candidates = []

        # Process each company
        for company in matched_companies:
            symbol = company["symbol"]
            similarity = company["similarity"]
            
            try:
                # Stage 3: Fetch EOD Bhavcopy history from Supabase (Avoids yfinance rate limits!)
                bhav_history = await query_supabase("daily_bhavcopy", {
                    "symbol": f"eq.{symbol}",
                    "order": "trade_date.asc",
                    "limit": 250
                })
                
                # Resilient fallback: download from yfinance if database history is empty
                if not bhav_history or len(bhav_history) < 90:
                    logger.info("Database cache miss for %s. Fetching EOD from yfinance...", symbol)
                    loop = asyncio.get_event_loop()
                    hist_df = await loop.run_in_executor(
                        None,
                        lambda: yf.Ticker(symbol).history(period="250d")
                    )
                    if hist_df.empty:
                        continue
                        
                    hist_df = hist_df.reset_index()
                    hist_df.rename(columns={
                        "Date": "timestamp",
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume"
                    }, inplace=True)
                    hist_df["timestamp"] = hist_df["timestamp"].astype(str)
                    candles = hist_df.to_dict(orient="records")
                    
                    # Store minimal history in Supabase to populate database
                    db_rows = []
                    for c in candles:
                        db_rows.append({
                            "symbol": symbol,
                            "trade_date": c["timestamp"].split("T")[0],
                            "open": float(c["open"]),
                            "high": float(c["high"]),
                            "low": float(c["low"]),
                            "close": float(c["close"]),
                            "prev_close": float(c["close"]), # proxy EOD
                            "volume": int(c["volume"]),
                            "delivery_volume": int(c["volume"] * 0.35), # neutral fallback
                            "delivery_pct": 35.0,
                            "turnover_cr": float(c["close"] * c["volume"] / 10000000.0)
                        })
                    await upsert_supabase("daily_bhavcopy", db_rows)
                    bhav_history = db_rows

                df = pd.DataFrame(bhav_history)
                
                # Clean invalid data points (Zero/Negative Price Filter)
                df = df[df["close"] > 0]
                if len(df) < 20:
                    continue
                    
                # Volume check
                zero_vol_days = int((df["volume"] == 0).sum())
                if zero_vol_days > len(df) * 0.5:
                    continue # Ignore illiquid/dead listings

                # Calculate indicators
                df = TrendEvaluator.calculate_indicators(df)
                
                current_price = float(df["close"].iloc[-1])
                last_volume = int(df["volume"].iloc[-1])
                
                # Check OBV trend
                last_obv = float(df["obv"].iloc[-1])
                last_obv_ema = float(df["obv_ema20"].iloc[-1])
                obv_status = "ACCUMULATION" if last_obv > last_obv_ema else "DISTRIBUTION"
                
                obv_diff_10d = float(df["obv"].iloc[-1] - df["obv"].iloc[-10]) if len(df) >= 10 else 0.0
                obv_rising = obv_diff_10d > 0.0

                # Weinstein stage evaluation
                weinstein_result = TrendEvaluator.evaluate_weinstein(df)
                stage = weinstein_result.get("stage", "Unknown")

                # Sourced Deliverable Volume analysis (The Retail edge)
                # Compute 20-day average delivery volume %
                df["delivery_pct"] = df["delivery_pct"].astype(float)
                delivery_avg_20d = float(df["delivery_pct"].rolling(window=20).mean().iloc[-1])
                latest_delivery_pct = float(df["delivery_pct"].iloc[-1])
                
                # Institutional buying spike criteria: delivery % is > 45% and at least 1.3x its 20d average
                is_delivery_spike = latest_delivery_pct >= 45.0 and latest_delivery_pct > (delivery_avg_20d * 1.3)
                delivery_status = "Institutional Buying (High Delivery)" if is_delivery_spike else "Normal Delivery"

                # Estimate contract impact ratio
                # Grab market cap from company details in Supabase
                comp_profile = await query_supabase("companies", {"symbol": f"eq.{symbol}", "select": "market_cap_cr"})
                market_cap_cr = float(comp_profile[0].get("market_cap_cr", 0.0)) if comp_profile and comp_profile[0].get("market_cap_cr") else 0.0
                
                # Fallback to yfinance if not set in db
                if market_cap_cr == 0.0:
                    loop = asyncio.get_event_loop()
                    info = await loop.run_in_executor(None, lambda: yf.Ticker(symbol).info)
                    mcap = info.get("marketCap", 0)
                    market_cap_cr = round(mcap / 10000000.0, 2) if mcap else 0.0
                    if market_cap_cr > 0:
                        await upsert_supabase("companies", [{"symbol": symbol, "market_cap_cr": market_cap_cr}])

                impact_pct = (budget_cr / market_cap_cr) * 100.0 if budget_cr and market_cap_cr > 0 else 0.0

                # Stage 4: Risk & Retail Guardrails
                
                # 1. Catalyst Exhaustion Filter (> 50% run-up in last 90 trading days)
                last_90d_df = df.iloc[-90:]
                min_90d_price = last_90d_df["low"].min()
                run_up_pct = (current_price - min_90d_price) / min_90d_price if min_90d_price > 0 else 0.0
                is_exhausted = run_up_pct >= 0.50
                
                # 2. Minimum Liquidity Gate (20-day average turnover < 5 Crores)
                df["turnover_cr"] = df["turnover_cr"].astype(float)
                avg_turnover_20d = float(df["turnover_cr"].rolling(window=20).mean().iloc[-1])
                is_illiquid = avg_turnover_20d < 5.0 # Less than 5 Cr average daily volume

                # 3. Operator Trap (3 consecutive upper circuits + negative cash flows check)
                circuit_hits_3d = bool(df["is_upper_circuit"].iloc[-3:].all())
                
                # Check Operating Cash Flow (CFO)
                cfo_is_negative = False
                try:
                    loop = asyncio.get_event_loop()
                    cfo_data = await loop.run_in_executor(None, lambda: yf.Ticker(symbol).cashflow)
                    if not cfo_data.empty:
                        for row_name in ["Operating Cash Flow", "Cash Flow From Operating Activities", "OperatingCashFlow"]:
                            if row_name in cfo_data.index:
                                latest_cfo = float(cfo_data.loc[row_name].iloc[0])
                                cfo_is_negative = latest_cfo < 0
                                break
                except Exception:
                    pass
                
                is_operator_trap = circuit_hits_3d and cfo_is_negative

                # Derive Recommendation Action
                if is_operator_trap:
                    recommendation = "Do Not Buy - Operator Pump Warning (Negative CFO)"
                    rec_color = "rose"
                elif is_illiquid:
                    recommendation = "Avoid - Illiquid Microcap (<5 Cr daily turnover)"
                    rec_color = "rose"
                elif is_exhausted:
                    recommendation = "Do Not Buy - Catalyst Exhausted"
                    rec_color = "rose"
                elif "Stage 4" in stage or "Stage 3" in stage:
                    recommendation = "Avoid - Downward Price Structure"
                    rec_color = "rose"
                elif obv_status == "DISTRIBUTION" or not obv_rising:
                    recommendation = "Watchlist - Institutional Selling/Weak Volume Support"
                    rec_color = "yellow"
                else:
                    timing = TrendEvaluator.get_entry_timing_assessment(df, weinstein_result, [])
                    timing_status = timing.get("status", "Neutral")
                    if timing_status in ["Avoid", "Train Has Left"]:
                        recommendation = f"Hold / Watchlist ({timing_status})"
                        rec_color = "yellow"
                    else:
                        recommendation = f"Buy Accumulation ({timing_status})"
                        rec_color = "emerald"

                arbitrage_candidates.append({
                    "symbol": symbol,
                    "name": company["name"],
                    "description": company["description"],
                    "match_score": round(similarity, 4),
                    "market_data": {
                        "current_price": round(current_price, 2),
                        "market_cap_cr": round(market_cap_cr, 2),
                        "contract_impact_pct": round(impact_pct, 2),
                        "run_up_90d_pct": round(run_up_pct * 100.0, 2),
                        "avg_turnover_20d_cr": round(avg_turnover_20d, 2)
                    },
                    "delivery_data": {
                        "delivery_avg_20d": round(delivery_avg_20d, 2),
                        "latest_delivery_pct": round(latest_delivery_pct, 2),
                        "delivery_status": delivery_status,
                        "is_buying_spike": is_delivery_spike
                    },
                    "technical_verification": {
                        "weinstein_stage": stage,
                        "obv_status": obv_status,
                        "obv_accumulation_90d": obv_rising,
                        "is_overextended": is_exhausted,
                        "is_operator_trap": is_operator_trap
                    },
                    "actionable_recommendation": {
                        "verdict": recommendation,
                        "color": rec_color
                    }
                })
            except Exception as e:
                logger.error("Error analyzing thematic candidate %s: %s", symbol, str(e), exc_info=True)
                continue

        # Sort candidates so that actionable "Buy" ratings, higher similarity score and higher delivery spike rank first
        arbitrage_candidates.sort(
            key=lambda x: (
                0 if "Buy" in x["actionable_recommendation"]["verdict"] else 1,
                0 if x["delivery_data"]["is_buying_spike"] else 1,
                -x["match_score"]
            )
        )

        return {
            "status": "success",
            "catalyst_ingested": {
                "text": catalyst_text,
                "theme": theme,
                "products_materials": products_materials,
                "budget_cr": budget_cr
            },
            "candidates_count": len(arbitrage_candidates),
            "candidates": arbitrage_candidates
        }
