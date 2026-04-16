"""Experiment tracker — record, persist, and retrieve lab experiments."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from spec2sphere.artifact_lab.lab_runner import compute_diff


@dataclass
class ExperimentRecord:
    id: str
    customer_id: str
    platform: str
    object_type: str
    experiment_type: str
    input_definition: dict
    output_definition: dict
    diff: dict
    route_used: str
    success: bool
    notes: Optional[str] = None


def build_experiment_record(
    customer_id: str,
    platform: str,
    object_type: str,
    experiment_type: str,
    input_definition: dict,
    output_definition: dict,
    route_used: str,
    success: bool,
    notes: Optional[str] = None,
) -> ExperimentRecord:
    """Create an ExperimentRecord with auto-computed diff."""
    diff = compute_diff(input_definition, output_definition)
    return ExperimentRecord(
        id=str(uuid.uuid4()),
        customer_id=customer_id,
        platform=platform,
        object_type=object_type,
        experiment_type=experiment_type,
        input_definition=input_definition,
        output_definition=output_definition,
        diff=diff,
        route_used=route_used,
        success=success,
        notes=notes,
    )


async def save_experiment(rec: ExperimentRecord) -> None:
    """Persist an ExperimentRecord to the database."""
    import json
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO lab_experiments (
                id, customer_id, platform, object_type, experiment_type,
                input_definition, output_definition, diff, route_used, success, notes
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            rec.id,
            rec.customer_id,
            rec.platform,
            rec.object_type,
            rec.experiment_type,
            json.dumps(rec.input_definition),
            json.dumps(rec.output_definition),
            json.dumps(rec.diff),
            rec.route_used,
            rec.success,
            rec.notes,
        )
    finally:
        await conn.close()


async def list_experiments(
    customer_id: str,
    platform: Optional[str] = None,
    limit: int = 50,
) -> list[ExperimentRecord]:
    """List experiments for a customer, optionally filtered by platform."""
    import json
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        if platform:
            rows = await conn.fetch(
                """
                SELECT * FROM lab_experiments
                WHERE customer_id = $1 AND platform = $2
                ORDER BY id DESC LIMIT $3
                """,
                customer_id,
                platform,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM lab_experiments
                WHERE customer_id = $1
                ORDER BY id DESC LIMIT $2
                """,
                customer_id,
                limit,
            )
    finally:
        await conn.close()

    return [
        ExperimentRecord(
            id=str(row["id"]),
            customer_id=row["customer_id"],
            platform=row["platform"],
            object_type=row["object_type"],
            experiment_type=row["experiment_type"],
            input_definition=json.loads(row["input_definition"]),
            output_definition=json.loads(row["output_definition"]),
            diff=json.loads(row["diff"]),
            route_used=row["route_used"],
            success=row["success"],
            notes=row["notes"],
        )
        for row in rows
    ]


async def get_experiment(experiment_id: str) -> Optional[ExperimentRecord]:
    """Retrieve a single experiment by ID."""
    import json
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM lab_experiments WHERE id = $1",
            experiment_id,
        )
    finally:
        await conn.close()

    if row is None:
        return None

    return ExperimentRecord(
        id=str(row["id"]),
        customer_id=row["customer_id"],
        platform=row["platform"],
        object_type=row["object_type"],
        experiment_type=row["experiment_type"],
        input_definition=json.loads(row["input_definition"]),
        output_definition=json.loads(row["output_definition"]),
        diff=json.loads(row["diff"]),
        route_used=row["route_used"],
        success=row["success"],
        notes=row["notes"],
    )
