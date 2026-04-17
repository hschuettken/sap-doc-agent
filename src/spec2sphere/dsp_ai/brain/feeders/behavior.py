"""Behavior feeder — widget telemetry → user_state (Postgres) + Brain behavior edges."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

import asyncpg

from ...settings import postgres_dsn
from ..client import run as brain_run

if TYPE_CHECKING:
    from ...adapters.live import TelemetryEvent  # noqa: F401

logger = logging.getLogger(__name__)


async def record_event(event: "TelemetryEvent") -> None:
    """Upsert user_state, then write the matching Brain behavior edge.

    Best-effort on the Brain side — Neo4j down must not break widget
    telemetry. The Postgres upsert is the system of record for last-visit.
    """
    conn = await asyncpg.connect(postgres_dsn())
    try:
        await conn.execute(
            """
            INSERT INTO dsp_ai.user_state (user_id, last_visited_at, updated_at)
            VALUES ($1, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                last_visited_at = EXCLUDED.last_visited_at,
                updated_at = EXCLUDED.updated_at
            """,
            event.user_id,
        )
    finally:
        await conn.close()

    if not event.object_id:
        return

    try:
        if event.kind == "widget.rendered":
            await brain_run(
                """
                MERGE (u:User {email: $email})
                MERGE (o:DspObject {id: $oid})
                MERGE (u)-[r:OPENED]->(o)
                SET r.ts = datetime($ts)
                """,
                email=event.user_id,
                oid=event.object_id,
                ts=dt.datetime.utcnow().isoformat(),
            )
        elif event.kind == "widget.dwelled":
            await brain_run(
                """
                MERGE (u:User {email: $email})
                MERGE (o:DspObject {id: $oid})
                MERGE (u)-[r:DWELLED_ON]->(o)
                SET r.duration_s = coalesce(r.duration_s, 0.0) + $d
                """,
                email=event.user_id,
                oid=event.object_id,
                d=event.duration_s or 0.0,
            )
        elif event.kind == "widget.clicked":
            await brain_run(
                """
                MERGE (u:User {email: $email})
                MERGE (o:DspObject {id: $oid})
                MERGE (u)-[r:CLICKED]->(o)
                SET r.count = coalesce(r.count, 0) + 1, r.ts = datetime($ts)
                """,
                email=event.user_id,
                oid=event.object_id,
                ts=dt.datetime.utcnow().isoformat(),
            )
        # widget.declined: no edge; could be added later
    except Exception:
        logger.exception("behavior.record_event: brain write failed (best-effort)")


async def synthesize_topics_async(lookback_days: int = 14) -> dict:
    """Derive Topic + INTERESTED_IN edges per active user (LLM-clustered).

    For every user with ≥1 OPENED/DWELLED_ON edge in the last N days,
    ask the LLM to cluster the DSP object IDs into named topics with weights.
    Writes :Topic nodes + :INTERESTED_IN edges (user → topic, weight float).

    Returns a summary dict for the scheduler.
    """
    users = await brain_run(
        """
        MATCH (u:User)-[r:OPENED|DWELLED_ON]->(o:DspObject)
        WHERE r.ts IS NULL OR r.ts > datetime() - duration({days: $d})
        RETURN u.email AS email, collect(DISTINCT o.id) AS objects
        """,
        d=lookback_days,
    )
    if not users:
        return {"users_seen": 0, "topics_written": 0}

    # Lazy import — the LLM router imports settings that bind to env, so
    # defer until first call to keep the module import-light at startup.
    from spec2sphere.llm.quality_router import resolve_and_call  # noqa: PLC0415

    schema = {
        "type": "object",
        "required": ["topics"],
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "members", "weight"],
                    "properties": {
                        "name": {"type": "string"},
                        "members": {"type": "array", "items": {"type": "string"}},
                        "weight": {"type": "number"},
                    },
                },
            },
        },
    }

    topics_written = 0
    for u in users:
        email = u["email"]
        objects = u["objects"]
        if not objects:
            continue
        prompt = (
            "Cluster these DSP object ids into 1–5 named business topics. "
            'Return JSON: {"topics":[{"name":str,"members":[str],"weight":float 0-1}]}.\n'
            f"Objects: {objects}"
        )
        try:
            result, _meta = await resolve_and_call(
                "test_llm",
                prompt,
                schema=schema,
            )
        except Exception:
            logger.exception("synthesize_topics: LLM call failed for %s", email)
            continue

        topics = (result or {}).get("topics", [])
        for t in topics:
            try:
                await brain_run(
                    """
                    MERGE (u:User {email: $email})
                    MERGE (t:Topic {name: $name})
                    MERGE (u)-[r:INTERESTED_IN]->(t)
                    SET r.weight = $w
                    """,
                    email=email,
                    name=t["name"],
                    w=float(t.get("weight", 0.5)),
                )
                topics_written += 1
            except Exception:
                logger.exception("synthesize_topics: brain write failed for %s/%s", email, t.get("name"))

    return {"users_seen": len(users), "topics_written": topics_written}
