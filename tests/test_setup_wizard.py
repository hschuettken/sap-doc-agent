"""Tests for the first-run setup wizard.

Three behavioural contract groups:

A. Marker ABSENT  — all non-exempt UI requests redirect to /ui/setup/welcome;
                    wizard routes themselves are reachable without auth.
B. Wizard flow    — each step is navigable; completing /ui/setup/done writes the marker.
C. Marker PRESENT — wizard routes return 404; app behaves exactly as before setup.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def output_dir(tmp_path):
    """Minimal output directory (same as test_web_server.py)."""
    import json

    graph = {
        "nodes": [{"id": "OBJ1", "name": "OBJ1", "type": "view", "layer": "harmonized", "source_system": "DSP"}],
        "edges": [],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "objects" / "view").mkdir(parents=True)
    (tmp_path / "objects" / "view" / "OBJ1.md").write_text("---\nobject_id: OBJ1\n---\n# OBJ1\nA view.")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "summary.md").write_text("# Quality Summary\nScore: 80%")
    return tmp_path


@pytest.fixture()
def marker_path(tmp_path):
    """Path for the setup marker inside tmp_path."""
    return tmp_path / "setup.complete"


@pytest.fixture()
def client_no_marker(output_dir, marker_path, monkeypatch):
    """App client where setup.complete does NOT exist (wizard enabled + no marker)."""
    monkeypatch.setenv("SETUP_WIZARD_ENABLED", "true")
    monkeypatch.setenv("SETUP_MARKER", str(marker_path))
    # Ensure the marker doesn't exist
    marker_path.unlink(missing_ok=True)

    from spec2sphere.web.server import create_app

    app = create_app(output_dir=str(output_dir))
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def client_with_marker(output_dir, marker_path, monkeypatch):
    """App client where setup.complete DOES exist (wizard enabled + marker present)."""
    monkeypatch.setenv("SETUP_WIZARD_ENABLED", "true")
    monkeypatch.setenv("SETUP_MARKER", str(marker_path))
    marker_path.touch()

    from spec2sphere.web.server import create_app

    app = create_app(output_dir=str(output_dir))
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# A. Marker ABSENT — redirect behaviour
# ---------------------------------------------------------------------------


class TestRedirectWhenNoMarker:
    def test_root_redirects_to_wizard(self, client_no_marker):
        resp = client_no_marker.get("/")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/ui/setup/welcome"

    def test_ui_dashboard_redirects_to_wizard(self, client_no_marker):
        resp = client_no_marker.get("/ui/dashboard")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/ui/setup/welcome"

    def test_arbitrary_ui_path_redirects(self, client_no_marker):
        resp = client_no_marker.get("/ui/scanner")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/ui/setup/welcome"

    def test_health_not_redirected(self, client_no_marker):
        resp = client_no_marker.get("/health")
        assert resp.status_code == 200

    def test_healthz_not_redirected(self, client_no_marker):
        resp = client_no_marker.get("/healthz")
        assert resp.status_code == 200

    def test_api_not_redirected(self, client_no_marker):
        resp = client_no_marker.get("/api/objects")
        # 200 or 404 — but NOT 302
        assert resp.status_code != 302

    def test_static_not_redirected(self, client_no_marker):
        # Static files may 404 if no files exist, but must not redirect.
        resp = client_no_marker.get("/static/style.css")
        assert resp.status_code != 302

    def test_wizard_welcome_accessible(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/welcome")
        assert resp.status_code == 200
        assert "Spec2Sphere" in resp.text

    def test_wizard_admin_accessible(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/admin")
        assert resp.status_code == 200

    def test_wizard_db_accessible(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/db")
        assert resp.status_code == 200

    def test_wizard_llm_accessible(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/llm")
        assert resp.status_code == 200

    def test_wizard_privacy_accessible(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/privacy")
        assert resp.status_code == 200

    def test_wizard_sap_accessible(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/sap")
        assert resp.status_code == 200

    def test_wizard_done_accessible(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/done")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# B. Wizard flow — step navigation and marker creation
# ---------------------------------------------------------------------------


class TestWizardFlow:
    def test_welcome_has_get_started_link(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/welcome")
        assert "Get Started" in resp.text or "/ui/setup/admin" in resp.text

    def test_admin_post_short_password_redirects_with_error(self, client_no_marker):
        resp = client_no_marker.post("/ui/setup/admin", data={"password": "abc", "confirm": "abc"})
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_admin_post_mismatch_redirects_with_error(self, client_no_marker):
        resp = client_no_marker.post("/ui/setup/admin", data={"password": "secret123", "confirm": "different"})
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_admin_post_valid_advances_to_db(self, client_no_marker):
        resp = client_no_marker.post("/ui/setup/admin", data={"password": "secret123", "confirm": "secret123"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup/db"

    def test_admin_post_valid_sets_env_var(self, client_no_marker):
        client_no_marker.post("/ui/setup/admin", data={"password": "newpass99", "confirm": "newpass99"})
        assert "SAP_DOC_AGENT_UI_PASSWORD_HASH" in os.environ

    def test_db_post_next_advances_to_llm(self, client_no_marker):
        resp = client_no_marker.post("/ui/setup/db", data={"db_url": "", "action": "next"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup/llm"

    def test_llm_post_default_profile_advances(self, client_no_marker):
        resp = client_no_marker.post("/ui/setup/llm", data={"profile": "default"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup/privacy"

    def test_llm_post_all_claude_sets_env(self, client_no_marker):
        client_no_marker.post(
            "/ui/setup/llm",
            data={"profile": "all-claude", "anthropic_api_key": "sk-ant-test"},
        )
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-test"

    def test_privacy_post_advances(self, client_no_marker):
        resp = client_no_marker.post("/ui/setup/privacy", data={"local_only": "on"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup/sap"

    def test_sap_skip_advances_to_done(self, client_no_marker):
        resp = client_no_marker.post("/ui/setup/sap", data={"skip": "1"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup/done"

    def test_sap_post_with_values_advances_to_done(self, client_no_marker):
        resp = client_no_marker.post(
            "/ui/setup/sap",
            data={"dsp_url": "https://example.hcs.cloud.sap", "dsp_user": "user", "dsp_pass": "pass"},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/setup/done"

    def test_done_post_creates_marker(self, client_no_marker, marker_path):
        assert not marker_path.exists()
        resp = client_no_marker.post("/ui/setup/done")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/dashboard"
        # Marker must now exist (primary path or env-overridden fallback)
        assert marker_path.exists() or Path(os.environ.get("SETUP_MARKER", "")).exists()

    def test_progress_bar_renders(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/admin")
        # Step 2 of 7
        assert "2" in resp.text
        assert "7" in resp.text

    def test_step_labels_appear(self, client_no_marker):
        resp = client_no_marker.get("/ui/setup/db")
        assert "Database" in resp.text


# ---------------------------------------------------------------------------
# C. Marker PRESENT — wizard disabled, existing app unaffected
# ---------------------------------------------------------------------------


class TestWizardDisabledWhenMarkerExists:
    def test_welcome_returns_404(self, client_with_marker):
        resp = client_with_marker.get("/ui/setup/welcome")
        assert resp.status_code == 404

    def test_admin_returns_404(self, client_with_marker):
        resp = client_with_marker.get("/ui/setup/admin")
        assert resp.status_code == 404

    def test_db_returns_404(self, client_with_marker):
        resp = client_with_marker.get("/ui/setup/db")
        assert resp.status_code == 404

    def test_llm_returns_404(self, client_with_marker):
        resp = client_with_marker.get("/ui/setup/llm")
        assert resp.status_code == 404

    def test_privacy_returns_404(self, client_with_marker):
        resp = client_with_marker.get("/ui/setup/privacy")
        assert resp.status_code == 404

    def test_sap_returns_404(self, client_with_marker):
        resp = client_with_marker.get("/ui/setup/sap")
        assert resp.status_code == 404

    def test_done_returns_404(self, client_with_marker):
        resp = client_with_marker.get("/ui/setup/done")
        assert resp.status_code == 404

    def test_done_post_returns_404(self, client_with_marker):
        resp = client_with_marker.post("/ui/setup/done")
        assert resp.status_code == 404

    def test_health_still_works(self, client_with_marker):
        resp = client_with_marker.get("/health")
        assert resp.status_code == 200

    def test_api_objects_still_works(self, client_with_marker):
        resp = client_with_marker.get("/api/objects")
        assert resp.status_code == 200

    def test_no_redirect_loop_on_ui_dashboard(self, client_with_marker):
        # With marker present, /ui/dashboard should NOT redirect to /ui/setup/*
        resp = client_with_marker.get("/ui/dashboard")
        # AuthMiddleware will redirect to /ui/login (not wizard)
        assert "/ui/setup" not in resp.headers.get("location", "")
