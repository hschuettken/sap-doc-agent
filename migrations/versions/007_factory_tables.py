"""Factory deployment tables.

Tracks complete factory runs and individual deployment steps for artifacts,
including route decisions, verification results, and deployment artifacts.

Revision ID: 007
Revises: 006
Create Date: 2026-04-15
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Factory: Deployment Runs ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS deployment_runs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        tech_spec_id UUID REFERENCES tech_specs(id),
        blueprint_id UUID REFERENCES sac_blueprints(id),
        status TEXT DEFAULT 'pending',
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        summary JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Factory: Deployment Steps ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS deployment_steps (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id UUID REFERENCES deployment_runs(id),
        technical_object_id UUID REFERENCES technical_objects(id),
        artifact_name TEXT NOT NULL,
        artifact_type TEXT NOT NULL,
        platform TEXT NOT NULL,
        route_chosen TEXT,
        route_alternatives JSONB DEFAULT '[]',
        route_reason TEXT,
        status TEXT DEFAULT 'pending',
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        duration_seconds FLOAT,
        error_message TEXT,
        readback_diff JSONB,
        screenshot_path TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Indexes ----
    op.execute("CREATE INDEX IF NOT EXISTS idx_deployment_runs_project ON deployment_runs(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deployment_steps_run ON deployment_steps(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_deployment_steps_status ON deployment_steps(status)")


def downgrade() -> None:
    # Drop steps first (FK depends on runs)
    op.execute("DROP TABLE IF EXISTS deployment_steps CASCADE")
    op.execute("DROP TABLE IF EXISTS deployment_runs CASCADE")
