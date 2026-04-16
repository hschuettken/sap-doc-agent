"""LLM-powered semantic extraction from BRS requirement documents.

Extracts entities, KPIs, grain, time semantics, source systems, security
implications, non-functional requirements, ambiguities, and open questions.
Stores results back into the requirements table.
"""

from __future__ import annotations

import json
import logging

from spec2sphere.db import _get_conn
from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schema for LLM extraction
# ---------------------------------------------------------------------------

_EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "business_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of business domains referenced (e.g. Sales, Finance, Logistics)",
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["dimension", "fact", "master"]},
                    "description": {"type": "string"},
                    "attributes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "type"],
            },
        },
        "facts_and_measures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["measure", "calculated_measure", "restricted_measure"]},
                    "aggregation": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "type"],
            },
        },
        "kpis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "formula": {"type": "string"},
                    "description": {"type": "string"},
                    "target_value": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "grain": {
            "type": "object",
            "properties": {
                "dimensions": {"type": "array", "items": {"type": "string"}},
                "time_granularity": {"type": "string"},
                "version_semantics": {"type": "string"},
            },
        },
        "time_semantics": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["snapshot", "event", "accumulating"]},
                "fiscal_variants": {"type": "array", "items": {"type": "string"}},
                "comparison_periods": {"type": "array", "items": {"type": "string"}},
            },
        },
        "source_systems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "tables": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
            },
        },
        "security_implications": {
            "type": "object",
            "properties": {
                "row_level_security": {"type": "boolean"},
                "column_level_security": {"type": "boolean"},
                "roles": {"type": "array", "items": {"type": "string"}},
            },
        },
        "non_functional": {
            "type": "object",
            "properties": {
                "expected_volume_rows": {"type": "integer"},
                "expected_query_latency_seconds": {"type": "number"},
                "refresh_frequency": {"type": "string"},
                "retention_period": {"type": "string"},
            },
        },
        "ambiguities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "element": {"type": "string"},
                    "issue": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "suggested_resolution": {"type": "string"},
                },
                "required": ["element", "issue", "severity"],
            },
        },
        "open_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "related_element": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["question", "severity"],
            },
        },
        "llm_confidence_notes": {
            "type": "object",
            "description": "LLM self-assessment of extraction confidence per category",
            "additionalProperties": {"type": "string"},
        },
    },
    "required": ["business_domains", "entities", "facts_and_measures", "kpis", "grain"],
}


# ---------------------------------------------------------------------------
# Confidence computation
# ---------------------------------------------------------------------------


def _compute_confidence(extracted: dict) -> dict:
    """Derive a confidence rating per category from the LLM output."""
    confidence: dict[str, dict] = {}

    llm_notes: dict = extracted.get("llm_confidence_notes", {})

    def _rate(key: str, items) -> dict:
        note = llm_notes.get(key, "")
        if not items:
            level = "low"
            rationale = "No data extracted"
        elif note and "low" in note.lower():
            level = "low"
            rationale = note
        elif note and "medium" in note.lower():
            level = "medium"
            rationale = note
        else:
            level = "high" if items else "low"
            rationale = note or f"{len(items) if hasattr(items, '__len__') else 'n/a'} item(s) extracted"
        return {"level": level, "rationale": rationale}

    confidence["entities"] = _rate("entities", extracted.get("entities", []))
    confidence["facts_and_measures"] = _rate("facts_and_measures", extracted.get("facts_and_measures", []))
    confidence["kpis"] = _rate("kpis", extracted.get("kpis", []))
    confidence["grain"] = _rate("grain", extracted.get("grain", {}))
    confidence["source_systems"] = _rate("source_systems", extracted.get("source_systems", []))
    confidence["security"] = _rate("security_implications", extracted.get("security_implications", {}))

    return confidence


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def parse_requirement(
    requirement_id: str,
    ctx: ContextEnvelope,
    llm: LLMProvider,
) -> dict:
    """Parse a requirement document using LLM to extract structured data.

    Updates the requirement record with parsed_entities, parsed_kpis,
    parsed_grain, confidence, and open_questions.

    Returns the updated requirement dict.
    """
    from spec2sphere.core.knowledge.knowledge_service import search_knowledge
    from spec2sphere.pipeline.intake import _row_to_dict

    # --- 1. Fetch the requirement ---
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM requirements WHERE id = $1::uuid AND project_id = $2",
            requirement_id,
            ctx.project_id,
        )
        if row is None:
            raise ValueError(f"Requirement {requirement_id} not found in project {ctx.project_id}")
        req = _row_to_dict(row)
    finally:
        await conn.close()

    # --- 2. Extract raw text from source_documents ---
    source_docs = req.get("source_documents") or []
    if isinstance(source_docs, str):
        source_docs = json.loads(source_docs)
    raw_text = "\n\n".join(doc.get("text", "") for doc in source_docs if doc.get("text"))
    if not raw_text:
        raise ValueError(f"Requirement {requirement_id} has no extractable text")

    # --- 3. Enrich with relevant knowledge base context ---
    kb_results = await search_knowledge(
        query=raw_text[:500],
        ctx=ctx,
        top_k=5,
        llm=llm,
    )
    knowledge_context = ""
    if kb_results:
        snippets = [f"- {r['title']}: {r['content'][:300]}" for r in kb_results]
        knowledge_context = "\n".join(snippets)

    # --- 4. Build extraction prompt ---
    system_prompt = (
        "You are a senior SAP data architect specialising in BW-to-DSP migrations. "
        "Extract structured information from Business Requirements Specification (BRS) documents. "
        "Be precise — only extract what is explicitly stated or strongly implied. "
        "For ambiguities and open questions, list everything that a data engineer would need clarified "
        "before building the solution. Populate llm_confidence_notes with per-category confidence "
        "as one of: 'high', 'medium', 'low', with a brief rationale."
    )

    prompt_parts = [
        "Extract all structured information from the following BRS document.",
        "",
        "=== BRS DOCUMENT ===",
        raw_text[:8000],  # guard against very long docs
        "",
    ]
    if knowledge_context:
        prompt_parts += [
            "=== RELEVANT EXISTING STANDARDS / LANDSCAPE CONTEXT ===",
            knowledge_context,
            "",
        ]
    prompt_parts += [
        "Extract entities, KPIs, grain, time semantics, source systems, security requirements, "
        "non-functional requirements, ambiguities, and open questions as specified in the schema.",
    ]
    prompt = "\n".join(prompt_parts)

    # --- 5. LLM extraction with retry ---
    logger.info("Running LLM extraction for requirement %s", requirement_id)
    extracted = await generate_json_with_retry(
        provider=llm,
        prompt=prompt,
        schema=_EXTRACTION_SCHEMA,
        system=system_prompt,
        max_retries=3,
        tier="large",
    )

    if extracted is None:
        logger.warning("LLM extraction returned None for requirement %s", requirement_id)
        extracted = {}

    # --- 6. Compute confidence ---
    confidence = _compute_confidence(extracted)

    # --- 7. Determine primary business_domain ---
    business_domains = extracted.get("business_domains", [])
    business_domain = business_domains[0] if business_domains else None

    # --- 8. Persist parsed data ---
    parsed_entities: dict = {
        "entities": extracted.get("entities", []),
        "facts_and_measures": extracted.get("facts_and_measures", []),
        "time_semantics": extracted.get("time_semantics", {}),
        "source_systems": extracted.get("source_systems", []),
        "security_implications": extracted.get("security_implications", {}),
        "non_functional": extracted.get("non_functional", {}),
        "ambiguities": extracted.get("ambiguities", []),
        "business_domains": business_domains,
    }
    parsed_kpis: list = extracted.get("kpis", [])
    parsed_grain: dict = extracted.get("grain", {})
    open_questions: list = extracted.get("open_questions", [])

    update_sets = [
        "parsed_entities = $1::jsonb",
        "parsed_kpis = $2::jsonb",
        "parsed_grain = $3::jsonb",
        "confidence = $4::jsonb",
        "open_questions = $5::jsonb",
    ]
    params: list = [
        json.dumps(parsed_entities),
        json.dumps(parsed_kpis),
        json.dumps(parsed_grain),
        json.dumps(confidence),
        json.dumps(open_questions),
    ]
    idx = 6

    if business_domain:
        update_sets.append(f"business_domain = ${idx}")
        params.append(business_domain)
        idx += 1

    params.append(requirement_id)
    sql = f"UPDATE requirements SET {', '.join(update_sets)} WHERE id = ${idx}::uuid RETURNING *"

    conn = await _get_conn()
    try:
        updated_row = await conn.fetchrow(sql, *params)
        if updated_row is None:
            raise ValueError(f"Requirement {requirement_id} disappeared during update")
        result = _row_to_dict(updated_row)
    finally:
        await conn.close()

    logger.info(
        "Parsed requirement %s: %d entities, %d KPIs, %d open questions",
        requirement_id,
        len(parsed_entities.get("entities", [])),
        len(parsed_kpis),
        len(open_questions),
    )
    return result


async def detect_ambiguities(requirement_id: str, llm: LLMProvider, project_id=None) -> list[dict]:
    """Re-run ambiguity detection on an already-parsed requirement.

    Returns the ambiguities list (also persisted to the requirement's parsed_entities).
    If project_id is provided, the requirement must belong to that project.
    """
    from spec2sphere.pipeline.intake import _row_to_dict

    conn = await _get_conn()
    try:
        if project_id is not None:
            row = await conn.fetchrow(
                "SELECT id, source_documents, parsed_entities FROM requirements WHERE id = $1::uuid AND project_id = $2",
                requirement_id,
                project_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT id, source_documents, parsed_entities FROM requirements WHERE id = $1::uuid",
                requirement_id,
            )
        if row is None:
            raise ValueError(f"Requirement {requirement_id} not found")
        req = _row_to_dict(row)
    finally:
        await conn.close()

    source_docs = req.get("source_documents") or []
    if isinstance(source_docs, str):
        source_docs = json.loads(source_docs)
    raw_text = "\n\n".join(doc.get("text", "") for doc in source_docs if doc.get("text"))

    parsed_entities = req.get("parsed_entities") or {}
    if isinstance(parsed_entities, str):
        parsed_entities = json.loads(parsed_entities)

    ambiguity_schema = {
        "type": "object",
        "properties": {
            "ambiguities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "element": {"type": "string"},
                        "issue": {"type": "string"},
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        "suggested_resolution": {"type": "string"},
                    },
                    "required": ["element", "issue", "severity"],
                },
            }
        },
        "required": ["ambiguities"],
    }

    already_extracted = json.dumps(
        {
            "entities": parsed_entities.get("entities", []),
            "facts_and_measures": parsed_entities.get("facts_and_measures", []),
        },
        indent=2,
    )

    prompt = (
        f"Given this BRS document:\n\n{raw_text[:6000]}\n\n"
        f"And these already-extracted entities and measures:\n{already_extracted}\n\n"
        "Identify ALL ambiguities: missing definitions, conflicting requirements, "
        "unclear grain, unstated business rules, or anything that needs human clarification "
        "before implementation can begin. Be thorough and critical."
    )

    result = await generate_json_with_retry(
        provider=llm,
        prompt=prompt,
        schema=ambiguity_schema,
        system="You are a critical SAP data architect reviewing a BRS for completeness.",
        max_retries=2,
        tier="large",
    )

    ambiguities: list[dict] = (result or {}).get("ambiguities", [])

    # Persist updated ambiguities back into parsed_entities
    parsed_entities["ambiguities"] = ambiguities
    conn = await _get_conn()
    try:
        await conn.execute(
            "UPDATE requirements SET parsed_entities = $1::jsonb WHERE id = $2::uuid",
            json.dumps(parsed_entities),
            requirement_id,
        )
    finally:
        await conn.close()

    return ambiguities
