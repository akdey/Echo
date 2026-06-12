import time
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class OrderBookAnalyzer:
    """
    Surveillance engine for Level 2/3 Order Book Dynamics.
    Calculates Weighted Order Flow Imbalance (WOFI), detects Iceberg absorption,
    and identifies spoofing limit walls.
    """
    
    @staticmethod
    def calculate_wofi(bids: List[Dict[str, float]], asks: List[Dict[str, float]], ltp: float) -> float:
        """
        Calculates Weighted Order Flow Imbalance (WOFI) from Level 2 depth.
        bids/asks list format: [{"price": float, "volume": float}]
        """
        if not bids or not asks or ltp <= 0:
            return 0.0
            
        epsilon = 0.01
        weighted_bid_vol = 0.0
        weighted_ask_vol = 0.0
        
        for b in bids:
            price = b["price"]
            vol = b["volume"]
            # Weight is inversely proportional to distance from LTP
            dist = abs(price - ltp)
            weight = 1.0 / (dist + epsilon)
            weighted_bid_vol += vol * weight
            
        for a in asks:
            price = a["price"]
            vol = a["volume"]
            dist = abs(price - ltp)
            weight = 1.0 / (dist + epsilon)
            weighted_ask_vol += vol * weight
            
        total_vol = weighted_bid_vol + weighted_ask_vol
        if total_vol == 0:
            return 0.0
            
        wofi = (weighted_bid_vol - weighted_ask_vol) / total_vol
        return round(float(wofi), 4)

    @staticmethod
    def detect_spoofing(
        prev_depth: Dict[str, List[Dict[str, float]]],
        curr_depth: Dict[str, List[Dict[str, float]]],
        trades: List[Dict[str, float]],
        ltp: float
    ) -> Dict[str, Any]:
        """
        Detects spoofing limit walls by tracking Liquidity Fade Velocity.
        If a large wall (e.g. volume > 5x average) disappears within 5 ticks of the LTP
        WITHOUT equivalent trade execution, it flags spoofing.
        """
        spoof_detected = False
        side = "None"
        reason = ""
        fade_velocity = 0.0
        
        # Helper to get volume at a price
        def get_vol_at_price(depth_list: List[Dict[str, float]], price: float) -> float:
            for item in depth_list:
                if abs(item["price"] - price) < 0.05:
                    return item["volume"]
            return 0.0
            
        # Get total volume executed in trades during the window
        trade_vol = sum([t.get("volume", 0.0) for t in trades])
        
        # Scan prev_depth bids for large walls that vanished
        prev_bids = prev_depth.get("bids", [])
        curr_bids = curr_depth.get("bids", [])
        
        # Calculate average bid size
        avg_bid_size = sum([b["volume"] for b in prev_bids]) / len(prev_bids) if prev_bids else 1.0
        
        for pb in prev_bids:
            price = pb["price"]
            vol_prev = pb["volume"]
            
            # Check if it was a large wall close to LTP (within 1%)
            if vol_prev > 4 * avg_bid_size and abs(price - ltp) / ltp <= 0.01:
                vol_curr = get_vol_at_price(curr_bids, price)
                vol_dropped = vol_prev - vol_curr
                
                # If volume dropped significantly but trades didn't execute this volume
                if vol_dropped > 2 * avg_bid_size and vol_dropped > 2 * trade_vol:
                    spoof_detected = True
                    side = "bid"
                    fade_velocity = vol_dropped / vol_prev
                    reason = f"Large bid wall of {vol_prev:.0f} shares at ₹{price:.2f} vanished without equivalent execution volume ({trade_vol:.0f} traded)."
                    break
                    
        # Check ask side if bid side is clean
        if not spoof_detected:
            prev_asks = prev_depth.get("asks", [])
            curr_asks = curr_depth.get("asks", [])
            avg_ask_size = sum([a["volume"] for a in prev_asks]) / len(prev_asks) if prev_asks else 1.0
            
            for pa in prev_asks:
                price = pa["price"]
                vol_prev = pa["volume"]
                
                if vol_prev > 4 * avg_ask_size and abs(price - ltp) / ltp <= 0.01:
                    vol_curr = get_vol_at_price(curr_asks, price)
                    vol_dropped = vol_prev - vol_curr
                    
                    if vol_dropped > 2 * avg_ask_size and vol_dropped > 2 * trade_vol:
                        spoof_detected = True
                        side = "ask"
                        fade_velocity = vol_dropped / vol_prev
                        reason = f"Large ask wall of {vol_prev:.0f} shares at ₹{price:.2f} vanished without equivalent execution volume ({trade_vol:.0f} traded)."
                        break
                        
        return {
            "spoof_detected": spoof_detected,
            "side": side,
            "fade_velocity": round(fade_velocity, 4),
            "reason": reason
        }

    @staticmethod
    def detect_iceberg_orders(
        depth: Dict[str, List[Dict[str, float]]],
        trades: List[Dict[str, Any]],
        ltp: float
    ) -> Dict[str, Any]:
        """
        Detects hidden Iceberg orders by tracking execution volume at a specific tick.
        If total traded volume at a price is > 3x the average displayed size at that price,
        while the price remains stagnant, it flags institutional iceberg absorption.
        """
        iceberg_detected = False
        side = "None"
        iceberg_price = 0.0
        absorbed_volume = 0.0
        reason = ""
        
        # 1. Summarize trade volume by price
        trade_summary = {}
        for t in trades:
            p = round(t["price"], 2)
            trade_summary[p] = trade_summary.get(p, 0.0) + t["volume"]
            
        # 2. Check bid depth (Buy icebergs: buyers absorb selling pressure)
        bids = depth.get("bids", [])
        avg_bid_size = sum([b["volume"] for b in bids]) / len(bids) if bids else 1.0
        
        for b in bids:
            price = round(b["price"], 2)
            displayed_vol = b["volume"]
            
            if price in trade_summary:
                executed_vol = trade_summary[price]
                # If executed volume is 3x displayed volume AND 2x avg size
                if executed_vol > 3 * displayed_vol and executed_vol > 2 * avg_bid_size:
                    iceberg_detected = True
                    side = "buy"
                    iceberg_price = price
                    absorbed_volume = executed_vol
                    reason = f"Iceberg Buyer detected at ₹{price:.2f}. Displayed size: {displayed_vol:.0f}, but absorbed {executed_vol:.0f} shares of selling pressure."
                    break
                    
        # Check ask depth (Sell icebergs: sellers absorb buying pressure)
        if not iceberg_detected:
            asks = depth.get("asks", [])
            avg_ask_size = sum([a["volume"] for a in asks]) / len(asks) if asks else 1.0
            
            for a in asks:
                price = round(a["price"], 2)
                displayed_vol = a["volume"]
                
                if price in trade_summary:
                    executed_vol = trade_summary[price]
                    if executed_vol > 3 * displayed_vol and executed_vol > 2 * avg_ask_size:
                        iceberg_detected = True
                        side = "sell"
                        iceberg_price = price
                        absorbed_volume = executed_vol
                        reason = f"Iceberg Seller detected at ₹{price:.2f}. Displayed size: {displayed_vol:.0f}, but absorbed {executed_vol:.0f} shares of buying pressure."
                        break
                        
        return {
            "iceberg_detected": iceberg_detected,
            "side": side,
            "price": iceberg_price,
            "absorbed_volume": absorbed_volume,
            "reason": reason
        }
