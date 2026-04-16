"""Approval gate workflow for Spec2Sphere pipeline stages.

Supports: requirements, hla_documents, tech_specs, sac_blueprints, test_specs.
Each artifact type has predefined checklist items (from Appendix B patterns).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import asyncpg

if TYPE_CHECKING:
    from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)

# Predefined checklists per artifact type
CHECKLISTS = {
    "requirement": [
        {"key": "scope_correct", "label": "Business scope correctly identified", "required": True},
        {"key": "entities_complete", "label": "All entities and relationships identified", "required": True},
        {"key": "kpis_defined", "label": "KPIs have clear formulas and targets", "required": True},
        {"key": "grain_agreed", "label": "Grain/dimensionality agreed", "required": True},
        {"key": "sources_identified", "label": "Source systems identified", "required": True},
        {"key": "open_questions_acceptable", "label": "Open questions at acceptable level", "required": True},
        {"key": "nfr_documented", "label": "Non-functional requirements documented", "required": False},
    ],
    "hla_document": [
        {"key": "scope_correct", "label": "Business scope matches requirements", "required": True},
        {"key": "entities_identified", "label": "All entities correctly mapped to layers", "required": True},
        {"key": "grain_agreed", "label": "Grain agreed and documented", "required": True},
        {
            "key": "arch_decisions_documented",
            "label": "Architecture decisions documented with rationale",
            "required": True,
        },
        {"key": "platform_placement_justified", "label": "DSP/SAC placement decisions justified", "required": True},
        {"key": "reuse_checked", "label": "Existing landscape objects checked for reuse", "required": True},
        {"key": "open_questions_acceptable", "label": "Remaining open questions acceptable", "required": False},
        {"key": "naming_conventions", "label": "Naming conventions followed", "required": False},
    ],
    "tech_spec": [
        {"key": "all_views_specified", "label": "All views fully specified", "required": True},
        {"key": "dependencies_resolved", "label": "Dependencies resolved and build order correct", "required": True},
        {"key": "sql_validated", "label": "SQL syntax validated", "required": True},
        {"key": "persistence_decided", "label": "Persistence decisions documented", "required": True},
        {"key": "naming_compliant", "label": "Naming conventions compliant", "required": True},
    ],
    "sac_blueprint": [
        {"key": "pages_complete", "label": "All pages and widgets defined", "required": True},
        {"key": "artifact_type_justified", "label": "Story/App/Widget decision justified", "required": True},
        {"key": "interactions_defined", "label": "Filters and navigation defined", "required": True},
        {"key": "design_tokens_applied", "label": "Design tokens applied correctly", "required": True},
        {"key": "performance_acceptable", "label": "Performance classification acceptable", "required": False},
    ],
    "test_spec": [
        {"key": "test_cases_comprehensive", "label": "Test cases cover all critical paths", "required": True},
        {"key": "tolerance_rules_defined", "label": "Tolerance rules defined for each test", "required": True},
        {
            "key": "expected_deltas_documented",
            "label": "Expected deltas documented (if improvement mode)",
            "required": False,
        },
        {"key": "dev_copy_commands_valid", "label": "DEV copy commands are valid SQL", "required": True},
        {"key": "golden_queries_included", "label": "Golden queries included for key KPIs", "required": False},
    ],
    "deployment": [
        {"key": "sandbox_validated", "label": "Sandbox deployment successful", "required": True},
        {"key": "reconciliation_passed", "label": "Reconciliation results acceptable", "required": True},
        {"key": "visual_qa_passed", "label": "Visual QA passed or differences accepted", "required": True},
        {"key": "interaction_qa_passed", "label": "Interaction tests passed", "required": False},
        {"key": "design_score_acceptable", "label": "Design quality score meets threshold", "required": False},
        {"key": "rollback_plan_documented", "label": "Rollback plan documented", "required": True},
    ],
    "release": [
        {"key": "hla_approved", "label": "HLA approved", "required": True},
        {"key": "tech_spec_approved", "label": "Technical specification approved", "required": True},
        {"key": "test_spec_approved", "label": "Test specification approved", "required": True},
        {"key": "sandbox_qa_passed", "label": "Sandbox QA passed", "required": True},
        {"key": "reconciliation_acceptable", "label": "Reconciliation results acceptable", "required": True},
        {"key": "open_issues_reviewed", "label": "Open issues register reviewed", "required": True},
        {"key": "documentation_generated", "label": "As-built documentation generated", "required": True},
        {"key": "rollback_plan_ready", "label": "Rollback plan documented", "required": True},
    ],
}

# Map artifact_type to the DB table that holds the artifact and its status column
ARTIFACT_TABLES = {
    "requirement": "requirements",
    "hla_document": "hla_documents",
    "tech_spec": "tech_specs",
    "sac_blueprint": "sac_blueprints",
    "test_spec": "test_specs",
    "release": "release_packages",
}

VALID_DECISIONS = {"approve", "reject", "rework"}


async def _get_conn() -> asyncpg.Connection:
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to plain dict, serialising timestamps and UUIDs."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "hex") and not isinstance(v, (str, bytes)):
            d[k] = str(v)
    return d


def _build_checklist(artifact_type: str) -> dict:
    """Build the initial checklist JSONB payload for a given artifact type."""
    items = CHECKLISTS.get(artifact_type, [])
    return {"items": [{**item, "checked": False} for item in items]}


def _merge_checklist(existing: dict, updates: dict) -> dict:
    """Merge key→bool updates into the existing checklist structure."""
    items = existing.get("items", [])
    for item in items:
        key = item.get("key")
        if key in updates:
            item["checked"] = bool(updates[key])
    return {"items": items}


async def submit_for_review(
    artifact_type: str,
    artifact_id: str,
    ctx: "ContextEnvelope",
    reviewer_id: Optional[str] = None,
) -> dict:
    """Submit an artifact for approval.

    Creates an approval record with a prefilled checklist and updates the
    artifact's status to 'pending_review'.  Creates a notification for the
    reviewer if one is specified.

    Returns the new approval record as a dict.
    """
    if artifact_type not in ARTIFACT_TABLES:
        raise ValueError(f"Unknown artifact_type: {artifact_type!r}. Must be one of {list(ARTIFACT_TABLES)}")

    checklist = _build_checklist(artifact_type)
    table = ARTIFACT_TABLES[artifact_type]

    conn = await _get_conn()
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO approvals (project_id, artifact_type, artifact_id, status, reviewer_id, checklist, comments)
                VALUES ($1, $2, $3::uuid, 'pending', $4::uuid, $5::jsonb, $6)
                RETURNING *
                """,
                ctx.project_id,
                artifact_type,
                artifact_id,
                reviewer_id,
                json.dumps(checklist),
                json.dumps({"submitter_id": str(ctx.user_id)}),
            )
            approval = _row_to_dict(row)

            await conn.execute(
                f"UPDATE {table} SET status = 'pending_review' WHERE id = $1::uuid",
                artifact_id,
            )

        logger.info(
            "Submitted %s %s for review (approval %s)",
            artifact_type,
            artifact_id,
            approval["id"],
        )

        if reviewer_id and ctx.project_id:
            try:
                from spec2sphere.governance.notifications import create_notification

                await create_notification(
                    project_id=str(ctx.project_id),
                    user_id=reviewer_id,
                    title="Review requested",
                    message=f"A {artifact_type.replace('_', ' ')} has been submitted for your review.",
                    link=f"/pipeline/{artifact_type}s/{artifact_id}",
                    notification_type="approval_required",
                )
            except Exception as exc:
                logger.warning("Failed to create review notification: %s", exc)

        return approval
    finally:
        await conn.close()


async def review_artifact(
    approval_id: str,
    decision: str,
    ctx: "ContextEnvelope",
    comments: Optional[str] = None,
    checklist_updates: Optional[dict] = None,
) -> dict:
    """Process a review decision.

    decision values:
      - "approve" → approval status 'approved', artifact status 'approved'
      - "reject"  → approval status 'rejected', artifact status 'rejected'
      - "rework"  → approval status 'rework',   artifact status 'rework'

    Creates a notification for the submitter (tracked via project context).
    Returns the updated approval dict.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Invalid decision {decision!r}. Must be one of {VALID_DECISIONS}")

    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM approvals WHERE id = $1::uuid",
            approval_id,
        )
        if not row:
            raise ValueError(f"Approval {approval_id!r} not found")

        approval = _row_to_dict(row)
        artifact_type = approval["artifact_type"]
        artifact_id = approval["artifact_id"]

        if artifact_type not in ARTIFACT_TABLES:
            raise ValueError(f"Approval references unknown artifact_type: {artifact_type!r}")

        # Merge checklist updates if provided
        existing_checklist = approval.get("checklist") or {"items": []}
        if isinstance(existing_checklist, str):
            existing_checklist = json.loads(existing_checklist)
        if checklist_updates:
            existing_checklist = _merge_checklist(existing_checklist, checklist_updates)

        table = ARTIFACT_TABLES[artifact_type]
        now = datetime.now(timezone.utc)

        async with conn.transaction():
            updated_row = await conn.fetchrow(
                """
                UPDATE approvals
                SET status       = $1,
                    reviewer_id  = $2::uuid,
                    comments     = $3,
                    checklist    = $4::jsonb,
                    resolved_at  = $5
                WHERE id = $6::uuid
                RETURNING *
                """,
                decision,
                str(ctx.user_id),
                comments,
                json.dumps(existing_checklist),
                now,
                approval_id,
            )
            updated = _row_to_dict(updated_row)

            await conn.execute(
                f"UPDATE {table} SET status = $1 WHERE id = $2::uuid",
                decision,
                artifact_id,
            )

        logger.info(
            "Approval %s decided: %s (artifact %s %s)",
            approval_id,
            decision,
            artifact_type,
            artifact_id,
        )

        # Notify artifact submitter — best-effort, non-blocking
        if ctx.project_id:
            try:
                from spec2sphere.governance.notifications import create_notification

                # Resolve submitter from the initial submission metadata
                submit_meta = approval.get("comments")
                submitter_id = None
                if isinstance(submit_meta, str):
                    try:
                        submitter_id = json.loads(submit_meta).get("submitter_id")
                    except (json.JSONDecodeError, AttributeError):
                        pass
                elif isinstance(submit_meta, dict):
                    submitter_id = submit_meta.get("submitter_id")
                # Fallback: notify all project users by using a well-known UUID
                notify_user = submitter_id or str(ctx.user_id)

                verb = {"approve": "approved", "reject": "rejected", "rework": "sent back for rework"}[decision]
                ntype = "approval_decision"
                await create_notification(
                    project_id=str(ctx.project_id),
                    user_id=notify_user,
                    title=f"Review decision: {verb}",
                    message=(
                        f"Your {artifact_type.replace('_', ' ')} was {verb}."
                        + (f" Comment: {comments}" if comments else "")
                    ),
                    link=f"/pipeline/{artifact_type}s/{artifact_id}",
                    notification_type=ntype,
                )
            except Exception as exc:
                logger.warning("Failed to create decision notification: %s", exc)

        return updated
    finally:
        await conn.close()


async def get_approval(approval_id: str, project_id=None) -> Optional[dict]:
    """Get a single approval record by ID, optionally scoped to a project."""
    conn = await _get_conn()
    try:
        if project_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM approvals WHERE id = $1::uuid AND project_id = $2",
                approval_id,
                project_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM approvals WHERE id = $1::uuid",
                approval_id,
            )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def list_approvals(
    ctx: "ContextEnvelope",
    artifact_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List approvals for the active project, newest first."""
    conditions: list[str] = ["project_id = $1"]
    params: list = [ctx.project_id]
    idx = 2

    if artifact_type is not None:
        conditions.append(f"artifact_type = ${idx}")
        params.append(artifact_type)
        idx += 1

    if status is not None:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    params.append(limit)
    where = " AND ".join(conditions)

    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            f"""
            SELECT * FROM approvals
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def get_approval_for_artifact(artifact_type: str, artifact_id: str) -> Optional[dict]:
    """Get the latest approval record for a specific artifact."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT * FROM approvals
            WHERE artifact_type = $1 AND artifact_id = $2::uuid
            ORDER BY created_at DESC
            LIMIT 1
            """,
            artifact_type,
            artifact_id,
        )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def update_checklist(
    approval_id: str,
    checklist_updates: dict,
    ctx: "ContextEnvelope",
) -> dict:
    """Update individual checklist items without making a final decision.

    checklist_updates is a flat dict of {key: bool}, e.g. {"scope_correct": True}.
    Returns the updated approval dict.
    """
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM approvals WHERE id = $1::uuid",
            approval_id,
        )
        if not row:
            raise ValueError(f"Approval {approval_id!r} not found")

        existing = _row_to_dict(row)
        checklist = existing.get("checklist") or {"items": []}
        if isinstance(checklist, str):
            checklist = json.loads(checklist)

        merged = _merge_checklist(checklist, checklist_updates)

        updated_row = await conn.fetchrow(
            """
            UPDATE approvals
            SET checklist = $1::jsonb
            WHERE id = $2::uuid
            RETURNING *
            """,
            json.dumps(merged),
            approval_id,
        )
        return _row_to_dict(updated_row)
    finally:
        await conn.close()
