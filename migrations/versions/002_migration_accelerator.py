"""Migration Accelerator tables.

Revision ID: 002
Revises: 001
Create Date: 2026-04-14
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE IF NOT EXISTS migration_projects_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255) NOT NULL,
        description TEXT,
        scan_id VARCHAR(255) NOT NULL,
        brs_folder VARCHAR(255),
        source_system VARCHAR(100),
        target_system VARCHAR(100) DEFAULT 'SAP Datasphere',
        status VARCHAR(50) DEFAULT 'created',
        config_json JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS migration_intent_cards_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES migration_projects_v1(id) ON DELETE CASCADE,
        chain_id VARCHAR(255) NOT NULL,
        business_purpose TEXT NOT NULL,
        data_domain VARCHAR(100),
        grain VARCHAR(255),
        intent_json JSONB NOT NULL,
        confidence FLOAT,
        needs_human_review BOOLEAN DEFAULT FALSE,
        review_status VARCHAR(50) DEFAULT 'pending',
        reviewer_notes TEXT,
        reviewed_by VARCHAR(100),
        reviewed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(project_id, chain_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS migration_classifications_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        intent_card_id UUID REFERENCES migration_intent_cards_v1(id) ON DELETE CASCADE,
        project_id UUID REFERENCES migration_projects_v1(id) ON DELETE CASCADE,
        chain_id VARCHAR(255) NOT NULL,
        classification VARCHAR(50) NOT NULL,
        rationale TEXT NOT NULL,
        effort_category VARCHAR(50),
        classification_json JSONB NOT NULL,
        review_status VARCHAR(50) DEFAULT 'pending',
        reviewer_notes TEXT,
        reviewed_by VARCHAR(100),
        reviewed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS migration_target_views_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES migration_projects_v1(id) ON DELETE CASCADE,
        technical_name VARCHAR(255) NOT NULL,
        space VARCHAR(100) NOT NULL,
        layer VARCHAR(50) NOT NULL,
        semantic_usage VARCHAR(50),
        description TEXT,
        view_spec_json JSONB NOT NULL,
        generated_sql TEXT,
        source_chains JSONB,
        review_status VARCHAR(50) DEFAULT 'pending',
        reviewer_notes TEXT,
        reviewed_by VARCHAR(100),
        reviewed_at TIMESTAMPTZ,
        deployed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(project_id, technical_name)
    )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS migration_target_views_v1")
    op.execute("DROP TABLE IF EXISTS migration_classifications_v1")
    op.execute("DROP TABLE IF EXISTS migration_intent_cards_v1")
    op.execute("DROP TABLE IF EXISTS migration_projects_v1")
