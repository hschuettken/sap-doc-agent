"""Tests for atlas design-system adoption in spec2sphere templates.

Verifies that:
- Key pages render with atlas component classes (not broken Tailwind/custom classes).
- The AppShell structure is present in every full-page response.
- Static CSS files are served and reference atlas token variables.
"""

import json
import pytest
from fastapi.testclient import TestClient
from spec2sphere.web.server import create_app

# Default secret key used when SAP_DOC_AGENT_SECRET_KEY is unset
_TEST_SECRET = "dev-secret-change-me"


def _make_session_cookie() -> str:
    """Create a valid signed session cookie for the test client."""
    from itsdangerous import URLSafeTimedSerializer

    s = URLSafeTimedSerializer(_TEST_SECRET)
    return s.dumps({"authenticated": True, "user": "admin"})


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def output_dir(tmp_path):
    graph = {
        "nodes": [
            {"id": "SPC.VIEW1", "name": "VIEW1", "type": "view", "layer": "harmonized", "source_system": "DSP"},
            {"id": "SPC.TBL1", "name": "TBL1", "type": "table", "layer": "raw", "source_system": "DSP"},
        ],
        "edges": [
            {"source": "SPC.VIEW1", "target": "SPC.TBL1", "type": "reads_from"},
        ],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))

    view_dir = tmp_path / "objects" / "view"
    view_dir.mkdir(parents=True)
    (view_dir / "SPC.VIEW1.md").write_text(
        "---\nobject_id: SPC.VIEW1\nname: VIEW1\n---\n# VIEW1\nA test view."
    )

    table_dir = tmp_path / "objects" / "table"
    table_dir.mkdir(parents=True)
    (table_dir / "SPC.TBL1.md").write_text(
        "---\nobject_id: SPC.TBL1\nname: TBL1\n---\n# TBL1\nA test table."
    )

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "summary.md").write_text("# Quality Summary\nScore: 82%")

    return tmp_path


@pytest.fixture
def client(output_dir, monkeypatch):
    marker = output_dir / "setup.complete"
    marker.touch()
    monkeypatch.setenv("SETUP_MARKER", str(marker))
    monkeypatch.setenv("SAP_DOC_AGENT_SECRET_KEY", _TEST_SECRET)
    app = create_app(output_dir=str(output_dir))
    session_cookie = _make_session_cookie()
    return TestClient(app, cookies={"session": session_cookie})


# ── AppShell structure ────────────────────────────────────────────────────────


def test_base_has_appshell(client):
    """Every full-page response must embed the atlas AppShell grid."""
    resp = client.get("/ui/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert 'class="atlas-appshell"' in html or "atlas-appshell" in html
    assert "atlas-appshell-sidebar" in html
    assert "atlas-appshell-header" in html
    assert "atlas-appshell-content" in html


def test_base_loads_atlas_css(client):
    """Base template must link atlas-tokens.css and atlas-ui.css."""
    resp = client.get("/ui/dashboard")
    html = resp.text
    assert "atlas-tokens.css" in html
    assert "atlas-ui.css" in html


def test_base_has_htmx(client):
    """HTMX script tag must be present in every full page."""
    resp = client.get("/ui/dashboard")
    assert "htmx" in resp.text.lower()


# ── Dashboard template ────────────────────────────────────────────────────────


def test_dashboard_uses_atlas_card(client):
    resp = client.get("/ui/dashboard")
    assert resp.status_code == 200
    html = resp.text
    # After migration the KPI cards should use atlas-card, not bare 'card' div
    assert "atlas-card" in html


def test_dashboard_uses_atlas_kpi(client):
    resp = client.get("/ui/dashboard")
    html = resp.text
    # KPI label / value classes from atlas-ui.css
    assert "atlas-kpi" in html


def test_dashboard_uses_atlas_btn(client):
    resp = client.get("/ui/dashboard")
    html = resp.text
    assert "atlas-btn" in html


def test_dashboard_uses_atlas_badge(client):
    resp = client.get("/ui/dashboard")
    html = resp.text
    # Type-count badges should use atlas-badge variants
    assert "atlas-badge" in html


def test_dashboard_no_raw_tailwind_colors(client):
    """The migrated dashboard must not reference broken Tailwind color utilities."""
    resp = client.get("/ui/dashboard")
    html = resp.text
    # These raw Tailwind classes must not appear as HTML class values in the migrated page
    assert 'class="text-[#1a2332]' not in html
    assert "bg-petrol " not in html
    assert "text-petrol " not in html


# ── Scanner template ──────────────────────────────────────────────────────────


def test_scanner_uses_atlas_card(client):
    resp = client.get("/ui/scanner")
    assert resp.status_code == 200
    assert "atlas-card" in resp.text


def test_scanner_uses_atlas_dot(client):
    resp = client.get("/ui/scanner")
    assert "atlas-dot" in resp.text


def test_scanner_uses_atlas_pre(client):
    resp = client.get("/ui/scanner")
    assert "atlas-pre" in resp.text


def test_scanner_uses_atlas_btn(client):
    resp = client.get("/ui/scanner")
    assert "atlas-btn--primary" in resp.text


# ── Objects template ──────────────────────────────────────────────────────────


def test_objects_uses_atlas_table(client):
    resp = client.get("/ui/objects")
    assert resp.status_code == 200
    assert "atlas-table" in resp.text


def test_objects_uses_atlas_input(client):
    resp = client.get("/ui/objects")
    assert "atlas-input" in resp.text


def test_objects_uses_atlas_select(client):
    resp = client.get("/ui/objects")
    assert "atlas-select" in resp.text


def test_objects_uses_atlas_badge_for_type(client):
    resp = client.get("/ui/objects")
    assert "atlas-badge" in resp.text


# ── CSS files ─────────────────────────────────────────────────────────────────


def test_atlas_tokens_css_served(client):
    resp = client.get("/static/atlas-tokens.css")
    assert resp.status_code == 200
    assert "--atlas-color-primary" in resp.text
    assert "--atlas-color-bg" in resp.text


def test_atlas_ui_css_served(client):
    resp = client.get("/static/atlas-ui.css")
    assert resp.status_code == 200
    assert ".atlas-appshell" in resp.text
    assert ".atlas-card" in resp.text
    assert ".atlas-btn" in resp.text


def test_atlas_ui_css_has_new_primitives(client):
    """atlas-ui.css must include the new form + tab + utility primitives."""
    resp = client.get("/static/atlas-ui.css")
    css = resp.text
    assert ".atlas-input" in css
    assert ".atlas-select" in css
    assert ".atlas-tab" in css
    assert ".atlas-pre" in css
    assert ".atlas-empty" in css
    assert ".atlas-kpi" in css
    assert ".atlas-grid-2" in css
    assert ".hidden" in css


def test_style_css_has_brand_aliases(client):
    """style.css bridge must define petrol/charcoal/accent → atlas-token mappings."""
    resp = client.get("/static/style.css")
    css = resp.text
    assert ".text-petrol" in css
    assert ".bg-petrol" in css
    assert ".text-charcoal" in css
    assert ".font-heading" in css
    assert ".text-gray-500" in css
    assert ".bg-white" in css


def test_style_css_has_layout_utilities(client):
    resp = client.get("/static/style.css")
    css = resp.text
    assert ".flex" in css
    assert ".grid" in css
    assert ".gap-4" in css
    assert ".hidden" in css


def test_style_css_global_form_reset(client):
    """style.css must apply atlas token styling to native form elements."""
    resp = client.get("/static/style.css")
    css = resp.text
    assert "atlas-color-primary" in css
    assert "input[type" in css


# ── Light/dark theme ──────────────────────────────────────────────────────────


def test_dark_theme_is_default(client):
    """HTML element must default to dark theme."""
    resp = client.get("/ui/dashboard")
    assert 'data-theme="dark"' in resp.text


def test_light_theme_tokens_present_in_css(client):
    """Light theme override block must be present in tokens CSS."""
    resp = client.get("/static/atlas-tokens.css")
    assert '[data-theme="light"]' in resp.text
