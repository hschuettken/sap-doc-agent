"""Tests for the quality routing system."""

from __future__ import annotations


import pytest

from spec2sphere.llm.quality_router import (
    ACTION_REGISTRY,
    BUILTIN_PROFILES,
    CLUSTER_REGISTRY,
    QUALITY_LEVELS,
    QualityRouter,
)


@pytest.fixture
def router(tmp_path):
    """Quality router with a temp config file."""
    return QualityRouter(config_path=tmp_path / "routing.json")


# --- Resolution ---


def test_resolve_action_default(router):
    """Action with no overrides resolves to its default quality."""
    assert router.resolve_quality("semantic_parser") == "Q3"
    assert router.resolve_quality("hla_generator") == "Q4"
    assert router.resolve_quality("test_llm") == "Q1"
    assert router.resolve_quality("chain_analyzer") == "Q2"


def test_resolve_action_to_model(router):
    """Default profile maps Q3 → claude-haiku, Q4 → claude-sonnet."""
    assert router.resolve("semantic_parser") == "claude-haiku-4-5-20251001"
    assert router.resolve("hla_generator") == "claude-sonnet-4-6"
    assert router.resolve("test_llm") == "qwen2.5:7b"
    assert router.resolve("chain_analyzer") == "qwen2.5:14b"


def test_resolve_legacy_tier(router):
    """Legacy tier names map to quality levels."""
    assert router.resolve_quality("small") == "Q1"
    assert router.resolve_quality("medium") == "Q2"
    assert router.resolve_quality("large") == "Q3"
    assert router.resolve_quality("reasoning") == "Q4"


def test_resolve_quality_level_passthrough(router):
    assert router.resolve_quality("Q5") == "Q5"
    assert router.resolve_quality("Q1") == "Q1"


def test_resolve_unknown_defaults_to_q3(router):
    assert router.resolve_quality("nonexistent") == "Q3"


# --- Action overrides ---


def test_action_override(router):
    router.set_action_override("test_llm", "Q5")
    assert router.resolve_quality("test_llm") == "Q5"
    assert router.resolve("test_llm") == "claude-sonnet-4-6"


def test_clear_action_override(router):
    router.set_action_override("test_llm", "Q5")
    router.clear_action_override("test_llm")
    assert router.resolve_quality("test_llm") == "Q1"


def test_action_override_invalid_action(router):
    with pytest.raises(ValueError, match="Unknown action"):
        router.set_action_override("nonexistent", "Q1")


def test_action_override_invalid_quality(router):
    with pytest.raises(ValueError, match="Invalid quality"):
        router.set_action_override("test_llm", "Q9")


# --- Cluster overrides ---


def test_cluster_override(router):
    router.set_cluster_override("pipeline", "Q5")
    # All pipeline actions should now resolve to Q5
    assert router.resolve_quality("semantic_parser") == "Q5"
    assert router.resolve_quality("hla_generator") == "Q5"


def test_action_override_beats_cluster(router):
    router.set_cluster_override("pipeline", "Q5")
    router.set_action_override("semantic_parser", "Q2")
    assert router.resolve_quality("semantic_parser") == "Q2"  # action wins
    assert router.resolve_quality("hla_generator") == "Q5"  # cluster still applies


def test_clear_cluster_override(router):
    router.set_cluster_override("pipeline", "Q5")
    router.clear_cluster_override("pipeline")
    assert router.resolve_quality("semantic_parser") == "Q3"  # back to default


# --- Profile switching ---


def test_switch_profile(router):
    router.set_active_profile("all-local")
    assert router.resolve("semantic_parser") == "qwen2.5:14b"  # Q3 in all-local
    assert router.resolve("test_llm") == "qwen2.5:7b"  # Q1 in all-local


def test_switch_to_all_claude(router):
    router.set_active_profile("all-claude")
    assert router.resolve("test_llm") == "claude-haiku-4-5-20251001"


def test_switch_to_unknown_profile(router):
    with pytest.raises(ValueError, match="Unknown profile"):
        router.set_active_profile("nonexistent")


# --- Custom profiles ---


def test_save_custom_profile(router):
    custom = {
        "Q1": {"model": "local-small"},
        "Q2": {"model": "local-medium"},
        "Q3": {"model": "cloud-fast"},
        "Q4": {"model": "cloud-smart"},
        "Q5": {"model": "cloud-genius"},
    }
    router.save_custom_profile("my-setup", custom)
    router.set_active_profile("my-setup")
    assert router.resolve("test_llm") == "local-small"
    assert router.resolve("hla_generator") == "cloud-smart"


def test_cannot_overwrite_builtin(router):
    with pytest.raises(ValueError, match="built-in"):
        router.save_custom_profile(
            "default",
            {
                "Q1": {"model": "x"},
                "Q2": {"model": "x"},
                "Q3": {"model": "x"},
                "Q4": {"model": "x"},
                "Q5": {"model": "x"},
            },
        )


def test_delete_custom_profile(router):
    custom = {f"Q{i}": {"model": f"m{i}"} for i in range(1, 6)}
    router.save_custom_profile("temp", custom)
    router.set_active_profile("temp")
    router.delete_custom_profile("temp")
    assert router.get_active_profile_name() == "default"  # falls back


# --- Persistence ---


def test_config_persists(tmp_path):
    path = tmp_path / "routing.json"
    r1 = QualityRouter(config_path=path)
    r1.set_action_override("test_llm", "Q4")
    r1.set_active_profile("all-claude")

    r2 = QualityRouter(config_path=path)
    assert r2.resolve_quality("test_llm") == "Q4"
    assert r2.get_active_profile_name() == "all-claude"


# --- Reset ---


def test_reset_all(router):
    router.set_action_override("test_llm", "Q5")
    router.set_cluster_override("pipeline", "Q4")
    router.set_active_profile("all-claude")
    router.reset_all_overrides()
    assert router.resolve_quality("test_llm") == "Q1"
    assert router.resolve_quality("semantic_parser") == "Q3"
    assert router.get_active_profile_name() == "default"


# --- Full state ---


def test_full_state_structure(router):
    state = router.get_full_state()
    assert "quality_levels" in state
    assert "active_profile" in state
    assert "profiles" in state
    assert "clusters" in state
    assert "actions" in state
    assert len(state["actions"]) == len(ACTION_REGISTRY)
    assert len(state["clusters"]) == len(CLUSTER_REGISTRY)


def test_full_state_effective_model(router):
    state = router.get_full_state()
    for action in state["actions"]:
        if action["action_id"] == "test_llm":
            assert action["effective_quality"] == "Q1"
            assert action["effective_model"] == "qwen2.5:7b"
            assert action["override_source"] == "default"
            break


def test_full_state_with_override(router):
    router.set_action_override("test_llm", "Q4")
    state = router.get_full_state()
    for action in state["actions"]:
        if action["action_id"] == "test_llm":
            assert action["effective_quality"] == "Q4"
            assert action["effective_model"] == "claude-sonnet-4-6"
            assert action["override_source"] == "action"
            break


# --- Privacy by design ---


def test_data_in_context_forces_local(router):
    """When data_in_context=True, resolve uses the data-safe profile (all-local)."""
    # Normal resolution: Q3 → claude-haiku
    normal = router.resolve("semantic_parser", data_in_context=False)
    assert normal == "claude-haiku-4-5-20251001"

    # With data: Q3 → qwen2.5:14b (from all-local profile)
    safe = router.resolve("semantic_parser", data_in_context=True)
    assert safe == "qwen2.5:14b"


def test_data_in_context_disabled(router):
    """When local_only_with_data is disabled, data_in_context has no effect."""
    router.set_privacy(local_only_with_data=False)
    safe = router.resolve("semantic_parser", data_in_context=True)
    assert safe == "claude-haiku-4-5-20251001"  # same as normal


def test_privacy_config_persists(tmp_path):
    path = tmp_path / "routing.json"
    r1 = QualityRouter(config_path=path)
    r1.set_privacy(local_only_with_data=True, local_models=["my-model"])

    r2 = QualityRouter(config_path=path)
    privacy = r2.get_privacy()
    assert privacy["local_only_with_data"] is True
    assert "my-model" in privacy["local_models"]


def test_is_model_local(router):
    assert router.is_model_local("qwen2.5:7b") is True
    assert router.is_model_local("qwen2.5:14b") is True
    assert router.is_model_local("claude-sonnet-4-6") is False


def test_full_state_includes_privacy(router):
    state = router.get_full_state()
    assert "privacy" in state
    assert "local_only_with_data" in state["privacy"]


# --- Registry completeness ---


def test_all_actions_have_valid_cluster():
    for action_id, action in ACTION_REGISTRY.items():
        assert action["cluster"] in CLUSTER_REGISTRY, f"{action_id} has invalid cluster {action['cluster']}"


def test_all_actions_have_valid_default_quality():
    for action_id, action in ACTION_REGISTRY.items():
        assert action["default_quality"] in QUALITY_LEVELS, (
            f"{action_id} has invalid quality {action['default_quality']}"
        )


def test_all_profiles_cover_all_levels():
    for name, profile in BUILTIN_PROFILES.items():
        for level in QUALITY_LEVELS:
            assert level in profile, f"Profile {name} missing {level}"
            assert "model" in profile[level], f"Profile {name}[{level}] missing 'model'"
