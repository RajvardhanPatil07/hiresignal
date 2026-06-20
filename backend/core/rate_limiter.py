"""Simple in-memory + Redis-backed rate limiter."""

from __future__ import annotations

import logging
import time
from typing import Optional

import redis.asyncio as redis

from backend.core.config import get_settings
from backend.core.exceptions import RateLimitError

logger = logging.getLogger(__name__)

# Fallback in-memory store when Redis is unavailable
_memory_store: dict[str, list[float]] = {}


async def check_rate_limit(
    api_key: str,
    redis_client: Optional[redis.Redis] = None,
) -> None:
    """Check if the API key has exceeded the rate limit.

    Uses Redis sliding window if available, falls back to in-memory.

    Args:
        api_key: The API key to check.
        redis_client: Optional Redis client. Creates one if not provided.

    Raises:
        RateLimitError: If the rate limit is exceeded.
    """
    settings = get_settings()
    limit = settings.RATE_LIMIT_REQUESTS_PER_MINUTE
    window = 60  # 1 minute window
    now = time.time()

    if redis_client is not None:
        try:
            await _check_redis(redis_client, api_key, limit, window, now)
            return
        except Exception:
            logger.warning("Redis rate limiter failed, falling back to memory")

    await _check_memory(api_key, limit, window, now)


async def _check_redis(
    r: redis.Redis,
    api_key: str,
    limit: int,
    window: int,
    now: float,
) -> None:
    """Redis-backed sliding window rate limit check."""
    key = f"rate_limit:{api_key}"
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, window)
    _, current_count, _, _ = await pipe.execute()

    if current_count >= limit:
        raise RateLimitError(
            f"Rate limit exceeded: {limit} requests per minute. "
            "Please slow down and try again later."
        )


async def _check_memory(
    api_key: str,
    limit: int,
    window: int,
    now: float,
) -> None:
    """In-memory sliding window rate limit check."""
    global _memory_store
    key = api_key
    window_start = now - window

    # Clean old entries
    entries = _memory_store.get(key, [])
    entries = [t for t in entries if t > window_start]
    _memory_store[key] = entries

    if len(entries) >= limit:
        raise RateLimitError(
            f"Rate limit exceeded: {limit} requests per minute. "
            "Please slow down and try again later."
        )

    entries.append(now)
