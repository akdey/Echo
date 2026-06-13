"""
risk_engine.py
==============
Four-layer institutional risk management system for Echo.

─────────────────────────────────────────────────────────────────────────────
LAYER 1 — Pre-Market Sanity Check
  Runs at 9:15:05 AM IST on market days.
  Fetches the NSE opening price for each trade candidate via curl-cffi.
  IF (Open - PreviousClose) / PreviousClose > 3 %: flag ABORT_TRADE.
  Never buy a gap-up — let retail FOMO absorb the slippage.

LAYER 2 — Macro Regime Filter
  Before evaluating ANY individual stock, determines whether the broad
  market is in RISK_ON or RISK_OFF:
    • Nifty 50 price < 20-day EMA          → RISK_OFF
    • Nifty Midcap 150 price < 50-day EMA  → RISK_OFF (for midcap picks)
    • 5-day cumulative FII flow < -5000 Cr  → RISK_OFF
  When RISK_OFF, conviction scoring returns a regime warning and issues
  zero buy signals. Cash is a position.

LAYER 3 — Chandelier Exit (ATR Trailing Stop)
  Dynamic trailing stop for every open trade in the journal.
  Chandelier Stop = Highest_High_Since_Entry − (3 × ATR14)
  ATR is calculated using Wilder's smoothing (same as TradingView).
  When price closes below the Chandelier Stop, the system fires an EXIT alert.

LAYER 4 — Kelly Criterion Position Sizing
  Derives mathematically optimal capital allocation from the historical
  win-rate and average R:R ratio in the trade_journal table.
  Uses HALF-Kelly for capital preservation (recommended for live trading):
    f* = ((p * (b + 1) − 1) / b) × 0.5
  where p = win rate, b = average (gain / loss) ratio.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import datetime
import math
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import numpy as np
import yfinance as yf
from backend.services.angel_data_gateway import AngelDataGateway

from backend.services.scraper_utils import fetch_nse_json, _make_session
from backend.services.db_handler import (
    query_db,
    upsert_db,
    IS_DB_CONFIGURED,
)

logger = logging.getLogger(__name__)

# ── Configurable constants (override with env vars in production) ──────────────
GAP_UP_ABORT_THRESHOLD    = 0.03    # Abort trade if open is > 3% above prev close
GAP_DOWN_CAUTION_THRESHOLD = 0.02   # Caution flag if open is > 2% below prev close
NIFTY50_EMA_PERIOD        = 20      # 20-day EMA for Nifty 50 regime
MIDCAP_EMA_PERIOD         = 50      # 50-day EMA for midcap regime
FII_5D_RISK_OFF_THRESHOLD = -5000.0 # Cr — 5-day cumulative FII below this = RISK_OFF
ATR_PERIOD                = 14      # Wilder's ATR period
CHANDELIER_MULTIPLIER     = 3.0     # Chandelier stop = highest_high - N × ATR
KELLY_HALF                = 0.5     # Half-Kelly conservative multiplier
REGIME_CACHE_HOURS        = 6       # How long to cache regime in Supabase

# ── Market index tickers ───────────────────────────────────────────────────────
NIFTY50_TICKER  = "^NSEI"
MIDCAP_TICKER   = "^CNXMDCP"        # Nifty Midcap 150
MIDCAP_FALLBACK = "MIDCPNIFTY.NS"   # Fallback if primary unavailable


# ════════════════════════════════════════════════════════════════════════════════
# LAYER 1 — Pre-Market Sanity Check
# ════════════════════════════════════════════════════════════════════════════════

class PreMarketSanityCheck:
    """
    Runs at 9:15:05 AM IST on every market day.
    Fetches live NSE prices via Angel One SmartAPI.
    Aborts trades where the stock gaps up > 3% from previous close.

    The gap-up abort prevents buying at distribution tops where retail FOMO
    has already priced in the news before your AMO executes.
    """

    def __init__(self):
        self.gateway = AngelDataGateway()

    async def check_symbol(
        self,
        symbol: str,
        fallback_prev_close: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Performs the pre-market gap check for a single symbol using Angel One SmartAPI LTP.

        Args:
            symbol: NSE ticker e.g. "RELIANCE.NS"
            fallback_prev_close: Previous close from Supabase if NSE API is down.

        Returns:
            Dict with keys:
              action        — "PROCEED" | "ABORT_GAP_UP" | "CAUTION_GAP_DOWN" | "DATA_UNAVAILABLE"
              symbol        — input symbol
              open_price    — today's opening price/LTP (or None)
              prev_close    — previous session close (or None)
              gap_pct       — gap percentage (positive = up)
              reason        — human-readable explanation
        """
        # Get previous close first
        prev_close = fallback_prev_close
        if prev_close is None or prev_close == 0:
            try:
                rows = await query_db("daily_bhavcopy", {
                    "symbol": f"eq.{symbol}",
                    "order": "trade_date.desc",
                    "limit": "1",
                    "select": "close",
                })
                if rows:
                    prev_close = float(rows[0]["close"])
            except Exception:
                pass

        # Retrieve live LTP as today's open price
        open_price = self.gateway.get_live_ltp(symbol, fallback_price=prev_close)

        if not open_price or not prev_close:
            return {
                "action":     "DATA_UNAVAILABLE",
                "symbol":     symbol,
                "open_price": open_price,
                "prev_close": prev_close,
                "gap_pct":    None,
                "reason":     "LTP or previous close not available.",
            }

        gap_pct = (open_price - prev_close) / prev_close

        if gap_pct > GAP_UP_ABORT_THRESHOLD:
            return {
                "action":     "ABORT_GAP_UP",
                "symbol":     symbol,
                "open_price": round(open_price, 2),
                "prev_close": round(prev_close, 2),
                "gap_pct":    round(gap_pct * 100, 2),
                "reason":     (
                    f"Gap-up of {round(gap_pct * 100, 1)}% detected. "
                    f"Aborting trade — never buy retail FOMO at the open. "
                    f"Wait for a clean 15-min setup after 9:30 AM."
                ),
            }
        elif gap_pct < -GAP_DOWN_CAUTION_THRESHOLD:
            return {
                "action":     "CAUTION_GAP_DOWN",
                "symbol":     symbol,
                "open_price": round(open_price, 2),
                "prev_close": round(prev_close, 2),
                "gap_pct":    round(gap_pct * 100, 2),
                "reason":     (
                    f"Gap-down of {abs(round(gap_pct * 100, 1))}% detected. "
                    f"Review your stop-loss before executing — the trade may have been stopped out pre-market."
                ),
            }
        else:
            return {
                "action":     "PROCEED",
                "symbol":     symbol,
                "open_price": round(open_price, 2),
                "prev_close": round(prev_close, 2),
                "gap_pct":    round(gap_pct * 100, 2),
                "reason":     f"Normal open ({round(gap_pct * 100, 1)}%). Trade plan valid.",
            }

    async def check_all_open_positions(self) -> List[Dict[str, Any]]:
        """
        Runs pre-market gap check on ALL open positions in the trade_journal
        (entries with no exit_date yet).
        """
        if not IS_DB_CONFIGURED:
            return [{"action": "ERROR", "reason": "Database not configured."}]

        open_trades = await query_db("trade_journal", {
            "select": "id,symbol,entry_price,stop_loss",
            "exit_date": "is.null",
            "limit": "200",
        })

        if not open_trades:
            return [{"action": "NO_OPEN_POSITIONS", "reason": "No open trades in journal."}]

        results = []
        for trade in open_trades:
            result = await self.check_symbol(
                symbol=trade["symbol"],
                fallback_prev_close=float(trade.get("entry_price") or 0),
            )
            result["trade_id"] = trade["id"]
            result["stop_loss"] = trade.get("stop_loss")
            results.append(result)

        return results


# ════════════════════════════════════════════════════════════════════════════════
# LAYER 2 — Macro Regime Filter
# ════════════════════════════════════════════════════════════════════════════════

class MacroRegimeFilter:
    """
    Determines whether the broad market is in RISK_ON or RISK_OFF mode before
    any conviction scoring or trade execution.

    RISK_OFF conditions (any one triggers):
      1. Nifty 50 closing price < 20-day EMA
      2. Nifty Midcap 150 closing price < 50-day EMA (for midcap stocks)
      3. 5-day cumulative FII cash flow < −5000 Crore

    In RISK_OFF mode, the conviction engine returns zero buy signals.
    The system explicitly acknowledges that CASH is a position.
    Result is cached in Supabase `risk_events` for REGIME_CACHE_HOURS hours
    to avoid repeated yfinance calls.
    """

    def _fetch_index_history(self, ticker: str, period: int) -> Optional[pd.DataFrame]:
        """Downloads index history from yfinance synchronously."""
        try:
            df = yf.Ticker(ticker).history(period=f"{period + 20}d")
            if df is not None and not df.empty and len(df) >= period:
                df.index = pd.to_datetime(df.index)
                return df
        except Exception as e:
            logger.warning("[Regime] yfinance failed for %s: %s", ticker, e)
        return None

    def _compute_ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    async def _get_nifty50_regime(self) -> Tuple[str, Dict[str, Any]]:
        """Returns ('RISK_ON'|'RISK_OFF', metrics_dict) for Nifty 50."""
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None, self._fetch_index_history, NIFTY50_TICKER, NIFTY50_EMA_PERIOD + 10
        )

        if df is None or df.empty:
            logger.warning("[Regime] Nifty 50 data unavailable — defaulting to RISK_OFF (cautious).")
            return "RISK_OFF", {"reason": "Nifty 50 data unavailable", "nifty50": None, "ema20": None}

        current = float(df["Close"].iloc[-1])
        ema20   = float(self._compute_ema(df["Close"], NIFTY50_EMA_PERIOD).iloc[-1])
        pct_above_ema = (current - ema20) / ema20 * 100

        regime = "RISK_ON" if current >= ema20 else "RISK_OFF"
        metrics = {
            "nifty50_current": round(current, 2),
            "nifty50_ema20":   round(ema20, 2),
            "pct_above_ema20": round(pct_above_ema, 2),
            "nifty50_above_ema": current >= ema20,
        }
        if regime == "RISK_OFF":
            metrics["reason"] = f"Nifty 50 ({current:.0f}) is below 20-EMA ({ema20:.0f})"
        return regime, metrics

    async def _get_midcap_regime(self) -> Tuple[str, Dict[str, Any]]:
        """Returns ('RISK_ON'|'RISK_OFF', metrics_dict) for Nifty Midcap 150."""
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None, self._fetch_index_history, MIDCAP_TICKER, MIDCAP_EMA_PERIOD + 10
        )
        if df is None or df.empty:
            # Try fallback ticker
            df = await loop.run_in_executor(
                None, self._fetch_index_history, MIDCAP_FALLBACK, MIDCAP_EMA_PERIOD + 10
            )
        if df is None or df.empty:
            return "RISK_ON", {"reason": "Midcap data unavailable — skipping midcap gate"}

        current = float(df["Close"].iloc[-1])
        ema50   = float(self._compute_ema(df["Close"], MIDCAP_EMA_PERIOD).iloc[-1])

        regime = "RISK_ON" if current >= ema50 else "RISK_OFF"
        metrics = {
            "midcap_current": round(current, 2),
            "midcap_ema50":   round(ema50, 2),
            "midcap_above_ema": current >= ema50,
        }
        if regime == "RISK_OFF":
            metrics["reason"] = f"Nifty Midcap ({current:.0f}) below 50-EMA ({ema50:.0f})"
        return regime, metrics

    async def _get_fii_regime(self) -> Tuple[str, Dict[str, Any]]:
        """
        Checks 5-day cumulative FII flow from Supabase conviction_matrix history
        or Redis.  Falls back to NSE API if no history.
        """
        try:
            from backend.services.scraper_utils import fetch_fii_dii_flows
            flows = await fetch_fii_dii_flows()
            fii_5d = flows.get("rolling_5d_fii", 0.0)
            regime = "RISK_ON" if fii_5d >= FII_5D_RISK_OFF_THRESHOLD else "RISK_OFF"
            metrics = {
                "fii_5d_cumulative_cr": round(fii_5d, 2),
                "fii_threshold_cr":     FII_5D_RISK_OFF_THRESHOLD,
                "fii_risk_off":         regime == "RISK_OFF",
            }
            if regime == "RISK_OFF":
                metrics["reason"] = (
                    f"5-day cumulative FII flow is ₹{fii_5d:,.0f} Cr "
                    f"(threshold: ₹{FII_5D_RISK_OFF_THRESHOLD:,.0f} Cr)"
                )
            return regime, metrics
        except Exception as e:
            logger.warning("[Regime] FII flow check failed: %s", e)
            return "RISK_ON", {"reason": "FII data unavailable — skipping FII gate"}

    async def get_regime(self) -> Dict[str, Any]:
        """
        Evaluates all three regime gates concurrently and returns the
        consolidated market state.

        Returns:
            {
              "regime":   "RISK_ON" | "RISK_OFF",
              "triggers": [list of triggered conditions],
              "metrics":  {nifty50, midcap, fii sub-dicts},
              "verdict":  human-readable string,
              "timestamp": ISO datetime
            }
        """
        # Run all three gates in parallel
        nifty_regime, nifty_metrics = await self._get_nifty50_regime()
        midcap_regime, midcap_metrics = await self._get_midcap_regime()
        fii_regime, fii_metrics = await self._get_fii_regime()

        triggers = []
        if nifty_regime == "RISK_OFF":
            triggers.append(nifty_metrics.get("reason", "Nifty 50 below EMA20"))
        if midcap_regime == "RISK_OFF":
            triggers.append(midcap_metrics.get("reason", "Midcap below EMA50"))
        if fii_regime == "RISK_OFF":
            triggers.append(fii_metrics.get("reason", "FII selling > threshold"))

        # Any single trigger puts us in RISK_OFF
        overall_regime = "RISK_OFF" if triggers else "RISK_ON"

        if overall_regime == "RISK_ON":
            verdict = (
                "✅ RISK_ON — Market structure is constructive. "
                "Conviction screener may issue buy signals."
            )
        else:
            trigger_str = " | ".join(triggers)
            verdict = (
                f"🚫 RISK_OFF — {trigger_str}. "
                f"System is in cash-preservation mode. No buy signals will be issued."
            )

        result = {
            "regime":    overall_regime,
            "triggers":  triggers,
            "metrics":   {
                "nifty50": nifty_metrics,
                "midcap":  midcap_metrics,
                "fii":     fii_metrics,
            },
            "verdict":   verdict,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

        # Persist regime change to database for audit trail
        if IS_DB_CONFIGURED:
            try:
                await upsert_db("risk_events", [{
                    "event_type":     "REGIME_CHECK",
                    "regime":         overall_regime,
                    "trigger_reason": " | ".join(triggers) if triggers else "None",
                    "metadata":       result["metrics"],
                }])
            except Exception as e:
                logger.warning("[Regime] Failed to persist regime event: %s", e)

        logger.info("[Regime] %s — Triggers: %s", overall_regime, triggers or "None")
        return result


# ════════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Chandelier Exit (ATR Trailing Stop)
# ════════════════════════════════════════════════════════════════════════════════

class ChandelierExit:
    """
    Calculates dynamic trailing stops for open journal positions using the
    Chandelier Exit method (developed by Charles Le Beau).

    Formula:
        True Range (TR) = max(
            High − Low,
            |High − Previous Close|,
            |Low  − Previous Close|
        )
        ATR(n) = Wilder's Smoothed Moving Average of TR over n periods
        Chandelier Stop = Highest High (since entry) − (multiplier × ATR)

    When the daily closing price drops below the Chandelier Stop, the system
    fires an EXIT signal.  The trailing nature ensures:
      - Wide enough to absorb normal price chop (unlike fixed % stops)
      - Tight enough to capture most of the trend when institutions exit
    """

    def _calculate_atr_wilder(self, df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
        """
        Wilder's smoothed ATR — identical to the TradingView ATR indicator.
        Uses exponential smoothing with alpha = 1/period (not simple moving average).
        """
        high = df["high"].astype(float)
        low  = df["low"].astype(float)
        prev_close = df["close"].astype(float).shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)

        # Wilder initialisation: first ATR = simple mean of first `period` TRs
        atr = tr.copy()
        first_valid = period - 1
        atr.iloc[:first_valid] = float("nan")
        if len(tr) >= period:
            atr.iloc[first_valid] = tr.iloc[:period].mean()
            for i in range(first_valid + 1, len(tr)):
                atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period

        return atr

    async def calculate_for_trade(
        self,
        symbol: str,
        entry_date: str,
        entry_price: float,
    ) -> Dict[str, Any]:
        """
        Calculates the Chandelier Exit stop level for one open position.

        Args:
            symbol:      NSE ticker e.g. "TATAMOTORS.NS"
            entry_date:  ISO date string "YYYY-MM-DD"
            entry_price: Price at which the position was entered.

        Returns dict with keys:
          chandelier_stop  — current trailing stop price
          atr14            — current 14-period ATR
          highest_high     — highest high since entry
          days_in_trade    — number of trading days since entry
          action           — "HOLD" | "EXIT_SIGNAL" | "INSUFFICIENT_DATA"
          distance_pct     — % distance of current price from stop (positive = above stop)
        """
        # Fetch price history from database
        rows = await query_db("daily_bhavcopy", {
            "symbol": f"eq.{symbol}",
            "order":  "trade_date.asc",
            "limit":  "300",
        })

        if not rows or len(rows) < ATR_PERIOD + 2:
            return {
                "action":          "INSUFFICIENT_DATA",
                "symbol":          symbol,
                "chandelier_stop": None,
                "atr14":           None,
                "highest_high":    None,
                "days_in_trade":   0,
                "reason":          "Fewer than 16 days of price history available.",
            }

        df = pd.DataFrame(rows)
        for col in ["close", "high", "low", "open"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(method="ffill")

        # Calculate ATR over full history (need 14 days for initialisation)
        df["atr14"] = self._calculate_atr_wilder(df, ATR_PERIOD)

        current_price    = float(df["close"].iloc[-1])
        current_atr      = float(df["atr14"].iloc[-1])

        # Filter to rows from entry date onward
        entry_date_dt = pd.to_datetime(entry_date).date()
        df["trade_date_dt"] = pd.to_datetime(df["trade_date"]).dt.date
        in_trade_df = df[df["trade_date_dt"] >= entry_date_dt]

        if in_trade_df.empty:
            # Entry today — use current row only
            in_trade_df = df.iloc[[-1]]

        days_in_trade = len(in_trade_df)
        highest_high  = float(in_trade_df["high"].max())

        # Chandelier Stop = Highest High Since Entry − (multiplier × ATR)
        chandelier_stop = highest_high - (CHANDELIER_MULTIPLIER * current_atr)

        # Clamp: stop should never be above entry price (protects new entries)
        chandelier_stop = min(chandelier_stop, entry_price * 0.99)

        distance_pct = (current_price - chandelier_stop) / chandelier_stop * 100.0
        action = "EXIT_SIGNAL" if current_price < chandelier_stop else "HOLD"

        result = {
            "action":          action,
            "symbol":          symbol,
            "entry_date":      entry_date,
            "entry_price":     round(entry_price, 2),
            "current_price":   round(current_price, 2),
            "chandelier_stop": round(chandelier_stop, 2),
            "atr14":           round(current_atr, 2),
            "highest_high":    round(highest_high, 2),
            "days_in_trade":   days_in_trade,
            "distance_pct":    round(distance_pct, 2),
            "multiplier":      CHANDELIER_MULTIPLIER,
        }

        if action == "EXIT_SIGNAL":
            result["reason"] = (
                f"Close ₹{current_price:.2f} broke below Chandelier Stop ₹{chandelier_stop:.2f}. "
                f"Institutional trend has broken — exit the position."
            )
        else:
            result["reason"] = (
                f"Price ₹{current_price:.2f} is {distance_pct:.1f}% above trailing stop ₹{chandelier_stop:.2f}. "
                f"Hold and trail the stop."
            )

        logger.info(
            "[Chandelier] %s — Stop: ₹%.2f | Price: ₹%.2f | ATR: ₹%.2f | Action: %s",
            symbol, chandelier_stop, current_price, current_atr, action
        )
        return result

    async def scan_all_open_positions(self) -> List[Dict[str, Any]]:
        """
        Scans all open positions in the trade journal for Chandelier Exit signals.
        Returns a list of results, EXIT_SIGNAL positions first.
        """
        if not IS_DB_CONFIGURED:
            return []

        open_trades = await query_db("trade_journal", {
            "select":    "id,symbol,entry_date,entry_price",
            "exit_date": "is.null",
            "limit":     "200",
        })

        if not open_trades:
            return []

        results = []
        for trade in open_trades:
            result = await self.calculate_for_trade(
                symbol=trade["symbol"],
                entry_date=str(trade["entry_date"]),
                entry_price=float(trade.get("entry_price") or 0),
            )
            result["trade_id"] = trade["id"]
            results.append(result)

        # EXIT_SIGNAL positions first
        results.sort(key=lambda r: 0 if r["action"] == "EXIT_SIGNAL" else 1)

        # Persist exit signals to risk_events table
        exit_signals = [r for r in results if r["action"] == "EXIT_SIGNAL"]
        if exit_signals and IS_DB_CONFIGURED:
            try:
                events = [
                    {
                        "event_type":     "CHANDELIER_EXIT",
                        "symbol":         r["symbol"],
                        "value":          r["chandelier_stop"],
                        "trigger_reason": r.get("reason", ""),
                        "metadata":       {k: v for k, v in r.items() if k not in ("reason",)},
                    }
                    for r in exit_signals
                ]
                await upsert_db("risk_events", events)
            except Exception as e:
                logger.warning("[Chandelier] Failed to persist exit signals: %s", e)

        return results


# ════════════════════════════════════════════════════════════════════════════════
# LAYER 4 — Kelly Criterion Position Sizing
# ════════════════════════════════════════════════════════════════════════════════

class KellyCriterion:
    """
    Derives the mathematically optimal position size from the historical
    win-rate and average gain/loss ratio in the trade_journal.

    Formula (Half-Kelly for capital preservation):
        Full Kelly:  f = (p × (b + 1) − 1) / b
        Half Kelly:  f* = f × 0.5

    where:
        p = probability of a winning trade (historical win rate)
        b = average winning gain / average losing loss  (R:R ratio)

    The Kelly fraction tells you what percentage of total capital to deploy
    into a single trade.  Half-Kelly is the institutional standard for live
    trading because the full formula is extremely sensitive to estimation error.

    Minimum requirements for reliable output: >= 20 closed trades in journal.
    Below this threshold, a conservative 2% of capital is suggested.
    """

    MIN_TRADES_FOR_KELLY = 20
    DEFAULT_KELLY_PCT    = 2.0    # Suggested allocation before enough history
    MAX_KELLY_PCT        = 10.0   # Hard cap — never risk more than 10% per trade

    async def calculate(self, total_capital: float) -> Dict[str, Any]:
        """
        Calculates the Kelly-optimal position size based on journal history.

        Args:
            total_capital: Your total investable capital in INR.

        Returns:
            {
              "suggested_allocation_pct": float,   — % of capital per trade
              "suggested_allocation_inr": float,   — INR amount per trade
              "win_rate": float,                   — historical win rate (0–1)
              "avg_rr_ratio": float,               — average gain/loss ratio
              "full_kelly_pct": float,             — uncapped Kelly fraction
              "half_kelly_pct": float,             — half-Kelly (what we use)
              "trades_analyzed": int,
              "confidence": str,                   — "HIGH" | "MEDIUM" | "LOW"
              "reasoning": str
            }
        """
        if not IS_DB_CONFIGURED:
            return self._default_response(total_capital, "Database not configured.")

        # Fetch all closed trades (have both entry_price and exit_price)
        closed_trades = await query_db("trade_journal", {
            "select":     "entry_price,exit_price,quantity",
            "exit_price": "not.is.null",
            "limit":      "500",
        })

        n_trades = len(closed_trades)

        if n_trades < self.MIN_TRADES_FOR_KELLY:
            return self._default_response(
                total_capital,
                f"Only {n_trades} closed trades in journal. "
                f"Need at least {self.MIN_TRADES_FOR_KELLY} for reliable Kelly sizing. "
                f"Using conservative default of {self.DEFAULT_KELLY_PCT}% per trade."
            )

        # Compute returns per trade
        gains   = []
        losses  = []

        for trade in closed_trades:
            try:
                entry = float(trade["entry_price"])
                exit_ = float(trade["exit_price"])
                if entry <= 0:
                    continue
                ret_pct = (exit_ - entry) / entry
                if ret_pct >= 0:
                    gains.append(ret_pct)
                else:
                    losses.append(abs(ret_pct))
            except (TypeError, ValueError):
                continue

        if not gains and not losses:
            return self._default_response(total_capital, "No valid closed trades found.")

        n_wins  = len(gains)
        n_total = n_wins + len(losses)
        p       = n_wins / n_total if n_total > 0 else 0.0

        avg_gain = float(np.mean(gains)) if gains else 0.0
        avg_loss = float(np.mean(losses)) if losses else 1.0   # Avoid division by zero

        # R:R ratio (b)
        b = avg_gain / avg_loss if avg_loss > 0 else 0.0

        # Kelly formula
        if b <= 0:
            full_kelly = 0.0
        else:
            full_kelly = ((p * (b + 1) - 1) / b)

        half_kelly = full_kelly * KELLY_HALF

        # Clamp to [0, MAX_KELLY_PCT]
        suggested_pct = max(0.0, min(half_kelly * 100.0, self.MAX_KELLY_PCT))

        # If Kelly says 0 or negative, system is unprofitable — cap at 1%
        if half_kelly <= 0:
            suggested_pct = 1.0
            confidence = "LOW"
            reasoning = (
                f"Kelly fraction is negative (p={p:.2f}, b={b:.2f}). "
                f"Your historical win-rate × R:R does not justify aggressive sizing. "
                f"Cap at 1% until edge improves."
            )
        elif n_total < 50:
            confidence = "MEDIUM"
            reasoning = (
                f"Based on {n_total} trades: win rate {p*100:.1f}%, avg R:R {b:.2f}:1. "
                f"Half-Kelly suggests {suggested_pct:.1f}% per trade. "
                f"Confidence is MEDIUM — more trade history will refine this."
            )
        else:
            confidence = "HIGH"
            reasoning = (
                f"Based on {n_total} trades: win rate {p*100:.1f}%, avg R:R {b:.2f}:1. "
                f"Half-Kelly optimal allocation is {suggested_pct:.1f}% per trade (₹{total_capital * suggested_pct / 100:,.0f})."
            )

        suggested_inr = round(total_capital * suggested_pct / 100.0, 2)

        result = {
            "suggested_allocation_pct": round(suggested_pct, 2),
            "suggested_allocation_inr": suggested_inr,
            "win_rate":                 round(p, 4),
            "win_rate_pct":             round(p * 100, 1),
            "avg_rr_ratio":             round(b, 3),
            "full_kelly_pct":           round(full_kelly * 100, 2),
            "half_kelly_pct":           round(half_kelly * 100, 2),
            "trades_analyzed":          n_total,
            "winning_trades":           n_wins,
            "losing_trades":            len(losses),
            "avg_win_pct":              round(avg_gain * 100, 2),
            "avg_loss_pct":             round(avg_loss * 100, 2),
            "total_capital":            total_capital,
            "confidence":               confidence,
            "reasoning":                reasoning,
        }

        logger.info(
            "[Kelly] p=%.2f | b=%.2f | half-Kelly=%.1f%% | suggested=₹%.0f",
            p, b, half_kelly * 100, suggested_inr
        )
        return result

    def _default_response(self, total_capital: float, reason: str) -> Dict[str, Any]:
        inr = round(total_capital * self.DEFAULT_KELLY_PCT / 100.0, 2)
        return {
            "suggested_allocation_pct": self.DEFAULT_KELLY_PCT,
            "suggested_allocation_inr": inr,
            "win_rate":                 None,
            "win_rate_pct":             None,
            "avg_rr_ratio":             None,
            "full_kelly_pct":           None,
            "half_kelly_pct":           None,
            "trades_analyzed":          0,
            "total_capital":            total_capital,
            "confidence":               "LOW",
            "reasoning":                reason,
        }


# ════════════════════════════════════════════════════════════════════════════════
# Convenience aggregator
# ════════════════════════════════════════════════════════════════════════════════

async def get_market_regime() -> Dict[str, Any]:
    """Module-level convenience wrapper for MacroRegimeFilter."""
    return await MacroRegimeFilter().get_regime()


async def run_premarket_checks() -> List[Dict[str, Any]]:
    """Module-level convenience wrapper for PreMarketSanityCheck.check_all_open_positions."""
    return await PreMarketSanityCheck().check_all_open_positions()


async def scan_exit_signals() -> List[Dict[str, Any]]:
    """Module-level convenience wrapper for ChandelierExit.scan_all_open_positions."""
    return await ChandelierExit().scan_all_open_positions()


async def get_position_size(total_capital: float) -> Dict[str, Any]:
    """Module-level convenience wrapper for KellyCriterion.calculate."""
    return await KellyCriterion().calculate(total_capital)


async def check_premarket_gap(symbol: str, previous_close: float) -> Dict[str, Any]:
    """
    Checks if a stock's opening gap is above the threshold (LTP - previous_close) / previous_close > 0.03.
    """
    gateway = AngelDataGateway()
    ltp = gateway.get_live_ltp(symbol, fallback_price=previous_close)
    if not ltp or previous_close <= 0:
        return {
            "is_vetoed": False,
            "action": "PROCEED",
            "ltp": ltp or previous_close,
            "gap_pct": 0.0,
            "reason": "LTP or previous close not available. Proceeding with caution."
        }
        
    gap_pct = (ltp - previous_close) / previous_close
    if gap_pct > GAP_UP_ABORT_THRESHOLD:
        return {
            "is_vetoed": True,
            "action": "ABORT_GAP_UP",
            "ltp": ltp,
            "gap_pct": gap_pct,
            "reason": f"Gap-up of {gap_pct * 100:.2f}% exceeds the 3% threshold. Aborting trade."
        }
    elif gap_pct < -GAP_DOWN_CAUTION_THRESHOLD:
        return {
            "is_vetoed": False,
            "action": "CAUTION_GAP_DOWN",
            "ltp": ltp,
            "gap_pct": gap_pct,
            "reason": f"Gap-down of {gap_pct * 100:.2f}% detected. Proceeding with caution."
        }
    else:
        return {
            "is_vetoed": False,
            "action": "PROCEED",
            "ltp": ltp,
            "gap_pct": gap_pct,
            "reason": f"Normal opening gap of {gap_pct * 100:.2f}%. Proceeding."
        }
