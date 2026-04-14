"""Customer standards and tenant knowledge tables.

Revision ID: 001
Revises:
Create Date: 2026-04-14
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE IF NOT EXISTS customer_standards_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        uploaded_at TIMESTAMPTZ DEFAULT now(),
        status TEXT DEFAULT 'processing',
        parsed_rules JSONB,
        raw_text TEXT,
        error_message TEXT
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS customer_standard_files_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        standard_id UUID REFERENCES customer_standards_v1(id) ON DELETE CASCADE,
        file_data BYTEA NOT NULL,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size_bytes INT
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS tenant_knowledge_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        category TEXT NOT NULL,
        key TEXT NOT NULL,
        value JSONB NOT NULL,
        source TEXT NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE(category, key)
    )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS customer_standard_files_v1")
    op.execute("DROP TABLE IF EXISTS customer_standards_v1")
    op.execute("DROP TABLE IF EXISTS tenant_knowledge_v1")
