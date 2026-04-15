"""Pipeline notifications table.

Adds the notifications table for in-app approval and pipeline event alerts,
plus performance indexes on the approvals table for artifact lookups.

Revision ID: 006
Revises: 005
Create Date: 2026-04-15
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        user_id UUID NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        link TEXT,
        notification_type TEXT DEFAULT 'info',
        is_read BOOLEAN DEFAULT false,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # Index for per-user notification listing (unread badge + full list)
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)")
    # Partial index for fast unread-count queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, is_read) WHERE NOT is_read"
    )
    # Index for chronological ordering and cleanup tasks
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)")

    # Approvals: fast lookup by artifact (used in get_approval_for_artifact)
    op.execute("CREATE INDEX IF NOT EXISTS idx_approvals_artifact ON approvals(artifact_type, artifact_id)")
    # Approvals: fast listing by project (used in list_approvals)
    op.execute("CREATE INDEX IF NOT EXISTS idx_approvals_project ON approvals(project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_approvals_artifact")
    op.execute("DROP INDEX IF EXISTS idx_approvals_project")
