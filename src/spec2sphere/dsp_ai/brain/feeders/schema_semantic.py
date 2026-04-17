"""Schema/semantic feeder — populates DspObject (+ optional Column, domain)
nodes in the Corporate Brain from the Spec2Sphere scanner's graph.json.

Accepts two graph shapes so the same feeder works against both the real
scanner output (``{nodes, edges}``) and hand-authored test fixtures that
use the more expressive ``{objects: [{columns: [...]}]}`` shape.

Triggers:
  - Celery on ``pg_notify('scan_completed', {customer, graph_path})``
  - cron ``BRAIN_FEEDER_CRON`` (default 0 */4 * * *)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any



def _normalise_graph(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield a uniform list of object dicts from either graph shape."""
    if "objects" in raw:
        return list(raw["objects"])
    # Scanner shape: {"nodes": [{"id": ..., "type": ..., ...}], "edges": [...]}
    objs: list[dict[str, Any]] = []
    for n in raw.get("nodes", []):
        objs.append(
            {
                "id": n.get("id"),
                "kind": n.get("type") or n.get("kind") or "Unknown",
                "columns": n.get("columns", []),
            }
        )
    return objs


async def feed_from_graph_json(customer: str, graph_path: Path) -> dict[str, int]:
    """Read ``graph_path``, MERGE DspObject + Column + HAS_COLUMN edges.

    Returns counts of objects + columns written so callers can log the
    feeder's effect.
    """
    from ..client import run_scoped  # noqa: PLC0415

    data = json.loads(Path(graph_path).read_text())
    counts = {"objects": 0, "columns": 0}
    for obj in _normalise_graph(data):
        oid = obj.get("id")
        if not oid:
            continue
        await run_scoped(
            """
            MERGE (o:DspObject {id: $id, customer: $customer})
            SET o.kind = $kind
            """,
            customer,
            id=oid,
            kind=obj.get("kind", "Unknown"),
        )
        counts["objects"] += 1
        for col in obj.get("columns") or []:
            col_name = col.get("name")
            if not col_name:
                continue
            col_id = f"{oid}.{col_name}"
            await run_scoped(
                """
                MATCH (o:DspObject {id: $oid, customer: $customer})
                MERGE (c:Column {id: $cid})
                SET c.dtype = $dtype, c.nullable = $nullable
                MERGE (o)-[:HAS_COLUMN]->(c)
                """,
                customer,
                oid=oid,
                cid=col_id,
                dtype=col.get("dtype", "?"),
                nullable=col.get("nullable", True),
            )
            counts["columns"] += 1
    return counts
