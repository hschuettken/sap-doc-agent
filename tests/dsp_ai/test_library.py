"""Unit tests for library.py — schema validation (no DB required for pure tests)."""

from __future__ import annotations

import json

import pytest

from spec2sphere.dsp_ai.library import LIBRARY_VERSION, export_library, import_library


def _valid_bundle(n: int = 2) -> dict:
    """Build a minimal valid library bundle with *n* enhancements."""
    enhancements = [
        {
            "name": f"Test Enhancement {i}",
            "kind": "narrative",
            "version": 1,
            "status": "draft",
            "config": {
                "name": f"Test Enhancement {i}",
                "kind": "narrative",
                "mode": "batch",
                "bindings": {"data": {"dsp_query": "SELECT 1", "parameters": {}}},
                "adaptive_rules": {
                    "per_user": False,
                    "per_time": False,
                    "per_delta": False,
                    "delta_lookback_seconds": 86400,
                },
                "prompt_template": "Say hello",
                "render_hint": "narrative_text",
                "ttl_seconds": 600,
            },
        }
        for i in range(n)
    ]
    return {"version": LIBRARY_VERSION, "enhancements": enhancements}


class TestImportLibraryValidation:
    """Pure validation tests — no database connection required."""

    @pytest.mark.asyncio
    async def test_wrong_version_raises(self):
        blob = {"version": "99.0", "enhancements": []}
        with pytest.raises(ValueError, match="unsupported library version"):
            await import_library(blob, "test-cust")

    @pytest.mark.asyncio
    async def test_missing_enhancements_key_raises(self):
        blob = {"version": LIBRARY_VERSION}
        with pytest.raises(ValueError, match="enhancements must be a list"):
            await import_library(blob, "test-cust")

    @pytest.mark.asyncio
    async def test_invalid_config_raises(self):
        blob = {
            "version": LIBRARY_VERSION,
            "enhancements": [
                {
                    "name": "bad",
                    "kind": "narrative",
                    "version": 1,
                    "status": "draft",
                    "config": {"name": "bad"},  # missing required fields
                }
            ],
        }
        with pytest.raises(ValueError, match="invalid config"):
            await import_library(blob, "test-cust")

    @pytest.mark.asyncio
    async def test_unknown_mode_raises(self):
        blob = _valid_bundle(1)
        with pytest.raises((ValueError, Exception)):
            await import_library(blob, "test-cust", mode="nonexistent_mode")


class TestExportBundle:
    """Test the CPG/Retail export bundle is well-formed."""

    def test_cpg_export_bundle_valid(self, tmp_path):
        import glob
        from pathlib import Path

        repo_root = Path(__file__).parent.parent.parent
        export_path = repo_root / "libraries" / "cpg_retail" / "export.json"

        if not export_path.exists():
            pytest.skip("CPG/Retail export.json not found")

        with open(export_path) as fh:
            blob = json.load(fh)

        assert blob["version"] == LIBRARY_VERSION
        assert isinstance(blob["enhancements"], list)
        assert len(blob["enhancements"]) == 8

        for e in blob["enhancements"]:
            assert "name" in e
            assert "kind" in e
            assert "config" in e
            assert isinstance(e["config"], dict)

    def test_cpg_individual_files_count(self):
        import glob
        from pathlib import Path

        repo_root = Path(__file__).parent.parent.parent
        files = glob.glob(str(repo_root / "libraries" / "cpg_retail" / "0*.json"))
        assert len(files) == 8, f"Expected 8 CPG templates, found {len(files)}"

    def test_cpg_templates_have_required_keys(self):
        import glob
        from pathlib import Path

        repo_root = Path(__file__).parent.parent.parent
        for fpath in sorted(glob.glob(str(repo_root / "libraries" / "cpg_retail" / "0*.json"))):
            with open(fpath) as fh:
                data = json.load(fh)
            assert "name" in data, f"{fpath}: missing name"
            assert "kind" in data, f"{fpath}: missing kind"
            assert "render_hint" in data, f"{fpath}: missing render_hint"
            assert "bindings" in data, f"{fpath}: missing bindings"
            assert "prompt_template" in data, f"{fpath}: missing prompt_template"
