"""Intelligence Core additions for Session 2.

Adds indexes for semantic search, incremental scanning, and design-system
queries. All DDL uses IF NOT EXISTS / IF EXISTS so re-running is safe.

Note on the embedding index: HNSW is preferred over IVFFlat for datasets
below ~10k rows because IVFFlat requires a training pass over existing data
and silently produces a near-useless index on empty tables. HNSW builds
incrementally and works correctly at any cardinality.

Revision ID: 005
Revises: 004
Create Date: 2026-04-15
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- knowledge_items ------------------------------------------------
    # Category index for naming-rule lookups (GET /knowledge?category=naming).
    op.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_items(category)")

    # Vector similarity index for semantic search.
    # Using HNSW (not IVFFlat) — works on empty tables and small datasets.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_embedding ON knowledge_items USING hnsw (embedding vector_cosine_ops)"
    )

    # ---- landscape_objects ----------------------------------------------
    op.execute("CREATE INDEX IF NOT EXISTS idx_landscape_platform ON landscape_objects(platform)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_landscape_type ON landscape_objects(object_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_landscape_name ON landscape_objects(object_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_landscape_scanned ON landscape_objects(last_scanned)")

    # content_hash for incremental scanning — skip unchanged objects.
    op.execute("ALTER TABLE landscape_objects ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")

    # ---- design_tokens --------------------------------------------------
    op.execute("CREATE INDEX IF NOT EXISTS idx_design_tokens_customer ON design_tokens(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_design_tokens_type ON design_tokens(token_type)")

    # ---- layout_archetypes ----------------------------------------------
    op.execute("CREATE INDEX IF NOT EXISTS idx_archetypes_customer ON layout_archetypes(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_archetypes_type ON layout_archetypes(archetype_type)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_knowledge_category")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_embedding")
    op.execute("DROP INDEX IF EXISTS idx_landscape_platform")
    op.execute("DROP INDEX IF EXISTS idx_landscape_type")
    op.execute("DROP INDEX IF EXISTS idx_landscape_name")
    op.execute("DROP INDEX IF EXISTS idx_landscape_scanned")
    op.execute("ALTER TABLE landscape_objects DROP COLUMN IF EXISTS content_hash")
    op.execute("DROP INDEX IF EXISTS idx_design_tokens_customer")
    op.execute("DROP INDEX IF EXISTS idx_design_tokens_type")
    op.execute("DROP INDEX IF EXISTS idx_archetypes_customer")
    op.execute("DROP INDEX IF EXISTS idx_archetypes_type")
