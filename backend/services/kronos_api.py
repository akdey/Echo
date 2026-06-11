import logging
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import numpy as np

from backend.services.kronos_brain import KronosPredictor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Echo Latent Physics Engine (Kronos)",
    description="Microservice hosting local Kronos foundation simulations for Indian Equities regime tracking.",
    version="1.0.0"
)

# Initialize Kronos Predictor once at startup
predictor = KronosPredictor()

class CandleInput(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float

class SimulationRequest(BaseModel):
    ticker: str
    history: List[CandleInput] = Field(..., min_items=1)
    steps: int = Field(24, ge=24, le=48)
    num_paths: int = Field(30, ge=10, le=100)
    temperature: float = Field(0.7, ge=0.1, le=1.5)

class SimulationResponse(BaseModel):
    ticker: str
    upside_probability: float = Field(..., description="Probability that momentum remains intact (final Close >= initial Close)")
    volatility_amplification: float = Field(..., description="Standard deviation of final Close normalized by initial Close")
    is_safe: bool = Field(..., description="True if upside_probability >= 0.85 and volatility risk is low")
    simulated_paths_sample: List[List[Dict[str, float]]] = Field(..., description="Sample paths showing the raw predicted forward prices")

@app.post("/simulate_regime", response_model=SimulationResponse)
async def simulate_regime(payload: SimulationRequest):
    """
    Evaluates the probability of momentum survival using Monte Carlo autoregressive rollouts.
    """
    try:
        # Convert Pydantic model items to dictionaries
        history_dicts = [candle.model_dump() for candle in payload.history]
        
        # Execute the Monte Carlo simulation paths
        paths = predictor.run_monte_carlo_rollout(
            history_dicts, 
            steps=payload.steps, 
            num_paths=payload.num_paths, 
            temperature=payload.temperature
        )
        
        if not paths:
            raise HTTPException(status_code=400, detail="Failed to run simulations on the input series.")

        start_close = history_dicts[-1]["close"]
        final_closes = [path[-1]["close"] for path in paths]

        # Calculate upside_probability: percentage of paths where structural Stage 2 momentum survives
        # Definition: The final close of the projection path is greater than or equal to the starting close.
        successful_paths = sum(1 for fc in final_closes if fc >= start_close)
        upside_probability = float(successful_paths / len(paths))

        # Calculate volatility_amplification: standard deviation of final close values normalized by starting close
        std_final_closes = float(np.std(final_closes))
        volatility_amplification = float(std_final_closes / start_close) if start_close > 0 else 0.0

        # Define safety threshold: upside probability >= 85% and volatility amplification < 15% (stable risk)
        is_safe = bool(upside_probability >= 0.85 and volatility_amplification <= 0.15)

        # Truncate sample paths output to return a small visual sample (e.g. first 3 paths) to optimize bandwidth
        sample_paths = paths[:3]

        return SimulationResponse(
            ticker=payload.ticker,
            upside_probability=upside_probability,
            volatility_amplification=volatility_amplification,
            is_safe=is_safe,
            simulated_paths_sample=sample_paths
        )

    except Exception as e:
        logger.error("Error running simulation for %s: %s", payload.ticker, str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Simulation error: {str(e)}")
