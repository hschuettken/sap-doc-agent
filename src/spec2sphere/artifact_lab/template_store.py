"""Template store — build, persist, and graduate learned templates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from spec2sphere.artifact_lab.experiment_tracker import ExperimentRecord


@dataclass
class TemplateRecord:
    id: str
    customer_id: str
    platform: str
    object_type: str
    template_definition: dict
    mutation_rules: dict
    deployment_hints: dict
    confidence: float
    approved: bool


def build_template_from_experiment(exp: ExperimentRecord) -> TemplateRecord:
    """Create an unapproved template with confidence=0.5 from an experiment."""
    return TemplateRecord(
        id=str(uuid.uuid4()),
        customer_id=exp.customer_id,
        platform=exp.platform,
        object_type=exp.object_type,
        template_definition=exp.output_definition,
        mutation_rules=exp.diff,
        deployment_hints={"route": exp.route_used, "experiment_type": exp.experiment_type},
        confidence=0.5,
        approved=False,
    )


async def save_template(rec: TemplateRecord) -> None:
    """Persist a TemplateRecord to the database."""
    import json
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO learned_templates (
                id, customer_id, platform, object_type, template_definition,
                mutation_rules, deployment_hints, confidence, approved
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            rec.id,
            rec.customer_id,
            rec.platform,
            rec.object_type,
            json.dumps(rec.template_definition),
            json.dumps(rec.mutation_rules),
            json.dumps(rec.deployment_hints),
            rec.confidence,
            rec.approved,
        )
    finally:
        await conn.close()


async def list_templates(
    customer_id: str,
    platform: Optional[str] = None,
    approved_only: bool = False,
    limit: int = 50,
) -> list[TemplateRecord]:
    """List templates for a customer."""
    import json
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        conditions = ["customer_id = $1"]
        params: list[Any] = [customer_id]
        idx = 2

        if platform:
            conditions.append(f"platform = ${idx}")
            params.append(platform)
            idx += 1

        if approved_only:
            conditions.append(f"approved = ${idx}")
            params.append(True)
            idx += 1

        params.append(limit)
        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"SELECT * FROM learned_templates WHERE {where} ORDER BY id DESC LIMIT ${idx}",
            *params,
        )
    finally:
        await conn.close()

    return [
        TemplateRecord(
            id=str(row["id"]),
            customer_id=row["customer_id"],
            platform=row["platform"],
            object_type=row["object_type"],
            template_definition=json.loads(row["template_definition"]),
            mutation_rules=json.loads(row["mutation_rules"]),
            deployment_hints=json.loads(row["deployment_hints"]),
            confidence=float(row["confidence"]),
            approved=row["approved"],
        )
        for row in rows
    ]


async def graduate_template(
    template_id: str,
    approved: bool,
    reviewer_id: str,
) -> None:
    """Approve or reject a template and record the reviewer."""
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        await conn.execute(
            """
            UPDATE learned_templates
            SET approved = $1, reviewer_id = $2
            WHERE id = $3
            """,
            approved,
            reviewer_id,
            template_id,
        )
    finally:
        await conn.close()
