"""Enhancement output cache (Redis).

Stores shaped engine output keyed by ``dspai:enhance:{id}:{user}:{hash}``.
Hash derives from context_hints so distinct filter views don't trample
each other. TTL from config; invalidated on ``enhancement_published``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from redis.asyncio import Redis

_redis: Redis | None = None


def _get() -> Redis:
    global _redis
    if _redis is None:
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis = Redis.from_url(url, decode_responses=True)
    return _redis


def key_for(enhancement_id: str, user_id: str | None, context_hints: dict[str, Any]) -> str:
    h = hashlib.sha256(json.dumps(context_hints, sort_keys=True).encode()).hexdigest()[:16]
    return f"dspai:enhance:{enhancement_id}:{user_id or '_'}:{h}"


async def get(k: str) -> dict[str, Any] | None:
    v = await _get().get(k)
    return json.loads(v) if v else None


async def set_(k: str, v: dict[str, Any], ttl: int) -> None:
    await _get().set(k, json.dumps(v), ex=ttl)


async def invalidate_prefix(prefix: str) -> int:
    """Delete all keys starting with ``prefix``. Returns count deleted."""
    r = _get()
    cursor = 0
    total = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=f"{prefix}*", count=200)
        if keys:
            await r.delete(*keys)
            total += len(keys)
        if cursor == 0:
            break
    return total


async def close() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
