"""Enhanced Standards Intake Pipeline.

Ingests a documentation standard (PDF / Word / Markdown) and stores each
extracted rule as a knowledge_item in the database.

Pipeline steps
--------------
1. Extract text from the file using spec2sphere.standards.extractor.
2. Use the LLM to extract structured rules with an enhanced schema that adds
   per-rule category, severity, and examples.
3. Persist each rule as a knowledge_item row (tenant + customer + project
   scoped via ContextEnvelope).
4. If the LLM provider supports embeddings, generate and store a vector for
   each rule so it can be semantically searched later.
5. Return a summary dict.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from uuid import UUID

import asyncpg

from spec2sphere.llm.base import LLMProvider
from spec2sphere.standards.extractor import extract_text
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


async def _get_conn():
    url = (
        os.environ.get("DATABASE_URL", "")
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )
    return await asyncpg.connect(url)


# ---------------------------------------------------------------------------
# Enhanced extraction schema
# ---------------------------------------------------------------------------

_ENHANCED_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["naming", "layering", "anti_pattern", "template", "quality", "governance"],
                    },
                    "rule_text": {"type": "string"},
                    "severity": {"type": "string", "enum": ["must", "should", "may"]},
                    "examples": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["category", "rule_text", "severity"],
            },
        }
    },
    "required": ["rules"],
}

_SYSTEM_PROMPT = """You are an SAP BI documentation standards analyst.
Extract every actionable rule from the provided text.
Classify each rule by category (naming | layering | anti_pattern | template | quality | governance),
assign a severity (must | should | may), and include short examples where present.
Return only valid JSON matching the provided schema."""


# ---------------------------------------------------------------------------
# LLM extraction helpers
# ---------------------------------------------------------------------------


async def _extract_rules_enhanced(text: str, llm: LLMProvider) -> list[dict]:
    """Run the enhanced extraction prompt.

    Falls back gracefully: if the LLM returns None or an unparsable response
    the function returns an empty list (never raises).
    """
    if not llm.is_available():
        logger.warning("LLM not available — skipping rule extraction")
        return []

    MAX_CHARS = 12_000
    all_rules: list[dict] = []

    chunks = (
        [text] if len(text) <= MAX_CHARS else [text[i : i + MAX_CHARS] for i in range(0, len(text), MAX_CHARS - 500)]
    )

    for i, chunk in enumerate(chunks):
        prompt = (
            f"Extract all documentation rules from the following standard text "
            f"(chunk {i + 1}/{len(chunks)}):\n\n{chunk}"
        )
        result = await llm.generate_json(prompt, _ENHANCED_RULE_SCHEMA, system=_SYSTEM_PROMPT, tier="medium")
        if result and isinstance(result.get("rules"), list):
            all_rules.extend(result["rules"])

    return all_rules


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _store_knowledge_item(
    conn,
    tenant_id: UUID,
    customer_id: Optional[UUID],
    project_id: Optional[UUID],
    category: str,
    title: str,
    content: str,
    source: str,
    confidence: float,
    embedding: Optional[list[float]],
) -> str:
    """Insert a single knowledge_item row. Returns the new UUID string."""
    if embedding:
        row = await conn.fetchrow(
            """
            INSERT INTO knowledge_items
                (tenant_id, customer_id, project_id, category, title, content,
                 source, confidence, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector)
            RETURNING id
            """,
            tenant_id,
            customer_id,
            project_id,
            category,
            title,
            content,
            source,
            confidence,
            str(embedding),  # asyncpg+pgvector: pass as string representation
        )
    else:
        row = await conn.fetchrow(
            """
            INSERT INTO knowledge_items
                (tenant_id, customer_id, project_id, category, title, content, source, confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            tenant_id,
            customer_id,
            project_id,
            category,
            title,
            content,
            source,
            confidence,
        )
    return str(row["id"])


def _rule_to_title(rule_text: str) -> str:
    """Extract a short title from a rule's text (first 100 chars, clean)."""
    title = rule_text.strip()
    if len(title) > 100:
        # Try to cut at a sentence boundary
        cut = title[:100]
        for sep in (". ", ".\n", "; ", ","):
            idx = cut.rfind(sep)
            if idx > 40:
                cut = cut[: idx + 1]
                break
        title = cut.rstrip(",;").strip()
    return title


def _rule_to_content(rule: dict) -> str:
    """Build the full content string from a rule dict."""
    parts = [rule.get("rule_text", "").strip()]
    examples = rule.get("examples") or []
    if examples:
        parts.append("Examples:")
        parts.extend(f"  - {ex}" for ex in examples)
    parts.append(f"Severity: {rule.get('severity', 'should')}")
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def ingest_standard(
    file_data: bytes,
    filename: str,
    content_type: str,
    ctx: ContextEnvelope,
    llm: LLMProvider,
) -> dict:
    """Full intake pipeline for a documentation standard file.

    Parameters
    ----------
    file_data:    Raw bytes of the uploaded file.
    filename:     Original filename (used as source reference on each rule).
    content_type: MIME type (application/pdf, application/vnd.openxmlformats-officedocument…, text/markdown, etc.)
    ctx:          ContextEnvelope carrying tenant_id, customer_id, project_id.
    llm:          Configured LLM provider.

    Returns
    -------
    dict with keys: filename, rules_extracted, rules (list of stored rule dicts).
    """
    logger.info("Starting standards intake for %s", filename)

    # Step 1: extract text
    try:
        text = extract_text(file_data, content_type)
    except Exception as exc:
        logger.error("Text extraction failed for %s: %s", filename, exc)
        return {"filename": filename, "rules_extracted": 0, "rules": [], "error": str(exc)}

    if not text.strip():
        return {"filename": filename, "rules_extracted": 0, "rules": [], "error": "Empty document"}

    # Step 2: extract structured rules via LLM
    rules = await _extract_rules_enhanced(text, llm)
    if not rules:
        logger.warning("No rules extracted from %s", filename)
        return {"filename": filename, "rules_extracted": 0, "rules": []}

    # Step 3 + 4: generate embeddings (best-effort) and persist
    embeddings: Optional[list[list[float]]] = None
    rule_texts = [r.get("rule_text", "") for r in rules]
    try:
        embeddings = await llm.embed(rule_texts)
    except Exception as exc:
        logger.debug("Embedding call failed (will store without vectors): %s", exc)

    conn = await _get_conn()
    stored: list[dict] = []
    try:
        for i, rule in enumerate(rules):
            rule_text = rule.get("rule_text", "").strip()
            if not rule_text:
                continue

            category = rule.get("category", "quality")
            severity = rule.get("severity", "should")
            title = _rule_to_title(rule_text)
            content = _rule_to_content(rule)
            embedding = embeddings[i] if (embeddings and i < len(embeddings)) else None

            try:
                item_id = await _store_knowledge_item(
                    conn=conn,
                    tenant_id=ctx.tenant_id,
                    customer_id=ctx.customer_id,
                    project_id=ctx.project_id,
                    category=category,
                    title=title,
                    content=content,
                    source=filename,
                    confidence=1.0,
                    embedding=embedding,
                )
                stored.append(
                    {
                        "id": item_id,
                        "category": category,
                        "severity": severity,
                        "title": title,
                        "examples": rule.get("examples", []),
                    }
                )
            except Exception as db_exc:
                logger.warning("Failed to store rule %d from %s: %s", i, filename, db_exc)
    finally:
        await conn.close()

    logger.info("Ingested %d rules from %s", len(stored), filename)
    return {
        "filename": filename,
        "rules_extracted": len(stored),
        "rules": stored,
    }


async def re_ingest_standard(
    standard_id: str,
    ctx: ContextEnvelope,
    llm: LLMProvider,
) -> dict:
    """Re-run extraction on an existing knowledge_item, deduplicating by title+source.

    Looks up the original knowledge_item by ID to retrieve source filename and
    content, then re-ingests the content treating it as the raw document text.

    Note: since the original file bytes may not be available, we re-extract
    rules directly from the stored content (which is the full rule text).
    Deduplication: ON CONFLICT is not available for knowledge_items, so we
    skip insertion when an identical (title, source) pair already exists.
    """
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM knowledge_items WHERE id = $1::uuid",
            standard_id,
        )
        if row is None:
            return {"error": f"knowledge_item {standard_id} not found"}

        source = row["source"] or f"re-ingest:{standard_id}"
        content = row["content"] or ""
        category = row["category"] or "quality"
    finally:
        await conn.close()

    # Re-extract from stored content
    rules = await _extract_rules_enhanced(content, llm)
    if not rules:
        return {"filename": source, "rules_extracted": 0, "rules": []}

    # Fetch existing (title, source) pairs for dedup
    conn = await _get_conn()
    try:
        existing_rows = await conn.fetch(
            "SELECT title, source FROM knowledge_items WHERE source = $1 AND tenant_id = $2::uuid",
            source,
            str(ctx.tenant_id),
        )
        existing_keys = {(r["title"], r["source"]) for r in existing_rows}
    finally:
        await conn.close()

    # Embeddings
    embeddings: Optional[list[list[float]]] = None
    rule_texts = [r.get("rule_text", "") for r in rules]
    try:
        embeddings = await llm.embed(rule_texts)
    except Exception:
        pass

    conn = await _get_conn()
    stored: list[dict] = []
    try:
        for i, rule in enumerate(rules):
            rule_text = rule.get("rule_text", "").strip()
            if not rule_text:
                continue

            title = _rule_to_title(rule_text)
            key = (title, source)
            if key in existing_keys:
                continue  # deduplicate

            rule_category = rule.get("category", category)
            rule_severity = rule.get("severity", "should")
            full_content = _rule_to_content(rule)
            embedding = embeddings[i] if (embeddings and i < len(embeddings)) else None

            try:
                item_id = await _store_knowledge_item(
                    conn=conn,
                    tenant_id=ctx.tenant_id,
                    customer_id=ctx.customer_id,
                    project_id=ctx.project_id,
                    category=rule_category,
                    title=title,
                    content=full_content,
                    source=source,
                    confidence=0.9,  # slightly lower confidence for re-ingested items
                    embedding=embedding,
                )
                stored.append(
                    {
                        "id": item_id,
                        "category": rule_category,
                        "severity": rule_severity,
                        "title": title,
                    }
                )
                existing_keys.add(key)
            except Exception as db_exc:
                logger.warning("Failed to store re-ingested rule %d: %s", i, db_exc)
    finally:
        await conn.close()

    return {
        "filename": source,
        "rules_extracted": len(stored),
        "rules": stored,
    }
