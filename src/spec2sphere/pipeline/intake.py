"""Requirement intake engine.

Accepts BRS documents (PDF, Word, Markdown, plain text, YAML), extracts text,
stores the raw document in the requirements table, and chunks the content into
knowledge_items for semantic retrieval.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from spec2sphere.db import _get_conn
from spec2sphere.llm.base import LLMProvider
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to plain dict, normalising special types."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += chunk_size - overlap
    return chunks


def _derive_title(text: str, filename: str) -> str:
    """Extract a title from the first non-empty line, or fall back to filename stem."""
    for line in text.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:200]
    stem = filename.rsplit(".", 1)[0]
    return stem[:200]


async def ingest_requirement(
    file_data: bytes,
    filename: str,
    content_type: str,
    ctx: ContextEnvelope,
    llm: Optional[LLMProvider] = None,
) -> dict:
    """Accept BRS in PDF/Word/Markdown/plain text/YAML. Parse, store in requirements table.

    Also chunks + embeds the text into knowledge_items for semantic retrieval.

    Returns:
        {"requirement_id": str, "title": str, "status": "draft"}
    """
    from spec2sphere.standards.extractor import UnsupportedFileType, extract_text

    # --- 1. Extract text ---
    ct_lower = content_type.lower()
    # YAML special-case: detect by extension when content_type is generic
    if filename.endswith((".yaml", ".yml")) and ct_lower in (
        "application/octet-stream",
        "text/plain",
        "",
    ):
        try:
            import yaml

            parsed = yaml.safe_load(file_data.decode("utf-8", errors="replace"))
            raw_text = json.dumps(parsed, indent=2) if not isinstance(parsed, str) else parsed
        except Exception as exc:
            logger.warning("YAML parse failed for %s, treating as plain text: %s", filename, exc)
            raw_text = file_data.decode("utf-8", errors="replace")
    else:
        try:
            raw_text = extract_text(file_data, content_type)
        except UnsupportedFileType:
            # Last-resort: try UTF-8 decode
            raw_text = file_data.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.error("Text extraction failed for %s: %s", filename, exc)
            raise

    title = _derive_title(raw_text, filename)

    # --- 2. Build source_documents JSONB entry ---
    source_doc_entry = {
        "filename": filename,
        "content_type": content_type,
        "text": raw_text,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    source_documents = [source_doc_entry]

    # --- 3. Insert into requirements table ---
    req_id = uuid.uuid4()
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO requirements
                (id, project_id, title, source_documents, status, created_at)
            VALUES ($1, $2, $3, $4::jsonb, 'draft', NOW())
            """,
            req_id,
            ctx.project_id,
            title,
            json.dumps(source_documents),
        )
    finally:
        await conn.close()

    logger.info("Ingested requirement %s (project=%s, file=%s)", req_id, ctx.project_id, filename)

    # --- 4. Chunk + embed into knowledge_items ---
    chunks = _chunk_text(raw_text, chunk_size=1000, overlap=200)
    if chunks:
        from spec2sphere.core.knowledge.knowledge_service import create_knowledge_item

        for i, chunk in enumerate(chunks):
            chunk_title = f"{filename} (part {i + 1})" if len(chunks) > 1 else filename
            try:
                await create_knowledge_item(
                    ctx=ctx,
                    title=chunk_title,
                    content=chunk,
                    category="requirement",
                    source=filename,
                    confidence=1.0,
                    llm=llm,  # type: ignore[arg-type]
                )
            except Exception as exc:
                logger.warning("Failed to store knowledge chunk %d for %s: %s", i + 1, filename, exc)

    return {"requirement_id": str(req_id), "title": title, "status": "draft"}


async def get_requirement(requirement_id: str, project_id=None) -> Optional[dict]:
    """Fetch a single requirement by ID, optionally scoped to a project."""
    conn = await _get_conn()
    try:
        if project_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM requirements WHERE id = $1::uuid AND project_id = $2",
                requirement_id,
                project_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM requirements WHERE id = $1::uuid",
                requirement_id,
            )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def list_requirements(
    ctx: ContextEnvelope,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List requirements for the active project."""
    if ctx.project_id is None:
        return []

    conditions: list[str] = ["project_id = $1"]
    params: list = [ctx.project_id]
    idx = 2

    if status is not None:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    params.append(limit)
    sql = f"SELECT * FROM requirements WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ${idx}"

    conn = await _get_conn()
    try:
        rows = await conn.fetch(sql, *params)
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def update_requirement(requirement_id: str, **fields) -> dict:
    """Update requirement fields (for human correction of parsed data).

    Allowed fields: title, business_domain, description, parsed_entities,
    parsed_kpis, parsed_grain, confidence, open_questions, status.

    JSONB fields are accepted as dicts and serialised automatically.
    """
    jsonb_fields = {
        "parsed_entities",
        "parsed_kpis",
        "parsed_grain",
        "confidence",
        "open_questions",
        "source_documents",
    }
    allowed = {
        "title",
        "business_domain",
        "description",
        "status",
        *jsonb_fields,
    }

    sets: list[str] = []
    params: list = []
    idx = 1

    for key, value in fields.items():
        if key not in allowed:
            logger.warning("update_requirement: ignoring unknown field %r", key)
            continue
        if key in jsonb_fields:
            sets.append(f"{key} = ${idx}::jsonb")
            params.append(json.dumps(value))
        else:
            sets.append(f"{key} = ${idx}")
            params.append(value)
        idx += 1

    if not sets:
        result = await get_requirement(requirement_id)
        if result is None:
            raise ValueError(f"Requirement {requirement_id} not found")
        return result

    params.append(requirement_id)
    sql = f"UPDATE requirements SET {', '.join(sets)} WHERE id = ${idx}::uuid RETURNING *"

    conn = await _get_conn()
    try:
        row = await conn.fetchrow(sql, *params)
        if row is None:
            raise ValueError(f"Requirement {requirement_id} not found")
        return _row_to_dict(row)
    finally:
        await conn.close()


async def ingest_from_bw_migration(
    intent_cards: list[dict],
    classified_chains: list[dict],
    ctx: ContextEnvelope,
) -> dict:
    """Create a requirement from BW migration module output.

    Takes IntentCard dicts (from interpreter.py) and ClassifiedChain dicts
    (from classifier.py) and produces the same structured requirement output
    as the BRS parser, so the rest of the pipeline is identical.

    Returns: {"requirement_id": str, "title": str, "status": "draft"}
    """
    if not intent_cards:
        raise ValueError("At least one IntentCard is required")

    # Derive title from the first intent card's business purpose
    first = intent_cards[0]
    title = f"BW Migration: {first.get('business_purpose', 'Unknown domain')}"
    business_domain = first.get("data_domain", "")

    # Aggregate entities, measures, KPIs, grain, sources across all cards
    all_entities = []
    all_measures = []
    all_sources = set()
    grains = []
    for card in intent_cards:
        for entity in card.get("key_entities", []):
            all_entities.append({"name": entity, "type": "dimension", "description": "", "source": "bw_migration"})
        for measure in card.get("key_measures", []):
            all_measures.append({"name": measure, "type": "measure", "description": "", "source": "bw_migration"})
        all_sources.update(card.get("source_systems", []))
        if card.get("grain"):
            grains.append(card["grain"])

    # Classify chains as debt/workaround/business_rule/obsolete/unclear
    migration_objects = []
    for chain in classified_chains:
        classification = chain.get("classification", "clarify")
        strategy = {
            "migrate": "replicate",
            "simplify": "clean",
            "replace": "redesign",
            "drop": "obsolete",
            "clarify": "unclear",
        }.get(classification, "unclear")
        migration_objects.append(
            {
                "chain_id": chain.get("chain_id", ""),
                "classification": classification,
                "rationale": chain.get("rationale", ""),
                "strategy": strategy,
                "effort": chain.get("effort_category", ""),
                "confidence": chain.get("confidence", 0),
            }
        )

    # Build source_documents equivalent
    bw_text = f"BW Migration Analysis\n\nDomain: {business_domain}\n\n"
    for card in intent_cards:
        bw_text += f"## {card.get('business_purpose', '')}\n"
        bw_text += f"Grain: {card.get('grain', '')}\n"
        bw_text += f"Entities: {', '.join(card.get('key_entities', []))}\n"
        bw_text += f"Measures: {', '.join(card.get('key_measures', []))}\n\n"

    source_doc = {
        "filename": "bw_migration_analysis",
        "content_type": "application/x-bw-migration",
        "text": bw_text,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "intent_cards_count": len(intent_cards),
        "classified_chains_count": len(classified_chains),
    }

    parsed_entities = {
        "entities": all_entities,
        "facts_and_measures": all_measures,
        "source_systems": [{"name": s, "type": "SAP BW"} for s in sorted(all_sources)],
        "migration_objects": migration_objects,
    }

    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO requirements
                (project_id, title, business_domain, description, source_documents,
                 parsed_entities, parsed_grain, status)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, 'draft')
            RETURNING id
            """,
            ctx.project_id,
            title,
            business_domain,
            f"Auto-generated from BW migration analysis of {len(intent_cards)} chain(s)",
            json.dumps([source_doc]),
            json.dumps(parsed_entities),
            json.dumps({"dimensions": grains, "source": "bw_migration"}),
        )
        req_id = str(row["id"])
    finally:
        await conn.close()

    logger.info(
        "Created BW migration requirement %s (%d cards, %d chains)", req_id, len(intent_cards), len(classified_chains)
    )
    return {"requirement_id": req_id, "title": title, "status": "draft"}
