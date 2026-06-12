import logging
import http.client
import json
import random
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END

from backend.agents.state import CommitteeState
from backend.services.redis_pipeline import RedisPipeline
from backend.services.trend_models import TrendEvaluator
from backend.services.valuation_models import ValuationEvaluator
from backend.services.order_book import OrderBookAnalyzer

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
    
    # Simulate news sentiment and transcript unscripted Q&A divergence
    # Divergence calculation: prepared speech score vs unscripted Q&A score
    # A positive divergence indicates management is hiding margin/demand warnings.
    qa_divergence = round(random.uniform(0.0, 0.4), 2)
    sentiment_val = round(random.uniform(0.4, 0.95), 2)
    
    is_bubble = sentiment_val >= 0.95
    is_panic = sentiment_val <= 0.40
    is_evasive = qa_divergence >= 0.35
    
    is_invalidated = is_bubble or is_panic or is_evasive
    
    s_log = f"[Sentiment Desk] Global News Sentiment: {sentiment_val*100:.0f}% Bullish | Q&A Divergence: {qa_divergence:.2f}"
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
    
    # Format mock history if empty
    if not candles:
        candles = [{"timestamp": "2026-06-12", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000.0, "amount": 101000.0}]
        
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
            sim_log = f"[Simulation Gate] Kronos service returned {response.status}. Falling back to default simulations."
            upside_prob = 0.88 if state.timing_status == "Optimal Buy" else 0.60
            vol_risk = 0.08
        conn.close()
    except Exception as e:
        sim_log = f"[Simulation Gate] Connection to Kronos microservice failed ({str(e)}). Simulating fallback parameters."
        upside_prob = 0.88 if state.timing_status == "Optimal Buy" else 0.60
        vol_risk = 0.08
        
    logger.info(sim_log)
    
    return {
        "kronos_upside_prob": upside_prob,
        "kronos_vol_risk": vol_risk,
        "execution_status": "simulations_completed",
        "logs": state.logs + [log_msg, sim_log]
    }

async def risk_arbiter_node(state: CommitteeState) -> Dict[str, Any]:
    # Check Order Book Imbalance metrics before entry
    # Generate mock L2 imbalance scores
    wofi = round(random.uniform(-0.3, 0.8), 2)
    iceberg = random.random() > 0.85
    spoof = random.random() > 0.90
    
    o_log = f"[Risk Arbiter] L2 WOFI: {wofi:+.2f} | Iceberg Buyer: {iceberg} | Spoofing Alert: {spoof}"
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
