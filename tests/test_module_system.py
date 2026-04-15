"""Tests for the module system — enable/disable, route mounting."""

from __future__ import annotations


from spec2sphere.modules import (
    ModuleSpec,
    configure_modules,
    get_enabled_ui_sections,
    get_module,
    is_enabled,
    list_modules,
    register_module,
    _REGISTRY,
)


class TestModuleRegistry:
    def test_core_always_registered(self):
        assert get_module("core") is not None

    def test_migration_accelerator_registered(self):
        assert get_module("migration_accelerator") is not None

    def test_list_modules_returns_all(self):
        modules = list_modules()
        names = {m.name for m in modules}
        assert "core" in names
        assert "migration_accelerator" in names
        assert "dsp_factory" in names
        assert "multi_tenant" in names

    def test_register_custom_module(self):
        spec = ModuleSpec(
            name="test_custom_module_xyz",
            description="Test module",
            enabled=False,
        )
        register_module(spec)
        assert get_module("test_custom_module_xyz") is spec
        # Clean up
        del _REGISTRY["test_custom_module_xyz"]


class TestConfigureModules:
    def test_core_always_enabled(self):
        # Even if config says false, core stays enabled
        configure_modules({"core": False})
        assert get_module("core").enabled is True

    def test_enable_migration_from_config(self):
        configure_modules({"migration_accelerator": True})
        assert is_enabled("migration_accelerator") is True

    def test_disable_migration_from_config(self):
        configure_modules({"migration_accelerator": False})
        assert is_enabled("migration_accelerator") is False

    def test_empty_config_disables_non_core(self):
        configure_modules({})
        # All optional modules default to disabled when config is empty
        # (except core)
        assert is_enabled("core") is True
        assert is_enabled("multi_tenant") is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ENABLED_MODULES", "migration_accelerator,dsp_factory")
        configure_modules({})
        assert is_enabled("migration_accelerator") is True
        assert is_enabled("dsp_factory") is True
        # multi_tenant not in env override
        assert is_enabled("multi_tenant") is False
        monkeypatch.delenv("ENABLED_MODULES")
        # Restore to known state
        configure_modules({"migration_accelerator": False, "dsp_factory": False})


class TestIsEnabled:
    def test_unregistered_returns_false(self):
        assert is_enabled("nonexistent_module_xyz") is False

    def test_enabled_returns_true(self):
        spec = get_module("core")
        spec.enabled = True
        assert is_enabled("core") is True


class TestGetEnabledUISections:
    def test_core_sections_always_present(self):
        # Ensure core is enabled
        get_module("core").enabled = True
        sections = get_enabled_ui_sections()
        assert "scanner" in sections
        assert "knowledge" in sections

    def test_disabled_module_sections_absent(self):
        # Disable multi_tenant, its UI section should not appear
        mt_module = get_module("multi_tenant")
        original_state = mt_module.enabled
        mt_module.enabled = False
        sections = get_enabled_ui_sections()
        assert "workspace_switcher" not in sections
        assert "tenant_admin" not in sections
        # Restore
        mt_module.enabled = original_state

    def test_enabled_module_sections_present(self):
        mt_module = get_module("multi_tenant")
        original_state = mt_module.enabled
        mt_module.enabled = True
        sections = get_enabled_ui_sections()
        assert "workspace_switcher" in sections
        # Restore
        mt_module.enabled = original_state
