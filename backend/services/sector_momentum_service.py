"""
sector_momentum_service.py
===========================
Calculates relative momentum for each Nifty sectoral index versus the Nifty 50
benchmark and classifies each sector into one of four quadrants:

  LEAD    – RS Score > 1 AND RS improving (momentum is rising and above benchmark)
  IMPROVE – RS Score <= 1 AND RS improving (recovering — money flowing in)
  WEAKEN  – RS Score > 1 AND RS declining (was a leader but losing steam)
  LAG     – RS Score <= 1 AND RS declining (avoid — losing money)

This is the back-end logic for the Sector Rotation Heatmap UI component.

Results are upserted to the `sector_momentum` Supabase table.
Data source: yfinance (free, no API key required).
"""

import asyncio
import logging
import datetime
import yfinance as yf
import pandas as pd
from typing import List, Dict, Any

from backend.services.db_handler import upsert_db, IS_DB_CONFIGURED

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Nifty Sectoral Indices — yfinance symbols
# Free and refreshed daily by yfinance history() calls
# ──────────────────────────────────────────────────────────────────────────────
SECTOR_INDEX_MAP: Dict[str, str] = {
    "NIFTY 50":         "^NSEI",
    "NIFTY IT":         "^CNXIT",
    "NIFTY BANK":       "^NSEBANK",
    "NIFTY AUTO":       "^CNXAUTO",
    "NIFTY METAL":      "^CNXMETAL",
    "NIFTY PHARMA":     "^CNXPHARMA",
    "NIFTY FMCG":       "^CNXFMCG",
    "NIFTY ENERGY":     "^CNXENERGY",
    "NIFTY REALTY":     "^CNXREALTY",
    "NIFTY INFRA":      "^CNXINFRA",
    "NIFTY MEDIA":      "^CNXMEDIA",
    "NIFTY PSU BANK":   "^CNXPSUBANK",
    "NIFTY CONSUMPTION":"^CNXCONSUM",
    "NIFTY HEALTHCARE": "^CNXHEALTH",
}

BENCHMARK_KEY = "NIFTY 50"
BENCHMARK_SYMBOL = SECTOR_INDEX_MAP[BENCHMARK_KEY]


def _momentum_regime(rs_score: float, rs_change_4w: float) -> str:
    """
    Quadrant classification based on Relative Strength value and direction.
    rs_score      : sector / benchmark ratio (>1 = outperforming)
    rs_change_4w  : change in rs_score over last 4 weeks (positive = improving)
    """
    outperforming = rs_score >= 1.0
    improving = rs_change_4w >= 0.0

    if outperforming and improving:
        return "LEAD"
    if outperforming and not improving:
        return "WEAKEN"
    if not outperforming and improving:
        return "IMPROVE"
    return "LAG"


async def _fetch_close_series(symbol: str, period: str = "6mo") -> pd.Series:
    """Async wrapper around yfinance history."""
    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(
        None,
        lambda: yf.Ticker(symbol).history(period=period, interval="1d")
    )
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df["Close"].dropna()


async def calculate_sector_momentum() -> List[Dict[str, Any]]:
    """
    Fetches 6-month daily closes for every sector index + Nifty 50.
    Computes RS score (ratio to benchmark) and 4-week momentum direction.
    Upserts results to Supabase and returns the full payload list.
    """
    logger.info("[SectorMomentum] Fetching benchmark Nifty 50 series...")
    nifty_series = await _fetch_close_series(BENCHMARK_SYMBOL)

    if nifty_series.empty:
        logger.error("[SectorMomentum] Failed to fetch Nifty 50 data — aborting.")
        return []

    nifty_latest = float(nifty_series.iloc[-1])

    payload: List[Dict[str, Any]] = []
    now_str = datetime.datetime.utcnow().isoformat()

    for sector_name, yf_symbol in SECTOR_INDEX_MAP.items():
        if sector_name == BENCHMARK_KEY:
            continue  # Skip benchmark itself

        try:
            sector_series = await _fetch_close_series(yf_symbol)
            if sector_series.empty or len(sector_series) < 30:
                logger.warning("[SectorMomentum] Insufficient data for %s — skipping.", sector_name)
                continue

            # Align on common dates
            aligned = pd.concat(
                [sector_series.rename("sector"), nifty_series.rename("nifty")],
                axis=1
            ).dropna()

            if len(aligned) < 30:
                continue

            # Compute RS ratio
            rs_series = aligned["sector"] / aligned["nifty"]
            rs_latest = float(rs_series.iloc[-1])

            # 4-week RS change (approx 20 trading sessions)
            rs_4w_ago = float(rs_series.iloc[-21]) if len(rs_series) >= 21 else float(rs_series.iloc[0])
            rs_change_4w = rs_latest - rs_4w_ago

            # SMA-50 and SMA-150 for sector index
            closes = aligned["sector"]
            sma_50 = float(closes.rolling(window=50).mean().iloc[-1]) if len(closes) >= 50 else None
            sma_150 = float(closes.rolling(window=150).mean().iloc[-1]) if len(closes) >= 150 else None

            current_price = float(closes.iloc[-1])
            regime = _momentum_regime(rs_latest, rs_change_4w)

            payload.append({
                "sector_name":    sector_name,
                "index_symbol":   yf_symbol,
                "current_price":  round(current_price, 2),
                "sma_50":         round(sma_50, 2) if sma_50 else None,
                "sma_150":        round(sma_150, 2) if sma_150 else None,
                "rs_score":       round(rs_latest, 4),
                "rs_change_4w":   round(rs_change_4w, 4),
                "momentum_regime": regime,
                "updated_at":     now_str,
            })

            logger.info(
                "[SectorMomentum] %s → RS=%.4f | Δ4W=%.4f | Regime=%s",
                sector_name, rs_latest, rs_change_4w, regime
            )

        except Exception as e:
            logger.error("[SectorMomentum] Error processing %s: %s", sector_name, e)
            continue

    if payload and IS_DB_CONFIGURED:
        await upsert_db("sector_momentum", payload)
        logger.info("[SectorMomentum] Upserted %d sector records to database.", len(payload))

    # Sort: LEAD first, then IMPROVE, WEAKEN, LAG
    regime_order = {"LEAD": 0, "IMPROVE": 1, "WEAKEN": 2, "LAG": 3}
    payload.sort(key=lambda x: regime_order.get(x["momentum_regime"], 4))
    return payload
