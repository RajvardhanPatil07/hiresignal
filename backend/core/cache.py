"""Redis cache utilities for HireSignal."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from backend.core.config import get_settings
from backend.core.exceptions import CacheError

logger = logging.getLogger(__name__)

_redis_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create a Redis connection pool.

    Returns:
        Async Redis client instance.
    """
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        try:
            _redis_pool = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as exc:
            logger.error("Failed to connect to Redis: %s", exc)
            raise CacheError(f"Redis connection failed: {exc}") from exc
    return _redis_pool


def _make_cache_key(prefix: str, data: dict[str, Any]) -> str:
    """Create a deterministic cache key from input data.

    Args:
        prefix: Key prefix for namespacing.
        data: Dictionary of data to hash.

    Returns:
        Cache key string.
    """
    payload = json.dumps(data, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32]
    return f"{prefix}:{digest}"


async def get_cached(prefix: str, data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Retrieve cached result if available.

    Args:
        prefix: Cache namespace prefix.
        data: Input data dict to generate cache key.

    Returns:
        Cached dict or None if miss.
    """
    try:
        r = await get_redis()
        key = _make_cache_key(prefix, data)
        cached = await r.get(key)
        if cached:
            logger.debug("Cache hit for key: %s", key)
            return json.loads(cached)
        return None
    except Exception as exc:
        logger.warning("Cache read error (non-blocking): %s", exc)
        return None


async def set_cached(
    prefix: str,
    data: dict[str, Any],
    result: dict[str, Any],
    ttl: Optional[int] = None,
) -> None:
    """Store result in cache with TTL.

    Args:
        prefix: Cache namespace prefix.
        data: Input data dict to generate cache key.
        result: Result dict to cache.
        ttl: Time-to-live in seconds. Uses default from settings if None.
    """
    try:
        r = await get_redis()
        key = _make_cache_key(prefix, data)
        settings = get_settings()
        ttl = ttl or settings.CACHE_TTL_SECONDS
        await r.set(key, json.dumps(result, default=str), ex=ttl)
        logger.debug("Cache set for key: %s (ttl=%ds)", key, ttl)
    except Exception as exc:
        logger.warning("Cache write error (non-blocking): %s", exc)


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Redis connection closed.")
