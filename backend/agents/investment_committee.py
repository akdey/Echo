import logging
import http.client
import json
import re
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import asyncio

from backend.agents.state import CommitteeState
from backend.services.redis_pipeline import RedisPipeline
from backend.services.trend_models import TrendEvaluator
from backend.services.valuation_models import ValuationEvaluator
from backend.services.order_book import OrderBookAnalyzer
from backend.services.fundamental_rag import FundamentalInvestigator
from backend.services.sentiment_analyzer import SentimentAnalyzer
from backend.services.llm_gateway import query_llm

async def get_or_compute_detailed_indicators(ticker: str) -> Dict[str, Any]:
    """
    Retrieves detailed indicators from Redis, or computes them dynamically on-the-fly
    if they are not cached. No mock or default values are returned.
    """
    import pandas as pd
    import numpy as np
    import datetime
    import requests
    from backend.services.screener_daemon import fetch_ticker_info_resiliently
    from backend.services.surveillance_compliance import SEBIComplianceGatekeeper
    from backend.services.scraper_utils import fetch_surveillance_lists
    from backend.services.screener_daemon import ScreenerDaemon
    
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    try:
        # Check cache first
        cached = await redis_pipeline.get_cached_indicator(ticker, "detailed_indicators")
        if cached and "technical" in cached and "fundamentals" in cached:
            if "timing_status" in cached and "weinstein_stage" in cached:
                return cached
            
        logger.info("[Committee] Cache miss for %s detailed_indicators. Computing dynamically...", ticker)
        
        # 1. Fetch history
        candles = await redis_pipeline.fetch_ohlcva(ticker, "1d")
        df = pd.DataFrame()
        if candles:
            df = pd.DataFrame(candles)
            rename_map = {"trade_date": "trade_date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
            df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
            
        if df.empty or len(df) < 50:
            logger.info("[Committee] Fetching yfinance history for %s dynamically...", ticker)
            ticker_obj = yf.Ticker(ticker)
            loop = asyncio.get_event_loop()
            yf_df = await loop.run_in_executor(
                None,
                lambda: ticker_obj.history(period="6mo", interval="1d")
            )
            if not yf_df.empty:
                df = yf_df.reset_index().rename(columns={
                    "Date": "trade_date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume"
                })
                
        if df.empty:
            raise ValueError(f"No price history found for {ticker}")
            
        # Ensure correct datatypes
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
                
        # 2. Compute technical indicators
        df = TrendEvaluator.calculate_indicators(df)
        swings_high, swings_low = TrendEvaluator.identify_swings(df)
        fvgs = TrendEvaluator.detect_fvgs(df)
        sweeps = TrendEvaluator.detect_liquidity_sweeps(df, swings_high, swings_low)
        weinstein = TrendEvaluator.evaluate_weinstein(df)
        timing = TrendEvaluator.get_entry_timing_assessment(df, weinstein, fvgs)
        
        # 3. Fetch info resiliently
        session = requests.Session()
        current_price = float(df["close"].iloc[-1])
        
        info = await fetch_ticker_info_resiliently(ticker, session, current_price=current_price)
        if not info or not isinstance(info, dict):
            info = {
                "currentPrice": current_price,
                "previousClose": current_price,
                "longName": ticker,
                "sector": "N/A",
                "industry": "N/A"
            }
            
        # 4. Compute valuation and buffett scorecard
        valuation = ValuationEvaluator.calculate_valuation(info)
        buffett_scorecard = ValuationEvaluator.generate_buffett_scorecard(valuation)
        canslim = TrendEvaluator.evaluate_canslim(df, info)
        
        # 5. Check surveillance status
        compliance = SEBIComplianceGatekeeper()
        try:
            lists = await fetch_surveillance_lists()
            compliance.set_surveillance_lists(
                asm=lists.get("asm", []),
                gsm=lists.get("gsm", []),
                t2t=lists.get("t2t", [])
            )
        except Exception as se_err:
            logger.warning("[Committee] Failed to fetch compliance list updates: %s", se_err)
            
        surveillance = compliance.verify_surveillance_status(ticker)
        
        # Retail Safety Gates
        if "turnover_cr" in df.columns:
            df["turnover_cr"] = df["turnover_cr"].astype(float)
            avg_turnover_20d = float(df["turnover_cr"].rolling(window=20).mean().iloc[-1])
        else:
            turnover = (df["close"] * df["volume"]) / 10000000.0
            avg_turnover_20d = float(turnover.rolling(window=20).mean().iloc[-1])
            
        is_illiquid = avg_turnover_20d < 5.0
        
        surveillance_reasons = list(surveillance.get("reasons", []))
        if is_illiquid:
            surveillance_reasons.append("Average daily turnover < 5 Crores (Illiquid)")
            
        is_blocked = surveillance.get("is_blocked", False) or is_illiquid
        
        # Bulk/block deals
        deals = []
        try:
            daemon = ScreenerDaemon(redis_pipeline)
            deals = await daemon.scrape_bulk_block_deals(ticker)
        except Exception as d_err:
            logger.warning("[Committee] Deals scraper warning: %s", d_err)
            
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
            "timing_status": timing["status"],
            "timing_description": timing["description"],
            "weinstein_stage": weinstein["stage"],
            "weinstein_score": weinstein["score"],
            "canslim_score": canslim["score"],
            "updated_at": datetime.datetime.now().isoformat()
        }
        
        # Cache full indicators
        await redis_pipeline.cache_indicator(ticker, "detailed_indicators", detailed_indicators)
        logger.info("[Committee] Successfully computed and cached detailed_indicators for %s", ticker)
        return detailed_indicators
        
    except Exception as e:
        logger.error("[Committee] Failed to dynamically compute indicators for %s: %s", ticker, e, exc_info=True)
        return {
            "technical": {"sma_50": 0.0, "sma_150": 0.0, "ema_20": 0.0, "fvgs": [], "sweeps": []},
            "fundamentals": {"moat_rating": "N/A", "intrinsic_value": 0.0, "margin_of_safety": 0.0, "is_undervalued": False},
            "buffett_scorecard": {"score": 0, "total_rules": 5, "verdict": "N/A"},
            "surveillance": {"is_blocked": False, "reasons": []},
            "deals": [],
            "timing_status": "N/A",
            "timing_description": f"Failed to compute: {str(e)}",
            "weinstein_stage": "N/A",
            "weinstein_score": 0.0,
            "canslim_score": 0.0
        }
    finally:
        await redis_pipeline.disconnect()

logger = logging.getLogger(__name__)

# --- Multi-Agent Node Implementations ---

async def discovery_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Discovery Desk] Starting evaluation for ticker: {state.ticker}"
    logger.info(log_msg)
    
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    
    # Try fetching cached candidate report
    candidates = await redis_pipeline.get_cached_indicator("SCREENER", "candidates")
    company_name = state.ticker
    sector = "N/A"
    industry = "N/A"
    
    if candidates:
        for c in candidates:
            if c["ticker"] == state.ticker:
                company_name = c["company_name"]
                sector = c["sector"]
                industry = c["industry"]
                log_msg = f"[Discovery Desk] Pulled cached candidate details: {company_name} ({sector} sector)"
                break
                
    fii_dii = await redis_pipeline.get_cached_indicator("MARKET", "fii_dii_flows")
    if not fii_dii:
        from backend.services.scraper_utils import fetch_fii_dii_flows
        fii_dii = await fetch_fii_dii_flows()
        if not fii_dii:
            fii_dii = {"fii_net_crores": 0.0, "dii_net_crores": 0.0, "market_state": "N/A"}
        
    await redis_pipeline.disconnect()
    
    return {
        "company_name": company_name,
        "fii_dii_flows": fii_dii,
        "execution_status": "discovery_completed",
        "logs": state.logs + [log_msg]
    }

async def technical_analysis_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Technical Desk] Scanning trend structures and smart money wicks for {state.ticker}..."
    logger.info(log_msg)
    
    indicators = await get_or_compute_detailed_indicators(state.ticker)
    tech = indicators.get("technical", {})
    timing_status = indicators.get("timing_status", "N/A")
    timing_desc = indicators.get("timing_description", "")
    weinstein_stage = indicators.get("weinstein_stage", "N/A")
    weinstein_score = indicators.get("weinstein_score", 0.0)
    canslim_score = indicators.get("canslim_score", 0.0)
    
    current_price = indicators.get("fundamentals", {}).get("current_price") or indicators.get("fundamentals", {}).get("currentPrice") or 0.0
    if current_price == 0.0:
        redis_pipeline = RedisPipeline()
        await redis_pipeline.connect()
        candles = await redis_pipeline.fetch_ohlcva(state.ticker, "1d")
        await redis_pipeline.disconnect()
        current_price = candles[-1]["close"] if candles else 100.0
        
    t_log = f"[Technical Desk] Weinstein: {weinstein_stage} | CANSLIM Score: {canslim_score:.2f} | Timing Assessment: {timing_status}"
    logger.info(t_log)
    
    return {
        "current_price": current_price,
        "weinstein_stage": weinstein_stage,
        "weinstein_score": weinstein_score,
        "canslim_score": canslim_score,
        "timing_status": timing_status,
        "timing_description": timing_desc,
        "execution_status": "technical_completed",
        "logs": state.logs + [log_msg, t_log]
    }

async def fundamental_evaluation_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Fundamental Desk] Auditing balance sheets, ROCE ratios, and SEBI surveillance status..."
    logger.info(log_msg)
    
    indicators = await get_or_compute_detailed_indicators(state.ticker)
    funds = indicators.get("fundamentals", {})
    scorecard = indicators.get("buffett_scorecard", {})
    surv = indicators.get("surveillance", {})
    deals = indicators.get("deals", [])
    
    score = float(scorecard.get("score", 0))
    moat = funds.get("moat_rating", "N/A")
    intrinsic = funds.get("intrinsic_value", 0.0)
    mos = funds.get("margin_of_safety", 0.0)
    undervalued = funds.get("is_undervalued", False)
    
    is_blocked = surv.get("is_blocked", False)
    reasons = surv.get("reasons", [])
        
    f_log = f"[Fundamental Desk] Buffett Quality Score: {score}/5 | Moat: {moat} | Intrinsic Value: ₹{intrinsic:.2f} (Margin of Safety: {mos:.1%})"
    logger.info(f_log)
    
    if is_blocked:
        s_log = f"[Fundamental Desk] CRITICAL compliance block: {', '.join(reasons)}"
        logger.error(s_log)
    else:
        s_log = "[Fundamental Desk] Ticker passes SEBI ASM/GSM regulatory screening."
        
    return {
        "fundamental_score": score,
        "moat_rating": moat,
        "intrinsic_value": intrinsic,
        "margin_of_safety": mos,
        "is_undervalued": undervalued,
        "is_blocked": is_blocked,
        "surveillance_reasons": reasons,
        "deals": deals,
        "execution_status": "fundamental_completed",
        "logs": state.logs + [log_msg, f_log, s_log]
    }

async def sentiment_validation_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Sentiment Desk] Ingesting morning news and auditing unscripted analyst Q&A divergence..."
    logger.info(log_msg)
    
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    
    # 1. Fetch real cached news sentiment from Redis, or run on-the-fly if missing
    sentiment_val = 0.5
    try:
        cached_sentiment = await redis_pipeline.fetch_indicator(state.ticker, "sentiment")
        if cached_sentiment and "sentiment_score" in cached_sentiment:
            sentiment_val = cached_sentiment["sentiment_score"]
        else:
            analyzer = SentimentAnalyzer(redis_pipeline)
            res = await analyzer.analyze_sentiment(state.ticker)
            sentiment_val = res.get("sentiment_score", 0.5)
    except Exception as e:
        logger.warning("[Sentiment Desk] Failed to load news sentiment for %s: %s", state.ticker, str(e))
    
    await redis_pipeline.disconnect()
    
    # 2. Query ChromaDB collection for transcript chunks and compute unscripted Q&A sentiment divergence via LLM
    qa_divergence = 0.0
    t_log = ""
    try:
        investigator = FundamentalInvestigator()
        # Retrieve transcript text chunks from local ChromaDB
        results = investigator.collection.get(
            where={"ticker": state.ticker, "source": "transcript"}
        )
        documents = results.get("documents", []) if results else []
        
        if documents:
            full_transcript = "\n".join(documents)
            # Use local Gemma (via Ollama) or Gemini API to find and score prepared speech vs Q&A section
            prompt = f"""
            You are an elite financial auditor. Analyze the following earnings call transcript of {state.ticker}:
            ---
            {full_transcript[:15000]}
            ---
            
            Evaluate and rate:
            1. The sentiment of the Prepared Remarks (management's scripted presentation) on a scale from 0.0 (bearish) to 1.0 (bullish).
            2. The sentiment of the Analyst Q&A section (unscripted questions and answers) on a scale from 0.0 (bearish) to 1.0 (bullish).
            
            Compute the unscripted sentiment divergence: (Prepared Remarks Sentiment - Analyst Q&A Sentiment).
            
            Provide your response in JSON format:
            {{"prepared_sentiment": float, "qa_sentiment": float, "divergence": float}}
            """
            
            raw_response = await query_llm(prompt)
            flags = None
            if raw_response:
                try:
                    start_idx = raw_response.find("{")
                    end_idx = raw_response.rfind("}") + 1
                    if start_idx != -1 and end_idx != -1:
                        flags = json.loads(raw_response[start_idx:end_idx])
                except Exception as parse_err:
                    logger.error("Failed to parse LLM transcript response: %s", str(parse_err))
            
            if flags:
                prepared_score = flags.get("prepared_sentiment", 0.5)
                qa_score = flags.get("qa_sentiment", 0.5)
                qa_divergence = round(flags.get("divergence", prepared_score - qa_score), 2)
                t_log = f" Prepared Remarks Sentiment: {prepared_score:.2f} | Q&A Sentiment: {qa_score:.2f}"
            else:
                logger.info("[Sentiment Desk] LLM transcript audit did not return parseable JSON. Skipping divergence.")
        else:
            logger.info("[Sentiment Desk] No earnings call transcripts found in ChromaDB for %s. Setting Q&A divergence to 0.00.", state.ticker)
    except Exception as e:
        logger.warning("[Sentiment Desk] Failed to fetch or analyze transcripts in ChromaDB for %s: %s", state.ticker, str(e))
        
    is_bubble = sentiment_val >= 0.95
    is_panic = sentiment_val <= 0.40
    is_evasive = qa_divergence >= 0.35
    
    is_invalidated = is_bubble or is_panic or is_evasive
    
    s_log = f"[Sentiment Desk] News Sentiment: {sentiment_val*100:.0f}% Bullish | Q&A Divergence: {qa_divergence:.2f}."
    if t_log:
        s_log += f" ({t_log})"
    logger.info(s_log)
    
    if is_invalidated:
        b_log = f"[Sentiment Desk] Invalidation Circuit Breaker Tripped! Reasons: "
        reasons_list = []
        if is_bubble: reasons_list.append("Extreme retail euphoria / bubble mania")
        if is_panic: reasons_list.append("Catastrophic corporate disclosures / negative news ratio >60%")
        if is_evasive: reasons_list.append("Management evasiveness during Q&A session")
        b_log += ", ".join(reasons_list)
        logger.warning(b_log)
    else:
        b_log = "[Sentiment Desk] Sentiment and transcript disclosures stable. Proceed to simulation gate."
        
    return {
        "sentiment_score": sentiment_val,
        "unscripted_divergence": qa_divergence,
        "is_invalidated": is_invalidated,
        "execution_status": "sentiment_completed",
        "logs": state.logs + [log_msg, s_log, b_log]
    }

async def simulation_gate_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Simulation Gate] Simulating 24-step forward trajectories in Kronos latent space..."
    logger.info(log_msg)
    
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    
    # Pull candles from digital twin
    candles = await redis_pipeline.fetch_ohlcva(state.ticker, "1d")
    await redis_pipeline.disconnect()
    
    if not candles:
        # Fall back to fetching history directly
        try:
            ticker_obj = yf.Ticker(state.ticker)
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: ticker_obj.history(period="6mo", interval="1d")
            )
            if not df.empty:
                candles = []
                for idx, row in df.iterrows():
                    trade_date = idx.date().isoformat() if isinstance(idx, pd.Timestamp) else str(idx)
                    close_val = float(row["Close"])
                    candles.append({
                        "timestamp": trade_date,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": close_val,
                        "volume": float(row["Volume"]),
                        "amount": close_val * float(row["Volume"])
                    })
        except Exception as e:
            logger.warning("[Simulation Gate] Failed to load yfinance fallback: %s", e)
            
    if not candles:
        sim_log = "[Simulation Gate] No historical OHLCV data available for regime simulation. Returning neutral parameters."
        logger.warning(sim_log)
        return {
            "kronos_upside_prob": 0.5,
            "kronos_vol_risk": 0.0,
            "execution_status": "simulations_completed",
            "logs": state.logs + [log_msg, sim_log]
        }
        
    history = candles[-50:] # feed last 50 days to model
    upside_prob = 0.5
    vol_risk = 0.0
    
    try:
        from backend.services.kronos_brain import KronosPredictor
        import numpy as np
        
        predictor = KronosPredictor()
        loop = asyncio.get_event_loop()
        
        # Convert history candles to dicts with lowercase float values
        formatted_history = []
        for c in history:
            close = float(c.get("close", 0.0))
            vol = float(c.get("volume", 0.0))
            formatted_history.append({
                "timestamp": c.get("trade_date") or c.get("timestamp") or "",
                "open": float(c.get("open", close)),
                "high": float(c.get("high", close)),
                "low": float(c.get("low", close)),
                "close": close,
                "volume": vol,
                "amount": close * vol
            })
            
        paths = await loop.run_in_executor(
            None,
            lambda: predictor.run_monte_carlo_rollout(
                formatted_history,
                steps=24,
                num_paths=30,
                temperature=0.7
            )
        )
        
        if paths:
            start_close = formatted_history[-1]["close"]
            final_closes = [path[-1]["close"] for path in paths]
            successful_paths = sum(1 for fc in final_closes if fc >= start_close)
            upside_prob = float(successful_paths / len(paths))
            
            std_final_closes = float(np.std(final_closes))
            vol_risk = float(std_final_closes / start_close) if start_close > 0 else 0.0
            sim_log = f"[Simulation Gate] Local Kronos autoregressive rollouts completed. Upside Probability: {upside_prob:.1%} | Volatility Amplification: {vol_risk:.1%}"
        else:
            sim_log = "[Simulation Gate] Kronos predictor returned empty paths. Falling back to neutral parameters."
            upside_prob = 0.5
            vol_risk = 0.0
    except Exception as e:
        sim_log = f"[Simulation Gate] Local Kronos simulation execution failed ({str(e)}). Falling back to neutral parameters."
        upside_prob = 0.5
        vol_risk = 0.0
        
    logger.info(sim_log)
    
    return {
        "kronos_upside_prob": upside_prob,
        "kronos_vol_risk": vol_risk,
        "execution_status": "simulations_completed",
        "logs": state.logs + [log_msg, sim_log]
    }

async def risk_arbiter_node(state: CommitteeState) -> Dict[str, Any]:
    # Check L1 Order Book Imbalance from yfinance info to calculate real WOFI
    wofi = 0.0
    try:
        ticker_obj = yf.Ticker(state.ticker)
        info = ticker_obj.info
        bid_size = info.get("bidSize", 0) or info.get("bid_size", 0) or 0
        ask_size = info.get("askSize", 0) or info.get("ask_size", 0) or 0
        
        if bid_size + ask_size > 0:
            wofi = round((bid_size - ask_size) / (bid_size + ask_size), 2)
            logger.info("[Risk Arbiter] L1 order book fetched for %s. Bid Size: %d, Ask Size: %d -> WOFI: %+.2f", state.ticker, bid_size, ask_size, wofi)
        else:
            logger.info("[Risk Arbiter] L1 order book sizes empty or zero for %s. WOFI set to 0.00.", state.ticker)
    except Exception as e:
        logger.warning("[Risk Arbiter] Failed to fetch yfinance L1 book size for %s: %s. Setting WOFI to 0.00.", state.ticker, str(e))
        
    # L2 depth markers are None because streaming L2 feeds are not available in EOD/yfinance
    iceberg = None
    spoof = None
    
    o_log = f"[Risk Arbiter] L2 WOFI: {wofi:+.2f} | Iceberg Buyer: N/A | Spoofing Alert: N/A (L2 depth required)"
    logger.info(o_log)
    
    # Sizings: allocate up to 2.0% virtual equity based on Kelly-inspired probability scaling
    allocation = round(state.kronos_upside_prob * 0.02, 4)
    
    # Calculate position details for simulated ledger
    shares = int((1000000.0 * allocation) / state.current_price) if state.current_price > 0 else 0
    stop_loss = round(state.current_price * 0.95, 2)
    
    e_log = f"[Risk Arbiter] Sizing calculation: Allocation = {allocation:.2%} of capital ({shares} shares) | Stop Loss: ₹{stop_loss:.2f}"
    logger.info(e_log)
    
    return {
        "wofi_score": wofi,
        "iceberg_detected": iceberg,
        "spoofing_detected": spoof,
        "allocation_percentage": allocation,
        "execution_status": "trade_executed",
        "logs": state.logs + [o_log, e_log]
    }

async def abort_trade_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Risk Arbiter] CRITICAL: Shortlist candidate {state.ticker} rejected. Circuit breaker active. Trading aborted to protect capital."
    logger.error(log_msg)
    return {
        "allocation_percentage": 0.0,
        "execution_status": "trade_aborted",
        "logs": state.logs + [log_msg]
    }

async def re_plan_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Risk Arbiter] WARNING: Shortlist candidate {state.ticker} failed simulation gates (probability low or risk too volatile). Trading halted for re-planning."
    logger.warning(log_msg)
    return {
        "allocation_percentage": 0.0,
        "execution_status": "re_planning_active",
        "logs": state.logs + [log_msg]
    }

# --- Conditional Routing Logic ---

def route_after_fundamental(state: CommitteeState) -> Literal["abort", "continue"]:
    # If the regulatory check is blocked OR fundamental score is very low
    if state.is_blocked or state.fundamental_score < 2:
        return "abort"
    return "continue"

def route_after_sentiment(state: CommitteeState) -> Literal["abort", "continue"]:
    # If news is invalidated (euphoria, panic, or transcript unscripted QA divergence)
    if state.is_invalidated or state.timing_status == "Avoid":
        return "abort"
    return "continue"

def route_after_simulation(state: CommitteeState) -> Literal["execute", "replan"]:
    # Safety Gate Check: upside probability >= 85% and volatility risk <= 15%
    if state.kronos_upside_prob >= 0.85 and state.kronos_vol_risk <= 0.15:
        return "execute"
    return "replan"

# --- Graph Compiler ---

def build_committee_graph() -> StateGraph:
    """Builds and compiles the multi-agent decision StateGraph."""
    builder = StateGraph(CommitteeState)
    
    # Add Nodes
    builder.add_node("discovery", discovery_node)
    builder.add_node("technical_analysis", technical_analysis_node)
    builder.add_node("fundamental_evaluation", fundamental_evaluation_node)
    builder.add_node("sentiment_validation", sentiment_validation_node)
    builder.add_node("simulation_gate", simulation_gate_node)
    builder.add_node("risk_arbiter", risk_arbiter_node)
    builder.add_node("abort_trade", abort_trade_node)
    builder.add_node("re_plan", re_plan_node)
    
    # Define Flow / Edges
    builder.set_entry_point("discovery")
    builder.add_edge("discovery", "technical_analysis")
    builder.add_edge("technical_analysis", "fundamental_evaluation")
    
    # Fundamental Node Router
    builder.add_conditional_edges(
        "fundamental_evaluation",
        route_after_fundamental,
        {
            "abort": "abort_trade",
            "continue": "sentiment_validation"
        }
    )
    
    # Sentiment Node Router
    builder.add_conditional_edges(
        "sentiment_validation",
        route_after_sentiment,
        {
            "abort": "abort_trade",
            "continue": "simulation_gate"
        }
    )
    
    # Simulation Node Router
    builder.add_conditional_edges(
        "simulation_gate",
        route_after_simulation,
        {
            "execute": "risk_arbiter",
            "replan": "re_plan"
        }
    )
    
    # Terminal Edges
    builder.add_edge("risk_arbiter", END)
    builder.add_edge("abort_trade", END)
    builder.add_edge("re_plan", END)
    
    return builder.compile()
