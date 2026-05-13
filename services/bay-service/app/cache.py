"""Redis async client and bay status cache helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Key patterns
BAY_STATUS_KEY = "bay:{bay_code}:status"
BAY_OCCUPANCY_KEY = "bay:{bay_code}:occupancy"

# 5-minute TTL — Mendix polls every 10 s so stale data is bounded
_STATUS_TTL = 300


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

_redis_pool: aioredis.Redis | None = None


def init_redis_pool() -> aioredis.Redis:
    """Create the module-level Redis connection pool."""
    global _redis_pool
    _redis_pool = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
    )
    return _redis_pool


async def close_redis_pool() -> None:
    """Close the Redis connection pool on shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency: yield the shared Redis client."""
    if _redis_pool is None:
        raise RuntimeError("Redis pool not initialised — call init_redis_pool() in lifespan")
    yield _redis_pool


# ---------------------------------------------------------------------------
# Bay status helpers
# ---------------------------------------------------------------------------

async def set_bay_status(r: aioredis.Redis, bay_code: str, status_dict: dict) -> None:
    """Serialise *status_dict* to JSON and store in Redis with TTL."""
    key = BAY_STATUS_KEY.format(bay_code=bay_code)
    await r.set(key, json.dumps(status_dict, default=str), ex=_STATUS_TTL)


async def get_bay_status(r: aioredis.Redis, bay_code: str) -> dict | None:
    """Return the cached status dict for *bay_code*, or ``None`` on cache miss."""
    key = BAY_STATUS_KEY.format(bay_code=bay_code)
    raw = await r.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Corrupt Redis entry for key %s — evicting", key)
        await r.delete(key)
        return None


async def get_all_bay_statuses(r: aioredis.Redis) -> list[dict]:
    """Scan all ``bay:*:status`` keys and return a list of status dicts.

    Uses SCAN to avoid blocking the Redis event loop.  Entries that fail
    JSON parsing are skipped with a warning.
    """
    pattern = "bay:*:status"
    results: list[dict] = []
    async for key in r.scan_iter(match=pattern, count=200):
        raw = await r.get(key)
        if raw is None:
            continue
        try:
            results.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("Skipping corrupt Redis entry: %s", key)
    return results


async def delete_bay_status(r: aioredis.Redis, bay_code: str) -> None:
    """Remove the cached status for *bay_code* (e.g., on bay deactivation)."""
    key = BAY_STATUS_KEY.format(bay_code=bay_code)
    await r.delete(key)
