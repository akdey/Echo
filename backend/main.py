import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.investment_committee import build_committee_graph
from backend.agents.state import CommitteeState
from backend.services.redis_pipeline import RedisPipeline
from backend.services.screener_daemon import ScreenerDaemon
from backend.services.thematic_engine import ThematicCatalystAnalyzer
from backend.services.data_fetcher import DataFetcher, InsiderDisclosureCrawler
from backend.services.embeddings import generate_embedding
from backend.services.conviction_engine import run_conviction_scoring
from backend.services.sector_momentum_service import calculate_sector_momentum
from backend.services.alert_dispatcher import dispatch_conviction_alerts
from backend.services.risk_engine import (
    MacroRegimeFilter,
    PreMarketSanityCheck,
    ChandelierExit,
    KellyCriterion,
    get_market_regime,
    run_premarket_checks,
    scan_exit_signals,
    get_position_size,
)
from backend.services.supabase_client import (
    query_supabase,
    upsert_supabase,
    delete_supabase,
    verify_supabase_connection,
    IS_SUPABASE_CONFIGURED
)
import yfinance as yf
import pandas as pd
import numpy as np
from backend.services.news_engine import (
    run_full_news_pipeline,
    MacroNewsEngine,
    CorporateAnnouncementCrawler,
    WatchlistNewsScanner,
    fetch_active_overrides
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Echo API Gateway",
    description="Bridge connecting the LangGraph Investment Committee to the React Dashboard Visualizer.",
    version="2.0.0"
)

# Enable CORS for local React/Vite development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global queue to stream state transitions for SSE
transition_queue = asyncio.Queue()

class TickerRequest(BaseModel):
    ticker: str

class ThematicRequest(BaseModel):
    catalyst_text: str

class NodeModel(BaseModel):
    id: str
    type: str
    label: str
    description: Optional[str] = None

class EdgeModel(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    role: Optional[str] = None
    pricing_power: Optional[str] = None
    catalyst_relevance: Optional[str] = None
    timestamp: Optional[int] = None

class TradeJournalEntry(BaseModel):
    symbol: str
    entry_date: str                     # ISO date string "YYYY-MM-DD"
    entry_price: float
    quantity: int
    conviction_score: int               # 0-100
    catalyst: Optional[str] = None
    stop_loss: float
    target_price: Optional[float] = None

class TradeJournalExit(BaseModel):
    trade_id: str                       # UUID from trade_journal
    exit_date: str
    exit_price: float
    outcome_notes: Optional[str] = None

class ConvictionRunRequest(BaseModel):
    symbols: Optional[List[str]] = None  # None = run over all companies


@app.on_event("startup")
async def startup_event():
    """Initializes cached items and database connections on startup."""
    logger.info("Initializing system cache and database checks...")
    
    # Verify Supabase connection
    if IS_SUPABASE_CONFIGURED:
        conn_ok = await verify_supabase_connection()
        if conn_ok:
            logger.info("Supabase PostgreSQL database connection verified successfully.")
        else:
            logger.warning("Supabase PostgreSQL connection failed. Check credentials.")
    else:
        logger.warning("Supabase credentials are not configured in environment.")

    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    
    # Run initial screening task in a background task if cache is empty
    candidates = await redis_pipeline.get_cached_indicator("SCREENER", "candidates")
    if not candidates:
        logger.info("Screener cache empty on startup. Triggering initial background crawler scan...")
        daemon = ScreenerDaemon(redis_pipeline)
        asyncio.create_task(daemon.execute_daily_screening())
        
    await redis_pipeline.disconnect()

@app.get("/api/screen")
async def get_screened_candidates():
    """
    Returns the list of candidates discovered by the background screening daemon.
    """
    redis_pipeline = RedisPipeline()
    await redis_pipeline.connect()
    try:
        candidates = await redis_pipeline.get_cached_indicator("SCREENER", "candidates")
        if not candidates:
            # If not cached, trigger a quick scan and return results
            logger.info("Screener cache empty during API request. Executing screening...")
            daemon = ScreenerDaemon(redis_pipeline)
            candidates = await daemon.execute_daily_screening()
        return {"status": "success", "count": len(candidates), "candidates": candidates}
    except Exception as e:
        logger.error("Failed to fetch screened candidates: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await redis_pipeline.disconnect()

@app.post("/api/analyze")
async def analyze_ticker(payload: TickerRequest):
    """
    Triggers the LangGraph Investment Committee state graph for a ticker
    and places the node execution updates into the streaming queue.
    """
    ticker = payload.ticker.upper()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker += ".NS"
        
    logger.info("Initializing multi-agent analysis loop for ticker: %s", ticker)
    graph = build_committee_graph()
    
    # Initialize state
    initial_state = CommitteeState(
        ticker=ticker,
        logs=[]
    )
    
    try:
        final_state_dict = {}
        async for output in graph.astream(initial_state):
            node_name = list(output.keys())[0]
            updates = output[node_name]
            
            update_msg = {
                "node": node_name,
                "status": f"Node '{node_name}' finished execution.",
                "ticker": ticker,
                "updates": updates
            }
            await transition_queue.put(update_msg)
            logger.info("Streamed node update: %s", node_name)
            
            final_state_dict.update(updates)
            await asyncio.sleep(0.5)
            
        return {"status": "success", "final_state": final_state_dict}
    except Exception as e:
        logger.error("Failed to run committee state graph: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thematic_analyze")
async def thematic_analyze(payload: ThematicRequest):
    """
    Ingests policy/budget updates, vectorizes search parameters,
    performs pgvector semantic search to find suppliers in Supabase,
    and runs retail safety checks.
    """
    logger.info("Received request for thematic catalyst analysis.")
    redis_pipeline = RedisPipeline()
    analyzer = ThematicCatalystAnalyzer(redis_pipeline)
    try:
        results = await analyzer.analyze_thematic_chain(payload.catalyst_text)
        return results
    except Exception as e:
        logger.error("Failed to execute thematic analysis: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/thematic/graph")
async def get_thematic_graph():
    """Retrieves all registered company profiles from Supabase."""
    try:
        data = await query_supabase("companies", {"select": "symbol,name,sector,industry,market_cap_cr,description"})
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error("Failed to retrieve companies list: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thematic/node")
async def add_thematic_node(payload: NodeModel):
    """Creates or updates a company profile (with embedding) in Supabase."""
    try:
        emb = generate_embedding(payload.description or "")
        row = {
            "symbol": payload.id.upper(),
            "name": payload.label,
            "description": payload.description or "No description available.",
            "description_embedding": emb,
            "sector": "N/A",
            "industry": "N/A"
        }
        await upsert_supabase("companies", [row])
        return {"status": "success", "message": f"Company profile '{payload.id}' added/updated."}
    except Exception as e:
        logger.error("Failed to add company profile: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/thematic/node/{node_id}")
async def delete_thematic_node(node_id: str):
    """Deletes a company profile from Supabase."""
    try:
        await delete_supabase("companies", {"symbol": f"eq.{node_id.upper()}"})
        return {"status": "success", "message": f"Company '{node_id}' deleted."}
    except Exception as e:
        logger.error("Failed to delete company: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thematic/edge")
async def add_thematic_edge(payload: EdgeModel):
    """Deprecated: Thematic relationships are now dynamically computed via pgvector."""
    return {"status": "deprecated", "message": "Thematic relationships are now dynamically computed via pgvector RAG matches."}

@app.delete("/api/thematic/edge/{edge_id}")
async def delete_thematic_edge(edge_id: int):
    """Deprecated: Thematic relationships are now dynamically computed via pgvector."""
    return {"status": "deprecated", "message": "Thematic relationships are now dynamically computed via pgvector RAG matches."}

@app.post("/api/thematic/crawl")
async def trigger_thematic_crawl():
    """Manually triggers the daily NSE Bhavcopy crawl and Supabase ingestion."""
    redis_pipeline = RedisPipeline()
    fetcher = DataFetcher(redis_pipeline)
    try:
        results = await fetcher.ingest_latest_bhavcopy()
        return results
    except Exception as e:
        logger.error("Failed to execute Bhavcopy ingest: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stream_pipeline")
async def stream_pipeline():
    """
    Exposes a Server-Sent Events (SSE) stream containing real-time agent execution transitions.
    """
    async def event_generator():
        while True:
            try:
                msg = await transition_queue.get()
                yield f"data: {json.dumps(msg)}\n\n"
                transition_queue.task_done()
            except asyncio.CancelledError:
                logger.info("SSE client disconnected.")
                break
            except Exception as e:
                logger.error("SSE stream error: %s", str(e))
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 12 — Conviction Matrix, Sector Heatmap, Insider Feed, Trade Journal
# ═══════════════════════════════════════════════════════════════════════════════

# ── Conviction Matrix ──────────────────────────────────────────────────────────

@app.post("/api/conviction/run")
async def run_conviction_matrix(payload: ConvictionRunRequest):
    """
    Triggers a full (or partial) nightly conviction scoring run.
    Scores each stock 0-100 across 5 data layers, upserts to Supabase,
    and dispatches Telegram/email alerts for any score >= threshold.

    Pass `symbols: ["RELIANCE.NS", "TCS.NS"]` to score a subset only.
    Pass no body to score ALL companies in the Supabase `companies` table.
    """
    if not IS_SUPABASE_CONFIGURED:
        raise HTTPException(status_code=503, detail="Supabase not configured.")
    try:
        logger.info("[API] Starting conviction scoring run...")

        # Pull current surveillance list from Supabase for trap detection
        surv_rows = await query_supabase("surveillance", {"select": "symbol"})
        surv_set  = {r["symbol"].replace(".NS", "").replace(".BO", "") for r in surv_rows}

        scored = await run_conviction_scoring(
            symbols=payload.symbols,
            surveillance_symbols=surv_set,
        )
        alert_result = await dispatch_conviction_alerts(scored)

        return {
            "status": "success",
            "scored_count": len(scored),
            "top_10": scored[:10],
            "alert_result": alert_result,
        }
    except Exception as e:
        logger.error("[API] Conviction run failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/conviction")
async def get_conviction_list(min_score: int = 0, limit: int = 50):
    """
    Returns the latest cached conviction scores from Supabase,
    sorted descending by conviction_score.

    Query params:
      - min_score (int): filter to scores >= this value (default 0)
      - limit (int): number of records to return (default 50, max 200)
    """
    limit = min(limit, 200)
    try:
        rows = await query_supabase("conviction_matrix", {
            "select": "*",
            "conviction_score": f"gte.{min_score}",
            "order": "conviction_score.desc",
            "limit": str(limit),
        })
        return {"status": "success", "count": len(rows), "results": rows}
    except Exception as e:
        logger.error("[API] Failed to fetch conviction list: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Sector Rotation Heatmap ───────────────────────────────────────────────────

@app.post("/api/sectors/refresh")
async def refresh_sector_momentum():
    """
    Fetches fresh Nifty sectoral index data from yfinance,
    computes relative strength vs Nifty 50, and upserts to Supabase.
    Returns the full sorted heatmap payload.
    """
    try:
        result = await calculate_sector_momentum()
        return {"status": "success", "sectors": result}
    except Exception as e:
        logger.error("[API] Sector momentum refresh failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sectors")
async def get_sector_heatmap():
    """
    Returns the cached sector momentum heatmap from Supabase.
    Each record contains: sector_name, rs_score, rs_change_4w, momentum_regime.
    """
    try:
        rows = await query_supabase("sector_momentum", {
            "select": "*",
            "order": "rs_score.desc",
        })
        # Sort locally by regime order: LEAD, IMPROVE, WEAKEN, LAG
        regime_order = {"LEAD": 0, "IMPROVE": 1, "WEAKEN": 2, "LAG": 3}
        rows.sort(key=lambda r: regime_order.get(r.get("momentum_regime", "LAG"), 4))
        return {"status": "success", "sectors": rows}
    except Exception as e:
        logger.error("[API] Failed to fetch sector heatmap: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── NSE Insider / Promoter Disclosure Feed ─────────────────────────────────────

@app.post("/api/insiders/crawl")
async def crawl_insider_disclosures():
    """
    Manually triggers the NSE SASTI insider disclosure crawler.
    Scans the last 7 days of NSE archives and upserts new filings.
    """
    try:
        crawler = InsiderDisclosureCrawler()
        result = await crawler.crawl_latest()
        return result
    except Exception as e:
        logger.error("[API] Insider crawl failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/insiders")
async def get_insider_disclosures(symbol: Optional[str] = None, limit: int = 100):
    """
    Returns insider/promoter trading disclosures.

    Query params:
      - symbol (str): filter by stock symbol e.g. "RELIANCE.NS" (optional)
      - limit (int): max records (default 100, max 500)
    """
    limit = min(limit, 500)
    params: Dict[str, Any] = {
        "select": "*",
        "order": "trade_date.desc",
        "limit": str(limit),
    }
    if symbol:
        params["symbol"] = f"eq.{symbol.upper()}"
    try:
        rows = await query_supabase("insider_disclosures", params)
        return {"status": "success", "count": len(rows), "disclosures": rows}
    except Exception as e:
        logger.error("[API] Failed to fetch insider disclosures: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Private Trade Journal ─────────────────────────────────────────────────────

@app.get("/api/journal")
async def get_journal(symbol: Optional[str] = None):
    """
    Returns all private trade journal entries, newest first.
    Optionally filtered to a single symbol.
    """
    params: Dict[str, Any] = {
        "select": "*",
        "order": "entry_date.desc",
        "limit": "500",
    }
    if symbol:
        params["symbol"] = f"eq.{symbol.upper()}"
    try:
        rows = await query_supabase("trade_journal", params)
        return {"status": "success", "count": len(rows), "entries": rows}
    except Exception as e:
        logger.error("[API] Failed to fetch trade journal: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/journal")
async def log_trade_entry(payload: TradeJournalEntry):
    """
    Logs a new trade entry in the private trade journal.
    Requires a stop-loss — no stop, no trade.
    """
    symbol = payload.symbol.upper()
    if not symbol.endswith((".NS", ".BO")):
        symbol += ".NS"

    if payload.stop_loss >= payload.entry_price:
        raise HTTPException(
            status_code=400,
            detail="Stop-loss must be below entry price for long positions."
        )
    if not (0 <= payload.conviction_score <= 100):
        raise HTTPException(status_code=400, detail="conviction_score must be 0-100.")

    row = {
        "symbol":          symbol,
        "entry_date":      payload.entry_date,
        "entry_price":     payload.entry_price,
        "quantity":        payload.quantity,
        "conviction_score": payload.conviction_score,
        "catalyst":        payload.catalyst,
        "stop_loss":       payload.stop_loss,
        "target_price":    payload.target_price,
    }
    try:
        result = await upsert_supabase("trade_journal", [row])
        return {"status": "success", "entry": result}
    except Exception as e:
        logger.error("[API] Failed to log trade entry: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/journal/exit")
async def log_trade_exit(payload: TradeJournalExit):
    """
    Records the exit price and outcome for an existing trade entry.
    Computes P&L automatically from the entry price stored in Supabase.
    """
    try:
        existing = await query_supabase("trade_journal", {
            "id": f"eq.{payload.trade_id}",
            "select": "entry_price,quantity",
        })
        if not existing:
            raise HTTPException(status_code=404, detail="Trade journal entry not found.")

        entry_price = float(existing[0]["entry_price"])
        quantity    = int(existing[0]["quantity"])
        pnl         = round((payload.exit_price - entry_price) * quantity, 2)

        update_row = {
            "id":            payload.trade_id,
            "exit_date":     payload.exit_date,
            "exit_price":    payload.exit_price,
            "pnl":           pnl,
            "outcome_notes": payload.outcome_notes,
            "updated_at":    __import__("datetime").datetime.utcnow().isoformat(),
        }
        result = await upsert_supabase("trade_journal", [update_row])
        return {"status": "success", "pnl": pnl, "entry": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[API] Failed to log trade exit: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/journal/{trade_id}")
async def delete_journal_entry(trade_id: str):
    """Permanently deletes a trade journal entry."""
    try:
        await delete_supabase("trade_journal", {"id": f"eq.{trade_id}"})
        return {"status": "success", "message": f"Trade {trade_id} deleted."}
    except Exception as e:
        logger.error("[API] Failed to delete journal entry: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Nightly Full-Stack Job ────────────────────────────────────────────────────

@app.post("/api/jobs/nightly")
async def trigger_nightly_job():
    """
    Convenience endpoint that chains the full nightly pipeline in order:
      1. Bhavcopy ingest (EOD prices + delivery volume)
      2. Insider disclosures crawl (NSE SASTI)
      3. Sector momentum refresh (Nifty sectoral RS)
      4. Conviction matrix scoring + alert dispatch

    Designed to be called by a free Hugging Face cron Space or cron-job.org
    at ~8:30 PM IST on market days.
    """
    results: Dict[str, Any] = {}

    try:
        redis = RedisPipeline()
        fetcher = DataFetcher(redis)
        results["bhavcopy"] = await fetcher.ingest_latest_bhavcopy()
    except Exception as e:
        results["bhavcopy"] = {"status": "error", "detail": str(e)}

    try:
        crawler = InsiderDisclosureCrawler()
        results["insider_crawl"] = await crawler.crawl_latest()
    except Exception as e:
        results["insider_crawl"] = {"status": "error", "detail": str(e)}

    try:
        results["sector_momentum"] = {"status": "success", "sectors": len(await calculate_sector_momentum())}
    except Exception as e:
        results["sector_momentum"] = {"status": "error", "detail": str(e)}

    try:
        surv_rows = await query_supabase("surveillance", {"select": "symbol"})
        surv_set  = {r["symbol"].replace(".NS", "").replace(".BO", "") for r in surv_rows}
        scored    = await run_conviction_scoring(surveillance_symbols=surv_set)
        results["conviction"] = await dispatch_conviction_alerts(scored)
        results["conviction"]["scored_count"] = len(scored)
    except Exception as e:
        results["conviction"] = {"status": "error", "detail": str(e)}

    return {"status": "success", "pipeline_results": results}


# ════════════════════════════════════════════════════════════════════════════════
# RISK ENGINE ENDPOINTS  (Phase 14)
# ════════════════════════════════════════════════════════════════════════════════


class ChandelierRequest(BaseModel):
    symbol:       str
    entry_date:   str           # ISO date "YYYY-MM-DD"
    entry_price:  float


class KellyRequest(BaseModel):
    total_capital: float        # INR — total investable capital


class PreMarketSymbolRequest(BaseModel):
    symbol:            str
    prev_close:        Optional[float] = None


@app.get(
    "/api/risk/regime",
    summary="Macro Regime Filter",
    description=(
        "Evaluates whether the broad market is in RISK_ON or RISK_OFF mode. "
        "RISK_OFF is triggered when: (1) Nifty 50 closes below its 20-day EMA, "
        "(2) Nifty Midcap 150 closes below its 50-day EMA, or "
        "(3) 5-day cumulative FII flow is below −60,000 Cr. "
        "In RISK_OFF mode, the conviction engine suppresses all buy signals."
    ),
)
async def get_regime_endpoint():
    """
    Returns current market regime with supporting metrics.
    Use this before placing any trade to confirm the macro environment is constructive.
    """
    try:
        return await get_market_regime()
    except Exception as e:
        logger.error("[API] /api/risk/regime failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/risk/premarket",
    summary="Pre-Market Gap Check (All Open Positions)",
    description=(
        "Runs at 9:15:05 AM IST. Checks every open trade journal position for "
        "abnormal gap-ups (> 3%) or gap-downs (> 2%) at the opening price. "
        "Returns ABORT_GAP_UP, CAUTION_GAP_DOWN, or PROCEED for each position."
    ),
)
async def premarket_all_positions():
    """
    Batch pre-market sanity check for all open journal positions.
    Schedule this endpoint to be called at 9:15:05 AM IST via a cron or APScheduler.
    """
    try:
        results = await run_premarket_checks()
        aborts   = [r for r in results if r["action"] == "ABORT_GAP_UP"]
        cautions = [r for r in results if r["action"] == "CAUTION_GAP_DOWN"]
        proceed  = [r for r in results if r["action"] == "PROCEED"]
        return {
            "status":    "success",
            "summary":   {
                "abort_count":   len(aborts),
                "caution_count": len(cautions),
                "proceed_count": len(proceed),
            },
            "results":   results,
        }
    except Exception as e:
        logger.error("[API] /api/risk/premarket failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/risk/premarket/symbol",
    summary="Pre-Market Gap Check (Single Symbol)",
)
async def premarket_single_symbol(req: PreMarketSymbolRequest):
    """
    Checks a single NSE symbol for an opening gap.
    Use before executing an AMO or placing a morning trade.
    """
    try:
        checker = PreMarketSanityCheck()
        return await checker.check_symbol(
            symbol=req.symbol,
            fallback_prev_close=req.prev_close,
        )
    except Exception as e:
        logger.error("[API] /api/risk/premarket/symbol failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/risk/exits",
    summary="Chandelier Exit Scan (All Open Positions)",
    description=(
        "Scans every open journal position and calculates the Chandelier Exit stop "
        "(Highest High since entry − 3 × ATR14). Returns EXIT_SIGNAL for any position "
        "where the latest close has broken below the trailing stop."
    ),
)
async def scan_exits_endpoint():
    """
    Returns Chandelier Exit status for all open positions.
    EXIT_SIGNAL positions are returned first.
    Run this nightly or intraday after 3:30 PM IST.
    """
    try:
        results    = await scan_exit_signals()
        exits      = [r for r in results if r["action"] == "EXIT_SIGNAL"]
        holds      = [r for r in results if r["action"] == "HOLD"]
        return {
            "status":        "success",
            "exit_signals":  len(exits),
            "hold_count":    len(holds),
            "results":       results,
        }
    except Exception as e:
        logger.error("[API] /api/risk/exits failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/risk/exit/symbol",
    summary="Chandelier Exit (Single Symbol)",
    description="Calculates the ATR14-based Chandelier trailing stop for a single open position.",
)
async def chandelier_single(req: ChandelierRequest):
    """
    Compute ATR-based trailing stop for a specific trade.
    Useful for portfolio review before market open.
    """
    try:
        engine = ChandelierExit()
        return await engine.calculate_for_trade(
            symbol=req.symbol,
            entry_date=req.entry_date,
            entry_price=req.entry_price,
        )
    except Exception as e:
        logger.error("[API] /api/risk/exit/symbol failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/risk/position-size",
    summary="Kelly Criterion Position Sizing",
    description=(
        "Calculates the mathematically optimal position size using Half-Kelly Criterion "
        "derived from your historical journal win-rate and average R:R ratio. "
        "Requires at least 20 closed trades in the journal for reliable output."
    ),
)
async def position_size_endpoint(req: KellyRequest):
    """
    Returns the suggested allocation per trade as both a percentage and INR amount.
    Minimum 20 closed trades required; below that threshold returns a conservative 2% default.
    """
    if req.total_capital <= 0:
        raise HTTPException(status_code=400, detail="total_capital must be a positive number.")
    try:
        return await get_position_size(req.total_capital)
    except Exception as e:
        logger.error("[API] /api/risk/position-size failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/risk/portfolio",
    summary="Full Portfolio Risk Scan",
    description=(
        "Runs all four risk layers simultaneously: "
        "(1) Macro Regime Filter, "
        "(2) Pre-Market Gap Check on all open positions, "
        "(3) Chandelier Exit scan, "
        "(4) Kelly position sizing for the given capital. "
        "This is the master risk dashboard endpoint."
    ),
)
async def portfolio_risk_scan(
    capital: float = Query(default=1000000.0, description="Total investable capital in INR"),
):
    """
    Master risk dashboard. Run this every morning before market open.
    Returns regime, all pre-market gap checks, all exit signals, and position sizing.
    """
    results: Dict[str, Any] = {}

    # Run all four layers concurrently
    regime_task     = asyncio.create_task(get_market_regime())
    premarket_task  = asyncio.create_task(run_premarket_checks())
    exits_task      = asyncio.create_task(scan_exit_signals())
    kelly_task      = asyncio.create_task(get_position_size(capital))

    regime, premarket, exits, kelly = await asyncio.gather(
        regime_task, premarket_task, exits_task, kelly_task,
        return_exceptions=True,
    )

    results["regime"] = regime if not isinstance(regime, Exception) else {
        "error": str(regime)
    }
    results["premarket_checks"] = {
        "summary": {
            "aborts":   len([r for r in (premarket or []) if isinstance(r, dict) and r.get("action") == "ABORT_GAP_UP"]),
            "cautions": len([r for r in (premarket or []) if isinstance(r, dict) and r.get("action") == "CAUTION_GAP_DOWN"]),
            "proceed":  len([r for r in (premarket or []) if isinstance(r, dict) and r.get("action") == "PROCEED"]),
        },
        "positions": premarket if not isinstance(premarket, Exception) else [],
    }
    results["exit_signals"] = {
        "count":     len([r for r in (exits or []) if isinstance(r, dict) and r.get("action") == "EXIT_SIGNAL"]),
        "positions": exits if not isinstance(exits, Exception) else [],
    }
    results["position_sizing"] = kelly if not isinstance(kelly, Exception) else {
        "error": str(kelly)
    }

    # Overall risk status
    regime_ok     = isinstance(regime, dict) and regime.get("regime") == "RISK_ON"
    exit_count    = results["exit_signals"]["count"]
    abort_count   = results["premarket_checks"]["summary"]["aborts"]
    results["overall_status"] = (
        "ALL_CLEAR" if (regime_ok and exit_count == 0 and abort_count == 0)
        else "REVIEW_REQUIRED"
    )
    results["alerts"] = []
    if not regime_ok:
        results["alerts"].append(f"⛔ Market is RISK_OFF — no new positions should be opened.")
    if exit_count > 0:
        results["alerts"].append(f"⚠️ {exit_count} position(s) have triggered Chandelier Exit — review for sell.")
    if abort_count > 0:
        results["alerts"].append(f"🚨 {abort_count} trade(s) have gap-up > 3% at open — abort those AMOs.")

    return {"status": "success", **results}


# ── NEWS ENGINE ENDPOINTS ─────────────────────────────────────────────────────

@app.post("/api/news/pipeline")
async def trigger_news_pipeline():
    """
    Manually triggers the full Three-Tier News Ingestion Pipeline.
    Runs Tier 1 (Macro) -> Tier 2 (Corporate Announcements) -> Tier 3 (Watchlist scans)
    sequentially and returns the accumulated signals and overrides.
    """
    try:
        results = await run_full_news_pipeline()
        return {"status": "success", "pipeline_results": results}
    except Exception as e:
        logger.error("[API] News pipeline execution failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/news/crawl/{tier}")
async def crawl_news_tier(tier: int):
    """
    Triggers news crawling for a specific tier manually:
      - Tier 1: Global Macro (DuckDuckGo News)
      - Tier 2: Corporate Announcements (NSE API announcements crawler)
      - Tier 3: Watchlist-Targeted News Sentiment
    """
    if tier not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail="Invalid news tier. Must be 1, 2, or 3.")
    
    try:
        if tier == 1:
            result = await MacroNewsEngine().run()
        elif tier == 2:
            result = await CorporateAnnouncementCrawler().run()
        else:
            result = await WatchlistNewsScanner().run()
        return {"status": "success", "tier": tier, "result": result}
    except Exception as e:
        logger.error("[API] Crawl for tier %d failed: %s", tier, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/signals")
async def get_news_signals(limit: int = 100):
    """Returns the processed news signals from Supabase news_signals table."""
    limit = min(limit, 200)
    try:
        rows = await query_supabase("news_signals", {
            "select": "*",
            "order": "processed_at.desc",
            "limit": str(limit),
        })
        return {"status": "success", "count": len(rows), "signals": rows}
    except Exception as e:
        logger.error("[API] Failed to fetch news signals: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/overrides")
async def get_conviction_overrides():
    """Returns all active (non-expired) conviction overrides."""
    try:
        # Call the helper RPC or query table directly
        rows = await rpc_supabase("get_active_conviction_overrides", {})
        if not rows:
            # Fall back to manual filter if RPC is not registered
            now_iso = __import__("datetime").datetime.utcnow().isoformat()
            rows = await query_supabase("conviction_overrides", {
                "select": "*",
                "expires_at": f"gt.{now_iso}",
                "limit": "200",
            })
        return {"status": "success", "overrides": rows}
    except Exception as e:
        logger.error("[API] Failed to fetch overrides: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/catalysts")
async def get_today_catalysts():
    """Returns all material corporate catalysts flagged within the last 24 hours."""
    try:
        # Query the view or run manual query
        now_iso = (__import__("datetime").datetime.utcnow() - __import__("datetime").timedelta(hours=24)).isoformat()
        rows = await query_supabase("news_signals", {
            "select": "*",
            "tier": "eq.2",
            "is_material_catalyst": "eq.true",
            "processed_at": f"gt.{now_iso}",
            "order": "processed_at.desc",
            "limit": "100",
        })
        return {"status": "success", "count": len(rows), "catalysts": rows}
    except Exception as e:
        logger.error("[API] Failed to fetch material catalysts: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── DATA HISTORY & SIMULATION ENDPOINTS ───────────────────────────────────────

@app.get("/api/history/{symbol}")
async def get_symbol_history(symbol: str, limit: int = 100):
    """
    Returns the last `limit` daily bars for the given stock from Supabase daily_bhavcopy.
    Falls back to yfinance history if Supabase is empty or not configured.
    """
    symbol = symbol.upper()
    if not symbol.endswith((".NS", ".BO")):
        symbol += ".NS"
    
    rows = []
    if IS_SUPABASE_CONFIGURED:
        try:
            # Query Supabase daily_bhavcopy table
            rows = await query_supabase("daily_bhavcopy", {
                "symbol": f"eq.{symbol}",
                "order": "trade_date.desc",
                "limit": str(limit),
            })
            # Reverse to chronological order
            rows.reverse()
        except Exception as e:
            logger.warning("[API] Failed to fetch history from Supabase: %s", e)
            
    if not rows:
        # Fall back to yfinance
        try:
            loop = asyncio.get_event_loop()
            ticker_obj = yf.Ticker(symbol)
            df = await loop.run_in_executor(
                None,
                lambda: ticker_obj.history(period="6mo", interval="1d")
            )
            if not df.empty:
                # Keep last `limit` rows
                df = df.tail(limit)
                df = df.reset_index()
                for _, row in df.iterrows():
                    # Format date string
                    t_val = row.get("Date")
                    if isinstance(t_val, pd.Timestamp):
                        trade_date = t_val.date().isoformat()
                    else:
                        trade_date = str(t_val).split(" ")[0]
                        
                    rows.append({
                        "trade_date": trade_date,
                        "close": float(row["Close"]),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "volume": int(row["Volume"]),
                        "delivery_pct": 0.0, # no delivery info in yfinance
                        "delivery_volume": 0
                    })
        except Exception as e:
            logger.error("[API] yfinance history fallback failed for %s: %s", symbol, e)
            raise HTTPException(status_code=500, detail=f"Failed to load history for {symbol}")
            
    return {"status": "success", "symbol": symbol, "history": rows}


@app.get("/api/simulate/{symbol}")
async def run_symbol_simulation(symbol: str):
    """
    Runs a Kronos Monte Carlo simulation for the given stock.
    Fetches the latest 50 daily close bars and runs the simulator.
    """
    symbol = symbol.upper()
    if not symbol.endswith((".NS", ".BO")):
        symbol += ".NS"
        
    # 1. Fetch latest 50 days of history
    history_resp = await get_symbol_history(symbol, limit=50)
    history = history_resp.get("history", [])
    if not history:
        raise HTTPException(status_code=400, detail=f"No history found for {symbol}")
        
    # Convert history keys to the expected CandleInput fields (volume, amount)
    formatted_history = []
    for h in history:
        close = float(h.get("close", 0.0))
        vol = float(h.get("volume", 0.0))
        formatted_history.append({
            "timestamp": h.get("trade_date") or h.get("timestamp") or "",
            "open": float(h.get("open", close)),
            "high": float(h.get("high", close)),
            "low": float(h.get("low", close)),
            "close": close,
            "volume": vol,
            "amount": close * vol
        })
        
    try:
        from backend.services.kronos_brain import KronosPredictor
        predictor = KronosPredictor()
        
        loop = asyncio.get_event_loop()
        paths = await loop.run_in_executor(
            None,
            lambda: predictor.run_monte_carlo_rollout(
                formatted_history,
                steps=24,
                num_paths=30,
                temperature=0.7
            )
        )
        
        if not paths:
            raise HTTPException(status_code=400, detail="Failed to run simulations.")
            
        start_close = formatted_history[-1]["close"]
        final_closes = [path[-1]["close"] for path in paths]
        successful_paths = sum(1 for fc in final_closes if fc >= start_close)
        upside_probability = float(successful_paths / len(paths))
        
        std_final_closes = float(np.std(final_closes))
        volatility_amplification = float(std_final_closes / start_close) if start_close > 0 else 0.0
        is_safe = bool(upside_probability >= 0.85 and volatility_amplification <= 0.15)
        
        # Return first 3 sample paths for visualization, plus summary stats
        return {
            "status": "success",
            "symbol": symbol,
            "upside_probability": upside_probability,
            "volatility_amplification": volatility_amplification,
            "is_safe": is_safe,
            "paths": paths[:3]
        }
    except Exception as e:
        logger.error("[API] Simulation run failed for %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
