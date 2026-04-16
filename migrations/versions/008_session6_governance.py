"""Session 6 governance tables.

Revision ID: 008
Revises: 007
Create Date: 2026-04-16
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS release_packages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        version TEXT NOT NULL,
        status TEXT DEFAULT 'draft',
        approval_id UUID REFERENCES approvals(id),
        manifest JSONB DEFAULT '{}',
        artifact_paths JSONB DEFAULT '[]',
        created_by UUID REFERENCES users(id),
        created_at TIMESTAMPTZ DEFAULT now(),
        finalized_at TIMESTAMPTZ
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS style_preferences (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        preference_type TEXT NOT NULL,
        preference_key TEXT NOT NULL,
        score FLOAT DEFAULT 0.0,
        evidence_count INT DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE(customer_id, preference_type, preference_key)
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS promotion_candidates (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_customer_id UUID REFERENCES customers(id),
        source_type TEXT NOT NULL,
        source_id UUID NOT NULL,
        target_layer TEXT NOT NULL,
        anonymized_content JSONB,
        status TEXT DEFAULT 'pending',
        reviewed_by UUID REFERENCES users(id),
        reviewed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_release_packages_project ON release_packages(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_style_prefs_customer ON style_preferences(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_promotion_candidates_status ON promotion_candidates(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS promotion_candidates CASCADE")
    op.execute("DROP TABLE IF EXISTS style_preferences CASCADE")
    op.execute("DROP TABLE IF EXISTS release_packages CASCADE")
