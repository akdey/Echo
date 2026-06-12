import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.investment_committee import build_committee_graph
from backend.agents.state import CommitteeState
from backend.services.redis_pipeline import RedisPipeline
from backend.services.screener_daemon import ScreenerDaemon
from backend.services.thematic_engine import ThematicCatalystAnalyzer
from backend.services.thematic_db import (
    init_db,
    add_node_async,
    delete_node_async,
    add_edge_async,
    delete_edge_async,
    get_graph_data_async
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

@app.on_event("startup")
async def startup_event():
    """Initializes cached items on startup."""
    logger.info("Initializing system cache and database checks...")
    
    # Initialize the SQLite Graph database
    init_db()
    
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
            # output contains a dict of {node_name: state_updates}
            node_name = list(output.keys())[0]
            updates = output[node_name]
            
            # Format update message
            update_msg = {
                "node": node_name,
                "status": f"Node '{node_name}' finished execution.",
                "ticker": ticker,
                "updates": updates
            }
            await transition_queue.put(update_msg)
            logger.info("Streamed node update: %s", node_name)
            
            # Keep track of cumulative updates
            final_state_dict.update(updates)
            await asyncio.sleep(0.5)  # Slight throttle to let UI animations play smoothly
            
        return {"status": "success", "final_state": final_state_dict}
    except Exception as e:
        logger.error("Failed to run committee state graph: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thematic_analyze")
async def thematic_analyze(payload: ThematicRequest):
    """
    Ingests policy/budget updates, maps them to supply chain,
    verifies accumulation using OBV, and runs risk filters.
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
    """Retrieves the full SQLite knowledge graph (nodes and edges)."""
    try:
        data = await get_graph_data_async()
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error("Failed to retrieve thematic graph: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thematic/node")
async def add_thematic_node(payload: NodeModel):
    """Creates or updates a node in the SQLite graph database."""
    try:
        success = await add_node_async(payload.id, payload.type, payload.label, payload.description)
        if success:
            return {"status": "success", "message": f"Node '{payload.id}' added/updated."}
        raise HTTPException(status_code=500, detail="Failed to add node.")
    except Exception as e:
        logger.error("Failed to add node: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/thematic/node/{node_id}")
async def delete_thematic_node(node_id: str):
    """Deletes a node from the SQLite graph database (cascades to edges)."""
    try:
        success = await delete_node_async(node_id)
        if success:
            return {"status": "success", "message": f"Node '{node_id}' and its connected edges deleted."}
        raise HTTPException(status_code=500, detail=f"Failed to delete node '{node_id}'.")
    except Exception as e:
        logger.error("Failed to delete node: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thematic/edge")
async def add_thematic_edge(payload: EdgeModel):
    """Creates or updates an edge in the SQLite graph database."""
    try:
        success = await add_edge_async(
            payload.source_id,
            payload.target_id,
            payload.relation_type,
            payload.weight,
            payload.role,
            payload.pricing_power,
            payload.catalyst_relevance,
            payload.timestamp
        )
        if success:
            return {"status": "success", "message": f"Edge '{payload.source_id} -> {payload.target_id}' added/updated."}
        raise HTTPException(status_code=500, detail="Failed to add edge.")
    except Exception as e:
        logger.error("Failed to add edge: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/thematic/edge/{edge_id}")
async def delete_thematic_edge(edge_id: int):
    """Deletes a specific edge from the SQLite graph database."""
    try:
        success = await delete_edge_async(edge_id)
        if success:
            return {"status": "success", "message": f"Edge '{edge_id}' deleted."}
        raise HTTPException(status_code=500, detail=f"Failed to delete edge '{edge_id}'.")
    except Exception as e:
        logger.error("Failed to delete edge: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/thematic/crawl")
async def trigger_thematic_crawl():
    """Manually triggers the news/announcement crawler to find new corporate contract wins."""
    redis_pipeline = RedisPipeline()
    analyzer = ThematicCatalystAnalyzer(redis_pipeline)
    try:
        results = await analyzer.crawl_and_extract_news_catalysts()
        return results
    except Exception as e:
        logger.error("Failed to execute news crawl: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stream_pipeline")
async def stream_pipeline():
    """
    Exposes a Server-Sent Events (SSE) stream containing real-time agent execution transitions
    and thought logs.
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
