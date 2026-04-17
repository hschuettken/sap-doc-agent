"""Allow non-engine LLM calls to log into dsp_ai.generations.

Session B Task 13: Every LLM call across the ecosystem (agents, migration,
standards, knowledge) logs via ObservedLLMProvider. Those calls have no
enhancement_id — relax the FK, add a ``caller`` column to identify the
origin, and index it for the Generation Log filter.
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE dsp_ai.generations ALTER COLUMN enhancement_id DROP NOT NULL")
    op.execute("ALTER TABLE dsp_ai.generations ADD COLUMN IF NOT EXISTS caller TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_generations_caller ON dsp_ai.generations(caller) WHERE caller IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS dsp_ai.idx_generations_caller")
    op.execute("ALTER TABLE dsp_ai.generations DROP COLUMN IF EXISTS caller")
    # Fill NULL enhancement_ids before re-applying NOT NULL
    op.execute("UPDATE dsp_ai.generations SET enhancement_id = gen_random_uuid() WHERE enhancement_id IS NULL")
    op.execute("ALTER TABLE dsp_ai.generations ALTER COLUMN enhancement_id SET NOT NULL")
