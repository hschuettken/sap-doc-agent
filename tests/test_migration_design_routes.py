"""Tests for design + generate API and UI routes."""

import json

from fastapi.testclient import TestClient


def _get_client(output_dir="tests/fixtures/sample_bw_scan"):
    import os

    from sap_doc_agent.web.auth import hash_password
    from sap_doc_agent.web.server import create_app

    pw_hash = hash_password("testpass")
    os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = pw_hash
    os.environ["SAP_DOC_AGENT_SECRET_KEY"] = "test-secret"
    app = create_app(output_dir=output_dir)
    client = TestClient(app, follow_redirects=True)
    client.post("/ui/login", data={"password": "testpass"}, follow_redirects=False)
    return client


# --- API route tests ---


def test_api_target_views_empty():
    client = _get_client()
    resp = client.get("/api/migration/projects/fake-id/target-views")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_target_views_reads_files(tmp_path):
    """Target views endpoint falls back to reading _target.json files."""
    chains_dir = tmp_path / "chains"
    chains_dir.mkdir()
    target = {
        "technical_name": "02_RV_TEST",
        "space": "SAP_ADMIN",
        "layer": "harmonization",
        "semantic_usage": "relational_dataset",
        "description": "Test view",
    }
    (chains_dir / "c1_target.json").write_text(json.dumps([target]))

    client = _get_client(output_dir=str(tmp_path))
    resp = client.get("/api/migration/projects/fake-id/target-views")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


def test_api_generated_sql_empty():
    client = _get_client()
    resp = client.get("/api/migration/projects/fake-id/generated-sql")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_generated_sql_reads_files(tmp_path):
    chains_dir = tmp_path / "chains"
    chains_dir.mkdir()
    sql_data = {
        "technical_name": "02_RV_TEST",
        "space": "SAP_ADMIN",
        "layer": "harmonization",
        "sql": "SELECT 1",
        "needs_manual_edit": False,
    }
    (chains_dir / "c1_sql.json").write_text(json.dumps([sql_data]))

    client = _get_client(output_dir=str(tmp_path))
    resp = client.get("/api/migration/projects/fake-id/generated-sql")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["technical_name"] == "02_RV_TEST"


# --- UI route tests ---


def test_ui_migration_design_page():
    client = _get_client()
    resp = client.get("/ui/migration/design")
    assert resp.status_code == 200
    assert "Target Architecture" in resp.text


def test_ui_migration_generate_page():
    client = _get_client()
    resp = client.get("/ui/migration/generate")
    assert resp.status_code == 200
    assert "Generated SQL" in resp.text


# --- SQL validation endpoint ---


def test_api_validate_sql():
    client = _get_client()
    resp = client.post(
        "/api/migration/validate-sql",
        json={"sql": "SELECT 1 FROM my_table"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "is_valid" in data
    assert data["is_valid"] is True


def test_api_validate_sql_with_violations():
    client = _get_client()
    resp = client.post(
        "/api/migration/validate-sql",
        json={"sql": "WITH cte AS (SELECT 1) SELECT * FROM cte"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False
    assert len(data["violations"]) > 0


# --- Report route tests ---


def test_api_report_empty_project():
    client = _get_client()
    resp = client.get("/api/migration/projects/fake-id/report")
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" in resp.text
    assert "Migration Assessment Report" in resp.text


def test_api_report_with_chain_data(tmp_path):
    """Report endpoint loads chain + classified files and generates HTML."""
    chains_dir = tmp_path / "chains"
    chains_dir.mkdir()

    from sap_doc_agent.migration.models import ClassifiedChain, IntentCard, MigrationClassification
    from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType

    chain = DataFlowChain(
        chain_id="c1",
        name="Test Chain",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[ChainStep(position=1, object_id="TR1", object_type=ObjectType.TRANSFORMATION, name="Step 1")],
        all_object_ids=["S", "TR1", "T"],
    )
    (chains_dir / "c1.json").write_text(chain.model_dump_json(indent=2))

    classified = ClassifiedChain(
        chain_id="c1",
        intent_card=IntentCard(chain_id="c1", business_purpose="Test purpose"),
        classification=MigrationClassification.MIGRATE,
    )
    (chains_dir / "c1_classified.json").write_text(classified.model_dump_json(indent=2))

    client = _get_client(output_dir=str(tmp_path))
    resp = client.get("/api/migration/projects/fake-id/report")
    assert resp.status_code == 200
    assert "c1" in resp.text
    assert "Test purpose" in resp.text


def test_ui_migration_report_page():
    client = _get_client()
    resp = client.get("/ui/migration/report")
    assert resp.status_code == 200
    assert "Migration Report" in resp.text
