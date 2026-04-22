"""FR-2395 — Spec2Sphere Atlas Design Language Adoption tests.

Verifies the specific changes made during this adoption session:
- atlas-tokens.css is byte-for-byte identical to the canonical package
- atlas-ui.css includes all expected new primitives and corrected values
- style.css has no hardcoded terminal panel colours
- base.html loads Inter Variable font
- sync_atlas_css.py script is runnable and canonical path resolves
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
ATLAS_ROOT = REPO_ROOT.parent / "atlas"
STATIC_DIR = REPO_ROOT / "src" / "spec2sphere" / "web" / "static"
TEMPLATES_DIR = REPO_ROOT / "src" / "spec2sphere" / "web" / "templates"
SCRIPTS_DIR = REPO_ROOT / "scripts"


# ── Token parity with canonical @atlas/design-tokens ─────────────────────────

class TestTokenParity:
    """Local atlas-tokens.css must be identical to the canonical dist."""

    _canonical_path = ATLAS_ROOT / "packages" / "atlas-design-tokens" / "dist" / "tokens.css"
    _local_path = STATIC_DIR / "atlas-tokens.css"

    def test_canonical_source_exists(self):
        assert self._canonical_path.exists(), (
            f"Canonical tokens not found at {self._canonical_path}. "
            "Run scripts/sync_atlas_css.py to regenerate."
        )

    def test_tokens_identical_to_canonical(self):
        if not self._canonical_path.exists():
            import pytest
            pytest.skip("canonical tokens.css not found — cannot compare")
        canonical = self._canonical_path.read_text()
        local = self._local_path.read_text()
        assert local == canonical, (
            "atlas-tokens.css diverged from canonical @atlas/design-tokens. "
            "Run: python scripts/sync_atlas_css.py"
        )

    def test_all_semantic_color_tokens_present(self):
        css = self._local_path.read_text()
        required = [
            "--atlas-color-bg",
            "--atlas-color-surface",
            "--atlas-color-elevated",
            "--atlas-color-border",
            "--atlas-color-fg",
            "--atlas-color-fg-muted",
            "--atlas-color-fg-subtle",
            "--atlas-color-primary",
            "--atlas-color-primary-subtle",
            "--atlas-color-info",
            "--atlas-color-success",
            "--atlas-color-warning",
            "--atlas-color-destructive",
            "--atlas-color-cyan",
            "--atlas-color-sidebar-bg",
            "--atlas-color-sidebar-active",
        ]
        for token in required:
            assert token in css, f"Required token missing: {token}"

    def test_spacing_scale_present(self):
        css = self._local_path.read_text()
        for step in [1, 2, 3, 4, 6, 8, 12]:
            assert f"--atlas-space-{step}:" in css, f"Missing spacing token --atlas-space-{step}"

    def test_radii_tokens_present(self):
        css = self._local_path.read_text()
        for r in ["none", "sm", "md", "lg", "xl", "2xl", "full"]:
            assert f"--atlas-radius-{r}:" in css, f"Missing radius token --atlas-radius-{r}"

    def test_motion_tokens_present(self):
        css = self._local_path.read_text()
        for dur in ["instant", "fast", "normal", "slow", "deliberate"]:
            assert f"--atlas-duration-{dur}:" in css, f"Missing motion token --atlas-duration-{dur}"

    def test_light_theme_override_present(self):
        css = self._local_path.read_text()
        assert '[data-theme="light"]' in css, "Light theme override block missing from tokens.css"

    def test_dark_theme_is_root_default(self):
        css = self._local_path.read_text()
        assert ':root' in css, "tokens.css must set :root defaults (dark theme)"

    def test_reduced_motion_media_query(self):
        css = self._local_path.read_text()
        assert "prefers-reduced-motion" in css


# ── Atlas-UI CSS correctness ───────────────────────────────────────────────────

class TestAtlasUiCss:
    """atlas-ui.css must match canonical class definitions and include new primitives."""

    _css = None

    @classmethod
    def _get_css(cls) -> str:
        if cls._css is None:
            cls._css = (STATIC_DIR / "atlas-ui.css").read_text()
        return cls._css

    # Button active states (added this session)
    def test_btn_primary_has_active_state(self):
        css = self._get_css()
        assert "atlas-btn--primary:active" in css

    def test_btn_secondary_has_active_state(self):
        css = self._get_css()
        assert "atlas-btn--secondary:active" in css

    def test_btn_ghost_has_active_state(self):
        css = self._get_css()
        assert "atlas-btn--ghost:active" in css

    def test_btn_loading_state_exists(self):
        css = self._get_css()
        assert "atlas-btn--loading" in css

    def test_btn_lg_size_exists(self):
        css = self._get_css()
        assert "atlas-btn--lg" in css

    # Input background uses surface (not elevated) — canonical alignment
    def test_input_uses_surface_background(self):
        css = self._get_css()
        # The .atlas-input block is a combined selector; search for background-color near atlas-input
        # Find the block that contains .atlas-input and .atlas-select together
        match = re.search(
            r'\.atlas-input[,\s].*?\{([^}]+)\}',
            css,
            re.DOTALL,
        )
        assert match, ".atlas-input rule not found"
        block = match.group(1)
        assert "atlas-color-surface" in block, (
            ".atlas-input background must use var(--atlas-color-surface), not elevated"
        )

    def test_input_hover_state_exists(self):
        css = self._get_css()
        assert "atlas-input:hover" in css or "atlas-input:hover:not(:disabled)" in css

    def test_input_error_state_exists(self):
        css = self._get_css()
        assert "atlas-input--error" in css

    # Card header padding alignment
    def test_card_header_uses_space_6(self):
        css = self._get_css()
        match = re.search(r'\.atlas-card-header\s*\{([^}]+)\}', css)
        assert match, ".atlas-card-header rule not found"
        block = match.group(1)
        # canonical uses padding: var(--atlas-space-6) — not the asymmetric 4/6 from old version
        assert "atlas-space-6" in block

    # New components added this session
    def test_panel_component_exists(self):
        css = self._get_css()
        assert ".atlas-panel" in css

    def test_section_component_exists(self):
        css = self._get_css()
        assert ".atlas-section" in css

    def test_checkbox_root_exists(self):
        css = self._get_css()
        assert ".atlas-checkbox-root" in css

    def test_switch_wrapper_exists(self):
        css = self._get_css()
        assert ".atlas-switch-wrapper" in css

    # AppShell transition uses token variable
    def test_appshell_sidebar_transition_uses_token(self):
        css = self._get_css()
        assert "atlas-duration-normal" in css, (
            "AppShell sidebar transition must use --atlas-duration-normal token"
        )


# ── style.css hardcoded colour elimination ────────────────────────────────────

class TestStyleCssClean:
    """style.css must have no hardcoded colours for terminal panel."""

    _css = None

    @classmethod
    def _get_css(cls) -> str:
        if cls._css is None:
            cls._css = (STATIC_DIR / "style.css").read_text()
        return cls._css

    def test_terminal_panel_uses_atlas_var(self):
        css = self._get_css()
        match = re.search(r'\.terminal-panel\s*\{([^}]+)\}', css)
        assert match, ".terminal-panel rule not found"
        block = match.group(1)
        assert "var(--atlas-" in block, ".terminal-panel must use atlas token variable"
        assert "#1a1a2e" not in block, "Hardcoded #1a1a2e still in .terminal-panel"

    def test_terminal_toolbar_uses_atlas_var(self):
        css = self._get_css()
        match = re.search(r'\.terminal-toolbar\s*\{([^}]+)\}', css)
        assert match, ".terminal-toolbar rule not found"
        block = match.group(1)
        assert "var(--atlas-" in block, ".terminal-toolbar must use atlas token variable"
        assert "#16213e" not in block, "Hardcoded #16213e still in .terminal-toolbar"

    def test_no_hardcoded_petrol_hex(self):
        css = self._get_css()
        # These old brand colours must not appear as raw hex
        assert "#05415A" not in css
        assert "#05415a" not in css

    def test_no_hardcoded_accent_hex(self):
        css = self._get_css()
        assert "#C8963E" not in css
        assert "#c8963e" not in css


# ── base.html font loading ────────────────────────────────────────────────────

class TestBaseFontLoading:
    """base.html must load Inter with full variable weight range."""

    _html = None

    @classmethod
    def _get_html(cls) -> str:
        if cls._html is None:
            cls._html = (TEMPLATES_DIR / "base.html").read_text()
        return cls._html

    def test_preconnect_fonts_gstatic(self):
        assert "fonts.gstatic.com" in self._get_html(), (
            "base.html must preconnect to fonts.gstatic.com for font performance"
        )

    def test_inter_variable_weight_range_loaded(self):
        html = self._get_html()
        # Inter variable font uses opsz/wght axes: 100..900
        assert "100..900" in html or "wght@" in html, (
            "base.html must load Inter with variable weight range (100..900)"
        )

    def test_font_display_swap(self):
        html = self._get_html()
        assert "display=swap" in html, "Font must use display=swap for performance"


# ── Sync script ───────────────────────────────────────────────────────────────

class TestSyncScript:
    """scripts/sync_atlas_css.py must exist and be executable."""

    _script = SCRIPTS_DIR / "sync_atlas_css.py"

    def test_script_exists(self):
        assert self._script.exists(), "scripts/sync_atlas_css.py not found"

    def test_script_is_valid_python(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(self._script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"sync_atlas_css.py has syntax errors: {result.stderr}"

    def test_script_runs_successfully(self):
        result = subprocess.run(
            [sys.executable, str(self._script)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"sync_atlas_css.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_script_output_mentions_tokens(self):
        result = subprocess.run(
            [sys.executable, str(self._script)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "tokens.css" in result.stdout


# ── Nav manifest completeness (FR-2395 specific) ──────────────────────────────

class TestNavManifestAdoption:
    """The nav manifest must be complete and meet atlas-nav-registry spec."""

    def _get_manifest(self):
        from fastapi.testclient import TestClient
        from spec2sphere.web.server import create_app
        client = TestClient(create_app())
        return client.get("/_atlas/nav-manifest").json()

    def test_shortcuts_registered(self):
        data = self._get_manifest()
        assert "shortcuts" in data
        assert isinstance(data["shortcuts"], list)
        assert len(data["shortcuts"]) >= 4, "Expected at least 4 keyboard shortcuts"

    def test_shortcuts_have_required_keys(self):
        shortcuts = self._get_manifest()["shortcuts"]
        for sc in shortcuts:
            assert "key" in sc, f"Shortcut missing 'key': {sc}"
            assert "description" in sc, f"Shortcut missing 'description': {sc}"
            assert "action" in sc, f"Shortcut missing 'action': {sc}"

    def test_groups_are_valid(self):
        routes = self._get_manifest()["routes"]
        valid_groups = {"Main", "Discover", "Quality", "Learning", "System", "Tools"}
        for route in routes:
            assert route["group"] in valid_groups, (
                f"Route {route['id']} has unknown group '{route['group']}'"
            )

    def test_routes_have_keywords(self):
        routes = self._get_manifest()["routes"]
        for route in routes:
            assert "keywords" in route, f"Route {route['id']} missing 'keywords'"
            assert isinstance(route["keywords"], list), f"keywords must be a list: {route['id']}"

    def test_version_field_present(self):
        data = self._get_manifest()
        assert "version" in data
        # Should be semver-like
        assert re.match(r"\d+\.\d+", data["version"]), f"Invalid version: {data['version']}"


# ── Template migration: atlas-* class usage ───────────────────────────────────

class TestTemplateMigration:
    """Key templates must use atlas-* classes directly (not legacy Tailwind-like names)."""

    _html = None

    @classmethod
    def _get_template(cls, name: str) -> str:
        return (TEMPLATES_DIR / "partials" / name).read_text()

    # notifications.html
    def test_notifications_uses_atlas_banner(self):
        html = self._get_template("notifications.html")
        assert "atlas-banner" in html, "notifications.html must use atlas-banner for errors"

    def test_notifications_uses_atlas_card(self):
        html = self._get_template("notifications.html")
        assert "atlas-card" in html

    def test_notifications_uses_atlas_badge(self):
        html = self._get_template("notifications.html")
        assert "atlas-badge" in html, "notification type must be shown as atlas-badge"

    def test_notifications_uses_atlas_btn(self):
        html = self._get_template("notifications.html")
        assert "atlas-btn" in html

    def test_notifications_no_bg_white(self):
        html = self._get_template("notifications.html")
        assert 'class="bg-white' not in html, "notifications.html must not use raw bg-white class"

    def test_notifications_uses_atlas_empty(self):
        html = self._get_template("notifications.html")
        assert "atlas-empty" in html

    # quality.html
    def test_quality_uses_atlas_card(self):
        html = self._get_template("quality.html")
        assert "atlas-card" in html

    def test_quality_uses_atlas_tab_list(self):
        html = self._get_template("quality.html")
        assert "atlas-tab-list" in html

    def test_quality_uses_atlas_tab(self):
        html = self._get_template("quality.html")
        assert "atlas-tab " in html or "atlas-tab\"" in html

    def test_quality_uses_atlas_tab_panel(self):
        html = self._get_template("quality.html")
        assert "atlas-tab-panel" in html

    def test_quality_no_raw_tailwind_tabs(self):
        html = self._get_template("quality.html")
        assert "border-b-2 border-petrol" not in html, (
            "quality.html must not use raw legacy tab classes"
        )

    # audit.html
    def test_audit_uses_atlas_card(self):
        html = self._get_template("audit.html")
        assert "atlas-card" in html

    def test_audit_uses_atlas_input(self):
        html = self._get_template("audit.html")
        assert "atlas-input" in html

    def test_audit_uses_atlas_textarea(self):
        html = self._get_template("audit.html")
        assert "atlas-textarea" in html

    def test_audit_uses_atlas_btn_primary(self):
        html = self._get_template("audit.html")
        assert "atlas-btn--primary" in html

    def test_audit_no_bg_petrol(self):
        html = self._get_template("audit.html")
        assert 'class="px-4 py-2 bg-petrol' not in html

    # reports.html
    def test_reports_uses_atlas_card(self):
        html = self._get_template("reports.html")
        assert "atlas-card" in html

    def test_reports_uses_atlas_btn(self):
        html = self._get_template("reports.html")
        assert "atlas-btn" in html

    def test_reports_uses_atlas_empty(self):
        html = self._get_template("reports.html")
        assert "atlas-empty" in html

    def test_reports_uses_atlas_code(self):
        html = self._get_template("reports.html")
        assert "atlas-code" in html

    # requirements.html
    def test_requirements_uses_atlas_card(self):
        html = self._get_template("requirements.html")
        assert "atlas-card" in html

    def test_requirements_uses_atlas_banner(self):
        html = self._get_template("requirements.html")
        assert "atlas-banner" in html

    def test_requirements_uses_atlas_badge_status(self):
        html = self._get_template("requirements.html")
        assert "atlas-badge--success" in html or "atlas-badge--warning" in html

    def test_requirements_uses_atlas_select(self):
        html = self._get_template("requirements.html")
        assert "atlas-select" in html, "requirements.html must use atlas-select for filter"

    def test_requirements_uses_atlas_empty(self):
        html = self._get_template("requirements.html")
        assert "atlas-empty" in html

    def test_requirements_no_raw_bg_white(self):
        html = self._get_template("requirements.html")
        assert 'class="bg-white' not in html

    # reconciliation.html
    def test_reconciliation_uses_atlas_card(self):
        html = self._get_template("reconciliation.html")
        assert "atlas-card" in html

    def test_reconciliation_uses_atlas_table(self):
        html = self._get_template("reconciliation.html")
        assert "atlas-table" in html

    def test_reconciliation_uses_atlas_dot(self):
        html = self._get_template("reconciliation.html")
        assert "atlas-dot" in html

    def test_reconciliation_uses_atlas_badge(self):
        html = self._get_template("reconciliation.html")
        assert "atlas-badge" in html

    def test_reconciliation_uses_atlas_empty(self):
        html = self._get_template("reconciliation.html")
        assert "atlas-empty" in html

    def test_reconciliation_uses_atlas_btn(self):
        html = self._get_template("reconciliation.html")
        assert "atlas-btn" in html

    # knowledge.html
    def test_knowledge_uses_atlas_card(self):
        html = self._get_template("knowledge.html")
        assert "atlas-card" in html

    def test_knowledge_uses_atlas_input(self):
        html = self._get_template("knowledge.html")
        assert "atlas-input" in html

    def test_knowledge_uses_atlas_select(self):
        html = self._get_template("knowledge.html")
        assert "atlas-select" in html

    def test_knowledge_uses_atlas_btn_primary(self):
        html = self._get_template("knowledge.html")
        assert "atlas-btn--primary" in html

    def test_knowledge_uses_atlas_badge(self):
        html = self._get_template("knowledge.html")
        assert "atlas-badge" in html

    def test_knowledge_uses_atlas_kpi(self):
        html = self._get_template("knowledge.html")
        assert "atlas-kpi" in html

    def test_knowledge_uses_atlas_empty(self):
        html = self._get_template("knowledge.html")
        assert "atlas-empty" in html


# ── atlas-ui.css dot variants ─────────────────────────────────────────────────

class TestDotVariants:
    """atlas-ui.css must include all intent dot variants used in templates."""

    _css = (STATIC_DIR / "atlas-ui.css").read_text()

    def test_dot_primary_exists(self):
        assert ".atlas-dot--primary" in self._css

    def test_dot_info_exists(self):
        assert ".atlas-dot--info" in self._css

    def test_dot_success_exists(self):
        assert ".atlas-dot--success" in self._css

    def test_dot_warning_exists(self):
        assert ".atlas-dot--warning" in self._css

    def test_dot_destructive_exists(self):
        assert ".atlas-dot--destructive" in self._css

    def test_dot_muted_exists(self):
        assert ".atlas-dot--muted" in self._css


# ── SSO theme receiver in base.html ──────────────────────────────────────────

class TestSsoReceiver:
    """base.html must include atlas SSO param receiver for cross-service jumps."""

    _html = (TEMPLATES_DIR / "base.html").read_text()

    def test_sso_reads_theme_param(self):
        assert "_theme" in self._html, "base.html must read _theme URL param for SSO"

    def test_sso_reads_at_param(self):
        assert "_at" in self._html, "base.html must read _at URL param for token SSO"

    def test_sso_stores_bifrost_token(self):
        assert "atlas.bifrost_token" in self._html

    def test_sso_strips_params_from_url(self):
        assert "replaceState" in self._html, (
            "base.html must strip SSO params from URL after reading them"
        )

    def test_sso_stores_atlas_theme(self):
        assert "atlasTheme" in self._html
