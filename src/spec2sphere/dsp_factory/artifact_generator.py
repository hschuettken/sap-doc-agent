"""Artifact Generator — builds DSP deployment artifacts from scanned objects.

Provides:
- DEV-copy SQL generation
- Topologically-sorted deployment manifests (Kahn's algorithm)
- CSN (Core Schema Notation) definition generation
"""

from __future__ import annotations

import logging
from collections import deque

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type mapping: SQL-ish types → CDS types
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "INT": "cds.Integer",
    "INTEGER": "cds.Integer",
    "BIGINT": "cds.Integer",
    "SMALLINT": "cds.Integer",
    "DECIMAL": "cds.Decimal",
    "FLOAT": "cds.Decimal",
    "DOUBLE": "cds.Decimal",
    "REAL": "cds.Decimal",
    "NUMERIC": "cds.Decimal",
    "DATE": "cds.Date",
    "TIME": "cds.Time",
    "TIMESTAMP": "cds.Timestamp",
    "DATETIME": "cds.Timestamp",
    "BOOL": "cds.Boolean",
    "BOOLEAN": "cds.Boolean",
}


def _sql_to_cds_type(sql_type: str) -> str:
    """Map a SQL/DSP column type to the corresponding CDS type string."""
    normalised = sql_type.upper().split("(")[0].strip()
    return _TYPE_MAP.get(normalised, "cds.String")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def generate_dev_copy_sql(view_name: str, original_sql: str) -> dict:
    """Return a DEV-copy view name and annotated SQL for the _DEV environment.

    The SQL is returned as-is with a comment header — no structural changes
    are made to the query itself so the caller can pipe it straight into DSP.
    """
    dev_view_name = f"{view_name}_DEV"
    dev_sql = f"-- _DEV copy of {view_name}\n{original_sql}"
    return {"dev_view_name": dev_view_name, "dev_sql": dev_sql}


def generate_deployment_manifest(objects: list[dict]) -> list[dict]:
    """Produce a topologically-sorted deployment manifest.

    Uses Kahn's BFS algorithm so that dependencies are deployed before
    dependants.  Nodes at the same depth are ordered alphabetically for
    deterministic output.  If a cycle is detected the remaining nodes are
    appended at the end with a warning.

    Each output item is a shallow copy of the input dict extended with:
        deploy_order (int, 0-based)
        create_or_update (str, always "create")
    """
    # Index by name
    by_name: dict[str, dict] = {obj["name"]: obj for obj in objects}

    # Build adjacency: in-degree count and reverse-edge map
    in_degree: dict[str, int] = {name: 0 for name in by_name}
    dependants: dict[str, list[str]] = {name: [] for name in by_name}

    for obj in objects:
        deps = obj.get("dependencies") or []
        for dep in deps:
            if dep not in by_name:
                # External dependency — ignore for ordering purposes
                continue
            in_degree[obj["name"]] += 1
            dependants[dep].append(obj["name"])

    # Kahn's BFS — process zero-in-degree nodes alphabetically for stability
    queue: deque[str] = deque(sorted(n for n, deg in in_degree.items() if deg == 0))
    result: list[dict] = []
    order = 0

    while queue:
        name = queue.popleft()
        entry = {**by_name[name], "deploy_order": order, "create_or_update": "create"}
        result.append(entry)
        order += 1

        # Reduce in-degree for dependants; add newly-zero ones in alpha order
        newly_free: list[str] = []
        for dependant in dependants[name]:
            in_degree[dependant] -= 1
            if in_degree[dependant] == 0:
                newly_free.append(dependant)
        for n in sorted(newly_free):
            queue.append(n)

    # Cycle detection: any node with in_degree > 0 is in a cycle
    remaining = sorted(n for n, deg in in_degree.items() if deg > 0)
    if remaining:
        logger.warning(
            "Cycle detected in dependency graph — appending %d node(s) unordered: %s",
            len(remaining),
            remaining,
        )
        for name in remaining:
            entry = {**by_name[name], "deploy_order": order, "create_or_update": "create"}
            result.append(entry)
            order += 1

    return result


def generate_csn_definition(obj: dict) -> dict:
    """Build a CSN-like JSON definition for a single DSP object.

    Input must contain:
        name (str)
        object_type (str)
        columns (list of {name: str, type: str})

    Returns a dict in the shape:
        {"definitions": {"<name>": {"kind": "entity", "elements": {<col>: {"type": <cds_type>}}}}}
    """
    name: str = obj["name"]
    columns: list[dict] = obj.get("columns") or []

    elements: dict[str, dict] = {}
    for col in columns:
        col_name = col["name"]
        cds_type = _sql_to_cds_type(col.get("type", ""))
        elements[col_name] = {"type": cds_type}

    return {
        "definitions": {
            name: {
                "kind": "entity",
                "elements": elements,
            }
        }
    }
