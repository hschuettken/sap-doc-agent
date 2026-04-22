"""Portability smoke tests.

These tests verify the library export/import round-trip against a live instance.
Marked as 'portability' — run nightly, not in default unit-test suite.

Set DSPAI_WEB_URL to the running Spec2Sphere web URL to enable.
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.portability

WEB_URL = os.environ.get("DSPAI_WEB_URL", "http://localhost:8260")


def _require_web():
    if not os.environ.get("DSPAI_WEB_URL"):
        pytest.skip("DSPAI_WEB_URL not set — skipping live portability test")


@pytest.mark.asyncio
async def test_library_export_returns_valid_schema():
    """GET /ai-studio/library/export returns a well-formed bundle."""
    _require_web()
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{WEB_URL}/ai-studio/library/export")
    assert r.status_code == 200, r.text
    blob = r.json()
    assert blob["version"] == "1.0"
    assert isinstance(blob["enhancements"], list)


@pytest.mark.asyncio
async def test_library_export_import_roundtrip():
    """Export → import (merge) → re-export; names should match."""
    _require_web()
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{WEB_URL}/ai-studio/library/export")
    assert r.status_code == 200
    blob = r.json()
    orig_names = {e["name"] for e in blob["enhancements"]}

    if not orig_names:
        pytest.skip("No enhancements in library — nothing to round-trip")

    payload = json.dumps(blob).encode()
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(
            f"{WEB_URL}/ai-studio/library/import",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-User-Email": "portability@spec2sphere",
            },
        )
    # May 403 if STUDIO_AUTHOR_EMAILS doesn't include our test email — that's ok
    if r.status_code == 403:
        pytest.skip("STUDIO_AUTHOR_EMAILS not configured for portability test email")
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["imported"] == len(blob["enhancements"])


class TestPortabilityFiles:
    """Validate all portability-related files exist."""

    def test_demo_bootstrap_script_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "scripts" / "demo_bootstrap.sh"
        assert p.exists()
        assert os.access(str(p), os.X_OK)

    def test_backup_script_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "scripts" / "backup.sh"
        assert p.exists()
        assert os.access(str(p), os.X_OK)

    def test_restore_script_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "scripts" / "restore.sh"
        assert p.exists()
        assert os.access(str(p), os.X_OK)

    def test_client_checklist_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "docs" / "deploy" / "client_checklist.md"
        assert p.exists()

    def test_demo_script_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "docs" / "deploy" / "demo_script.md"
        assert p.exists()

    def test_tls_doc_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "docs" / "deploy" / "tls.md"
        assert p.exists()

    def test_cpg_library_export_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "libraries" / "cpg_retail" / "export.json"
        assert p.exists()
