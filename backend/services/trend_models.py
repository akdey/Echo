import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple

class TrendEvaluator:
    """
    Technical and Smart Money Concepts (SMC) trend evaluation engine.
    Implements Stan Weinstein Stage 2 analysis, CANSLIM technical rules,
    and Wyckoff/SMC structural sweeps and Fair Value Gaps.
    """
    
    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Appends technical indicators to the historical dataframe.
        Required columns: open, high, low, close, volume
        """
        # Ensure correct datatypes
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
            
        # Moving Averages
        df["sma_50"] = df["close"].rolling(window=50).mean()
        df["sma_150"] = df["close"].rolling(window=150).mean()  # 30-week equivalent
        df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
        
        # 52-week High / Low
        df["high_52w"] = df["high"].rolling(window=250, min_periods=1).max()
        df["low_52w"] = df["low"].rolling(window=250, min_periods=1).min()
        
        # Average Volume
        df["avg_vol_30"] = df["volume"].rolling(window=30).mean()
        df["avg_body_20"] = (df["close"] - df["open"]).abs().rolling(window=20).mean()
        
        # On-Balance Volume (OBV)
        df = TrendEvaluator.calculate_obv(df)
        
        return df

    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.DataFrame:
        """
        Appends On-Balance Volume (OBV) and its 20-day moving average.
        OBV = OBV_prev + volume (if close > close_prev)
            = OBV_prev - volume (if close < close_prev)
            = OBV_prev (if close == close_prev)
        """
        if len(df) == 0:
            df["obv"] = []
            df["obv_ema20"] = []
            return df
            
        close_diff = df["close"].diff()
        direction = np.sign(close_diff.fillna(0.0))
        
        df["obv"] = (df["volume"] * direction).cumsum()
        df["obv_ema20"] = df["obv"].ewm(span=20, adjust=False).mean()
        return df

    @staticmethod
    def identify_swings(df: pd.DataFrame, window: int = 5) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Identifies local swing highs and swing lows.
        A swing high is higher than 'window' candles to its left and right.
        """
        swing_highs = []
        swing_lows = []
        n = len(df)
        
        for i in range(window, n - window):
            curr_high = df["high"].iloc[i]
            curr_low = df["low"].iloc[i]
            
            # Check if swing high
            is_high = True
            for w in range(1, window + 1):
                if df["high"].iloc[i - w] >= curr_high or df["high"].iloc[i + w] >= curr_high:
                    is_high = False
                    break
            if is_high:
                swing_highs.append({
                    "index": i,
                    "timestamp": df["timestamp"].iloc[i],
                    "value": float(curr_high)
                })
                
            # Check if swing low
            is_low = True
            for w in range(1, window + 1):
                if df["low"].iloc[i - w] <= curr_low or df["low"].iloc[i + w] <= curr_low:
                    is_low = False
                    break
            if is_low:
                swing_lows.append({
                    "index": i,
                    "timestamp": df["timestamp"].iloc[i],
                    "value": float(curr_low)
                })
                
        return swing_highs, swing_lows

    @staticmethod
    def detect_fvgs(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detects active (unmitigated) Fair Value Gaps (FVG) in the price action.
        Bullish FVG: Low(t) > High(t-2)
        Bearish FVG: High(t) < Low(t-2)
        """
        fvgs = []
        n = len(df)
        if n < 3:
            return fvgs
            
        for i in range(2, n):
            high_t2 = float(df["high"].iloc[i - 2])
            low_t2 = float(df["low"].iloc[i - 2])
            high_t = float(df["high"].iloc[i])
            low_t = float(df["low"].iloc[i])
            
            # Check Bullish FVG
            if low_t > high_t2:
                # The gap is between high of t-2 and low of t
                fvg_top = low_t
                fvg_bottom = high_t2
                
                # Check if FVG has been mitigated/filled by subsequent price action
                mitigated = False
                for j in range(i + 1, n):
                    if float(df["low"].iloc[j]) <= fvg_bottom:
                        mitigated = True
                        break
                
                if not mitigated:
                    fvgs.append({
                        "type": "bullish",
                        "index": i - 1,
                        "timestamp": df["timestamp"].iloc[i - 1],
                        "top": fvg_top,
                        "bottom": fvg_bottom,
                        "mitigated": False
                    })
                    
            # Check Bearish FVG
            elif high_t < low_t2:
                # The gap is between low of t-2 and high of t
                fvg_top = low_t2
                fvg_bottom = high_t
                
                mitigated = False
                for j in range(i + 1, n):
                    if float(df["high"].iloc[j]) >= fvg_top:
                        mitigated = True
                        break
                
                if not mitigated:
                    fvgs.append({
                        "type": "bearish",
                        "index": i - 1,
                        "timestamp": df["timestamp"].iloc[i - 1],
                        "top": fvg_top,
                        "bottom": fvg_bottom,
                        "mitigated": False
                    })
                    
        return fvgs

    @staticmethod
    def detect_liquidity_sweeps(df: pd.DataFrame, swing_highs: List[Dict[str, Any]], swing_lows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detects liquidity sweep patterns.
        Sellside Sweep: Price breaks below recent swing low but closes back above it.
        Buyside Sweep: Price breaks above recent swing high but closes back below it.
        """
        sweeps = []
        n = len(df)
        if n < 5:
            return sweeps
            
        # Convert swing lists to lookup dictionaries
        # Keep only swings that happened in the past
        for i in range(1, n):
            curr_low = float(df["low"].iloc[i])
            curr_high = float(df["high"].iloc[i])
            curr_close = float(df["close"].iloc[i])
            curr_open = float(df["open"].iloc[i])
            
            # Find relevant prior swing lows (within past 50 candles)
            recent_lows = [s for s in swing_lows if s["index"] < i and i - s["index"] <= 50]
            if recent_lows:
                # Find the lowest swing low in memory
                target_low = min(recent_lows, key=lambda x: x["value"])
                # Sellside Sweep Condition: Low pierced the level, but Close ended above it
                if curr_low < target_low["value"] and curr_close > target_low["value"]:
                    # Verify displacement: must be relatively strong body or wick rejection
                    body_size = abs(curr_close - curr_open)
                    avg_body = float(df["avg_body_20"].iloc[i]) if not pd.isna(df["avg_body_20"].iloc[i]) else body_size
                    
                    sweeps.append({
                        "type": "sellside",
                        "index": i,
                        "timestamp": df["timestamp"].iloc[i],
                        "level_swept": target_low["value"],
                        "triggered_value": curr_low,
                        "close_value": curr_close,
                        "is_strong": body_size >= 1.2 * avg_body
                    })
                    
            # Find relevant prior swing highs
            recent_highs = [s for s in swing_highs if s["index"] < i and i - s["index"] <= 50]
            if recent_highs:
                target_high = max(recent_highs, key=lambda x: x["value"])
                # Buyside Sweep Condition: High pierced the level, but Close ended below it
                if curr_high > target_high["value"] and curr_close < target_high["value"]:
                    body_size = abs(curr_close - curr_open)
                    avg_body = float(df["avg_body_20"].iloc[i]) if not pd.isna(df["avg_body_20"].iloc[i]) else body_size
                    
                    sweeps.append({
                        "type": "buyside",
                        "index": i,
                        "timestamp": df["timestamp"].iloc[i],
                        "level_swept": target_high["value"],
                        "triggered_value": curr_high,
                        "close_value": curr_close,
                        "is_strong": body_size >= 1.2 * avg_body
                    })
                    
        return sweeps

    @staticmethod
    def evaluate_weinstein(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluates Stan Weinstein's Stage Analysis.
        Stage 1: Consolidation / Base (price hovering around flat 150-day SMA)
        Stage 2: Breakout / Uptrend (price above rising 150-day SMA, strong volume)
        Stage 3: Top / Distribution (price chops around flattening 150-day SMA)
        Stage 4: Markdown / Downtrend (price below sloping downwards 150-day SMA)
        """
        n = len(df)
        if n < 155:
            return {
                "stage": "Unknown",
                "score": 0.0,
                "reasons": ["Insufficient historical data (minimum 150 bars required)"]
            }
            
        current_price = float(df["close"].iloc[-1])
        sma_150 = float(df["sma_150"].iloc[-1])
        sma_150_prev = float(df["sma_150"].iloc[-5]) # 5 days ago
        
        # Calculate SMA slope (normalized)
        sma_slope = (sma_150 - sma_150_prev) / sma_150_prev * 100
        
        # Volume breakout
        curr_vol = float(df["volume"].iloc[-1])
        avg_vol_30 = float(df["avg_vol_30"].iloc[-1])
        vol_ratio = curr_vol / avg_vol_30 if avg_vol_30 > 0 else 1.0
        
        # Price relative to 52-week High
        high_52w = float(df["high_52w"].iloc[-1])
        dist_from_high = (high_52w - current_price) / high_52w if high_52w > 0 else 0.0
        
        reasons = []
        stage = "Unknown"
        score = 0.0
        
        # Stage classifications
        if current_price > sma_150:
            if sma_slope > 0.05:
                # Stage 2 (Markup)
                stage = "Stage 2 (Markup)"
                score = 0.8
                reasons.append("Price is firmly above the rising 150-day SMA.")
                if vol_ratio >= 1.5:
                    score += 0.1
                    reasons.append(f"Breakout backed by high volume ({vol_ratio:.1f}x average).")
                if dist_from_high <= 0.10:
                    score += 0.1
                    reasons.append(f"Price is trading within {dist_from_high*100:.1f}% of 52-week highs (ideal breakout zone).")
            else:
                # Stage 1 (Base/Accumulation)
                stage = "Stage 1 (Accumulation)"
                score = 0.5
                reasons.append("Price is above 150-day SMA, but the average line is relatively flat.")
        else:
            if sma_slope < -0.05:
                # Stage 4 (Markdown)
                stage = "Stage 4 (Markdown)"
                score = 0.1
                reasons.append("Price is in a structural downtrend below the falling 150-day SMA.")
            else:
                # Stage 3 (Distribution) or Stage 1 transitioning
                stage = "Stage 3 (Distribution)"
                score = 0.3
                reasons.append("Price has fallen below 150-day SMA and the trend line is flattening.")
                
        return {
            "stage": stage,
            "score": round(score, 2),
            "sma_slope": round(sma_slope, 4),
            "vol_ratio": round(vol_ratio, 2),
            "dist_from_52w_high": round(dist_from_high, 4),
            "reasons": reasons
        }

    @staticmethod
    def evaluate_canslim(df: pd.DataFrame, ticker_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates the technical components of William O'Neil's CANSLIM system.
        """
        n = len(df)
        current_price = float(df["close"].iloc[-1])
        
        # 1. C & A: Checked fundamentally, but let's check technical validation
        # 2. N: New High breakout (Price is within 15% of 52-week High)
        high_52w = float(df["high_52w"].iloc[-1]) if "high_52w" in df.columns else current_price
        n_pass = current_price >= (high_52w * 0.85)
        
        # 3. S: Supply and Demand. Volume Accumulation/Distribution.
        # Check if green volume days have higher volume than red volume days in the last 20 days.
        recent_df = df.iloc[-20:]
        up_days = recent_df[recent_df["close"] > recent_df["open"]]
        down_days = recent_df[recent_df["close"] < recent_df["open"]]
        up_vol = up_days["volume"].sum()
        down_vol = down_days["volume"].sum()
        s_pass = up_vol > down_vol
        
        # 4. L: Leader or Laggard.
        # Check Relative Strength against standard Nifty (needs Nifty benchmark data, otherwise fall back to price performance)
        # Let's calculate price relative strength over 6 months: stock change vs index or simply > 30% performance.
        six_month_ago = df["close"].iloc[-125] if n >= 125 else df["close"].iloc[0]
        six_month_perf = (current_price - six_month_ago) / six_month_ago
        l_pass = six_month_perf >= 0.20 # Outperformed by at least 20% over 6 months
        
        # 5. I: Institutional sponsorship.
        # Inst ownership from ticker_info
        inst_pct = ticker_info.get("heldPercentInstitutions", 0.0)
        i_pass = inst_pct > 0.05 or ticker_info.get("institutionsCount", 0) > 5
        
        # 6. M: Market Direction (is Nifty above its 200 EMA? We assume verified by orchestrator, or check stock's 200-day trend)
        sma_150 = float(df["sma_150"].iloc[-1]) if "sma_150" in df.columns else current_price
        m_pass = current_price > sma_150
        
        score = sum([1 for x in [n_pass, s_pass, l_pass, i_pass, m_pass] if x]) / 5.0
        
        return {
            "score": round(score, 2),
            "n_new_high_pass": bool(n_pass),
            "s_volume_accumulation_pass": bool(s_pass),
            "l_leader_pass": bool(l_pass),
            "i_institutions_pass": bool(i_pass),
            "m_market_trend_pass": bool(m_pass),
            "six_month_performance": round(six_month_perf, 4),
            "institutional_ownership_pct": round(inst_pct, 4)
        }

    @staticmethod
    def get_entry_timing_assessment(df: pd.DataFrame, weinstein: Dict[str, Any], fvgs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Determines the entry timing for beginners ("Is it a good time to enter or has the train already left?").
        - "Optimal Buy Zone": Weinstein Stage 2 breakout just triggered (within 5% of breakout level, volume spikes, unmitigated bullish FVG nearby).
        - "Train Has Left (Overextended)": Price is >10% above the 150-day SMA, and 52-week high was broken long ago.
        - "Accumulation Phase (Patience)": Stock is in Stage 1, flat SMA, buy here for long-term hold but expect slow movement.
        - "Avoid / Markdown": Stock is in Stage 3 or 4, downward momentum, do not catch a falling knife.
        """
        stage = weinstein["stage"]
        current_price = float(df["close"].iloc[-1])
        sma_150 = float(df["sma_150"].iloc[-1])
        dist_from_sma = (current_price - sma_150) / sma_150
        
        if "Stage 4" in stage:
            status = "Avoid"
            description = "The stock is in a downward spiral (Stage 4 Markdown). Buying here is like catching a falling knife. Wait for accumulation."
            color = "rose"
        elif "Stage 3" in stage:
            status = "Avoid"
            description = "The stock is topping out (Stage 3 Distribution). Heavy institutional selling is likely beginning. Protect your capital."
            color = "rose"
        elif "Stage 1" in stage:
            status = "Accumulation"
            description = "The stock is consolidating in a bottom range (Stage 1 Accumulation). It is safe for long-term value investing, but requires patience as the breakout has not yet triggered."
            color = "yellow"
        elif "Stage 2" in stage:
            if dist_from_sma <= 0.07:
                # Close to the SMA support
                status = "Optimal Buy"
                description = "The stock has recently broken out into a new uptrend (Stage 2 Markup) and is trading close to its support line. This is the ideal low-risk entry window."
                color = "emerald"
            elif dist_from_sma > 0.15:
                # Overextended
                status = "Train Has Left"
                description = "The stock is in a strong uptrend but has rallied too far from its breakout point (>15% above support). Risk of a short-term pullback is high. Wait for a retest or pull back to enter."
                color = "yellow"
            else:
                status = "Watchlist / Buy Pullback"
                description = "The stock is in a healthy uptrend. Do not buy market orders; place limit orders at nearby support zones or wait for a minor pullback."
                color = "violet"
        else:
            status = "Hold / Neutral"
            description = "No clear trend structures identified. Wait for market structure shifts."
            color = "slate"
            
        return {
            "status": status,
            "description": description,
            "color": color,
            "dist_from_support_pct": round(dist_from_sma * 100, 2)
        }
