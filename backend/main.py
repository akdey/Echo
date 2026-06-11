import asyncio
import json
import logging
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.investment_committee import build_committee_graph
from backend.agents.state import CommitteeState
from backend.services.redis_pipeline import RedisPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Echo API Gateway",
    description="Bridge connecting the LangGraph Investment Committee to the React Dashboard Visualizer.",
    version="1.0.0"
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

@app.post("/api/analyze")
async def analyze_ticker(payload: TickerRequest):
    """
    Triggers the LangGraph Investment Committee state graph for a ticker
    and places the node execution updates into the streaming queue.
    """
    ticker = payload.ticker.upper()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        # Auto-append NSE suffix for convenience
        ticker += ".NS"
        
    logger.info("Initializing multi-agent analysis loop for ticker: %s", ticker)
    graph = build_committee_graph()
    
    # Initialize state
    initial_state = CommitteeState(
        ticker=ticker,
        logs=[]
    )
    
    try:
        # Run graph execution in the background, or sequentially while pushing updates
        # Since each node updates the state, we can run graph steps using the LangGraph streaming API!
        # LangGraph allows streaming updates after each node:
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

@app.get("/api/stream_pipeline")
async def stream_pipeline():
    """
    Exposes a Server-Sent Events (SSE) stream containing real-time agent execution transitions
    and thought logs.
    """
    async def event_generator():
        while True:
            try:
                # Wait for next state change update in the queue
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
