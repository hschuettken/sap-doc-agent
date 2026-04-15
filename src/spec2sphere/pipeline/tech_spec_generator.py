"""Technical Specification Generator.

Generates detailed technical object inventories from approved HLA documents.
Produces DSP SQL views, dependency graphs, and deployment ordering.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from spec2sphere.db import _get_conn
from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.migration.sql_validator import validate_dsp_sql
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer naming conventions
# ---------------------------------------------------------------------------

# HLA layer name → naming prefix for technical objects
_LAYER_PREFIXES: dict[str, str] = {
    "raw": "01_LT_",
    "harmonized": "02_RV_",
    "mart": "03_FV_",
    "consumption": "04_CV_",
}

# Canonical layer name normalization (HLA uses uppercase)
_LAYER_NORM: dict[str, str] = {
    "RAW": "raw",
    "HARMONIZED": "harmonized",
    "MART": "mart",
    "CONSUMPTION": "consumption",
    # lower-case pass-through
    "raw": "raw",
    "harmonized": "harmonized",
    "mart": "mart",
    "consumption": "consumption",
}

# HLA view type → technical object_type
_TYPE_MAP: dict[str, str] = {
    "relational_dataset": "relational_view",
    "fact": "fact_view",
    "dimension": "dimension_view",
    "text": "text_view",
    "hierarchy": "hierarchy_view",
    "analytic_model": "analytic_model",
}

# Topological layer ordering for stable sort
_LAYER_ORDER: dict[str, int] = {
    "raw": 0,
    "harmonized": 1,
    "mart": 2,
    "consumption": 3,
}

# DSP SQL rules summary (injected into generation prompt)
_DSP_SQL_RULES_SUMMARY = (
    "DSP SQL constraints you MUST follow:\n"
    "1. No WITH/CTE clauses — use inline subqueries instead.\n"
    "2. LIMIT inside UNION ALL must be wrapped in parentheses.\n"
    "3. Column aliases required on every UNION ALL leg.\n"
    "4. SELECT * fails on cross-space joins — use explicit column names.\n"
    '5. Cross-space references must use quoted "SPACE"."view_name" format.\n'
    "6. Avoid --> inside block comments.\n"
    "7. ROW_NUMBER ORDER BY should include DATAB DESC for validity periods.\n"
    "8. Date comparisons must use VARCHAR YYYYMMDD string format (e.g. DATAB <= '20260101').\n"
)


# ---------------------------------------------------------------------------
# JSON schema for LLM technical object detail generation
# ---------------------------------------------------------------------------

_TECH_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "data_type": {"type": "string"},
                    "description": {"type": "string"},
                    "source_field": {"type": "string"},
                    "is_key": {"type": "boolean"},
                    "is_measure": {"type": "boolean"},
                    "calculation": {"type": "string"},
                    "transformation": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "source_to_target_mapping": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_object": {"type": "string"},
                    "source_field": {"type": "string"},
                    "target_field": {"type": "string"},
                    "transformation": {"type": "string"},
                },
            },
        },
        "join_conditions": {"type": "array", "items": {"type": "string"}},
        "business_rules": {"type": "array", "items": {"type": "string"}},
        "filters": {"type": "array", "items": {"type": "string"}},
        "parameters": {"type": "array", "items": {"type": "string"}},
        "sql": {"type": "string"},
    },
    "required": ["columns", "sql"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to plain dict, serializing UUIDs and datetimes."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d


def _normalize_layer(raw_layer: str) -> str:
    """Normalize an HLA layer string to lowercase canonical form."""
    return _LAYER_NORM.get(raw_layer, raw_layer.lower())


def _apply_naming_prefix(name: str, layer: str) -> str:
    """Ensure a technical object name carries the correct layer prefix.

    If the name already starts with the expected prefix, it is returned as-is.
    Otherwise the prefix is prepended.
    """
    prefix = _LAYER_PREFIXES.get(layer, "")
    if not prefix:
        return name
    if name.upper().startswith(prefix.upper()):
        return name
    # Strip any existing numeric prefix pattern (01_XX_, 02_XX_, …) before adding ours
    import re  # noqa: PLC0415

    cleaned = re.sub(r"^\d{2}_[A-Z]{2,3}_", "", name)
    return f"{prefix}{cleaned}"


def _build_dependency_graph(views: list[dict]) -> dict[str, list[str]]:
    """Build {object_name: [depends_on_names]} from view source declarations."""
    name_set = {v["name"] for v in views}
    graph: dict[str, list[str]] = {}
    for v in views:
        deps = [s for s in v.get("sources", []) if s in name_set]
        graph[v["name"]] = deps
    return graph


def _topological_sort(
    names: list[str],
    dep_graph: dict[str, list[str]],
    layer_by_name: dict[str, str],
) -> list[str]:
    """Kahn's algorithm topological sort; ties broken by layer order.

    Mirrors the pattern from spec2sphere.migration.architect._build_migration_sequence.
    """
    in_degree: dict[str, int] = {n: 0 for n in names}
    dependents: dict[str, list[str]] = {n: [] for n in names}

    for name in names:
        for dep in dep_graph.get(name, []):
            if dep in in_degree:
                in_degree[name] += 1
                dependents[dep].append(name)

    queue = sorted(
        [n for n, deg in in_degree.items() if deg == 0],
        key=lambda n: _LAYER_ORDER.get(layer_by_name.get(n, ""), 99),
    )
    ordered: list[str] = []

    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for child in sorted(dependents[current]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
        queue.sort(key=lambda n: _LAYER_ORDER.get(layer_by_name.get(n, ""), 99))

    # Append any nodes not reached (cycles or disconnected)
    for n in names:
        if n not in ordered:
            ordered.append(n)

    return ordered


async def _generate_dsp_object_detail(
    view: dict,
    hla_context: dict,
    llm: LLMProvider,
    kb_context: str = "",
) -> tuple[dict, str, int]:
    """Generate column definitions and SQL for a single DSP view.

    Returns (definition_dict, validated_sql, sql_error_count).
    """
    system_prompt = (
        "You are an SAP Datasphere SQL developer. "
        "Generate clean, deployable DSP SQL for the described view. "
        f"{_DSP_SQL_RULES_SUMMARY}"
        "Return a JSON object with 'columns' (array of column definitions) and 'sql' (the complete SELECT statement). "
        "Do not include CREATE VIEW — only the SELECT body."
    )

    view_summary = json.dumps(
        {
            "name": view.get("name"),
            "layer": view.get("layer"),
            "type": view.get("type"),
            "description": view.get("description", ""),
            "sources": view.get("sources", []),
            "columns": view.get("columns", []),
        },
        indent=2,
    )

    replication_info = ""
    replication_strategy = hla_context.get("replication_strategy", [])
    if replication_strategy:
        replication_info = "\nReplication strategy (source tables available in RAW layer):\n" + json.dumps(
            replication_strategy[:5], indent=2
        )

    prompt = f"Generate a complete technical specification for this DSP view:\n\n{view_summary}\n{replication_info}\n"
    if kb_context:
        prompt += f"\nExisting landscape context:\n{kb_context}\n"
    prompt += (
        "\nGenerate realistic column definitions with SAP naming conventions "
        "(UPPERCASE with underscores) and a valid DSP SQL SELECT statement. "
        "Include all required columns, join logic, and business transformations."
    )

    result = await generate_json_with_retry(
        provider=llm,
        prompt=prompt,
        schema=_TECH_OBJECT_SCHEMA,
        system=system_prompt,
        max_retries=3,
    )

    if result is None:
        result = {"columns": [], "sql": ""}

    generated_sql: str = result.get("sql", "") or ""
    sql_error_count = 0

    if generated_sql.strip():
        validation = validate_dsp_sql(generated_sql)
        sql_error_count = validation.error_count
        if not validation.is_valid:
            logger.warning(
                "SQL validation issues for view '%s': %d error(s), %d warning(s)",
                view.get("name"),
                validation.error_count,
                validation.warning_count,
            )

    definition = {
        "columns": result.get("columns", []),
        "source_to_target_mapping": result.get("source_to_target_mapping", []),
        "join_conditions": result.get("join_conditions", []),
        "business_rules": result.get("business_rules", []),
        "filters": result.get("filters", []),
        "parameters": result.get("parameters", []),
        "sources": view.get("sources", []),
        "description": view.get("description", ""),
    }

    return definition, generated_sql, sql_error_count


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def generate_tech_spec(
    hla_id: str,
    ctx: ContextEnvelope,
    llm: LLMProvider,
) -> dict:
    """Generate technical specification from an approved (or draft) HLA document.

    For each view in the HLA:
    - Creates a technical_objects record with full column definitions.
    - For DSP objects, generates and validates SQL via the LLM.
    - Builds a dependency graph and topological deployment order.

    Returns:
        {
            "tech_spec_id": str,
            "object_count": int,
            "dsp_objects": int,
            "sac_objects": int,
            "sql_errors": int,
            "status": "draft",
        }
    """
    from spec2sphere.core.knowledge.knowledge_service import search_knowledge  # noqa: PLC0415

    # --- 1. Fetch and validate HLA document ---
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM hla_documents WHERE id = $1::uuid AND project_id = $2",
            hla_id,
            ctx.project_id,
        )
        if row is None:
            raise ValueError(f"HLA document {hla_id} not found in project {ctx.project_id}")
        hla_doc = _row_to_dict(row)
    finally:
        await conn.close()

    hla_content = hla_doc.get("content") or {}
    if isinstance(hla_content, str):
        hla_content = json.loads(hla_content)

    if hla_doc.get("status") not in ("approved", "draft"):
        raise ValueError(f"HLA {hla_id} has status '{hla_doc.get('status')}'; expected 'approved' or 'draft'")

    views: list[dict] = hla_content.get("views", [])
    if not views:
        logger.warning("HLA %s has no views — generating empty tech spec", hla_id)

    # --- 2. Knowledge base context for SQL generation ---
    domain_query = hla_doc.get("narrative") or "SAP DSP view architecture"
    try:
        kb_results = await search_knowledge(query=domain_query[:200], ctx=ctx, top_k=5, llm=llm)
        kb_context = "\n".join(f"- [{r['category']}] {r['title']}: {r['content'][:200]}" for r in kb_results)
    except Exception as exc:
        logger.warning("Knowledge search failed, continuing without context: %s", exc)
        kb_context = ""

    # --- 3. Build technical objects list ---
    tech_objects: list[dict] = []
    total_sql_errors = 0
    dsp_count = 0
    sac_count = 0

    for view in views:
        raw_layer = view.get("layer", "HARMONIZED")
        layer = _normalize_layer(raw_layer)
        raw_name = view.get("name", f"UNNAMED_{uuid.uuid4().hex[:8].upper()}")

        # Determine platform from placement annotation (set by placement engine)
        platform_placement = view.get("platform_placement", "dsp")
        platform = "sac" if platform_placement == "sac" else "dsp"

        # Ensure naming prefix
        technical_name = _apply_naming_prefix(raw_name, layer)

        # Map HLA type → technical object_type
        hla_type = view.get("type", "relational_dataset")
        object_type = _TYPE_MAP.get(hla_type, "relational_view")

        obj_record: dict = {
            "name": technical_name,
            "object_type": object_type,
            "platform": platform,
            "layer": layer,
            "sources": view.get("sources", []),
        }

        if platform == "dsp":
            dsp_count += 1
            definition, generated_sql, sql_errors = await _generate_dsp_object_detail(
                view={**view, "name": technical_name},
                hla_context=hla_content,
                llm=llm,
                kb_context=kb_context,
            )
            total_sql_errors += sql_errors
            obj_record["definition"] = definition
            obj_record["generated_artifact"] = generated_sql
        else:
            sac_count += 1
            # SAC objects: record metadata only, no SQL generation
            obj_record["definition"] = {
                "columns": view.get("columns", []),
                "description": view.get("description", ""),
                "sources": view.get("sources", []),
            }
            obj_record["generated_artifact"] = ""

        tech_objects.append(obj_record)

    # --- 4. Build dependency graph (use technical names) ---
    name_remap: dict[str, str] = {}
    for original, tech_obj in zip(views, tech_objects):
        name_remap[original.get("name", "")] = tech_obj["name"]

    # Remap source references to use technical names
    for tech_obj in tech_objects:
        tech_obj["sources"] = [name_remap.get(s, s) for s in tech_obj.get("sources", [])]
        if "definition" in tech_obj and isinstance(tech_obj["definition"], dict):
            tech_obj["definition"]["sources"] = tech_obj["sources"]

    dep_graph: dict[str, list[str]] = _build_dependency_graph(tech_objects)
    layer_by_name = {t["name"]: t["layer"] for t in tech_objects}

    # --- 5. Build deployment order ---
    all_names = [t["name"] for t in tech_objects]
    ordered_names = _topological_sort(all_names, dep_graph, layer_by_name)
    deployment_order = [{"order": i + 1, "name": n} for i, n in enumerate(ordered_names)]

    # --- 6. Persist tech_spec + technical_objects in a transaction ---
    tech_spec_id = uuid.uuid4()
    conn = await _get_conn()
    try:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO tech_specs
                    (id, project_id, hla_id, version, objects, dependency_graph,
                     deployment_order, status, created_at)
                VALUES ($1, $2, $3::uuid, 1, $4::jsonb, $5::jsonb, $6::jsonb, 'draft', NOW())
                """,
                tech_spec_id,
                ctx.project_id,
                hla_id,
                json.dumps([t["name"] for t in tech_objects]),
                json.dumps(dep_graph),
                json.dumps(deployment_order),
            )

            for tech_obj in tech_objects:
                obj_id = uuid.uuid4()
                # Infer implementation_route from platform
                if tech_obj["platform"] == "dsp":
                    impl_route = "api"
                    route_confidence = 0.85
                else:
                    impl_route = "click_guide"
                    route_confidence = 0.70

                await conn.execute(
                    """
                    INSERT INTO technical_objects
                        (id, tech_spec_id, project_id, name, object_type, platform, layer,
                         definition, generated_artifact, implementation_route,
                         route_confidence, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11, 'planned', NOW())
                    """,
                    obj_id,
                    tech_spec_id,
                    ctx.project_id,
                    tech_obj["name"],
                    tech_obj["object_type"],
                    tech_obj["platform"],
                    tech_obj["layer"],
                    json.dumps(tech_obj.get("definition", {})),
                    tech_obj.get("generated_artifact", ""),
                    impl_route,
                    route_confidence,
                )
    finally:
        await conn.close()

    logger.info(
        "Generated tech spec %s for HLA %s: %d objects (%d DSP, %d SAC), %d SQL errors",
        tech_spec_id,
        hla_id,
        len(tech_objects),
        dsp_count,
        sac_count,
        total_sql_errors,
    )

    return {
        "tech_spec_id": str(tech_spec_id),
        "object_count": len(tech_objects),
        "dsp_objects": dsp_count,
        "sac_objects": sac_count,
        "sql_errors": total_sql_errors,
        "status": "draft",
    }


async def get_tech_spec(tech_spec_id: str, project_id=None) -> Optional[dict]:
    """Fetch a tech_spec record by ID, optionally scoped to a project.

    JSONB columns (objects, dependency_graph, deployment_order) are parsed
    into Python structures before returning.
    """
    conn = await _get_conn()
    try:
        if project_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM tech_specs WHERE id = $1::uuid AND project_id = $2",
                tech_spec_id,
                project_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM tech_specs WHERE id = $1::uuid",
                tech_spec_id,
            )
        if row is None:
            return None
        result = _row_to_dict(row)
        # Parse JSONB columns that asyncpg may return as strings
        for col in ("objects", "dependency_graph", "deployment_order"):
            val = result.get(col)
            if isinstance(val, str):
                try:
                    result[col] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        return result
    finally:
        await conn.close()


async def list_tech_specs(
    ctx: ContextEnvelope,
    hla_id: Optional[str] = None,
) -> list[dict]:
    """List tech specs for the active project, optionally filtered by hla_id."""
    if ctx.project_id is None:
        return []

    conditions = ["project_id = $1"]
    params: list = [ctx.project_id]
    idx = 2

    if hla_id is not None:
        conditions.append(f"hla_id = ${idx}::uuid")
        params.append(hla_id)
        idx += 1

    sql = (
        f"SELECT id, project_id, hla_id, version, status, approved_by, approved_at, created_at "
        f"FROM tech_specs WHERE {' AND '.join(conditions)} ORDER BY created_at DESC"
    )

    conn = await _get_conn()
    try:
        rows = await conn.fetch(sql, *params)
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def get_technical_objects(tech_spec_id: str) -> list[dict]:
    """Fetch all technical_objects for a tech_spec, ordered by deployment position.

    Objects are ordered by the deployment_order stored in the parent tech_spec.
    Falls back to created_at ordering when no deployment_order is available.
    """
    conn = await _get_conn()
    try:
        # Fetch deployment order from the parent spec
        spec_row = await conn.fetchrow(
            "SELECT deployment_order FROM tech_specs WHERE id = $1::uuid",
            tech_spec_id,
        )
        deployment_order: list[dict] = []
        if spec_row:
            raw = spec_row["deployment_order"]
            if isinstance(raw, str):
                try:
                    deployment_order = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    deployment_order = []
            elif isinstance(raw, list):
                deployment_order = raw

        order_map: dict[str, int] = {
            entry["name"]: entry["order"] for entry in deployment_order if isinstance(entry, dict)
        }

        rows = await conn.fetch(
            "SELECT * FROM technical_objects WHERE tech_spec_id = $1::uuid ORDER BY created_at",
            tech_spec_id,
        )
        objects = [_row_to_dict(r) for r in rows]

        # Parse JSONB definition column
        for obj in objects:
            val = obj.get("definition")
            if isinstance(val, str):
                try:
                    obj["definition"] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            # Inject deployment position
            obj["deployment_position"] = order_map.get(obj.get("name", ""), 999)

        # Sort by deployment position
        objects.sort(key=lambda o: (o.get("deployment_position", 999), o.get("name", "")))
        return objects
    finally:
        await conn.close()


async def get_technical_object(obj_id: str) -> Optional[dict]:
    """Fetch a single technical_object by ID with full definition."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM technical_objects WHERE id = $1::uuid",
            obj_id,
        )
        if row is None:
            return None
        result = _row_to_dict(row)
        val = result.get("definition")
        if isinstance(val, str):
            try:
                result["definition"] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
        return result
    finally:
        await conn.close()
