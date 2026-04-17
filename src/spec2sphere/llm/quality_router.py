"""Quality Router — granular, configurable LLM model routing.

Instead of hardcoded tier→model mappings, the quality router introduces:

1. **Quality Levels (Q1–Q5)**: Abstract capability tiers, model-agnostic.
2. **Model Profiles**: Named mappings from quality level → concrete model.
3. **Action Registry**: Every LLM call site declares its action name; each action
   has a default quality level that can be overridden per-action or per-cluster.

Resolution chain:
    action_override → cluster_override → action_default → profile[quality] → model

Config is persisted in a JSON file (default: /app/llm_routing.json, override via
LLM_ROUTING_CONFIG env var). Only overrides and custom profiles are stored — the
built-in action registry and profiles live in code.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quality levels
# ---------------------------------------------------------------------------

QUALITY_LEVELS: dict[str, dict[str, str]] = {
    "Q1": {"name": "Trivial", "description": "Simple checks, validation, connectivity tests"},
    "Q2": {"name": "Basic", "description": "Classification, rule extraction, pattern matching"},
    "Q3": {"name": "Capable", "description": "Document parsing, code generation, structured analysis"},
    "Q4": {"name": "Expert", "description": "Architecture decisions, complex multi-step reasoning"},
    "Q5": {"name": "Frontier", "description": "Critical decisions, novel problem-solving"},
}

# Map old tier names to quality levels for backward compat
_TIER_TO_QUALITY: dict[str, str] = {
    "small": "Q1",
    "medium": "Q2",
    "large": "Q3",
    "reasoning": "Q4",
}

# ---------------------------------------------------------------------------
# Built-in model profiles
# ---------------------------------------------------------------------------

BUILTIN_PROFILES: dict[str, dict[str, dict[str, str]]] = {
    "default": {
        "Q1": {"model": "qwen2.5:7b"},
        "Q2": {"model": "qwen2.5:14b"},
        "Q3": {"model": "claude-haiku-4-5-20251001"},
        "Q4": {"model": "claude-sonnet-4-6"},
        "Q5": {"model": "claude-sonnet-4-6"},
    },
    "all-local": {
        "Q1": {"model": "qwen2.5:7b"},
        "Q2": {"model": "qwen2.5:7b"},
        "Q3": {"model": "qwen2.5:14b"},
        "Q4": {"model": "qwen2.5:14b"},
        "Q5": {"model": "qwen2.5:14b"},
    },
    "all-claude": {
        "Q1": {"model": "claude-haiku-4-5-20251001"},
        "Q2": {"model": "claude-haiku-4-5-20251001"},
        "Q3": {"model": "claude-sonnet-4-6"},
        "Q4": {"model": "claude-sonnet-4-6"},
        "Q5": {"model": "claude-sonnet-4-6"},
    },
}

# ---------------------------------------------------------------------------
# Cluster registry
# ---------------------------------------------------------------------------

CLUSTER_REGISTRY: dict[str, dict[str, str]] = {
    "pipeline": {
        "display_name": "Pipeline Generation",
        "description": "Core delivery pipeline: parsing, HLA, tech specs, blueprints, tests",
    },
    "migration": {
        "display_name": "Migration Tools",
        "description": "BW migration workflow: classification, interpretation, design, code generation",
    },
    "analysis": {
        "display_name": "Scanning & Analysis",
        "description": "Chain analysis, dependency scanning, document review",
    },
    "standards": {
        "display_name": "Standards Processing",
        "description": "Rule extraction from standards, standards intake & enrichment",
    },
    "system": {
        "display_name": "System",
        "description": "Connectivity tests, health checks, system operations",
    },
}

# ---------------------------------------------------------------------------
# Action registry — every LLM call site in the codebase
# ---------------------------------------------------------------------------

ACTION_REGISTRY: dict[str, dict[str, str]] = {
    # Pipeline
    "semantic_parser": {
        "display_name": "Semantic Parser",
        "cluster": "pipeline",
        "description": "Parse BRS/functional specs into structured requirement models",
        "default_quality": "Q3",
    },
    "hla_generator": {
        "display_name": "HLA Generator",
        "cluster": "pipeline",
        "description": "Generate High-Level Architecture from parsed requirements",
        "default_quality": "Q4",
    },
    "tech_spec_generator": {
        "display_name": "Tech Spec Generator",
        "cluster": "pipeline",
        "description": "Generate detailed technical specifications for DSP objects",
        "default_quality": "Q3",
    },
    "blueprint_generator": {
        "display_name": "Blueprint Generator",
        "cluster": "pipeline",
        "description": "Generate implementation blueprints with SQL/code",
        "default_quality": "Q3",
    },
    "test_generator": {
        "display_name": "Test Generator",
        "cluster": "pipeline",
        "description": "Generate test cases and validation rules",
        "default_quality": "Q3",
    },
    "placement": {
        "display_name": "Placement Engine",
        "cluster": "pipeline",
        "description": "Decide optimal DSP layer placement for objects",
        "default_quality": "Q4",
    },
    # Migration
    "migration_architect": {
        "display_name": "Migration Architect",
        "cluster": "migration",
        "description": "Design migration strategy and target architecture",
        "default_quality": "Q4",
    },
    "migration_generator": {
        "display_name": "Migration Code Generator",
        "cluster": "migration",
        "description": "Generate migration scripts and transformation code",
        "default_quality": "Q3",
    },
    "migration_interpreter": {
        "display_name": "Migration Interpreter",
        "cluster": "migration",
        "description": "Interpret BW transformation logic and map to DSP equivalents",
        "default_quality": "Q3",
    },
    "migration_classifier": {
        "display_name": "Migration Classifier",
        "cluster": "migration",
        "description": "Classify BW objects by migration complexity and approach",
        "default_quality": "Q2",
    },
    "brs_reconciler": {
        "display_name": "BRS Reconciler",
        "cluster": "migration",
        "description": "Reconcile BRS documents against implementation artifacts",
        "default_quality": "Q3",
    },
    # Analysis
    "chain_analyzer": {
        "display_name": "Chain Analyzer",
        "cluster": "analysis",
        "description": "Analyze transformation chain steps and data flow dependencies",
        "default_quality": "Q2",
    },
    "doc_review": {
        "display_name": "Document Review",
        "cluster": "analysis",
        "description": "AI-powered review of documentation quality and completeness",
        "default_quality": "Q3",
    },
    # Standards
    "rule_extractor": {
        "display_name": "Rule Extractor",
        "cluster": "standards",
        "description": "Extract structured rules from standard YAML definitions",
        "default_quality": "Q2",
    },
    "standards_intake": {
        "display_name": "Standards Intake",
        "cluster": "standards",
        "description": "Enrich and validate uploaded standards with AI analysis",
        "default_quality": "Q2",
    },
    # System
    "test_llm": {
        "display_name": "LLM Connectivity Test",
        "cluster": "system",
        "description": "Quick connectivity test to verify LLM provider is reachable",
        "default_quality": "Q1",
    },
}

# ---------------------------------------------------------------------------
# Config file path
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(os.environ.get("LLM_ROUTING_CONFIG", "/app/llm_routing.json"))


def _default_config() -> dict[str, Any]:
    return {
        "active_profile": "default",
        "custom_profiles": {},
        "cluster_overrides": {},
        "action_overrides": {},
        # Privacy-by-design settings
        "privacy": {
            # When True, any LLM call with data_in_context=True is routed
            # exclusively to models in the local_models list below.
            "local_only_with_data": True,
            # Models considered "local" (no data leaves the network).
            # These run on the LLM Router → Ollama, never sent to cloud APIs.
            "local_models": [
                "qwen2.5:7b",
                "qwen2.5:14b",
                "qwen2.5:32b",
            ],
            # Profile to use when data_in_context is True and local_only_with_data
            # is enabled. Must only contain local models.
            "data_safe_profile": "all-local",
        },
    }


# ---------------------------------------------------------------------------
# Quality Router singleton
# ---------------------------------------------------------------------------


class QualityRouter:
    """Resolves action names to concrete model names via quality levels."""

    def __init__(self, config_path: Path | None = None):
        self._path = config_path or _CONFIG_PATH
        self._lock = threading.Lock()
        self._config = _default_config()
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._config = json.loads(self._path.read_text())
                logger.info("Loaded LLM routing config from %s", self._path)
            except Exception as exc:
                logger.warning("Failed to load LLM routing config: %s", exc)
                self._config = _default_config()
        else:
            self._config = _default_config()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._config, indent=2) + "\n")
        except Exception as exc:
            logger.warning("Failed to save LLM routing config: %s", exc)

    # -- resolution ----------------------------------------------------------

    def resolve(self, action_or_tier: str, data_in_context: bool = False) -> str:
        """Resolve an action name, quality level, or legacy tier to a model name.

        When data_in_context=True and local_only_with_data is enabled,
        the data-safe profile is used instead of the active profile —
        ensuring customer data never leaves the local network.

        Returns the concrete model name string (e.g. "claude-sonnet-4-6").
        """
        quality = self.resolve_quality(action_or_tier)
        profile = self._get_effective_profile(data_in_context)
        entry = profile.get(quality, profile.get("Q3", {"model": "qwen2.5:14b"}))
        return entry["model"]

    def _get_effective_profile(self, data_in_context: bool) -> dict[str, dict[str, str]]:
        """Return the profile to use, accounting for privacy settings."""
        defaults = _default_config()["privacy"]
        privacy = self._config.get("privacy", defaults)
        if data_in_context and privacy.get("local_only_with_data", True):
            safe_name = privacy.get("data_safe_profile", "all-local")
            if safe_name in BUILTIN_PROFILES:
                return BUILTIN_PROFILES[safe_name]
            custom = self._config.get("custom_profiles", {})
            if safe_name in custom:
                return custom[safe_name]
            return BUILTIN_PROFILES["all-local"]
        return self.get_active_profile()

    def is_model_local(self, model: str) -> bool:
        """Check whether a model is considered local (no cloud API)."""
        defaults = _default_config()["privacy"]
        local = self._config.get("privacy", defaults).get("local_models", defaults["local_models"])
        return model in local

    def resolve_quality(self, action_or_tier: str) -> str:
        """Resolve an action name or tier to a quality level (Q1-Q5).

        Resolution order:
        1. Known action → action_override or cluster_override or default_quality
        2. Quality level (Q1-Q5) → pass through
        3. Legacy tier (small/medium/large/reasoning) → map to quality
        4. Unknown → Q3 (safe default)
        """
        # 1. Known action
        if action_or_tier in ACTION_REGISTRY:
            action = ACTION_REGISTRY[action_or_tier]
            # Check action-level override
            override = self._config.get("action_overrides", {}).get(action_or_tier)
            if override:
                return override
            # Check cluster-level override
            cluster = action["cluster"]
            cluster_override = self._config.get("cluster_overrides", {}).get(cluster)
            if cluster_override:
                return cluster_override
            # Use action's built-in default
            return action["default_quality"]

        # 2. Already a quality level
        if action_or_tier in QUALITY_LEVELS:
            return action_or_tier

        # 3. Legacy tier name
        if action_or_tier in _TIER_TO_QUALITY:
            return _TIER_TO_QUALITY[action_or_tier]

        # 4. Unknown → safe default
        return "Q3"

    def get_active_profile_name(self) -> str:
        return self._config.get("active_profile", "default")

    def get_active_profile(self) -> dict[str, dict[str, str]]:
        """Return the currently active model profile (quality → model mapping)."""
        name = self.get_active_profile_name()
        if name in BUILTIN_PROFILES:
            return BUILTIN_PROFILES[name]
        custom = self._config.get("custom_profiles", {})
        if name in custom:
            return custom[name]
        return BUILTIN_PROFILES["default"]

    def get_all_profiles(self) -> dict[str, dict[str, dict[str, str]]]:
        """Return all profiles (built-in + custom)."""
        result = dict(BUILTIN_PROFILES)
        result.update(self._config.get("custom_profiles", {}))
        return result

    # -- full state for UI ---------------------------------------------------

    def get_full_state(self) -> dict[str, Any]:
        """Return the complete routing state for the UI."""
        profile = self.get_active_profile()
        actions_with_effective = []
        for action_id, action in ACTION_REGISTRY.items():
            effective_quality = self.resolve_quality(action_id)
            effective_model = profile.get(effective_quality, {}).get("model", "unknown")
            override_source = "default"
            if action_id in self._config.get("action_overrides", {}):
                override_source = "action"
            elif action["cluster"] in self._config.get("cluster_overrides", {}):
                override_source = "cluster"
            actions_with_effective.append(
                {
                    "action_id": action_id,
                    "display_name": action["display_name"],
                    "cluster": action["cluster"],
                    "description": action["description"],
                    "default_quality": action["default_quality"],
                    "effective_quality": effective_quality,
                    "effective_model": effective_model,
                    "override_source": override_source,
                }
            )

        clusters_with_effective = []
        for cluster_id, cluster in CLUSTER_REGISTRY.items():
            override = self._config.get("cluster_overrides", {}).get(cluster_id)
            clusters_with_effective.append(
                {
                    "cluster_id": cluster_id,
                    "display_name": cluster["display_name"],
                    "description": cluster["description"],
                    "quality_override": override,
                }
            )

        return {
            "quality_levels": QUALITY_LEVELS,
            "active_profile": self.get_active_profile_name(),
            "profiles": self.get_all_profiles(),
            "clusters": clusters_with_effective,
            "actions": actions_with_effective,
            "action_overrides": self._config.get("action_overrides", {}),
            "cluster_overrides": self._config.get("cluster_overrides", {}),
            "privacy": self._config.get("privacy", _default_config()["privacy"]),
        }

    # -- mutations -----------------------------------------------------------

    def set_active_profile(self, name: str) -> None:
        with self._lock:
            all_profiles = self.get_all_profiles()
            if name not in all_profiles:
                raise ValueError(f"Unknown profile: {name!r}")
            self._config["active_profile"] = name
            self._save()

    def save_custom_profile(self, name: str, mapping: dict[str, dict[str, str]]) -> None:
        with self._lock:
            if name in BUILTIN_PROFILES:
                raise ValueError(f"Cannot overwrite built-in profile: {name!r}")
            for q in QUALITY_LEVELS:
                if q not in mapping:
                    raise ValueError(f"Profile must define all quality levels, missing: {q}")
            self._config.setdefault("custom_profiles", {})[name] = mapping
            self._save()

    def delete_custom_profile(self, name: str) -> None:
        with self._lock:
            if name in BUILTIN_PROFILES:
                raise ValueError(f"Cannot delete built-in profile: {name!r}")
            self._config.get("custom_profiles", {}).pop(name, None)
            if self._config.get("active_profile") == name:
                self._config["active_profile"] = "default"
            self._save()

    def set_action_override(self, action_id: str, quality: str) -> None:
        with self._lock:
            if action_id not in ACTION_REGISTRY:
                raise ValueError(f"Unknown action: {action_id!r}")
            if quality not in QUALITY_LEVELS:
                raise ValueError(f"Invalid quality level: {quality!r}")
            self._config.setdefault("action_overrides", {})[action_id] = quality
            self._save()

    def clear_action_override(self, action_id: str) -> None:
        with self._lock:
            self._config.get("action_overrides", {}).pop(action_id, None)
            self._save()

    def set_cluster_override(self, cluster_id: str, quality: str) -> None:
        with self._lock:
            if cluster_id not in CLUSTER_REGISTRY:
                raise ValueError(f"Unknown cluster: {cluster_id!r}")
            if quality not in QUALITY_LEVELS:
                raise ValueError(f"Invalid quality level: {quality!r}")
            self._config.setdefault("cluster_overrides", {})[cluster_id] = quality
            self._save()

    def clear_cluster_override(self, cluster_id: str) -> None:
        with self._lock:
            self._config.get("cluster_overrides", {}).pop(cluster_id, None)
            self._save()

    def reset_all_overrides(self) -> None:
        with self._lock:
            self._config["action_overrides"] = {}
            self._config["cluster_overrides"] = {}
            self._config["active_profile"] = "default"
            self._save()

    # -- privacy mutations ---------------------------------------------------

    def set_privacy(
        self,
        local_only_with_data: bool | None = None,
        local_models: list[str] | None = None,
        data_safe_profile: str | None = None,
    ) -> None:
        """Update privacy-by-design settings.

        Raises ValueError if the resulting configuration would send customer
        data to a non-local model (e.g., the chosen data_safe_profile contains
        a model not in the local_models list).
        """
        with self._lock:
            privacy = self._config.setdefault("privacy", _default_config()["privacy"])
            # Apply proposed changes to a working copy, then validate before committing
            new_local_only = (
                local_only_with_data if local_only_with_data is not None else privacy.get("local_only_with_data", True)
            )
            new_local_models = list(local_models) if local_models is not None else list(privacy.get("local_models", []))
            new_safe_profile = (
                data_safe_profile if data_safe_profile is not None else privacy.get("data_safe_profile", "all-local")
            )

            # Validate profile exists
            all_profiles = self.get_all_profiles()
            if new_safe_profile not in all_profiles:
                raise ValueError(f"Unknown profile: {new_safe_profile!r}")

            # Validate every model in the data-safe profile is local (only matters when enforcement is on)
            if new_local_only:
                profile_models = {entry.get("model") for entry in all_profiles[new_safe_profile].values()}
                non_local = [m for m in profile_models if m and m not in new_local_models]
                if non_local:
                    raise ValueError(
                        f"Data-safe profile {new_safe_profile!r} contains non-local models: {non_local}. "
                        f"Either add them to local_models or pick a different profile."
                    )

            # All checks passed — commit
            privacy["local_only_with_data"] = new_local_only
            privacy["local_models"] = new_local_models
            privacy["data_safe_profile"] = new_safe_profile
            self._save()

    def get_privacy(self) -> dict:
        """Return current privacy settings."""
        return self._config.get("privacy", _default_config()["privacy"])

    def reload(self) -> None:
        """Re-read config from disk."""
        with self._lock:
            self._load()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: QualityRouter | None = None
_instance_lock = threading.Lock()


def get_quality_router() -> QualityRouter:
    """Get or create the singleton QualityRouter instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = QualityRouter()
    return _instance
