"""
conviction_engine.py
====================
Calculates a 0–100 Conviction Score for every Nifty 500 stock daily.

Scoring breakdown
-----------------
+30  Technicals   – Weinstein Stage 1/2 base breakout on the daily chart
+30  Smart Money  – NSE Bhavcopy delivery volume >= 2x 20-day average
+20  Thematic     – pgvector cosine similarity >= 0.35 to any active macro theme
+20  Fundamentals – Positive Operating Cash Flow AND ROCE > 15%
-50  Trap Filter  – Stock is in ASM/GSM list OR has run up >= 60% in 90 days

Score is clamped to [0, 100].  Results are upserted to the `conviction_matrix`
Supabase table.  Any stock with score >= 75 is flagged for async alerting.
"""

import asyncio
import logging
import datetime
import yfinance as yf
import pandas as pd
from typing import List, Dict, Any, Optional

from backend.services.supabase_client import (
    query_supabase,
    upsert_supabase,
    IS_SUPABASE_CONFIGURED,
)
from backend.services.trend_models import TrendEvaluator
from backend.services.embeddings import generate_embedding
from backend.services.supabase_client import rpc_supabase

logger = logging.getLogger(__name__)

# Lazy import to avoid circular deps — only imported at runtime inside the function
_macro_regime_filter = None

def _get_regime_filter():
    global _macro_regime_filter
    if _macro_regime_filter is None:
        from backend.services.risk_engine import MacroRegimeFilter
        _macro_regime_filter = MacroRegimeFilter()
    return _macro_regime_filter


# ──────────────────────────────────────────────────────────────────────────────
# Thematic seed queries – expanded regularly.
# The engine scores a +20 if the company pgvector similarity to ANY seed >= 0.35
# ──────────────────────────────────────────────────────────────────────────────
MACRO_THEMES = [
    "solar panel manufacturing renewable energy EPC contractor",
    "defense electronics missile component supplier",
    "semiconductor chip fab PCB manufacturing",
    "railway signalling infrastructure wagons",
    "electric vehicle battery lithium cell manufacturer",
    "data center cooling power infrastructure",
    "API pharmaceutical specialty chemicals bulk drug",
    "green hydrogen electrolyser fuel cell",
]

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(score: int) -> int:
    return max(0, min(100, score))


async def _fetch_bhavcopy_df(symbol: str) -> Optional[pd.DataFrame]:
    """Load EOD history from Supabase.  Returns None if insufficient."""
    rows = await query_supabase("daily_bhavcopy", {
        "symbol": f"eq.{symbol}",
        "order": "trade_date.asc",
        "limit": 250
    })
    if not rows or len(rows) < 22:
        return None
    df = pd.DataFrame(rows)
    for col in ["close", "high", "low", "open", "volume", "delivery_volume",
                "delivery_pct", "turnover_cr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


async def _fetch_cfo_and_roce(symbol: str) -> Dict[str, Any]:
    """
    Fetches Operating Cash Flow and Return on Capital Employed from yfinance.
    Returns dict with keys: cfo_positive (bool), roce_pct (float).
    Falls back to neutral (cfo_positive=False, roce_pct=0) on any failure.
    """
    result = {"cfo_positive": False, "roce_pct": 0.0}
    loop = asyncio.get_event_loop()
    try:
        ticker_obj = yf.Ticker(symbol)
        cashflow = await loop.run_in_executor(None, lambda: ticker_obj.cashflow)
        if not cashflow.empty:
            for row_name in ["Operating Cash Flow",
                             "Cash Flow From Operating Activities",
                             "OperatingCashFlow"]:
                if row_name in cashflow.index:
                    cfo = float(cashflow.loc[row_name].iloc[0])
                    result["cfo_positive"] = cfo > 0
                    break

        info = await loop.run_in_executor(None, lambda: ticker_obj.info)
        # ROCE proxy: EBIT / (Total Assets - Current Liabilities)
        # yfinance doesn't expose ROCE directly; we derive it from ROE + debtToEquity
        roe = _safe_float(info.get("returnOnEquity"), 0.0) * 100.0
        roa = _safe_float(info.get("returnOnAssets"), 0.0) * 100.0
        # Use average of ROE and ROA as a conservative ROCE proxy
        roce_proxy = (roe + roa) / 2.0
        result["roce_pct"] = roce_proxy
    except Exception as e:
        logger.warning("CFO/ROCE fetch failed for %s: %s", symbol, e)
    return result


async def _thematic_score(symbol: str, company_desc: str) -> int:
    """
    Returns +20 if the company vector is close (≥ 0.35) to any macro theme seed.
    We check pre-existing similarity from pgvector for each theme embedding.
    """
    if not IS_SUPABASE_CONFIGURED:
        return 0
    for theme_query in MACRO_THEMES:
        try:
            theme_vec = generate_embedding(theme_query)
            matches = await rpc_supabase("match_companies", {
                "query_embedding": theme_vec,
                "match_threshold": 0.35,
                "match_count": 5,
            })
            matched_syms = [m["symbol"] for m in matches]
            if symbol in matched_syms:
                return 20
        except Exception as e:
            logger.warning("Thematic RPC failed for theme '%s': %s", theme_query[:40], e)
            continue
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Main scoring function
# ──────────────────────────────────────────────────────────────────────────────

async def score_single_ticker(
    symbol: str,
    company_desc: str,
    surveillance_symbols: set,
) -> Optional[Dict[str, Any]]:
    """
    Computes the full Conviction Matrix for a single symbol.
    Returns a dict ready for Supabase upsert, or None if data is insufficient.
    """

    # ── Load EOD history ──────────────────────────────────────────────────────
    df = await _fetch_bhavcopy_df(symbol)
    if df is None:
        logger.warning("[Conviction] Insufficient history for %s — skipping.", symbol)
        return None

    df = TrendEvaluator.calculate_indicators(df)
    current_price = _safe_float(df["close"].iloc[-1])

    # ── SCORE 1: Technicals (+30) ─────────────────────────────────────────────
    weinstein = TrendEvaluator.evaluate_weinstein(df)
    stage = weinstein.get("stage", "Unknown")
    tech_score = 0
    if "Stage 1" in stage or "Stage 2" in stage:
        # Stage 2 (Markup) earns full marks; late Stage 1 (base) earns partial
        tech_score = 30 if "Stage 2" in stage else 20

    # ── SCORE 2: Smart Money / Delivery Volume (+30) ──────────────────────────
    smart_money_score = 0
    if "delivery_volume" in df.columns and "volume" in df.columns:
        df["delivery_pct"] = df["delivery_pct"].astype(float)
        avg_deliv_20d = float(df["delivery_pct"].rolling(window=20).mean().iloc[-1])
        latest_deliv = float(df["delivery_pct"].iloc[-1])

        # Primary: delivery % ≥ 2× the 20-day average AND ≥ 45%
        if latest_deliv >= 45.0 and latest_deliv >= avg_deliv_20d * 2.0:
            smart_money_score = 30
        elif latest_deliv >= 40.0 and latest_deliv >= avg_deliv_20d * 1.5:
            smart_money_score = 20
        elif latest_deliv >= 35.0 and latest_deliv >= avg_deliv_20d * 1.2:
            smart_money_score = 10

    # ── SCORE 3: Thematic (+20) ───────────────────────────────────────────────
    thematic_score = await _thematic_score(symbol, company_desc)

    # ── SCORE 4: Fundamentals (+20) ───────────────────────────────────────────
    fundamental_score = 0
    fundamentals = await _fetch_cfo_and_roce(symbol)
    if fundamentals["cfo_positive"] and fundamentals["roce_pct"] >= 15.0:
        fundamental_score = 20
    elif fundamentals["cfo_positive"] or fundamentals["roce_pct"] >= 10.0:
        fundamental_score = 10

    # ── SCORE 5: Trap Penalty (-50) ──────────────────────────────────────────
    trap_penalty = 0
    trap_reasons = []

    # 5a. Surveillance / ASM / GSM list membership
    bare_symbol = symbol.replace(".NS", "").replace(".BO", "")
    if bare_symbol in surveillance_symbols or symbol in surveillance_symbols:
        trap_penalty += 30
        trap_reasons.append("ASM/GSM Surveillance")

    # 5b. 60% run-up in last 90 trading days — catalyst exhaustion
    if len(df) >= 90:
        low_90d = float(df["low"].iloc[-90:].min())
        run_up_pct = (current_price - low_90d) / low_90d if low_90d > 0 else 0.0
        if run_up_pct >= 0.60:
            trap_penalty += 20
            trap_reasons.append(f"Catalyst Exhaustion ({round(run_up_pct * 100, 1)}% 90d run-up)")

    # 5c. 3 consecutive upper circuits (operator pump)
    if "is_upper_circuit" in df.columns:
        if bool(df["is_upper_circuit"].iloc[-3:].all()):
            trap_penalty += 10
            trap_reasons.append("3 Consecutive Upper Circuits")

    # ── Compute raw score ─────────────────────────────────────────────────────
    raw_score = tech_score + smart_money_score + thematic_score + fundamental_score - trap_penalty
    conviction_score = _clamp(raw_score)

    # ── Derive stop-loss: most recent swing low (last 20 bars) ────────────────
    stop_loss_level: Optional[float] = None
    if len(df) >= 20:
        stop_loss_level = round(float(df["low"].iloc[-20:].min()), 2)

    # ── Build verdict text ────────────────────────────────────────────────────
    catalyst_tags: List[str] = []
    if tech_score >= 20:
        catalyst_tags.append(f"Weinstein {stage}")
    if smart_money_score >= 20:
        catalyst_tags.append("Delivery Volume Spike")
    if thematic_score > 0:
        catalyst_tags.append("Macro Theme Match")
    if fundamental_score > 0:
        catalyst_tags.append("Positive CFO + ROCE")
    for t in trap_reasons:
        catalyst_tags.append(f"⚠ {t}")

    if trap_penalty >= 30:
        verdict = f"DO NOT BUY — Trap Detected ({', '.join(trap_reasons)}). Conviction: {conviction_score}%"
    elif conviction_score >= 75:
        verdict = (
            f"HIGH CONVICTION BUY — {', '.join([t for t in catalyst_tags if '⚠' not in t])}. "
            f"Stop-Loss at ₹{stop_loss_level}."
        )
    elif conviction_score >= 50:
        verdict = (
            f"WATCHLIST — Score {conviction_score}/100. "
            f"Catalyst: {', '.join([t for t in catalyst_tags if '⚠' not in t]) or 'None'}."
        )
    else:
        verdict = f"PASS — Insufficient confluence. Score {conviction_score}/100."

    return {
        "symbol": symbol,
        "conviction_score": conviction_score,
        "technical_score": tech_score,
        "smart_money_score": smart_money_score,
        "thematic_score": thematic_score,
        "fundamental_score": fundamental_score,
        "trap_penalty": trap_penalty,
        "verdict": verdict,
        "stop_loss_level": stop_loss_level,
        "catalyst_tags": catalyst_tags,
        "updated_at": datetime.datetime.utcnow().isoformat(),
    }


async def run_conviction_scoring(
    symbols: Optional[List[str]] = None,
    surveillance_symbols: Optional[set] = None,
    skip_regime_check: bool = False,
) -> List[Dict[str, Any]]:
    """
    Runs the full conviction scoring loop over provided symbols (or all companies
    in Supabase) and upserts results to `conviction_matrix`.

    ⚠️  REGIME GATE: Before scoring any individual stock, the Macro Regime Filter
    is evaluated.  If the market is in RISK_OFF mode (Nifty < 20-EMA, or
    5-day FII flow < -5000 Cr), ALL buy signals are suppressed and the function
    returns a regime warning for every stock.  This is the most important
    risk control in the system — when the tide goes out, all boats sink.

    Returns a list of all scored records, sorted descending by conviction_score.
    """
    if not IS_SUPABASE_CONFIGURED:
        logger.warning("[Conviction] Supabase not configured — aborting.")
        return []

    # ── REGIME GATE ───────────────────────────────────────────────
    if not skip_regime_check:
        try:
            regime_result = await _get_regime_filter().get_regime()
            if regime_result["regime"] == "RISK_OFF":
                triggers = regime_result.get("triggers", [])
                verdict  = f"RISK_OFF — {' | '.join(triggers)}. No buy signals issued."
                logger.warning(
                    "[Conviction] ⛔ RISK_OFF mode detected. Suppressing all buy signals.\n"
                    "Triggers: %s", triggers
                )
                # Return a single regime-warning record (not per-stock)
                return [{
                    "symbol":           "__MARKET__",
                    "conviction_score": 0,
                    "verdict":          verdict,
                    "catalyst_tags":    triggers,
                    "regime":           "RISK_OFF",
                    "regime_details":   regime_result,
                    "updated_at":       datetime.datetime.utcnow().isoformat(),
                }]
        except Exception as regime_err:
            # Never let a regime check failure block scoring entirely
            logger.warning(
                "[Conviction] Regime check failed (%s) — proceeding without gate.",
                regime_err
            )


    surv = surveillance_symbols or set()

    # Load company list from Supabase if not provided
    if not symbols:
        companies = await query_supabase("companies", {
            "select": "symbol,description",
            "limit": 1000,
        })
        symbol_desc_map = {c["symbol"]: c.get("description", "") for c in companies}
    else:
        rows = await query_supabase("companies", {
            "select": "symbol,description",
            "limit": 1000,
        })
        symbol_desc_map = {c["symbol"]: c.get("description", "") for c in rows}
        symbol_desc_map = {k: v for k, v in symbol_desc_map.items() if k in set(symbols)}

    logger.info("[Conviction] Scoring %d symbols...", len(symbol_desc_map))
    results = []

    for symbol, description in symbol_desc_map.items():
        try:
            scored = await score_single_ticker(symbol, description, surv)
            if scored:
                results.append(scored)
                logger.info(
                    "[Conviction] %s → Score: %d | %s",
                    symbol, scored["conviction_score"], scored["verdict"][:60]
                )
        except Exception as e:
            logger.error("[Conviction] Error scoring %s: %s", symbol, e)

    if results:
        await upsert_supabase("conviction_matrix", results)
        logger.info("[Conviction] Upserted %d conviction scores to Supabase.", len(results))

    # Return sorted descending by conviction score
    results.sort(key=lambda x: x["conviction_score"], reverse=True)
    return results
