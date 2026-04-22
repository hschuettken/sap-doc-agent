"""Tests for Atlas design-language adoption in spec2sphere.

Covers:
- /_atlas/nav-manifest endpoint structure
- Static CSS files are present on disk
- Base template references atlas CSS files
"""

from pathlib import Path
from fastapi.testclient import TestClient


def get_client():
    from spec2sphere.web.server import create_app
    return TestClient(create_app())


STATIC_DIR = Path(__file__).parents[1] / "src" / "spec2sphere" / "web" / "static"
TEMPLATES_DIR = Path(__file__).parents[1] / "src" / "spec2sphere" / "web" / "templates"


# ── nav-manifest ──────────────────────────────────────────────────────────────

class TestNavManifest:
    def test_returns_200(self):
        client = get_client()
        resp = client.get("/_atlas/nav-manifest")
        assert resp.status_code == 200

    def test_content_type_json(self):
        client = get_client()
        resp = client.get("/_atlas/nav-manifest")
        assert "application/json" in resp.headers["content-type"]

    def test_required_fields(self):
        client = get_client()
        data = client.get("/_atlas/nav-manifest").json()
        assert data["serviceId"] == "spec2sphere"
        assert data["serviceName"] == "Spec2Sphere"
        assert "serviceUrl" in data
        assert "routes" in data
        assert isinstance(data["routes"], list)

    def test_routes_have_required_keys(self):
        client = get_client()
        routes = client.get("/_atlas/nav-manifest").json()["routes"]
        required = {"id", "label", "path", "group"}
        for route in routes:
            assert required.issubset(route.keys()), f"Route missing keys: {route}"

    def test_routes_paths_start_with_slash(self):
        client = get_client()
        routes = client.get("/_atlas/nav-manifest").json()["routes"]
        for route in routes:
            assert route["path"].startswith("/"), f"Path must be absolute: {route['path']}"

    def test_dashboard_route_present(self):
        client = get_client()
        routes = client.get("/_atlas/nav-manifest").json()["routes"]
        ids = {r["id"] for r in routes}
        assert "dashboard" in ids

    def test_minimum_route_count(self):
        client = get_client()
        routes = client.get("/_atlas/nav-manifest").json()["routes"]
        assert len(routes) >= 20, "Expected at least 20 routes registered"

    def test_service_url_format(self):
        client = get_client()
        data = client.get("/_atlas/nav-manifest").json()
        url = data["serviceUrl"]
        assert url.startswith("http"), f"serviceUrl should be an HTTP URL, got: {url}"


# ── Static CSS files ──────────────────────────────────────────────────────────

class TestStaticAssets:
    def test_atlas_tokens_css_exists(self):
        assert (STATIC_DIR / "atlas-tokens.css").exists()

    def test_atlas_tokens_css_not_empty(self):
        css = (STATIC_DIR / "atlas-tokens.css").read_text()
        assert len(css) > 100
        assert "--atlas-color-primary" in css

    def test_atlas_ui_css_exists(self):
        assert (STATIC_DIR / "atlas-ui.css").exists()

    def test_atlas_ui_css_appshell_rules(self):
        css = (STATIC_DIR / "atlas-ui.css").read_text()
        assert ".atlas-appshell" in css
        assert ".atlas-sidebar" in css
        assert ".atlas-appshell-header" in css

    def test_atlas_ui_css_uses_tokens(self):
        css = (STATIC_DIR / "atlas-ui.css").read_text()
        assert "var(--atlas-color-" in css

    def test_style_css_uses_atlas_tokens(self):
        css = (STATIC_DIR / "style.css").read_text()
        # Old hardcoded hex colours should be gone
        assert "#05415A" not in css, "Old petrol colour still hardcoded in style.css"
        assert "#C8963E" not in css, "Old accent colour still hardcoded in style.css"
        # Token vars should be present
        assert "var(--atlas-color-" in css

    def test_style_css_bridges_legacy_card(self):
        css = (STATIC_DIR / "style.css").read_text()
        assert ".card" in css

    def test_style_css_bridges_legacy_badge(self):
        css = (STATIC_DIR / "style.css").read_text()
        assert ".badge" in css


# ── Base template ─────────────────────────────────────────────────────────────

class TestBaseTemplate:
    def _base(self):
        return (TEMPLATES_DIR / "base.html").read_text()

    def test_loads_atlas_tokens(self):
        assert "atlas-tokens.css" in self._base()

    def test_loads_atlas_ui(self):
        assert "atlas-ui.css" in self._base()

    def test_appshell_class_present(self):
        assert "atlas-appshell" in self._base()

    def test_sidebar_class_present(self):
        assert "atlas-sidebar" in self._base()

    def test_appshell_header_present(self):
        assert "atlas-appshell-header" in self._base()

    def test_appshell_content_present(self):
        assert "atlas-appshell-content" in self._base()

    def test_dark_theme_attribute(self):
        assert 'data-theme="dark"' in self._base()

    def test_no_tailwind_cdn(self):
        assert "cdn.tailwindcss.com" not in self._base(), "Tailwind CDN should be removed"

    def test_no_old_css_vars(self):
        base = self._base()
        assert "--color-primary:" not in base, "Old --color-primary still in base.html"
        assert "--color-accent:" not in base, "Old --color-accent still in base.html"

    def test_htmx_still_present(self):
        assert "htmx.org" in self._base(), "HTMX transport must be kept"

    def test_sidebar_nav_item_class(self):
        assert "atlas-sidebar-nav-item" in self._base()

    def test_sidebar_group_collapsible_class(self):
        assert "atlas-sidebar-group--collapsible" in self._base()

    def test_mobile_drawer_toggle(self):
        assert "openDrawer" in self._base()
        assert "closeDrawer" in self._base()


# ── Setup wizard ──────────────────────────────────────────────────────────────

class TestSetupWizard:
    def _wizard(self):
        return (TEMPLATES_DIR / "setup" / "base_wizard.html").read_text()

    def test_no_tailwind_cdn(self):
        assert "cdn.tailwindcss.com" not in self._wizard(), "Tailwind CDN must be removed from setup wizard"

    def test_loads_atlas_tokens(self):
        assert "atlas-tokens.css" in self._wizard()

    def test_loads_atlas_ui(self):
        assert "atlas-ui.css" in self._wizard()

    def test_loads_style_css(self):
        assert "style.css" in self._wizard()

    def test_dark_theme_default(self):
        assert 'data-theme="dark"' in self._wizard()

    def test_no_hardcoded_petrol_hex(self):
        wizard = self._wizard()
        assert "#05415A" not in wizard, "Old petrol hex colour in wizard base"
        assert "#C8963E" not in wizard, "Old accent hex colour in wizard base"

    def test_uses_atlas_token_vars(self):
        assert "var(--atlas-color-" in self._wizard()

    def test_wizard_card_class_present(self):
        assert "wizard-card" in self._wizard()

    def test_wizard_progress_present(self):
        assert "wizard-progress" in self._wizard()

    def test_sub_page_welcome_no_tailwind_cdn(self):
        welcome = (TEMPLATES_DIR / "setup" / "welcome.html").read_text()
        assert "cdn.tailwindcss.com" not in welcome

    def test_sub_page_admin_uses_atlas_input(self):
        admin = (TEMPLATES_DIR / "setup" / "admin.html").read_text()
        assert "atlas-input" in admin

    def test_sub_page_admin_uses_atlas_btn(self):
        admin = (TEMPLATES_DIR / "setup" / "admin.html").read_text()
        assert "atlas-btn" in admin


# ── Error pages ───────────────────────────────────────────────────────────────

class TestErrorPages:
    def _page(self, name: str) -> str:
        return (TEMPLATES_DIR / "errors" / name).read_text()

    def test_404_loads_atlas_tokens(self):
        assert "atlas-tokens.css" in self._page("404.html")

    def test_404_no_hardcoded_petrol(self):
        page = self._page("404.html")
        assert "#05415A" not in page, "Old petrol colour in 404 page"
        assert "#C8963E" not in page, "Old accent colour in 404 page"

    def test_404_uses_atlas_primary_var(self):
        assert "var(--atlas-color-primary)" in self._page("404.html")

    def test_404_dark_theme_default(self):
        assert 'data-theme="dark"' in self._page("404.html")

    def test_404_respects_stored_theme(self):
        assert "atlasTheme" in self._page("404.html")

    def test_500_loads_atlas_tokens(self):
        assert "atlas-tokens.css" in self._page("500.html")

    def test_500_uses_destructive_var(self):
        assert "var(--atlas-color-destructive)" in self._page("500.html")

    def test_500_no_hardcoded_colors(self):
        page = self._page("500.html")
        assert "#05415A" not in page
        assert "#C8963E" not in page
        assert "#353434" not in page
