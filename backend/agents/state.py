from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class CommitteeState(BaseModel):
    """
    Expanded state schema for the Echo Multi-Agent Investment Committee.
    """
    ticker: str = Field(..., description="The NSE/BSE ticker symbol under evaluation")
    company_name: str = Field("", description="The full long name of the company")
    current_price: float = Field(0.0, description="Latest market price of the ticker")
    
    # Fundamental & Valuation Scorecard
    fundamental_score: float = Field(0.0, description="Normalized score from the Fundamental Desk (0 to 5)")
    moat_rating: str = Field("None", description="Wide Moat, Narrow Moat, or No Moat classification")
    intrinsic_value: float = Field(0.0, description="Benjamin Graham calculated intrinsic value")
    margin_of_safety: float = Field(0.0, description="Computed margin of safety percentage")
    is_undervalued: bool = Field(False, description="True if margin of safety >= 30%")
    
    # Trend & Timing Scorecard
    weinstein_stage: str = Field("Unknown", description="Stan Weinstein Stage Analysis result")
    weinstein_score: float = Field(0.0, description="Weinstein Trend score (0.0 to 1.0)")
    canslim_score: float = Field(0.0, description="O'Neil CANSLIM technical rating (0.0 to 1.0)")
    timing_status: str = Field("Neutral", description="Buy Timing assessment: Optimal Buy, Train Has Left, etc.")
    timing_description: str = Field("", description="Human-friendly narrative explaining the timing status")
    
    # Sentiment & NLP Scorecard
    sentiment_score: float = Field(0.0, description="News sentiment score from FinBERT (0.0 to 1.0)")
    unscripted_divergence: float = Field(0.0, description="Prepared Remarks vs Analyst Q&A sentiment divergence")
    is_invalidated: bool = Field(False, description="Flag indicating if circuit breakers or mania thresholds triggered")
    
    # Order Book & Flows
    wofi_score: float = Field(0.0, description="Weighted Order Flow Imbalance score (-1.0 to 1.0)")
    iceberg_detected: bool = Field(False, description="True if hidden institutional iceberg accumulation is active")
    spoofing_detected: bool = Field(False, description="True if market makers are placing fake liquidity walls")
    
    # Regulatory Compliance
    is_blocked: bool = Field(False, description="True if listed on SEBI ASM/GSM or T2T segments")
    surveillance_reasons: List[str] = Field(default_factory=list, description="Reasons for SEBI surveillance block")
    
    # Autoregressive Simulation
    kronos_upside_prob: float = Field(0.0, description="Upside probability from Kronos simulation")
    kronos_vol_risk: float = Field(0.0, description="Volatility amplification risk metric from Kronos")
    
    # Portfolio Sizing & Execution
    allocation_percentage: float = Field(0.0, description="Calculated simulated position sizing allocation (0% to 2%)")
    execution_status: str = Field("initialized", description="Current status of the state machine")
    
    # Indicators & News Data Caches (for frontend consumption)
    detailed_indicators: Dict[str, Any] = Field(default_factory=dict, description="Detailed JSON dictionary of all indicators")
    fii_dii_flows: Dict[str, Any] = Field(default_factory=dict, description="FII & DII daily statistics")
    deals: List[Dict[str, Any]] = Field(default_factory=list, description="Recent bulk and block deal transactions")
    logs: List[str] = Field(default_factory=list, description="Reasoning and transition audit trails recorded by nodes")
