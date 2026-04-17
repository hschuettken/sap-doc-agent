"""Dual-read graph access for the Session B Neo4j cutover.

Read the DSP object graph from either the legacy ``output/graph.json`` file
(default) or the Corporate Brain (Neo4j), controlled by
``GRAPH_READ_FROM_BRAIN=true``.

Only new code paths (e.g. ContentHub in Task 9) call these helpers —
``chain_builder`` and the scan Web routes still consume the file directly
to keep Session B changes minimal.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def read_from_brain() -> bool:
    return os.environ.get("GRAPH_READ_FROM_BRAIN", "false").lower() == "true"


def _graph_file(output_dir: str | Path = "output") -> Path:
    return Path(output_dir) / "graph.json"


async def list_objects(customer: str | None = None, *, output_dir: str | Path = "output") -> list[dict[str, Any]]:
    """Return all DSP objects for the given customer.

    If the Brain flag is off, read the newest graph.json. ``customer`` is a
    no-op in file mode (one file per scan). When reading from Brain, filter
    by the customer property on DspObject nodes.
    """
    if read_from_brain():
        from spec2sphere.dsp_ai.brain.client import run as brain_run  # noqa: E402

        cypher = (
            "MATCH (o:DspObject) "
            + ("WHERE o.customer = $customer " if customer else "")
            + "OPTIONAL MATCH (o)-[:HAS_COLUMN]->(c:Column) "
            "RETURN o.id AS id, o.kind AS kind, o.name AS name, "
            "collect(DISTINCT c.id) AS column_ids"
        )
        params: dict[str, Any] = {}
        if customer:
            params["customer"] = customer
        rows = await brain_run(cypher, **params)
        return [dict(r) for r in rows]

    path = _graph_file(output_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return list(data.get("nodes", []))


async def list_edges(customer: str | None = None, *, output_dir: str | Path = "output") -> list[dict[str, Any]]:
    """Return all DSP dependency edges for the given customer.

    File mode returns edges from graph.json; Brain mode queries Neo4j
    relationships between DspObject nodes.
    """
    if read_from_brain():
        from spec2sphere.dsp_ai.brain.client import run as brain_run  # noqa: E402

        cypher = (
            "MATCH (s:DspObject)-[r]->(t:DspObject) "
            + ("WHERE s.customer = $customer " if customer else "")
            + "RETURN s.id AS source, t.id AS target, type(r) AS type LIMIT 5000"
        )
        params: dict[str, Any] = {}
        if customer:
            params["customer"] = customer
        rows = await brain_run(cypher, **params)
        return [dict(r) for r in rows]

    path = _graph_file(output_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return list(data.get("edges", []))
