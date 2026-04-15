"""Async PostgreSQL CRUD for migration tables."""

from __future__ import annotations

import json
import os
from typing import Optional

import asyncpg


async def _get_conn():
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


# --- Projects ---


async def create_project(
    name: str,
    scan_id: str,
    description: str = "",
    source_system: str = "",
    brs_folder: str = "",
    config_json: Optional[dict] = None,
) -> str:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """INSERT INTO migration_projects_v1
               (name, scan_id, description, source_system, brs_folder, config_json)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb) RETURNING id""",
            name,
            scan_id,
            description,
            source_system,
            brs_folder,
            json.dumps(config_json or {}),
        )
        return str(row["id"])
    finally:
        await conn.close()


async def get_project(project_id: str) -> Optional[dict]:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM migration_projects_v1 WHERE id = $1::uuid", project_id)
        return dict(row) if row else None
    finally:
        await conn.close()


async def list_projects() -> list[dict]:
    conn = await _get_conn()
    try:
        rows = await conn.fetch("SELECT * FROM migration_projects_v1 ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def update_project_status(project_id: str, status: str) -> None:
    conn = await _get_conn()
    try:
        await conn.execute(
            "UPDATE migration_projects_v1 SET status = $1, updated_at = NOW() WHERE id = $2::uuid",
            status,
            project_id,
        )
    finally:
        await conn.close()


async def delete_project(project_id: str) -> None:
    conn = await _get_conn()
    try:
        await conn.execute("DELETE FROM migration_projects_v1 WHERE id = $1::uuid", project_id)
    finally:
        await conn.close()


# --- Intent Cards ---


async def upsert_intent_card(project_id: str, chain_id: str, intent_json: dict) -> str:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """INSERT INTO migration_intent_cards_v1
               (project_id, chain_id, business_purpose, data_domain, grain,
                intent_json, confidence, needs_human_review)
               VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7, $8)
               ON CONFLICT (project_id, chain_id) DO UPDATE SET
                   business_purpose = EXCLUDED.business_purpose,
                   data_domain = EXCLUDED.data_domain,
                   grain = EXCLUDED.grain,
                   intent_json = EXCLUDED.intent_json,
                   confidence = EXCLUDED.confidence,
                   needs_human_review = EXCLUDED.needs_human_review
               RETURNING id""",
            project_id,
            chain_id,
            intent_json.get("business_purpose", ""),
            intent_json.get("data_domain", ""),
            intent_json.get("grain", ""),
            json.dumps(intent_json),
            intent_json.get("confidence", 0.0),
            intent_json.get("confidence", 1.0) < 0.7,
        )
        return str(row["id"])
    finally:
        await conn.close()


async def get_intent_card(card_id: str) -> Optional[dict]:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM migration_intent_cards_v1 WHERE id = $1::uuid", card_id)
        return dict(row) if row else None
    finally:
        await conn.close()


async def list_intent_cards(project_id: str) -> list[dict]:
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM migration_intent_cards_v1 WHERE project_id = $1::uuid ORDER BY chain_id",
            project_id,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def review_intent_card(card_id: str, decision: str, reviewer: str, notes: str = "") -> None:
    conn = await _get_conn()
    try:
        await conn.execute(
            """UPDATE migration_intent_cards_v1
               SET review_status = $1, reviewed_by = $2, reviewer_notes = $3, reviewed_at = NOW()
               WHERE id = $4::uuid""",
            decision,
            reviewer,
            notes,
            card_id,
        )
    finally:
        await conn.close()


# --- Classifications ---


async def upsert_classification(
    project_id: str,
    chain_id: str,
    intent_card_id: str,
    classification_json: dict,
) -> str:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """INSERT INTO migration_classifications_v1
               (project_id, chain_id, intent_card_id, classification, rationale,
                effort_category, classification_json)
               VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6, $7::jsonb)
               RETURNING id""",
            project_id,
            chain_id,
            intent_card_id,
            classification_json.get("classification", "clarify"),
            classification_json.get("rationale", ""),
            classification_json.get("effort_category"),
            json.dumps(classification_json),
        )
        return str(row["id"])
    finally:
        await conn.close()


async def list_classifications(project_id: str) -> list[dict]:
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM migration_classifications_v1 WHERE project_id = $1::uuid ORDER BY chain_id",
            project_id,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def review_classification(classification_id: str, decision: str, reviewer: str, notes: str = "") -> None:
    conn = await _get_conn()
    try:
        await conn.execute(
            """UPDATE migration_classifications_v1
               SET review_status = $1, reviewed_by = $2, reviewer_notes = $3, reviewed_at = NOW()
               WHERE id = $4::uuid""",
            decision,
            reviewer,
            notes,
            classification_id,
        )
    finally:
        await conn.close()


# --- Target Views ---


async def upsert_target_view(project_id: str, technical_name: str, view_spec: dict) -> str:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """INSERT INTO migration_target_views_v1
               (project_id, technical_name, space, layer, semantic_usage,
                description, view_spec_json, source_chains, generated_sql)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9)
               ON CONFLICT (project_id, technical_name) DO UPDATE SET
                   view_spec_json = EXCLUDED.view_spec_json,
                   generated_sql = EXCLUDED.generated_sql
               RETURNING id""",
            project_id,
            technical_name,
            view_spec.get("space", ""),
            view_spec.get("layer", ""),
            view_spec.get("semantic_usage", ""),
            view_spec.get("description", ""),
            json.dumps(view_spec),
            json.dumps(view_spec.get("source_chains", [])),
            view_spec.get("generated_sql"),
        )
        return str(row["id"])
    finally:
        await conn.close()


async def list_target_views(project_id: str) -> list[dict]:
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM migration_target_views_v1 WHERE project_id = $1::uuid ORDER BY layer, technical_name",
            project_id,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()
