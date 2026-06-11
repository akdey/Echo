from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class CommitteeState(BaseModel):
    """
    Global state schema for the Echo Multi-Agent Investment Committee.
    """
    ticker: str = Field(..., description="The NSE/BSE ticker symbol under evaluation")
    current_price: float = Field(0.0, description="Latest market price of the ticker")
    fundamental_score: float = Field(0.0, description="Normalized score from the Forensic RAG Desk (0.0 to 1.0)")
    sentiment_score: float = Field(0.0, description="Normalized sentiment score from FinBERT (0.0 to 1.0)")
    kronos_upside_prob: float = Field(0.0, description="Upside probability from Kronos simulation")
    kronos_vol_risk: float = Field(0.0, description="Volatility amplification risk metric from Kronos")
    is_invalidated: bool = Field(False, description="Flag indicating if circuit breakers or mania thresholds triggered")
    allocation_percentage: float = Field(0.0, description="Calculated simulated position sizing allocation (0% to 2%)")
    execution_status: str = Field("initialized", description="Current status of the state machine")
    logs: List[str] = Field(default_factory=list, description="Reasoning and transition audit trails recorded by nodes")
