"""Object fields, transformation rules, version history, and scan runs.

Adds structured field-level metadata for all scanned objects (DSP views,
BW ADSOs, InfoObjects, transformations, etc.), a transformation rule table
for BW/DSP field mappings, full version history with snapshots, and scan
run tracking for time-travel capability.

Revision ID: 009
Revises: 008
Create Date: 2026-04-17
"""

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- ================================================================
    -- Scan runs — tracks each scan execution (version anchor)
    -- ================================================================
    CREATE TABLE IF NOT EXISTS scan_runs (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id     UUID REFERENCES customers(id),
        project_id      UUID REFERENCES projects(id),
        scanner_type    TEXT NOT NULL,
        scan_config     JSONB DEFAULT '{}',
        status          TEXT DEFAULT 'running',
        started_at      TIMESTAMPTZ DEFAULT now(),
        completed_at    TIMESTAMPTZ,
        object_count    INT DEFAULT 0,
        field_count     INT DEFAULT 0,
        stats           JSONB DEFAULT '{}',
        change_summary  JSONB DEFAULT '{}',
        version_label   TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_scan_runs_customer_project
        ON scan_runs(customer_id, project_id);
    CREATE INDEX IF NOT EXISTS idx_scan_runs_started
        ON scan_runs(started_at DESC);

    -- ================================================================
    -- Object fields — structured field-level metadata
    -- ================================================================
    CREATE TABLE IF NOT EXISTS object_fields (
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        landscape_object_id  UUID NOT NULL REFERENCES landscape_objects(id) ON DELETE CASCADE,
        scan_run_id          UUID REFERENCES scan_runs(id),
        field_name           TEXT NOT NULL,
        field_ordinal        INT,
        data_type            TEXT,
        field_length         INT,
        field_decimals       INT,
        expression           TEXT,
        source_object        TEXT,
        source_field         TEXT,
        is_key               BOOLEAN DEFAULT FALSE,
        is_calculated        BOOLEAN DEFAULT FALSE,
        is_aggregated        BOOLEAN DEFAULT FALSE,
        aggregation_type     TEXT,
        field_role           TEXT,
        description          TEXT,
        metadata             JSONB DEFAULT '{}',
        content_hash         VARCHAR(64)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_object_fields_obj_name
        ON object_fields(landscape_object_id, field_name);
    CREATE INDEX IF NOT EXISTS idx_object_fields_name
        ON object_fields(field_name);
    CREATE INDEX IF NOT EXISTS idx_object_fields_source
        ON object_fields(source_object, source_field)
        WHERE source_object IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_object_fields_role
        ON object_fields(field_role)
        WHERE field_role IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_object_fields_scan_run
        ON object_fields(scan_run_id);

    -- ================================================================
    -- Transformation rules — field mappings in BW/DSP transformations
    -- ================================================================
    CREATE TABLE IF NOT EXISTS transformation_rules (
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        landscape_object_id  UUID NOT NULL REFERENCES landscape_objects(id) ON DELETE CASCADE,
        scan_run_id          UUID REFERENCES scan_runs(id),
        source_object        TEXT NOT NULL,
        target_object        TEXT NOT NULL,
        source_field         TEXT,
        target_field         TEXT NOT NULL,
        rule_type            TEXT,
        rule_expression      TEXT,
        routine_name         TEXT,
        routine_code         TEXT,
        metadata             JSONB DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_transrules_obj
        ON transformation_rules(landscape_object_id);
    CREATE INDEX IF NOT EXISTS idx_transrules_target_field
        ON transformation_rules(target_field);
    CREATE INDEX IF NOT EXISTS idx_transrules_source
        ON transformation_rules(source_object, source_field)
        WHERE source_field IS NOT NULL;

    -- ================================================================
    -- Object history — full version snapshots for time-travel
    -- ================================================================
    CREATE TABLE IF NOT EXISTS object_history (
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        landscape_object_id  UUID NOT NULL REFERENCES landscape_objects(id) ON DELETE CASCADE,
        scan_run_id          UUID REFERENCES scan_runs(id),
        version_number       INT NOT NULL,
        -- Object snapshot
        object_name          TEXT,
        technical_name       TEXT,
        object_type          TEXT,
        platform             TEXT,
        layer                TEXT,
        metadata             JSONB,
        documentation        TEXT,
        dependencies         JSONB,
        content_hash         VARCHAR(64),
        -- Fields snapshot (array of field dicts)
        fields_snapshot      JSONB DEFAULT '[]',
        -- Change tracking
        change_type          TEXT NOT NULL,
        changes              JSONB DEFAULT '{}',
        captured_at          TIMESTAMPTZ DEFAULT now()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_object_history_version
        ON object_history(landscape_object_id, version_number);
    CREATE INDEX IF NOT EXISTS idx_object_history_captured
        ON object_history(captured_at DESC);
    CREATE INDEX IF NOT EXISTS idx_object_history_change_type
        ON object_history(change_type);

    -- ================================================================
    -- Extend landscape_objects with version tracking columns
    -- ================================================================
    ALTER TABLE landscape_objects
        ADD COLUMN IF NOT EXISTS version_number INT DEFAULT 1;
    ALTER TABLE landscape_objects
        ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;
    ALTER TABLE landscape_objects
        ADD COLUMN IF NOT EXISTS last_scan_run_id UUID;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE landscape_objects DROP COLUMN IF EXISTS last_scan_run_id;
    ALTER TABLE landscape_objects DROP COLUMN IF EXISTS first_seen_at;
    ALTER TABLE landscape_objects DROP COLUMN IF EXISTS version_number;
    DROP TABLE IF EXISTS object_history;
    DROP TABLE IF EXISTS transformation_rules;
    DROP TABLE IF EXISTS object_fields;
    DROP TABLE IF EXISTS scan_runs;
    """)
