"""Cross-platform dependency graph builder.

Builds an in-memory DependencyGraph from all landscape_objects for a given
customer/project.  Edges come from the dependencies JSONB column stored by
the scanners.  Also cross-links SAC stories to DSP/BW models where the
model_binding target_id matches a known landscape_object technical_name.

Public helpers:
  build_dependency_graph(ctx) -> DependencyGraph
  upstream(graph, object_id) -> list[GraphNode]
  downstream(graph, object_id) -> list[GraphNode]
  impact_analysis(graph, object_id) -> dict
  to_vis_js(graph) -> dict   (vis.js compatible format for the UI)
"""

from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import asyncpg

from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)

# Edge type constants (mirrors DependencyType in scanner models + SAC extensions)
READS_FROM = "reads_from"
WRITES_TO = "writes_to"
REFERENCES = "references"
CONTAINS = "contains"
MODEL_BINDING = "model_binding"

# Color palette for vis.js node groups (platform → color)
_PLATFORM_COLORS: dict[str, str] = {
    "dsp": "#0070F3",  # blue
    "sac": "#FF6B35",  # orange
    "bw": "#7B2D8B",  # purple
}

# Shape by object_type for vis.js
_TYPE_SHAPES: dict[str, str] = {
    "view": "ellipse",
    "table": "box",
    "adso": "box",
    "transformation": "diamond",
    "process_chain": "triangle",
    "story": "star",
    "optimized_story": "star",
    "analytic_application": "star",
    "model": "circle",
    "data_source": "database",
    "report": "ellipse",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    id: str
    name: str
    platform: str
    object_type: str
    layer: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    edge_type: str  # reads_from | writes_to | references | contains | model_binding
    metadata: Optional[dict] = None


@dataclass
class DependencyGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    # Internal index — built lazily by build_dependency_graph
    _node_index: dict[str, GraphNode] = field(default_factory=dict, repr=False)
    # adjacency: forward (source -> [target]) and backward (target -> [source])
    _forward: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _backward: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def _build_index(self) -> None:
        self._node_index = {n.id: n for n in self.nodes}
        self._forward = {}
        self._backward = {}
        for edge in self.edges:
            self._forward.setdefault(edge.source_id, []).append(edge.target_id)
            self._backward.setdefault(edge.target_id, []).append(edge.source_id)


# ---------------------------------------------------------------------------
# Internal DB helper
# ---------------------------------------------------------------------------


async def _get_conn() -> asyncpg.Connection:
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


async def build_dependency_graph(ctx: ContextEnvelope) -> DependencyGraph:
    """Query all landscape_objects for this customer/project and build a graph.

    Nodes are created from every landscape_object row.
    Edges are derived from the dependencies JSONB column on each row.
    Cross-platform edges (e.g. SAC story -> DSP model) are added by resolving
    model_binding target_ids against the technical_name index.
    """
    import json as _json

    conn = await _get_conn()
    try:
        conditions = ["customer_id = $1"]
        params = [ctx.customer_id]
        if ctx.project_id is not None:
            conditions.append("project_id = $2")
            params.append(ctx.project_id)

        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"""
            SELECT id, platform, object_type, object_name, technical_name,
                   layer, metadata, dependencies
            FROM landscape_objects
            WHERE {where}
            """,
            *params,
        )
    finally:
        await conn.close()

    # Build technical_name → id lookup for cross-platform resolution
    tech_to_id: dict[str, str] = {}
    for row in rows:
        key = row["technical_name"] or row["object_name"]
        if key:
            tech_to_id[key] = str(row["id"])

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for row in rows:
        node_id = str(row["id"])
        meta = row["metadata"]
        if isinstance(meta, str):
            try:
                meta = _json.loads(meta)
            except Exception:
                meta = {}

        nodes.append(
            GraphNode(
                id=node_id,
                name=row["object_name"] or row["technical_name"] or node_id,
                platform=row["platform"],
                object_type=row["object_type"],
                layer=row["layer"],
                metadata=meta,
            )
        )

        # Process dependencies JSONB column
        raw_deps = row["dependencies"]
        if isinstance(raw_deps, str):
            try:
                raw_deps = _json.loads(raw_deps)
            except Exception:
                raw_deps = []

        if isinstance(raw_deps, list):
            for dep in raw_deps:
                if not isinstance(dep, dict):
                    continue
                target_raw = dep.get("target_id", "")
                edge_type = dep.get("dependency_type", READS_FROM)
                dep_meta = dep.get("metadata") or {}

                # Resolve target: might already be a UUID or a technical_name
                target_id = _resolve_target(target_raw, tech_to_id)
                if target_id:
                    edges.append(
                        GraphEdge(
                            source_id=node_id,
                            target_id=target_id,
                            edge_type=edge_type,
                            metadata=dep_meta,
                        )
                    )

    graph = DependencyGraph(nodes=nodes, edges=edges)
    graph._build_index()
    return graph


def _resolve_target(target_raw: str, tech_to_id: dict[str, str]) -> Optional[str]:
    """Resolve a dependency target to a node UUID.

    Accepts either a UUID (already a node id) or a technical_name that maps
    to a known node.  Returns None if unresolvable.
    """
    if not target_raw:
        return None
    # If it's already a UUID-shaped string, trust it
    if len(target_raw) == 36 and target_raw.count("-") == 4:
        return target_raw
    # Try technical_name lookup
    return tech_to_id.get(target_raw)


# ---------------------------------------------------------------------------
# Traversal helpers
# ---------------------------------------------------------------------------


def upstream(graph: DependencyGraph, object_id: str) -> list[GraphNode]:
    """Return all nodes that feed into object_id (BFS over backward edges)."""
    if not graph._node_index:
        graph._build_index()

    visited: set[str] = set()
    queue: deque[str] = deque()
    result: list[GraphNode] = []

    queue.append(object_id)
    visited.add(object_id)

    while queue:
        current = queue.popleft()
        for source_id in graph._backward.get(current, []):
            if source_id not in visited:
                visited.add(source_id)
                node = graph._node_index.get(source_id)
                if node:
                    result.append(node)
                    queue.append(source_id)

    return result


def downstream(graph: DependencyGraph, object_id: str) -> list[GraphNode]:
    """Return all nodes that consume from object_id (BFS over forward edges)."""
    if not graph._node_index:
        graph._build_index()

    visited: set[str] = set()
    queue: deque[str] = deque()
    result: list[GraphNode] = []

    queue.append(object_id)
    visited.add(object_id)

    while queue:
        current = queue.popleft()
        for target_id in graph._forward.get(current, []):
            if target_id not in visited:
                visited.add(target_id)
                node = graph._node_index.get(target_id)
                if node:
                    result.append(node)
                    queue.append(target_id)

    return result


def impact_analysis(graph: DependencyGraph, object_id: str) -> dict:
    """Full impact analysis for an object.

    Returns upstream nodes (sources feeding in) and downstream nodes
    (consumers), the total affected count, and the set of platforms touched.
    """
    if not graph._node_index:
        graph._build_index()

    up = upstream(graph, object_id)
    down = downstream(graph, object_id)

    all_affected = up + down
    platforms: set[str] = {n.platform for n in all_affected}

    return {
        "object_id": object_id,
        "upstream": [_node_to_dict(n) for n in up],
        "downstream": [_node_to_dict(n) for n in down],
        "affected_count": len(all_affected),
        "platforms_affected": sorted(platforms),
    }


def _node_to_dict(node: GraphNode) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "platform": node.platform,
        "object_type": node.object_type,
        "layer": node.layer,
    }


# ---------------------------------------------------------------------------
# vis.js serialization
# ---------------------------------------------------------------------------


def to_vis_js(graph: DependencyGraph) -> dict:
    """Serialize the graph to vis.js Network format.

    Returns:
        {
            "nodes": [{"id", "label", "group", "color", "shape", "title"}, ...],
            "edges": [{"from", "to", "label", "arrows"}, ...]
        }

    Node groups map to platforms (dsp / sac / bw / unknown).
    Edge arrows always point from source to target.
    """
    vis_nodes = []
    for node in graph.nodes:
        color = _PLATFORM_COLORS.get(node.platform, "#888888")
        shape = _TYPE_SHAPES.get(node.object_type, "ellipse")
        title = f"{node.platform.upper()} | {node.object_type}" + (f" | {node.layer}" if node.layer else "")
        vis_nodes.append(
            {
                "id": node.id,
                "label": node.name,
                "group": node.platform,
                "color": color,
                "shape": shape,
                "title": title,
            }
        )

    vis_edges = []
    for edge in graph.edges:
        vis_edges.append(
            {
                "from": edge.source_id,
                "to": edge.target_id,
                "label": edge.edge_type.replace("_", " "),
                "arrows": "to",
            }
        )

    return {"nodes": vis_nodes, "edges": vis_edges}
