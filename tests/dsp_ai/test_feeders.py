"""Integration tests for Brain feeders.

Skipped when NEO4J_URL is unset.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spec2sphere.dsp_ai.brain import client, schema
from spec2sphere.dsp_ai.brain.feeders.dsp_data import record_row_count_delta
from spec2sphere.dsp_ai.brain.feeders.schema_semantic import feed_from_graph_json

pytestmark = pytest.mark.skipif(
    not (os.environ.get("NEO4J_URL") and os.environ.get("NEO4J_PASSWORD")),
    reason="NEO4J_URL / NEO4J_PASSWORD not set — integration test",
)


@pytest.fixture(autouse=True)
async def _clean_brain():
    await schema.bootstrap()
    await client.run("MATCH (n) DETACH DELETE n")
    yield
    await client.close()


@pytest.mark.asyncio
async def test_feed_from_graph_json_objects_shape(tmp_path: Path) -> None:
    graph = {
        "objects": [
            {
                "id": "space.sales.daily",
                "kind": "View",
                "columns": [
                    {"name": "region", "dtype": "TEXT", "nullable": False},
                    {"name": "revenue", "dtype": "NUMERIC", "nullable": True},
                ],
            },
        ]
    }
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(graph))
    counts = await feed_from_graph_json("horvath", p)
    assert counts == {"objects": 1, "columns": 2}

    rows = await client.run("MATCH (o:DspObject)-[:HAS_COLUMN]->(c) RETURN count(c) AS n")
    assert rows[0]["n"] == 2

    customers = await client.run("MATCH (o:DspObject) RETURN o.customer AS c")
    assert {r["c"] for r in customers} == {"horvath"}


@pytest.mark.asyncio
async def test_feed_from_graph_json_scanner_shape(tmp_path: Path) -> None:
    """Accepts the real scanner output format (nodes + edges, no nested columns)."""
    graph = {
        "source_system": "horvath_demo",
        "nodes": [
            {"id": "DSP_SALES_VIEW", "type": "View", "name": "Sales", "layer": "mart"},
            {"id": "DSP_RAW_ORDERS", "type": "Table", "name": "Orders", "layer": "raw"},
        ],
        "edges": [{"source": "DSP_SALES_VIEW", "target": "DSP_RAW_ORDERS", "type": "uses"}],
    }
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(graph))
    counts = await feed_from_graph_json("horvath", p)
    assert counts == {"objects": 2, "columns": 0}
    rows = await client.run("MATCH (o:DspObject) RETURN count(o) AS n")
    assert rows[0]["n"] == 2


@pytest.mark.asyncio
async def test_record_row_count_delta_creates_event() -> None:
    eid = await record_row_count_delta("DSP_SALES_VIEW", old=100, new=250)
    rows = await client.run(
        """
        MATCH (o:DspObject {id: $oid})-[:CHANGED_AT]->(e:Event)
        RETURN e.id AS id, e.old_value AS old, e.new_value AS new, e.metric AS metric
        """,
        oid="DSP_SALES_VIEW",
    )
    assert rows[0]["id"] == eid
    assert rows[0]["old"] == 100
    assert rows[0]["new"] == 250
    assert rows[0]["metric"] == "row_count"
