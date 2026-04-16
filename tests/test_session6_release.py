"""Tests for release package assembler (Session 6, Task 3)."""

from __future__ import annotations

import json
import uuid
import zipfile
from io import BytesIO

import pytest

from spec2sphere.governance.release import ReleaseManifest, assemble_release_package


@pytest.fixture
def sample_project_data() -> dict:
    """Sample project data for release testing.

    Contains:
      - project: name "Sales Planning"
      - customer: name "Acme Corp"
      - 1 requirement
      - 1 HLA
      - 1 tech spec
      - 1 architecture decision
      - 1 reconciliation result (pass)
      - 1 technical object with generated_artifact "SELECT 1"
      - 1 approval
    """
    project_id = uuid.uuid4()
    requirement_id = uuid.uuid4()
    hla_id = uuid.uuid4()
    tech_spec_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    object_id = uuid.uuid4()
    approval_id = uuid.uuid4()

    return {
        "project": {
            "id": str(project_id),
            "name": "Sales Planning",
            "description": "Sales planning and forecasting system",
            "customer_id": "cust-001",
        },
        "customer": {
            "id": "cust-001",
            "name": "Acme Corp",
        },
        "requirements": [
            {
                "id": str(requirement_id),
                "project_id": str(project_id),
                "name": "Sales Forecasting",
                "status": "approved",
            }
        ],
        "hla_documents": [
            {
                "id": str(hla_id),
                "project_id": str(project_id),
                "name": "Sales Architecture",
                "status": "approved",
            }
        ],
        "tech_specs": [
            {
                "id": str(tech_spec_id),
                "project_id": str(project_id),
                "name": "Sales Views",
                "status": "approved",
            }
        ],
        "architecture_decisions": [
            {
                "id": str(decision_id),
                "project_id": str(project_id),
                "title": "Use Dimension Tables for Hierarchies",
                "status": "approved",
            }
        ],
        "technical_objects": [
            {
                "id": str(object_id),
                "name": "LT_Sales",
                "object_type": "view",
                "generated_artifact": "SELECT 1",
            }
        ],
        "reconciliation_results": [
            {
                "test_key": "revenue_total",
                "delta_status": "pass",
                "delta_value": 0.0,
                "tolerance": 0,
            }
        ],
        "approvals": [
            {
                "id": str(approval_id),
                "artifact_type": "tech_spec",
                "artifact_id": str(tech_spec_id),
                "approved_by": "user@example.com",
                "approved_at": "2026-04-16T10:00:00Z",
            }
        ],
    }


def test_release_manifest_from_project_data(sample_project_data):
    """Test that ReleaseManifest.from_project_data returns correct counts and metadata."""
    manifest = ReleaseManifest.from_project_data(sample_project_data, version="1.0.0")

    assert manifest.version == "1.0.0"
    assert manifest.project_name == "Sales Planning"
    assert manifest.customer_name == "Acme Corp"
    assert manifest.object_count == 1
    assert manifest.approval_count == 1
    assert manifest.test_count == 1
    assert manifest.test_pass_count == 1
    assert manifest.generated_at is not None


def test_assemble_release_package_produces_zip(sample_project_data):
    """Test that assemble_release_package returns bytes and creates valid ZIP."""
    result = assemble_release_package(sample_project_data, version="1.0.0")

    # Verify it's bytes
    assert isinstance(result, bytes)
    assert len(result) > 0

    # Verify it's a valid ZIP
    with zipfile.ZipFile(BytesIO(result), "r") as zf:
        namelist = zf.namelist()

        # Check for expected files
        assert "manifest.json" in namelist
        assert "docs/technical.html" in namelist
        assert "docs/technical.md" in namelist
        assert "docs/functional.md" in namelist
        assert "reconciliation/summary.json" in namelist
        assert "decisions/decision_log.json" in namelist
        assert "approvals/approvals.json" in namelist
        assert "artifacts/LT_Sales.sql" in namelist


def test_assemble_release_package_manifest_content(sample_project_data):
    """Test that manifest.json inside ZIP has correct version and project_name."""
    result = assemble_release_package(sample_project_data, version="2.0.0")

    with zipfile.ZipFile(BytesIO(result), "r") as zf:
        manifest_json = zf.read("manifest.json").decode("utf-8")
        manifest_data = json.loads(manifest_json)

        assert manifest_data["version"] == "2.0.0"
        assert manifest_data["project_name"] == "Sales Planning"
        assert manifest_data["customer_name"] == "Acme Corp"
        assert manifest_data["object_count"] == 1
        assert manifest_data["approval_count"] == 1
        assert "files" in manifest_data
        assert len(manifest_data["files"]) > 0
