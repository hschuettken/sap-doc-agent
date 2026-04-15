"""Knowledge Engine for Spec2Sphere.

Provides scoped CRUD and semantic search over the knowledge_items table.
Items exist at three specificity layers:
  - global   : customer_id IS NULL, project_id IS NULL
  - customer : customer_id set,     project_id IS NULL
  - project  : customer_id set,     project_id set

Search returns results across all three layers (where the context allows),
re-ranked by embedding similarity boosted by specificity.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

import asyncpg

from spec2sphere.llm.base import LLMProvider
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB connection helper — identical pattern to standards/db.py and migration/db.py
# ---------------------------------------------------------------------------


async def _get_conn() -> asyncpg.Connection:
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


async def create_knowledge_item(
    ctx: ContextEnvelope,
    title: str,
    content: str,
    category: str,
    source: str,
    confidence: float,
    llm: LLMProvider,
) -> str:
    """Insert a new knowledge item and return its UUID string.

    Generates an embedding from *content* when the LLM provider supports it.
    Stores NULL embedding when embedding generation fails or is unsupported.
    """
    embedding: Optional[list[float]] = None
    if llm is not None:
        try:
            result = await llm.embed([content])
            if result:
                embedding = result[0]
        except Exception as exc:
            logger.warning("Embedding generation failed, storing NULL: %s", exc)

    item_id = uuid.uuid4()
    conn = await _get_conn()
    try:
        emb_value = embedding  # asyncpg handles list[float] → vector via pgvector codec
        await conn.execute(
            """
            INSERT INTO knowledge_items
                (id, tenant_id, customer_id, project_id, category, title, content,
                 embedding, source, confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, $10)
            """,
            item_id,
            ctx.tenant_id,
            ctx.customer_id,
            ctx.project_id,
            category,
            title,
            content,
            str(emb_value) if emb_value is not None else None,
            source,
            confidence,
        )
        return str(item_id)
    finally:
        await conn.close()


async def get_knowledge_item(item_id: str) -> Optional[dict]:
    """Fetch a single knowledge item by UUID. Returns None if not found."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM knowledge_items WHERE id = $1::uuid", item_id)
        return dict(row) if row else None
    finally:
        await conn.close()


async def update_knowledge_item(
    item_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    category: Optional[str] = None,
    llm: Optional[LLMProvider] = None,
) -> bool:
    """Partial update of a knowledge item. Re-generates embedding when content changes.

    Returns True if a row was updated, False if the item was not found.
    """
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT id, content FROM knowledge_items WHERE id = $1::uuid", item_id)
        if not row:
            return False

        sets: list[str] = []
        params: list = []
        idx = 1

        if title is not None:
            sets.append(f"title = ${idx}")
            params.append(title)
            idx += 1

        if category is not None:
            sets.append(f"category = ${idx}")
            params.append(category)
            idx += 1

        new_content = content if content is not None else row["content"]
        if content is not None:
            sets.append(f"content = ${idx}")
            params.append(content)
            idx += 1

            # Re-generate embedding for the new content
            new_embedding: Optional[list[float]] = None
            if llm is not None:
                try:
                    result = await llm.embed([new_content])
                    if result:
                        new_embedding = result[0]
                except Exception as exc:
                    logger.warning("Embedding re-generation failed: %s", exc)

            sets.append(f"embedding = ${idx}::vector")
            params.append(str(new_embedding) if new_embedding is not None else None)
            idx += 1

        if not sets:
            # Nothing to update
            return True

        params.append(item_id)
        sql = f"UPDATE knowledge_items SET {', '.join(sets)} WHERE id = ${idx}::uuid"
        result = await conn.execute(sql, *params)
        return result != "UPDATE 0"
    finally:
        await conn.close()


async def delete_knowledge_item(item_id: str) -> bool:
    """Delete a knowledge item by UUID. Returns True if a row was deleted."""
    conn = await _get_conn()
    try:
        result = await conn.execute("DELETE FROM knowledge_items WHERE id = $1::uuid", item_id)
        return result != "DELETE 0"
    finally:
        await conn.close()


async def list_knowledge_items(
    ctx: ContextEnvelope,
    category: Optional[str] = None,
    layer: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List knowledge items scoped to ctx.tenant_id.

    layer filter values:
      "global"   — customer_id IS NULL
      "customer" — customer_id set, project_id IS NULL
      "project"  — project_id set
    """
    conditions: list[str] = ["tenant_id = $1"]
    params: list = [ctx.tenant_id]
    idx = 2

    if layer == "global":
        conditions.append("customer_id IS NULL")
    elif layer == "customer":
        conditions.append("customer_id IS NOT NULL")
        conditions.append("project_id IS NULL")
    elif layer == "project":
        conditions.append("project_id IS NOT NULL")

    if category is not None:
        conditions.append(f"category = ${idx}")
        params.append(category)
        idx += 1

    where = "WHERE " + " AND ".join(conditions)
    params.extend([limit, offset])

    sql = f"""
        SELECT id, tenant_id, customer_id, project_id, category, title, content,
               source, confidence, created_at
        FROM knowledge_items
        {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """

    conn = await _get_conn()
    try:
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


def _pgvector_embedding_str(vec: list[float]) -> str:
    """Format a Python float list as a pgvector literal string e.g. '[0.1,0.2,...]'."""
    return "[" + ",".join(str(v) for v in vec) + "]"


async def _search_layer_semantic(
    conn: asyncpg.Connection,
    tenant_id: uuid.UUID,
    query_embedding: list[float],
    layer: str,
    top_k: int,
    customer_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
) -> list[dict]:
    """Run pgvector cosine similarity search for one layer."""
    emb_str = _pgvector_embedding_str(query_embedding)

    if layer == "global":
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, customer_id, project_id, category, title, content,
                   source, confidence, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM knowledge_items
            WHERE tenant_id = $2
              AND customer_id IS NULL
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            emb_str,
            tenant_id,
            top_k,
        )
    elif layer == "customer":
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, customer_id, project_id, category, title, content,
                   source, confidence, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM knowledge_items
            WHERE tenant_id = $2
              AND customer_id = $3
              AND project_id IS NULL
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            emb_str,
            tenant_id,
            customer_id,
            top_k,
        )
    else:  # project
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, customer_id, project_id, category, title, content,
                   source, confidence, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM knowledge_items
            WHERE tenant_id = $2
              AND customer_id = $3
              AND project_id = $4
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $5
            """,
            emb_str,
            tenant_id,
            customer_id,
            project_id,
            top_k,
        )

    return [dict(r) for r in rows]


async def _search_layer_text(
    conn: asyncpg.Connection,
    query: str,
    tenant_id: uuid.UUID,
    layer: str,
    top_k: int,
    customer_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
) -> list[dict]:
    """ILIKE fallback text search for one layer."""
    pattern = f"%{query}%"

    if layer == "global":
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, customer_id, project_id, category, title, content,
                   source, confidence, created_at, NULL::float AS similarity
            FROM knowledge_items
            WHERE tenant_id = $1
              AND customer_id IS NULL
              AND (title ILIKE $2 OR content ILIKE $2)
            LIMIT $3
            """,
            tenant_id,
            pattern,
            top_k,
        )
    elif layer == "customer":
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, customer_id, project_id, category, title, content,
                   source, confidence, created_at, NULL::float AS similarity
            FROM knowledge_items
            WHERE tenant_id = $1
              AND customer_id = $2
              AND project_id IS NULL
              AND (title ILIKE $3 OR content ILIKE $3)
            LIMIT $4
            """,
            tenant_id,
            customer_id,
            pattern,
            top_k,
        )
    else:  # project
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, customer_id, project_id, category, title, content,
                   source, confidence, created_at, NULL::float AS similarity
            FROM knowledge_items
            WHERE tenant_id = $1
              AND customer_id = $2
              AND project_id = $3
              AND (title ILIKE $4 OR content ILIKE $4)
            LIMIT $5
            """,
            tenant_id,
            customer_id,
            project_id,
            pattern,
            top_k,
        )

    return [dict(r) for r in rows]


async def search_knowledge(
    query: str,
    ctx: ContextEnvelope,
    top_k: int = 10,
    llm: Optional[LLMProvider] = None,
) -> list[dict]:
    """Scoped semantic search across project → customer → global layers.

    Re-ranks results by combining cosine similarity with a specificity bonus:
      project  +0.10
      customer +0.05
      global   +0.00

    Falls back to ILIKE text search when embeddings are unavailable.
    Deduplicates by title (most specific layer wins).
    """
    # Determine which layers are accessible from this context
    allowed = set(ctx.allowed_knowledge_layers)  # e.g. ["global", "customer", "project"]

    # Try to generate a query embedding
    query_embedding: Optional[list[float]] = None
    if llm is not None:
        try:
            result = await llm.embed([query])
            if result:
                query_embedding = result[0]
        except Exception as exc:
            logger.warning("Query embedding failed, falling back to text search: %s", exc)

    conn = await _get_conn()
    try:
        # Fetch candidates from each layer in specificity order
        layer_bonus = {"project": 0.10, "customer": 0.05, "global": 0.00}
        all_results: list[dict] = []

        for layer in ("project", "customer", "global"):
            if layer not in allowed:
                continue
            # Skip layers that require ids we don't have
            if layer == "project" and ctx.project_id is None:
                continue
            if layer == "customer" and ctx.customer_id is None:
                continue

            if query_embedding is not None:
                rows = await _search_layer_semantic(
                    conn,
                    ctx.tenant_id,
                    query_embedding,
                    layer,
                    top_k,
                    customer_id=ctx.customer_id,
                    project_id=ctx.project_id,
                )
            else:
                rows = await _search_layer_text(
                    conn,
                    query,
                    ctx.tenant_id,
                    layer,
                    top_k,
                    customer_id=ctx.customer_id,
                    project_id=ctx.project_id,
                )

            bonus = layer_bonus[layer]
            for row in rows:
                row["source_layer"] = layer
                sim = row.get("similarity") or 0.0
                row["score"] = float(sim) + bonus

            all_results.extend(rows)

        # Deduplicate by title — keep highest score (most specific layer wins on tie)
        seen_titles: dict[str, dict] = {}
        for item in all_results:
            t = (item.get("title") or "").lower()
            if t not in seen_titles or item["score"] > seen_titles[t]["score"]:
                seen_titles[t] = item

        ranked = sorted(seen_titles.values(), key=lambda x: x["score"], reverse=True)
        return ranked[:top_k]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Document ingestion
# ---------------------------------------------------------------------------


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split *text* into overlapping chunks of approximately *chunk_size* chars."""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
        if start >= len(text):
            break
    return chunks


async def ingest_documents(
    files: list[tuple[str, bytes, str]],
    ctx: ContextEnvelope,
    llm: LLMProvider,
) -> dict:
    """Ingest a list of files into the knowledge base.

    Args:
        files: List of (filename, data, content_type) tuples.
        ctx: Scoped context for tenant/customer/project assignment.
        llm: LLM provider used for embedding generation.

    Returns:
        {"ingested": int, "errors": list[str]}
    """
    from spec2sphere.standards.extractor import UnsupportedFileType, extract_text

    ingested = 0
    errors: list[str] = []

    for filename, data, content_type in files:
        try:
            text = extract_text(data, content_type)
        except UnsupportedFileType as exc:
            errors.append(f"{filename}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{filename}: extraction failed: {exc}")
            continue

        chunks = _chunk_text(text, chunk_size=1000, overlap=200)
        if not chunks:
            errors.append(f"{filename}: extracted text was empty")
            continue

        for i, chunk in enumerate(chunks):
            chunk_title = f"{filename} (part {i + 1})" if len(chunks) > 1 else filename
            try:
                await create_knowledge_item(
                    ctx=ctx,
                    title=chunk_title,
                    content=chunk,
                    category="document",
                    source=filename,
                    confidence=1.0,
                    llm=llm,
                )
                ingested += 1
            except Exception as exc:
                errors.append(f"{filename} chunk {i + 1}: DB insert failed: {exc}")

    return {"ingested": ingested, "errors": errors}
