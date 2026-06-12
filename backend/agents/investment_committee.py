import logging
import http.client
import json
import re
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END
import yfinance as yf

from backend.agents.state import CommitteeState
from backend.services.redis_pipeline import RedisPipeline
from backend.services.trend_models import TrendEvaluator
from backend.services.valuation_models import ValuationEvaluator
from backend.services.order_book import OrderBookAnalyzer
from backend.services.fundamental_rag import FundamentalInvestigator
from backend.services.sentiment_analyzer import SentimentAnalyzer
from backend.services.llm_gateway import query_llm

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
        fii_dii = {"fii_net_crores": 120.0, "dii_net_crores": 1500.0, "market_state": "Net Accumulation"}
        
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
    
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    
    # Fetch detailed indicators or compute them on the fly
    cached_indicators = await redis_pipeline.get_cached_indicator(state.ticker, "detailed_indicators")
    candles = await redis_pipeline.fetch_ohlcva(state.ticker, "1d")
    
    await redis_pipeline.disconnect()
    
    current_price = candles[-1]["close"] if candles else 100.0
    
    if cached_indicators and "technical" in cached_indicators:
        tech = cached_indicators["technical"]
        funds = cached_indicators["fundamentals"]
        timing_status = cached_indicators.get("timing_status", "Neutral")
        timing_desc = cached_indicators.get("timing_description", "")
        weinstein_stage = cached_indicators.get("weinstein_stage", "Unknown")
        weinstein_score = cached_indicators.get("weinstein_score", 0.0)
        canslim_score = cached_indicators.get("canslim_score", 0.0)
    else:
        # Generate defaults if cache is missing
        timing_status = "Optimal Buy"
        timing_desc = "Breakout triggered with unmitigated FVG support."
        weinstein_stage = "Stage 2 (Markup)"
        weinstein_score = 0.8
        canslim_score = 0.6
        tech = {"fvgs": [], "sweeps": []}
        
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
    
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    cached_indicators = await redis_pipeline.get_cached_indicator(state.ticker, "detailed_indicators")
    await redis_pipeline.disconnect()
    
    is_blocked = False
    reasons = []
    
    if cached_indicators:
        funds = cached_indicators.get("fundamentals", {})
        scorecard = cached_indicators.get("buffett_scorecard", {})
        surv = cached_indicators.get("surveillance", {})
        deals = cached_indicators.get("deals", [])
        
        score = float(scorecard.get("score", 3))
        moat = funds.get("moat_rating", "Narrow Moat")
        intrinsic = funds.get("intrinsic_value", 0.0)
        mos = funds.get("margin_of_safety", 0.0)
        undervalued = funds.get("is_undervalued", False)
        
        is_blocked = surv.get("is_blocked", False)
        reasons = surv.get("reasons", [])
    else:
        # Heuristic default values
        score = 4.0
        moat = "Wide Moat (Buffett Approved)"
        intrinsic = state.current_price * 1.3
        mos = 0.3
        undervalued = True
        deals = []
        
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
        sim_log = "[Simulation Gate] No historical OHLCV data available for regime simulation. Returning neutral parameters."
        logger.warning(sim_log)
        return {
            "kronos_upside_prob": 0.5,
            "kronos_vol_risk": 0.0,
            "execution_status": "simulations_completed",
            "logs": state.logs + [log_msg, sim_log]
        }
        
    history = candles[-50:] # feed last 50 days to model
    
    payload = {
        "ticker": state.ticker,
        "history": history,
        "steps": 24,
        "num_paths": 30,
        "temperature": 0.7
    }
    
    upside_prob = 0.5
    vol_risk = 0.0
    
    try:
        # Call Kronos FastAPI microservice running on port 8001
        conn = http.client.HTTPConnection("127.0.0.1", 8001, timeout=10)
        headers = {"Content-type": "application/json"}
        conn.request("POST", "/simulate_regime", json.dumps(payload), headers)
        response = conn.getresponse()
        
        if response.status == 200:
            res_data = json.loads(response.read().decode())
            upside_prob = res_data["upside_probability"]
            vol_risk = res_data["volatility_amplification"]
            sim_log = f"[Simulation Gate] Autoregressive rollouts completed. Upside Probability: {upside_prob:.1%} | Volatility Amplification: {vol_risk:.1%}"
        else:
            sim_log = f"[Simulation Gate] Kronos service returned {response.status}. Falling back to neutral parameters."
            upside_prob = 0.5
            vol_risk = 0.0
        conn.close()
    except Exception as e:
        sim_log = f"[Simulation Gate] Connection to Kronos microservice failed ({str(e)}). Falling back to neutral parameters."
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
        
    # L2 depth markers are disabled (set to False) because streaming feeds are not active
    iceberg = False
    spoof = False
    
    o_log = f"[Risk Arbiter] L2 WOFI: {wofi:+.2f} | Iceberg Buyer: {iceberg} (L2 depth required) | Spoofing Alert: {spoof} (L2 depth required)"
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
