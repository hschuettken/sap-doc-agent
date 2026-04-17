"""Postgres LISTEN/NOTIFY helpers for the dsp_ai event bus.

Every cross-service signal in dsp_ai rides on Postgres NOTIFY so the
entire add-on stays portable (no NATS, no MQTT, no Redis pub/sub).

Usage::

    # fire-and-forget signal
    await emit("enhancement_published", {"id": "..."})

    # background listener
    async for event in subscribe("briefing_generated"):
        handle(event)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import asyncpg

from .settings import postgres_dsn

logger = logging.getLogger(__name__)


async def emit(channel: str, payload: dict[str, Any]) -> None:
    """Publish a NOTIFY on ``channel`` with a JSON payload.

    Opens and closes a dedicated connection — emits are rare and short,
    so the pool overhead is wasted complexity here.
    """
    from .db import get_conn  # noqa: PLC0415

    async with get_conn() as conn:
        await conn.execute("SELECT pg_notify($1, $2)", channel, json.dumps(payload))


async def subscribe(
    channel: str,
    *,
    reconnect_delay: float = 2.0,
) -> AsyncIterator[dict[str, Any]]:
    """Yield payloads received on ``channel``.

    Runs forever; caller cancels the enclosing task to stop listening.
    Each consumer gets its own LISTEN connection — keeps the wiring
    trivial at small scale, and avoids cross-consumer head-of-line blocking.
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def _callback(_conn, _pid, _channel, payload_str):  # type: ignore[no-untyped-def]
        try:
            queue.put_nowait(json.loads(payload_str))
        except Exception:  # pragma: no cover — malformed NOTIFY payload
            logger.exception("failed to decode NOTIFY payload on %s", channel)

    from .db import current_customer  # noqa: PLC0415

    while True:
        try:
            conn = await asyncpg.connect(postgres_dsn())
            await conn.execute("SELECT set_config('dspai.customer', $1, false)", current_customer())
        except Exception:
            logger.warning("NOTIFY listen connect failed for %s; retrying", channel, exc_info=True)
            await asyncio.sleep(reconnect_delay)
            continue

        try:
            await conn.add_listener(channel, _callback)
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # heartbeat ping so dead connections surface quickly
                    await conn.execute("SELECT 1")
                    continue
                yield payload
        except (asyncpg.PostgresConnectionError, ConnectionError, OSError):
            logger.warning("NOTIFY listen connection lost for %s; reconnecting", channel)
            await asyncio.sleep(reconnect_delay)
        finally:
            try:
                await conn.remove_listener(channel, _callback)
            except Exception:
                pass
            await conn.close()
