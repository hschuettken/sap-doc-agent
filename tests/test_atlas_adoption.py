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


# ── Settings template ────────────────────────────────────────────────────────


def test_settings_uses_atlas_tab_list(client):
    resp = client.get("/ui/settings")
    assert resp.status_code == 200
    assert "atlas-tab-list" in resp.text


def test_settings_uses_atlas_input(client):
    resp = client.get("/ui/settings")
    assert "atlas-input" in resp.text


def test_settings_uses_atlas_btn(client):
    resp = client.get("/ui/settings")
    assert "atlas-btn--primary" in resp.text


def test_settings_uses_atlas_dot(client):
    resp = client.get("/ui/settings")
    assert "atlas-dot" in resp.text


# ── Chains template ───────────────────────────────────────────────────────────


def test_chains_uses_atlas_btn(client):
    resp = client.get("/ui/chains")
    assert resp.status_code == 200
    assert "atlas-btn--primary" in resp.text


def test_chains_uses_atlas_empty_state(client):
    resp = client.get("/ui/chains")
    assert "atlas-empty" in resp.text


def test_chains_uses_atlas_split(client):
    resp = client.get("/ui/chains")
    assert "atlas-split" in resp.text


# ── Landscape template ────────────────────────────────────────────────────────


def test_landscape_uses_atlas_tab_list(client):
    resp = client.get("/ui/landscape")
    assert resp.status_code == 200
    assert "atlas-tab-list" in resp.text


def test_landscape_uses_atlas_table(client):
    resp = client.get("/ui/landscape")
    assert "atlas-table" in resp.text


def test_landscape_uses_atlas_select(client):
    resp = client.get("/ui/landscape")
    assert "atlas-select" in resp.text


# ── Admin template ────────────────────────────────────────────────────────────


def test_admin_uses_atlas_tab_list(client):
    resp = client.get("/ui/admin")
    assert resp.status_code == 200
    assert "atlas-tab-list" in resp.text


def test_admin_uses_atlas_table(client):
    resp = client.get("/ui/admin")
    assert "atlas-table" in resp.text


def test_admin_uses_atlas_input(client):
    resp = client.get("/ui/admin")
    assert "atlas-input" in resp.text


# ── Audit log template ────────────────────────────────────────────────────────


def test_audit_log_uses_atlas_card(client):
    resp = client.get("/ui/audit-log")
    assert resp.status_code == 200
    assert "atlas-card" in resp.text


def test_audit_log_uses_atlas_input(client):
    resp = client.get("/ui/audit-log")
    assert "atlas-input" in resp.text


def test_audit_log_uses_atlas_btn(client):
    resp = client.get("/ui/audit-log")
    assert "atlas-btn--primary" in resp.text


# ── Object detail template ────────────────────────────────────────────────────


def test_object_detail_uses_atlas_card(client):
    resp = client.get("/ui/objects/SPC.VIEW1")
    assert resp.status_code == 200
    assert "atlas-card" in resp.text


def test_object_detail_uses_atlas_badge(client):
    resp = client.get("/ui/objects/SPC.VIEW1")
    assert "atlas-badge" in resp.text


def test_object_detail_no_old_badge_class(client):
    """Migrated object_detail must not use old bare .badge class."""
    resp = client.get("/ui/objects/SPC.VIEW1")
    html = resp.text
    assert 'class="badge' not in html


# ── Graph template ────────────────────────────────────────────────────────────


def test_graph_uses_atlas_card(client):
    resp = client.get("/ui/graph")
    assert resp.status_code == 200
    assert "atlas-card" in resp.text


def test_graph_uses_atlas_input(client):
    resp = client.get("/ui/graph")
    assert "atlas-input" in resp.text


def test_graph_uses_atlas_select(client):
    resp = client.get("/ui/graph")
    assert "atlas-select" in resp.text


# ── Bridge CSS aliases ────────────────────────────────────────────────────────


def test_style_css_has_btn_alias(client):
    """style.css bridge must define .btn and .btn-primary for any legacy markup."""
    resp = client.get("/static/style.css")
    css = resp.text
    assert ".btn " in css or ".btn{" in css or ".btn\n" in css or ".btn," in css
    assert "btn-primary" in css


# ── Light/dark theme ──────────────────────────────────────────────────────────


def test_dark_theme_is_default(client):
    """HTML element must default to dark theme."""
    resp = client.get("/ui/dashboard")
    assert 'data-theme="dark"' in resp.text


def test_light_theme_tokens_present_in_css(client):
    """Light theme override block must be present in tokens CSS."""
    resp = client.get("/static/atlas-tokens.css")
    assert '[data-theme="light"]' in resp.text


# ── Nav manifest (/_atlas/nav-manifest) ──────────────────────────────────────


def test_nav_manifest_accessible(client):
    """/_atlas/nav-manifest must be accessible without authentication."""
    resp = client.get("/_atlas/nav-manifest")
    assert resp.status_code == 200


def test_nav_manifest_service_id(client):
    data = client.get("/_atlas/nav-manifest").json()
    assert data["serviceId"] == "spec2sphere"


def test_nav_manifest_service_name(client):
    data = client.get("/_atlas/nav-manifest").json()
    assert "Spec2Sphere" in data["serviceName"]


def test_nav_manifest_service_url(client):
    data = client.get("/_atlas/nav-manifest").json()
    assert "8260" in data["serviceUrl"]


def test_nav_manifest_has_routes(client):
    data = client.get("/_atlas/nav-manifest").json()
    assert isinstance(data["routes"], list)
    assert len(data["routes"]) >= 10


def test_nav_manifest_route_schema(client):
    data = client.get("/_atlas/nav-manifest").json()
    for route in data["routes"]:
        assert "id" in route, f"Route missing 'id': {route}"
        assert "label" in route, f"Route missing 'label': {route}"
        assert "path" in route, f"Route missing 'path': {route}"


def test_nav_manifest_has_core_routes(client):
    data = client.get("/_atlas/nav-manifest").json()
    ids = {r["id"] for r in data["routes"]}
    for required in ("dashboard", "pipeline", "factory", "reports", "scanner"):
        assert required in ids, f"Missing core route: {required}"


def test_nav_manifest_has_shortcuts(client):
    data = client.get("/_atlas/nav-manifest").json()
    assert isinstance(data["shortcuts"], list)
    assert len(data["shortcuts"]) > 0


def test_nav_manifest_shortcut_schema(client):
    data = client.get("/_atlas/nav-manifest").json()
    for sc in data["shortcuts"]:
        assert "key" in sc, f"Shortcut missing 'key': {sc}"
        assert "description" in sc, f"Shortcut missing 'description': {sc}"


def test_nav_manifest_has_version(client):
    data = client.get("/_atlas/nav-manifest").json()
    assert "version" in data and data["version"]


# ── Command palette HTML structure ────────────────────────────────────────────


def test_base_has_command_palette_markup(client):
    """Base template must render the atlas command palette container."""
    resp = client.get("/ui/dashboard")
    html = resp.text
    assert 'id="atlas-palette"' in html


def test_base_palette_has_overlay(client):
    html = client.get("/ui/dashboard").text
    assert "atlas-palette-overlay" in html


def test_base_palette_has_input(client):
    html = client.get("/ui/dashboard").text
    assert 'id="palette-input"' in html


def test_base_palette_trigger_button_present(client):
    html = client.get("/ui/dashboard").text
    assert "atlasOpenPalette" in html


def test_atlas_ui_css_has_palette_classes(client):
    css = client.get("/static/atlas-ui.css").text
    assert ".atlas-palette-overlay" in css
    assert ".atlas-palette-dialog" in css
    assert ".atlas-palette-input" in css
    assert ".atlas-palette-item" in css
    assert ".atlas-palette-footer" in css


def test_palette_ctrl_k_handler_present(client):
    """The Ctrl+K keyboard handler must be inlined in the base template."""
    html = client.get("/ui/dashboard").text
    assert "atlasOpenPalette" in html
    assert "atlasClosePalette" in html
