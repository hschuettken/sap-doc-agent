"""Multi-tenant isolation: customer column + Row-Level Security.

Revision ID: 012
Revises: 011
Create Date: 2026-04-22

Adds a ``customer TEXT NOT NULL DEFAULT 'default'`` column to every dsp_ai.*
table, creates an index per table, enables RLS, and installs a policy that
restricts each session to rows where ``customer = current_setting('dspai.customer', true)``.

Connection helper usage (engine.py / library.py):
    await conn.execute("SELECT set_config('dspai.customer', $1, false)", customer)
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None

_TABLES = [
    "enhancements",
    "briefings",
    "rankings",
    "item_enhancements",
    "user_state",
    "generations",
    "studio_audit",
]


def upgrade() -> None:
    for tbl in _TABLES:
        op.execute(
            f"ALTER TABLE dsp_ai.{tbl} "
            f"ADD COLUMN IF NOT EXISTS customer TEXT NOT NULL DEFAULT 'default'"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{tbl}_customer ON dsp_ai.{tbl}(customer)"
        )
        op.execute(f"ALTER TABLE dsp_ai.{tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"DROP POLICY IF EXISTS {tbl}_customer_isolation ON dsp_ai.{tbl}"
        )
        op.execute(
            f"""
            CREATE POLICY {tbl}_customer_isolation ON dsp_ai.{tbl}
                USING (customer = current_setting('dspai.customer', true))
                WITH CHECK (customer = current_setting('dspai.customer', true))
            """
        )


def downgrade() -> None:
    for tbl in _TABLES:
        op.execute(
            f"DROP POLICY IF EXISTS {tbl}_customer_isolation ON dsp_ai.{tbl}"
        )
        op.execute(f"ALTER TABLE dsp_ai.{tbl} DISABLE ROW LEVEL SECURITY")
        op.execute(
            f"ALTER TABLE dsp_ai.{tbl} DROP COLUMN IF EXISTS customer"
        )
