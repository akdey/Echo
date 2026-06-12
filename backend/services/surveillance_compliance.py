import time
import asyncio
import logging
from typing import Dict, Any, List, Set

logger = logging.getLogger(__name__)

class SEBIComplianceGatekeeper:
    """
    SEBI 2026 Algorithmic Framework compliance validator.
    Controls order rates (10 OPS limit), converts market orders with Market Price Protection,
    tags transactions with Algo-IDs, and filters ASM/GSM surveillance lists.
    """
    
    def __init__(self, max_ops: float = 9.0):
        # Token-bucket rate limiter: max 9 orders per second
        self.capacity = max_ops
        self.tokens = max_ops
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()
        
        # ASM and GSM lists (cached in memory, filled by crawler)
        self.asm_set: Set[str] = set()
        self.gsm_set: Set[str] = set()
        self.t2t_set: Set[str] = set()
        
    def set_surveillance_lists(self, asm: List[str], gsm: List[str], t2t: List[str]):
        """Sets the active ASM, GSM, and Trade-to-Trade list caches."""
        self.asm_set = {t.upper() for t in asm}
        self.gsm_set = {t.upper() for t in gsm}
        self.t2t_set = {t.upper() for t in t2t}
        logger.info("Updated Compliance Lists: %d ASM, %d GSM, %d T2T tickers loaded.", len(asm), len(gsm), len(t2t))

    async def consume_token(self) -> bool:
        """
        Consumes an order execution token. Returns True if order is allowed,
        False if 10 OPS threshold is exceeded.
        """
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            
            # Add new tokens based on elapsed time (1 token per second rate)
            self.tokens = min(self.capacity, self.tokens + elapsed * self.capacity)
            
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

    async def enforce_rate_limiter(self) -> None:
        """
        Delays execution until an order token becomes available (leaky bucket queueing).
        """
        while not await self.consume_token():
            await asyncio.sleep(0.1)

    def verify_surveillance_status(self, ticker: str) -> Dict[str, Any]:
        """
        Validates if a stock is listed in ASM, GSM, or T2T categories.
        Returns a dict indicating if trading is blocked.
        """
        clean_ticker = ticker.upper().replace(".NS", "").replace(".BO", "")
        
        is_asm = clean_ticker in self.asm_set
        is_gsm = clean_ticker in self.gsm_set
        is_t2t = clean_ticker in self.t2t_set
        
        is_blocked = is_asm or is_gsm or is_t2t
        
        reasons = []
        if is_asm:
            reasons.append("Listed under SEBI Additional Surveillance Measure (ASM) - 100% upfront margins required.")
        if is_gsm:
            reasons.append("Listed under SEBI Graded Surveillance Measure (GSM) - extreme price band / liquidity restrictions.")
        if is_t2t:
            reasons.append("Listed under Trade-to-Trade (T2T) segment - intraday netting prohibited, delivery only.")
            
        return {
            "ticker": ticker,
            "is_blocked": is_blocked,
            "is_asm": is_asm,
            "is_gsm": is_gsm,
            "is_t2t": is_t2t,
            "reasons": reasons
        }

    @staticmethod
    def apply_market_price_protection(
        order_payload: Dict[str, Any],
        ltp: float,
        mpp_buffer_pct: float = 0.015
    ) -> Dict[str, Any]:
        """
        Applies Market Price Protection (MPP) by converting any ORDER_TYPE_MARKET
        to an ORDER_TYPE_LIMIT order placed at the buffer boundary.
        """
        modified_payload = order_payload.copy()
        order_type = modified_payload.get("order_type", "MARKET")
        transaction_type = modified_payload.get("transaction_type", "BUY") # BUY or SELL
        
        if order_type == "MARKET":
            modified_payload["order_type"] = "LIMIT"
            # Calculate buffer price
            if transaction_type == "BUY":
                limit_price = ltp * (1.0 + mpp_buffer_pct)
            else:
                limit_price = ltp * (1.0 - mpp_buffer_pct)
                
            # Round to tick size (5 paise / 0.05 rupees in India)
            tick_size = 0.05
            limit_price = round(round(limit_price / tick_size) * tick_size, 2)
            
            modified_payload["price"] = limit_price
            modified_payload["mpp_applied"] = True
            logger.info("SEBI Compliance: Converted MARKET order for %s to LIMIT order at ₹%s (LTP: ₹%s)", 
                        modified_payload.get("ticker"), limit_price, ltp)
        else:
            modified_payload["mpp_applied"] = False
            
        return modified_payload

    @staticmethod
    def inject_strategy_tagging(order_payload: Dict[str, Any], algo_id: str = "ECHO_ALGO_2026") -> Dict[str, Any]:
        """
        Adds audit tags and Algo ID to order payloads to satisfy SEBI traceability mandates.
        """
        modified_payload = order_payload.copy()
        modified_payload["algo_id"] = algo_id
        modified_payload["trace_timestamp"] = int(time.time())
        return modified_payload
