"""High-Level Architecture (HLA) generator.

Generates layered DSP architecture documents and architecture decisions
from approved/draft requirements. Calls the placement engine for each artifact.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from spec2sphere.db import _get_conn
from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schema for LLM HLA generation
# ---------------------------------------------------------------------------

_HLA_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "domain_decomposition": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "rationale": {"type": "string"},
                    "primary_artifacts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["domain", "rationale"],
            },
        },
        "layered_architecture": {
            "type": "object",
            "properties": {
                "RAW": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "tables": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "HARMONIZED": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "views": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "MART": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "views": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "CONSUMPTION": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "views": {"type": "array", "items": {"type": "string"}},
                        "analytic_models": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
        "fact_dimension_strategy": {
            "type": "object",
            "properties": {
                "schema_type": {"type": "string", "enum": ["star", "snowflake", "flat"]},
                "fact_tables": {"type": "array", "items": {"type": "string"}},
                "dimension_tables": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
        },
        "replication_strategy": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_table": {"type": "string"},
                    "source_system": {"type": "string"},
                    "target_table": {"type": "string"},
                    "delta_enabled": {"type": "boolean"},
                    "schedule": {"type": "string"},
                },
                "required": ["source_table", "target_table"],
            },
        },
        "views": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "layer": {"type": "string", "enum": ["RAW", "HARMONIZED", "MART", "CONSUMPTION"]},
                    "type": {
                        "type": "string",
                        "enum": ["relational_dataset", "fact", "dimension", "text", "hierarchy", "analytic_model"],
                    },
                    "description": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "data_type": {"type": "string"},
                                "description": {"type": "string"},
                                "is_key": {"type": "boolean"},
                                "is_measure": {"type": "boolean"},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["name", "layer", "type"],
            },
        },
        "key_decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "choice": {"type": "string"},
                    "alternatives": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                    "platform_placement": {"type": "string", "enum": ["dsp", "sac", "both"]},
                },
                "required": ["topic", "choice", "rationale", "platform_placement"],
            },
        },
        "reuse_opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "existing_object": {"type": "string"},
                    "reuse_type": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["existing_object", "reuse_type"],
            },
        },
        "narrative": {"type": "string"},
    },
    "required": ["layered_architecture", "views", "key_decisions"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d


async def _fetch_requirement(conn, requirement_id: str, project_id) -> dict:
    row = await conn.fetchrow(
        "SELECT * FROM requirements WHERE id = $1::uuid AND project_id = $2",
        requirement_id,
        project_id,
    )
    if row is None:
        raise ValueError(f"Requirement {requirement_id} not found in project {project_id}")
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def generate_hla(
    requirement_id: str,
    ctx: ContextEnvelope,
    llm: LLMProvider,
) -> dict:
    """Generate HLA from an approved/draft requirement.

    Creates one hla_documents record and one architecture_decisions record
    per key decision returned by the LLM.

    Returns:
        {"hla_id": str, "decisions_count": int, "status": "draft"}
    """
    from spec2sphere.core.knowledge.knowledge_service import search_knowledge
    from spec2sphere.pipeline.placement import place_architecture

    # --- 1. Fetch requirement ---
    conn = await _get_conn()
    try:
        req = await _fetch_requirement(conn, requirement_id, ctx.project_id)
    finally:
        await conn.close()

    parsed_entities = req.get("parsed_entities") or {}
    if isinstance(parsed_entities, str):
        parsed_entities = json.loads(parsed_entities)
    parsed_kpis = req.get("parsed_kpis") or []
    if isinstance(parsed_kpis, str):
        parsed_kpis = json.loads(parsed_kpis)
    parsed_grain = req.get("parsed_grain") or {}
    if isinstance(parsed_grain, str):
        parsed_grain = json.loads(parsed_grain)

    # --- 2. Knowledge base search for existing landscape + standards ---
    domain_query = req.get("business_domain") or req.get("title") or "SAP data architecture"
    kb_results = await search_knowledge(query=domain_query, ctx=ctx, top_k=8, llm=llm)
    kb_context = "\n".join(f"- [{r['category']}] {r['title']}: {r['content'][:300]}" for r in kb_results)

    # --- 3. Build HLA generation prompt ---
    system_prompt = (
        "You are a senior SAP Data Sphere architect. Generate a complete High-Level Architecture "
        "for a DSP migration based on the extracted requirement data. "
        "Apply best-practice layering (RAW → HARMONIZED → MART → CONSUMPTION), "
        "star-schema design, and SAP-standard naming conventions. "
        "Be specific — name views, tables, and analytic models using technical SAP naming patterns."
    )

    req_summary = json.dumps(
        {
            "title": req.get("title"),
            "business_domain": req.get("business_domain"),
            "entities": parsed_entities.get("entities", [])[:10],
            "facts_and_measures": parsed_entities.get("facts_and_measures", [])[:10],
            "kpis": parsed_kpis[:5],
            "grain": parsed_grain,
            "source_systems": parsed_entities.get("source_systems", [])[:5],
            "time_semantics": parsed_entities.get("time_semantics", {}),
            "security_implications": parsed_entities.get("security_implications", {}),
            "non_functional": parsed_entities.get("non_functional", {}),
        },
        indent=2,
    )

    prompt = f"Generate a High-Level Architecture for the following requirement:\n\n{req_summary}\n\n"
    if kb_context:
        prompt += f"Existing landscape context (reuse where possible):\n{kb_context}\n\n"
    prompt += (
        "Design the full layered DSP architecture including: domain decomposition, "
        "layer-by-layer view/table design, star schema strategy, replication flows "
        "from source systems, key architectural decisions with platform placement (DSP/SAC/Both), "
        "and reuse opportunities from the existing landscape. "
        "Provide a concise narrative summary."
    )

    # --- 4. LLM generation ---
    logger.info("Running HLA generation for requirement %s", requirement_id)
    hla_content = await generate_json_with_retry(
        provider=llm,
        prompt=prompt,
        schema=_HLA_SCHEMA,
        system=system_prompt,
        max_retries=3,
    )

    if hla_content is None:
        logger.warning("HLA LLM generation returned None for requirement %s", requirement_id)
        hla_content = {"views": [], "key_decisions": [], "layered_architecture": {}}

    narrative: str = hla_content.get("narrative") or ""

    # --- 5. Run placement engine over artifacts ---
    try:
        placement_decisions = await place_architecture(hla_content, llm=llm)
        # Annotate views with placement decision
        placement_map = {d.artifact_name: d.platform.value for d in placement_decisions}
        for view in hla_content.get("views", []):
            view["platform_placement"] = placement_map.get(view["name"], "dsp")
    except Exception as exc:
        logger.warning("Placement engine failed, continuing without placement: %s", exc)

    # --- 6. Insert hla_documents record ---
    hla_id = uuid.uuid4()
    conn = await _get_conn()
    try:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO hla_documents
                    (id, project_id, requirement_id, version, content, narrative, status, created_at)
                VALUES ($1, $2, $3::uuid, 1, $4::jsonb, $5, 'draft', NOW())
                """,
                hla_id,
                ctx.project_id,
                requirement_id,
                json.dumps(hla_content),
                narrative,
            )

            # --- 7. Insert architecture_decisions records ---
            key_decisions = hla_content.get("key_decisions", [])
            for decision in key_decisions:
                await conn.execute(
                    """
                    INSERT INTO architecture_decisions
                        (id, project_id, requirement_id, topic, choice, alternatives,
                         rationale, platform_placement, status, created_at)
                    VALUES (gen_random_uuid(), $1, $2::uuid, $3, $4, $5::jsonb, $6, $7, 'draft', NOW())
                    """,
                    ctx.project_id,
                    requirement_id,
                    decision.get("topic", ""),
                    decision.get("choice", ""),
                    json.dumps(decision.get("alternatives", [])),
                    decision.get("rationale", ""),
                    decision.get("platform_placement", "dsp"),
                )
    finally:
        await conn.close()

    decisions_count = len(hla_content.get("key_decisions", []))
    logger.info(
        "Generated HLA %s for requirement %s: %d views, %d decisions",
        hla_id,
        requirement_id,
        len(hla_content.get("views", [])),
        decisions_count,
    )

    return {"hla_id": str(hla_id), "decisions_count": decisions_count, "status": "draft"}


async def get_hla(hla_id: str) -> Optional[dict]:
    """Fetch HLA document by ID."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM hla_documents WHERE id = $1::uuid",
            hla_id,
        )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def list_hla_documents(
    ctx: ContextEnvelope,
    requirement_id: Optional[str] = None,
) -> list[dict]:
    """List HLA documents for the active project."""
    if ctx.project_id is None:
        return []

    conditions = ["project_id = $1"]
    params: list = [ctx.project_id]
    idx = 2

    if requirement_id is not None:
        conditions.append(f"requirement_id = ${idx}::uuid")
        params.append(requirement_id)
        idx += 1

    sql = (
        f"SELECT id, project_id, requirement_id, version, narrative, status, created_at "
        f"FROM hla_documents WHERE {' AND '.join(conditions)} ORDER BY created_at DESC"
    )

    conn = await _get_conn()
    try:
        rows = await conn.fetch(sql, *params)
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def compare_hla_versions(hla_id_a: str, hla_id_b: str) -> dict:
    """Compare two HLA versions and return a structured diff.

    Returns a dict with added/removed/changed keys for views and key_decisions.
    """
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT id, version, content FROM hla_documents WHERE id = ANY($1::uuid[])",
            [hla_id_a, hla_id_b],
        )
    finally:
        await conn.close()

    by_id: dict[str, dict] = {}
    for row in rows:
        by_id[str(row["id"])] = _row_to_dict(row)

    if hla_id_a not in by_id:
        raise ValueError(f"HLA {hla_id_a} not found")
    if hla_id_b not in by_id:
        raise ValueError(f"HLA {hla_id_b} not found")

    def _parse_content(doc: dict) -> dict:
        c = doc.get("content") or {}
        if isinstance(c, str):
            c = json.loads(c)
        return c

    content_a = _parse_content(by_id[hla_id_a])
    content_b = _parse_content(by_id[hla_id_b])

    def _diff_list(a_items: list, b_items: list, key: str) -> dict:
        a_map = {item.get(key, ""): item for item in a_items}
        b_map = {item.get(key, ""): item for item in b_items}
        added = [b_map[k] for k in b_map if k not in a_map]
        removed = [a_map[k] for k in a_map if k not in b_map]
        changed = []
        for k in a_map:
            if k in b_map and a_map[k] != b_map[k]:
                changed.append({"name": k, "before": a_map[k], "after": b_map[k]})
        return {"added": added, "removed": removed, "changed": changed}

    return {
        "version_a": by_id[hla_id_a].get("version"),
        "version_b": by_id[hla_id_b].get("version"),
        "views": _diff_list(
            content_a.get("views", []),
            content_b.get("views", []),
            "name",
        ),
        "key_decisions": _diff_list(
            content_a.get("key_decisions", []),
            content_b.get("key_decisions", []),
            "topic",
        ),
    }
