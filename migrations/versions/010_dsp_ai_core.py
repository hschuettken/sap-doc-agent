"""dsp_ai core tables — enhancements, generations, briefings, rankings, etc.

Adds the ``dsp_ai.*`` schema used by the new AI Studio + dsp-ai engine:
authoring (`enhancements`), provenance ledger (`generations`), write-back
content tables (`briefings`, `rankings`, `item_enhancements`), per-user
ambient state (`user_state`), and the authoring audit log (`studio_audit`).

Revision ID: 010
Revises: 009
Create Date: 2026-04-17
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS dsp_ai")
    op.execute("""
    CREATE TABLE dsp_ai.enhancements (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        version INT NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'draft',
        config JSONB NOT NULL,
        author TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (name, version)
    )
    """)
    op.execute("""
    CREATE TABLE dsp_ai.generations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        user_id TEXT,
        context_key TEXT,
        prompt_hash TEXT NOT NULL,
        input_ids JSONB NOT NULL,
        model TEXT NOT NULL,
        quality_level TEXT NOT NULL,
        latency_ms INT NOT NULL,
        tokens_in INT,
        tokens_out INT,
        cost_usd NUMERIC(10,6),
        cached BOOLEAN NOT NULL DEFAULT FALSE,
        quality_warnings JSONB,
        error_kind TEXT,
        preview BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX idx_generations_enhancement_time ON dsp_ai.generations (enhancement_id, created_at DESC)")
    op.execute("CREATE INDEX idx_generations_user_time ON dsp_ai.generations (user_id, created_at DESC)")

    op.execute("""
    CREATE TABLE dsp_ai.briefings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        user_id TEXT NOT NULL,
        context_key TEXT NOT NULL,
        generated_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ,
        narrative_text TEXT NOT NULL,
        key_points JSONB,
        suggested_actions JSONB,
        render_hint TEXT NOT NULL,
        generation_id UUID NOT NULL REFERENCES dsp_ai.generations(id),
        UNIQUE (enhancement_id, user_id, context_key)
    )
    """)

    op.execute("""
    CREATE TABLE dsp_ai.rankings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        user_id TEXT NOT NULL,
        context_key TEXT NOT NULL,
        item_id TEXT NOT NULL,
        rank INT NOT NULL,
        score FLOAT NOT NULL,
        reason TEXT,
        generated_at TIMESTAMPTZ NOT NULL,
        generation_id UUID NOT NULL REFERENCES dsp_ai.generations(id)
    )
    """)
    op.execute("CREATE INDEX idx_rankings_lookup ON dsp_ai.rankings (enhancement_id, user_id, context_key, rank)")

    op.execute("""
    CREATE TABLE dsp_ai.item_enhancements (
        object_type TEXT NOT NULL,
        object_id TEXT NOT NULL,
        user_id TEXT NOT NULL DEFAULT '_global',
        title_suggested TEXT,
        description_suggested TEXT,
        tags JSONB,
        kpi_suggestions JSONB,
        generated_at TIMESTAMPTZ NOT NULL,
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        generation_id UUID NOT NULL REFERENCES dsp_ai.generations(id),
        PRIMARY KEY (object_type, object_id, user_id)
    )
    """)

    op.execute("""
    CREATE TABLE dsp_ai.user_state (
        user_id TEXT PRIMARY KEY,
        last_visited_at TIMESTAMPTZ,
        last_briefed_at TIMESTAMPTZ,
        topics_of_interest JSONB,
        preferences JSONB,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)

    op.execute("""
    CREATE TABLE dsp_ai.studio_audit (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        action TEXT NOT NULL,
        enhancement_id UUID,
        author TEXT NOT NULL,
        before JSONB,
        after JSONB,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS dsp_ai CASCADE")
