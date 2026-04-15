"""Async database operations for customer standards and tenant knowledge."""

from __future__ import annotations

import json
import os
from typing import Optional

import asyncpg


async def _get_conn():
    db_url = os.environ.get("DATABASE_URL", "")
    # asyncpg needs postgresql:// not postgresql+psycopg://
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


async def create_standard(name: str, filename: str, content_type: str) -> str:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "INSERT INTO customer_standards_v1(name, filename, content_type) VALUES($1,$2,$3) RETURNING id",
            name,
            filename,
            content_type,
        )
        return str(row["id"])
    finally:
        await conn.close()


async def store_standard_file(standard_id: str, file_data: bytes, filename: str, content_type: str) -> None:
    conn = await _get_conn()
    try:
        await conn.execute(
            "INSERT INTO customer_standard_files_v1(standard_id, file_data, filename, content_type, size_bytes) VALUES($1,$2,$3,$4,$5)",
            standard_id,
            file_data,
            filename,
            content_type,
            len(file_data),
        )
    finally:
        await conn.close()


async def update_standard_rules(
    standard_id: str,
    parsed_rules: dict,
    raw_text: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    conn = await _get_conn()
    try:
        await conn.execute(
            "UPDATE customer_standards_v1 SET parsed_rules=$1, raw_text=$2, status=$3, error_message=$4 WHERE id=$5",
            json.dumps(parsed_rules),
            raw_text,
            status,
            error_message,
            standard_id,
        )
    finally:
        await conn.close()


async def list_standards(status: Optional[str] = None) -> list[dict]:
    conn = await _get_conn()
    try:
        if status:
            rows = await conn.fetch(
                "SELECT id, name, filename, content_type, uploaded_at, status FROM customer_standards_v1 WHERE status=$1 ORDER BY uploaded_at DESC",
                status,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, name, filename, content_type, uploaded_at, status FROM customer_standards_v1 ORDER BY uploaded_at DESC"
            )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_standard(standard_id: str) -> Optional[dict]:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM customer_standards_v1 WHERE id=$1", standard_id)
        return dict(row) if row else None
    finally:
        await conn.close()


async def delete_standard(standard_id: str) -> None:
    conn = await _get_conn()
    try:
        await conn.execute("DELETE FROM customer_standards_v1 WHERE id=$1", standard_id)
    finally:
        await conn.close()


async def get_standard_file(standard_id: str) -> Optional[dict]:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM customer_standard_files_v1 WHERE standard_id=$1", standard_id)
        return dict(row) if row else None
    finally:
        await conn.close()


async def upsert_knowledge(category: str, key: str, value: dict, source: str) -> None:
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO tenant_knowledge_v1(category, key, value, source)
            VALUES($1,$2,$3,$4)
            ON CONFLICT (category, key) DO UPDATE
            SET value=EXCLUDED.value, source=EXCLUDED.source, updated_at=now()
            WHERE tenant_knowledge_v1.source != 'manual' OR EXCLUDED.source = 'manual'
            """,
            category,
            key,
            json.dumps(value),
            source,
        )
    finally:
        await conn.close()


async def list_knowledge(category: Optional[str] = None) -> list[dict]:
    conn = await _get_conn()
    try:
        if category:
            rows = await conn.fetch(
                "SELECT * FROM tenant_knowledge_v1 WHERE category=$1 ORDER BY updated_at DESC", category
            )
        else:
            rows = await conn.fetch("SELECT * FROM tenant_knowledge_v1 ORDER BY updated_at DESC")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def delete_knowledge(knowledge_id: str) -> None:
    conn = await _get_conn()
    try:
        await conn.execute("DELETE FROM tenant_knowledge_v1 WHERE id=$1", knowledge_id)
    finally:
        await conn.close()
