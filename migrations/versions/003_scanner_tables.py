"""Scanner base tables.

Revision ID: 003
Revises: 002
Create Date: 2026-04-14
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE IF NOT EXISTS scanned_objects_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        scan_id VARCHAR(255) NOT NULL,
        object_id VARCHAR(255) NOT NULL,
        object_type VARCHAR(50) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT DEFAULT '',
        package VARCHAR(255) DEFAULT '',
        owner VARCHAR(255) DEFAULT '',
        source_system VARCHAR(255) DEFAULT '',
        technical_name VARCHAR(255) DEFAULT '',
        layer VARCHAR(100) DEFAULT '',
        source_code TEXT DEFAULT '',
        metadata JSONB DEFAULT '{}',
        content_hash VARCHAR(64),
        scanned_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(scan_id, object_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS dependencies_v1 (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        scan_id VARCHAR(255) NOT NULL,
        source_id VARCHAR(255) NOT NULL,
        target_id VARCHAR(255) NOT NULL,
        dependency_type VARCHAR(50) NOT NULL,
        metadata JSONB DEFAULT '{}'
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_scanned_objects_scan_id ON scanned_objects_v1(scan_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_scanned_objects_type ON scanned_objects_v1(object_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_scan_id ON dependencies_v1(scan_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_source ON dependencies_v1(source_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_target ON dependencies_v1(target_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_dependencies_target")
    op.execute("DROP INDEX IF EXISTS idx_dependencies_source")
    op.execute("DROP INDEX IF EXISTS idx_dependencies_scan_id")
    op.execute("DROP INDEX IF EXISTS idx_scanned_objects_type")
    op.execute("DROP INDEX IF EXISTS idx_scanned_objects_scan_id")
    op.execute("DROP TABLE IF EXISTS dependencies_v1")
    op.execute("DROP TABLE IF EXISTS scanned_objects_v1")
