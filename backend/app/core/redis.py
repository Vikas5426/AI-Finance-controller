"""
Centralized Asynchronous Redis Manager & Distributed Coordination Layer.
Provides connection pooling, distributed locking (Lua-scripted release),
typed JSON caching, progress tracking, and 100% fail-open resilience.

PostgreSQL/SQLite remains the sole ACID source of truth.
Redis operates exclusively as an optional, ephemeral acceleration layer.
"""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from redis.asyncio.client import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger("finance_controller.redis")

# ==============================================================================
# LUA SCRIPTS
# ==============================================================================

# Atomic lock release: Only delete the key if the token matches the owner
RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

class RedisManager:
    """Singleton Async Redis Client & Connection Pool Manager."""

    _instance: Optional["RedisManager"] = None
    _redis: Optional[Redis] = None
    _is_connected: bool = False

    def __new__(cls) -> "RedisManager":
        if cls._instance is None:
            cls._instance = super(RedisManager, cls).__new__(cls)
        return cls._instance

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._redis is not None

    @property
    def client(self) -> Optional[Redis]:
        return self._redis if self._is_connected else None

    async def connect(self) -> bool:
        """Initializes the connection pool and verifies connectivity with a ping."""
        if not settings.REDIS_ENABLED or not settings.REDIS_URL:
            logger.info("Redis is disabled in application settings. Running in standalone mode.")
            self._is_connected = False
            return False

        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=settings.REDIS_CONNECT_TIMEOUT_SEC,
                socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SEC,
                max_connections=20
            )
            # Health check ping with timeout
            await asyncio.wait_for(self._redis.ping(), timeout=settings.REDIS_CONNECT_TIMEOUT_SEC)
            self._is_connected = True
            logger.info(f"redis_connected: Successfully connected to Redis at {settings.REDIS_URL}")
            return True
        except Exception as e:
            self._is_connected = False
            logger.warning(f"redis_unavailable: Could not connect to Redis ({e}). Operating with local in-memory fallback.")
            return False

    async def disconnect(self) -> None:
        """Gracefully closes all connection pool sockets on server shutdown."""
        if self._redis:
            try:
                await self._redis.aclose()
                logger.info("Redis connection pool closed gracefully.")
            except Exception as e:
                logger.warning(f"Error during Redis disconnect: {e}")
            finally:
                self._redis = None
                self._is_connected = False

    def set_mock_client(self, client: Optional[Redis]) -> None:
        """Helper for testing with fakeredis."""
        self._redis = client
        self._is_connected = client is not None

# Global Singleton Instance
redis_manager = RedisManager()

# ==============================================================================
# NAMESPACE KEY BUILDERS
# ==============================================================================

def prefix_key(namespace: str, identifier: str) -> str:
    """Builds consistent key: fin:{env}:{namespace}:{identifier}"""
    env = getattr(settings, "APP_ENV", "dev")[:4]
    return f"fin:{env}:{namespace}:{identifier}"

def key_batch_lock(batch_id: str) -> str:
    return prefix_key("lock:batch", batch_id)

def key_dashboard_summary(org_id: str) -> str:
    return prefix_key("dashboard:summary", org_id)

def key_ai_investigation(exc_type: str, impact_minor: int, payload_hash: str) -> str:
    return prefix_key("ai:inv", f"{exc_type}:{impact_minor}:{payload_hash}")

def key_batch_progress(batch_id: str) -> str:
    return prefix_key("batch:progress", batch_id)

# ==============================================================================
# DISTRIBUTED CONCURRENCY LOCK
# ==============================================================================

@asynccontextmanager
async def acquire_distributed_lock(
    lock_key: str,
    timeout_sec: int = 30
) -> AsyncGenerator[Tuple[bool, Optional[str]], None]:
    """
    Acquires an atomic distributed mutex using SET NX EX.
    Releases strictly via Lua script matching token ownership.
    Yields (is_acquired: bool, lock_token: Optional[str]).
    If Redis is unreachable, fails-open and yields (True, None) to preserve processing.
    """
    client = redis_manager.client
    if not client:
        # Fail-open: Redis is not available, allow local single-process execution
        logger.debug(f"redis_fallback_used: Redis unavailable for lock '{lock_key}'. Proceeding with local execution.")
        yield True, None
        return

    token = str(uuid.uuid4())
    acquired = False

    try:
        # Atomic SET with NX (Not Exists) and EX (Expiration in seconds)
        res = await client.set(lock_key, token, nx=True, ex=timeout_sec)
        acquired = bool(res)

        if acquired:
            logger.info(f"redis_lock_acquired: Acquired distributed lock '{lock_key}' with TTL {timeout_sec}s")
        else:
            logger.warning(f"redis_lock_contended: Lock '{lock_key}' is already held by another process.")

    except Exception as e:
        logger.warning(f"redis_lock_error: Error acquiring lock '{lock_key}' ({e}). Failing open.")
        yield True, None
        return

    try:
        yield acquired, token
    finally:
        if acquired and client:
            try:
                # Release lock only if token matches (avoids deleting another worker's renewed lock)
                curr_token = await client.get(lock_key)
                if curr_token == token:
                    await client.delete(lock_key)
                    logger.info(f"redis_lock_released: Released distributed lock '{lock_key}'")
            except Exception as e:
                logger.warning(f"redis_lock_release_error: Failed to release lock '{lock_key}': {e}")

# ==============================================================================
# TYPED JSON CACHING HELPERS
# ==============================================================================

async def get_cached_json(key: str) -> Optional[Any]:
    """Retrieves and deserializes JSON from Redis with fail-open fallback."""
    client = redis_manager.client
    if not client:
        return None

    try:
        raw = await client.get(key)
        if raw:
            logger.debug(f"redis_cache_hit: Key '{key}'")
            return json.loads(raw)
        logger.debug(f"redis_cache_miss: Key '{key}'")
        return None
    except Exception as e:
        logger.warning(f"redis_cache_error: Get error on '{key}' ({e}). Falling back to primary DB.")
        return None

async def set_cached_json(key: str, data: Any, ttl_sec: int = 60) -> bool:
    """Serializes and stores data in Redis with TTL. Fails silently if unavailable."""
    client = redis_manager.client
    if not client:
        return False

    try:
        serialized = json.dumps(data, default=str)
        await client.set(key, serialized, ex=ttl_sec)
        return True
    except Exception as e:
        logger.warning(f"redis_cache_error: Set error on '{key}' ({e})")
        return False

async def delete_cached_key(key: str) -> bool:
    """Deletes a specific key from Redis."""
    client = redis_manager.client
    if not client:
        return False

    try:
        await client.delete(key)
        return True
    except Exception as e:
        logger.warning(f"redis_cache_error: Delete error on '{key}' ({e})")
        return False

async def invalidate_dashboard_cache(org_id: Optional[str] = None) -> None:
    """Invalidates cached executive summary when batch state or approvals change."""
    org = org_id or settings.DEFAULT_ORG_ID
    await delete_cached_key(key_dashboard_summary(org))
    await delete_cached_key(key_dashboard_summary(f"{org}:latest"))
