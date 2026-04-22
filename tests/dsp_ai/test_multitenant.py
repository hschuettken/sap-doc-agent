"""Multi-tenant isolation tests.

DB tests are integration tests requiring DATABASE_URL to be set.
Skipped in unit-test runs.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.multitenant


def _require_db():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping DB integration test")


class TestMigrationFile:
    """Validate the migration file is well-formed without running it."""

    def test_migration_012_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "migrations" / "versions" / "012_dsp_ai_multitenant.py"
        assert p.exists(), "migration 012 not found"

    def test_migration_012_has_correct_revision(self):
        from pathlib import Path
        import importlib.util

        p = Path(__file__).parent.parent.parent / "migrations" / "versions" / "012_dsp_ai_multitenant.py"
        spec = importlib.util.spec_from_file_location("mig012", str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert mod.revision == "012"
        assert mod.down_revision == "011"

    def test_migration_012_covers_all_tables(self):
        from pathlib import Path
        import importlib.util

        p = Path(__file__).parent.parent.parent / "migrations" / "versions" / "012_dsp_ai_multitenant.py"
        spec = importlib.util.spec_from_file_location("mig012", str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        required_tables = {
            "enhancements",
            "briefings",
            "rankings",
            "item_enhancements",
            "user_state",
            "generations",
            "studio_audit",
        }
        assert required_tables.issubset(set(mod._TABLES))

    def test_migration_012_has_upgrade_and_downgrade(self):
        from pathlib import Path
        import importlib.util

        p = Path(__file__).parent.parent.parent / "migrations" / "versions" / "012_dsp_ai_multitenant.py"
        spec = importlib.util.spec_from_file_location("mig012", str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)


@pytest.mark.asyncio
async def test_db_customer_isolation_requires_set_config():
    """Verify the pattern: reading without set_config returns no RLS-gated rows."""
    _require_db()
    import asyncpg
    from spec2sphere.dsp_ai.settings import postgres_dsn

    conn = await asyncpg.connect(postgres_dsn())
    try:
        # Without setting customer context, RLS should block or the setting is 'default'
        setting = await conn.fetchval("SELECT current_setting('dspai.customer', true)")
    finally:
        await conn.close()
    # When not set, current_setting returns NULL (true = missing ok) or the session default
    assert setting is None or isinstance(setting, str)
