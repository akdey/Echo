import logging
import http.client
import json
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END

from backend.agents.state import CommitteeState
from backend.services.redis_pipeline import RedisPipeline
from backend.services.fundamental_rag import FundamentalInvestigator
from backend.services.sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)

# Core Multi-Agent Nodes
async def discovery_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Discovery Desk] Pulled shortlist candidate: {state.ticker}"
    logger.info(log_msg)
    return {
        "execution_status": "candidate_discovered",
        "current_price": 1263.0,  # mock/fetched latest price
        "logs": state.logs + [log_msg]
    }

async def fundamental_analysis_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Fundamental Desk] Commencing forensic RAG analysis for {state.ticker}..."
    logger.info(log_msg)
    
    investigator = FundamentalInvestigator()
    res = await investigator.investigate_ticker(state.ticker)
    
    score = res["fundamental_conviction_score"]
    f_log = f"[Fundamental Desk] Investigation complete. Conviction Score: {score:.2f}. Source: {res['source']}. Flags: {res['flags']}"
    logger.info(f_log)
    
    return {
        "fundamental_score": score,
        "execution_status": "fundamental_analyzed",
        "logs": state.logs + [log_msg, f_log]
    }

async def sentiment_validation_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Sentiment Desk] Scanning morning news feeds and exchange disclosures for {state.ticker}..."
    logger.info(log_msg)
    
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    
    analyzer = SentimentAnalyzer(redis_pipeline)
    res = await analyzer.analyze_sentiment(state.ticker)
    
    await redis_pipeline.disconnect()
    
    score = res["sentiment_score"]
    is_invalidated = res["is_invalidated"]
    s_log = f"[Sentiment Desk] Morning Sentiment Score: {score:.2f}. Bubble Mania: {res['is_bubble_mania']}. Invalidated: {is_invalidated}"
    logger.info(s_log)
    
    return {
        "sentiment_score": score,
        "is_invalidated": is_invalidated,
        "execution_status": "sentiment_validated",
        "logs": state.logs + [log_msg, s_log]
    }

async def simulation_gate_node(state: CommitteeState) -> Dict[str, Any]:
    log_msg = f"[Simulation Gate] Requesting autoregressive Monte Carlo rollouts from Kronos service..."
    logger.info(log_msg)
    
    # Connect to the local FastAPI Kronos service at port 8001
    # Generate mock history for simulation payload if database has empty twin
    history = [
        {"timestamp": f"2026-06-11T10:00:00+05:30", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000.0, "amount": 101000.0}
    ]
    
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
        conn = http.client.HTTPConnection("127.0.0.1", 8001, timeout=15)
        headers = {"Content-type": "application/json"}
        conn.request("POST", "/simulate_regime", json.dumps(payload), headers)
        response = conn.getresponse()
        if response.status == 200:
            res_data = json.loads(response.read().decode())
            upside_prob = res_data["upside_probability"]
            vol_risk = res_data["volatility_amplification"]
            gate_log = f"[Simulation Gate] Kronos output received. Upside Probability: {upside_prob:.2%}. Volatility Risk: {vol_risk:.2%}"
        else:
            gate_log = f"[Simulation Gate] Kronos server responded with status: {response.status}. Using conservative fallback metrics."
        conn.close()
    except Exception as e:
        gate_log = f"[Simulation Gate] Connection to Kronos service failed: {str(e)}. Using safe fallback metrics."
        logger.warning(gate_log)
        
    logger.info(gate_log)
    
    return {
        "kronos_upside_prob": upside_prob,
        "kronos_vol_risk": vol_risk,
        "execution_status": "simulations_completed",
        "logs": state.logs + [log_msg, gate_log]
    }

async def risk_arbiter_node(state: CommitteeState) -> Dict[str, Any]:
    # Pass check: Risk Arbiter sizing calculation
    # Sizing formula: allocate up to 2% virtual account equity if upside probability is maximum (1.0)
    allocation = float(state.kronos_upside_prob * 0.02)
    log_msg = f"[Risk Arbiter] Trade Approved! Position sizing finalized: {allocation:.2%} of simulated equity. Placing paper order."
    logger.info(log_msg)
    return {
        "allocation_percentage": allocation,
        "execution_status": "trade_executed",
        "logs": state.logs + [log_msg]
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

# Conditional Routing Logic
def route_after_sentiment(state: CommitteeState) -> Literal["abort", "continue"]:
    # If the sentiment is invalidated OR fundamental conviction drops below 0.4
    if state.is_invalidated or state.fundamental_score < 0.4:
        return "abort"
    return "continue"

def route_after_simulation(state: CommitteeState) -> Literal["execute", "replan"]:
    # Safety Gate Check: upside probability >= 85% and volatility risk <= 15%
    if state.kronos_upside_prob >= 0.85 and state.kronos_vol_risk <= 0.15:
        return "execute"
    return "replan"

def build_committee_graph() -> StateGraph:
    """Builds and compiles the multi-agent decision StateGraph."""
    # Define state schema using dict representation for LangGraph compatibility
    builder = StateGraph(CommitteeState)
    
    # Add Nodes
    builder.add_node("discovery", discovery_node)
    builder.add_node("fundamental_analysis", fundamental_analysis_node)
    builder.add_node("sentiment_validation", sentiment_validation_node)
    builder.add_node("simulation_gate", simulation_gate_node)
    builder.add_node("risk_arbiter", risk_arbiter_node)
    builder.add_node("abort_trade", abort_trade_node)
    builder.add_node("re_plan", re_plan_node)
    
    # Define Flow / Edges
    builder.set_entry_point("discovery")
    builder.add_edge("discovery", "fundamental_analysis")
    builder.add_edge("fundamental_analysis", "sentiment_validation")
    
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
