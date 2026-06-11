import json
import logging
from typing import Dict, List, Optional, Any
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

class RedisPipeline:
    """
    Redis Digital Twin Adapter for caching and serving high-frequency and historical
    OHLCVA (Open, High, Low, Close, Volume, Amount) tensors for BSE/NSE tickers.
    Features a robust in-memory fallback for Hugging Face Space deployments.
    """
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: Optional[str] = None):
        self.redis_url = f"redis://{host}:{port}/{db}"
        self.password = password
        self.client: Optional[aioredis.Redis] = None
        self.use_in_memory = False
        self._in_memory_db: Dict[str, str] = {}

    async def connect(self) -> None:
        """Establish async connection to local Redis instance, fallback to in-memory on failure."""
        if self.use_in_memory:
            return

        try:
            if not self.client:
                self.client = aioredis.from_url(
                    self.redis_url, 
                    password=self.password, 
                    decode_responses=True
                )
                # Test the connection immediately
                await self.client.ping()
                logger.info("Connected to Redis Digital Twin at %s", self.redis_url)
        except Exception as e:
            logger.warning("Redis connection failed (%s). Falling back to in-memory mock cache.", str(e))
            self.use_in_memory = True
            self.client = None

    async def disconnect(self) -> None:
        """Close the Redis client connection."""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("Disconnected from Redis Digital Twin")

    async def _ensure_connected(self) -> None:
        """Ensure Redis client is connected or fallback is active before executing commands."""
        if not self.use_in_memory and not self.client:
            await self.connect()

    def _get_ticker_key(self, ticker: str, interval: str) -> str:
        """Generate a structured redis key for a ticker's candles."""
        return f"twin:{ticker.upper()}:{interval}"

    async def store_ohlcva(self, ticker: str, interval: str, data: List[Dict[str, Any]]) -> bool:
        """
        Stores structured OHLCVA candles in Redis or in-memory dictionary.
        Each data point in list should contain:
        - timestamp: str (ISO format or epoch)
        - open: float
        - high: float
        - low: float
        - close: float
        - volume: float
        - amount: float
        """
        await self._ensure_connected()
        key = self._get_ticker_key(ticker, interval)
        try:
            serialized = json.dumps(data)
            if self.use_in_memory:
                self._in_memory_db[key] = serialized
                logger.info("[In-Memory] Cached %d candles for %s (%s)", len(data), ticker, interval)
                return True
            
            assert self.client is not None
            await self.client.set(key, serialized)
            logger.info("Successfully stored %d candles for %s (%s)", len(data), ticker, interval)
            return True
        except Exception as e:
            logger.error("Failed to store OHLCVA for %s: %s", ticker, str(e))
            return False

    async def fetch_ohlcva(self, ticker: str, interval: str) -> List[Dict[str, Any]]:
        """
        Fetches structured OHLCVA candles from Redis or in-memory dictionary.
        """
        await self._ensure_connected()
        key = self._get_ticker_key(ticker, interval)
        try:
            if self.use_in_memory:
                raw_data = self._in_memory_db.get(key)
            else:
                assert self.client is not None
                raw_data = await self.client.get(key)
                
            if not raw_data:
                logger.warning("No cached data found for key: %s", key)
                return []
            return json.loads(raw_data)
        except Exception as e:
            logger.error("Failed to fetch OHLCVA for %s: %s", ticker, str(e))
            return []

    async def cache_indicator(self, ticker: str, name: str, value: Any, expire_seconds: Optional[int] = None) -> bool:
        """Cache computed indicators or intermediate state."""
        await self._ensure_connected()
        key = f"indicator:{ticker.upper()}:{name}"
        try:
            serialized = json.dumps(value)
            if self.use_in_memory:
                self._in_memory_db[key] = serialized
                return True
                
            assert self.client is not None
            if expire_seconds:
                await self.client.setex(key, expire_seconds, serialized)
            else:
                await self.client.set(key, serialized)
            return True
        except Exception as e:
            logger.error("Failed to cache indicator %s for %s: %s", name, ticker, str(e))
            return False

    async def get_cached_indicator(self, ticker: str, name: str) -> Optional[Any]:
        """Retrieve computed indicators or intermediate state."""
        await self._ensure_connected()
        key = f"indicator:{ticker.upper()}:{name}"
        try:
            if self.use_in_memory:
                raw_data = self._in_memory_db.get(key)
            else:
                assert self.client is not None
                raw_data = await self.client.get(key)
                
            if not raw_data:
                return None
            return json.loads(raw_data)
        except Exception as e:
            logger.error("Failed to retrieve cached indicator %s for %s: %s", name, ticker, str(e))
            return None

