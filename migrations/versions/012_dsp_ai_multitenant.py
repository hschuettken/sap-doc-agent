"""Multi-tenant isolation for dsp_ai.* — customer column + RLS.

Adds ``customer TEXT NOT NULL DEFAULT 'default'`` plus an index and
an RLS policy on every dsp_ai.* table. Queries must set
``dspai.customer`` via ``set_config()`` before touching any dsp_ai
table or the policy silently returns zero rows.

Revision ID: 012
Revises: 011
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None

_TABLES = (
    "enhancements",
    "briefings",
    "rankings",
    "item_enhancements",
    "user_state",
    "generations",
    "studio_audit",
)


def upgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"ALTER TABLE dsp_ai.{tbl} ADD COLUMN IF NOT EXISTS customer TEXT NOT NULL DEFAULT 'default'")
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_customer ON dsp_ai.{tbl}(customer)")
        op.execute(f"ALTER TABLE dsp_ai.{tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {tbl}_customer_isolation ON dsp_ai.{tbl}
                USING (customer = current_setting('dspai.customer', true))
                WITH CHECK (customer = current_setting('dspai.customer', true))
            """
        )


def downgrade() -> None:
    for tbl in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {tbl}_customer_isolation ON dsp_ai.{tbl}")
        op.execute(f"ALTER TABLE dsp_ai.{tbl} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP INDEX IF EXISTS dsp_ai.idx_{tbl}_customer")
        op.execute(f"ALTER TABLE dsp_ai.{tbl} DROP COLUMN IF EXISTS customer")
