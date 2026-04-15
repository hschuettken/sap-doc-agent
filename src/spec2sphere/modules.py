"""Module system for Spec2Sphere.

Each module registers its FastAPI routes and Celery tasks only when enabled.
Disabled modules: routes not mounted, tasks not imported, UI sections hidden.

Configuration from config.yaml:
    modules:
      core: true
      migration_accelerator: true
      dsp_factory: true
      sac_factory: true
      governance: true
      artifact_lab: true
      multi_tenant: false  # true = full multi-tenant mode
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModuleSpec:
    """Descriptor for a Spec2Sphere module."""

    name: str
    description: str
    enabled: bool = False
    routes_factory: Optional[Callable] = None  # () -> APIRouter
    celery_tasks_module: Optional[str] = None  # dotted module path to import when enabled
    ui_sections: list[str] = field(default_factory=list)


# Global module registry
_REGISTRY: dict[str, ModuleSpec] = {}


def register_module(spec: ModuleSpec) -> None:
    """Register a module. Called at import time by each module package."""
    _REGISTRY[spec.name] = spec
    logger.debug("Registered module: %s (enabled=%s)", spec.name, spec.enabled)


def get_module(name: str) -> Optional[ModuleSpec]:
    return _REGISTRY.get(name)


def is_enabled(name: str) -> bool:
    spec = _REGISTRY.get(name)
    return spec.enabled if spec else False


def list_modules() -> list[ModuleSpec]:
    return list(_REGISTRY.values())


# ---------------------------------------------------------------------------
# Default module definitions (registered at import time)
# ---------------------------------------------------------------------------

_DEFAULT_MODULES = [
    ModuleSpec(
        name="core",
        description="Core scanning, documentation, knowledge base, and design system",
        enabled=True,  # always on
        ui_sections=["scanner", "knowledge", "standards", "docs"],
    ),
    ModuleSpec(
        name="migration_accelerator",
        description="BW semantic interpretation, debt classification, migration reports",
        ui_sections=["migration"],
        celery_tasks_module="spec2sphere.tasks.migration_tasks",
    ),
    ModuleSpec(
        name="dsp_factory",
        description="DSP artifact generation, deployment, reconciliation",
        ui_sections=["dsp_factory"],
        celery_tasks_module="spec2sphere.tasks.factory_tasks",
    ),
    ModuleSpec(
        name="sac_factory",
        description="SAC blueprint to multi-route execution, visual/data/interaction QA",
        ui_sections=["sac_factory"],
    ),
    ModuleSpec(
        name="governance",
        description="Approval workflow, confidence scoring, traceability, RBAC",
        ui_sections=["governance", "approvals"],
    ),
    ModuleSpec(
        name="artifact_lab",
        description="Sandbox experimentation, template learning, route fitness tracking",
        ui_sections=["artifact_lab"],
    ),
    ModuleSpec(
        name="multi_tenant",
        description="Multi-tenant workspace switching, tenant/customer/project CRUD",
        ui_sections=["workspace_switcher", "tenant_admin"],
    ),
]

for _m in _DEFAULT_MODULES:
    register_module(_m)


def configure_modules(config: dict[str, Any]) -> None:
    """Apply module enable/disable flags from parsed config.yaml modules section.

    Also reads ENABLED_MODULES env var (comma-separated) as override.
    Core is always enabled regardless of config.
    """
    env_override = os.environ.get("ENABLED_MODULES", "")
    env_enabled = {m.strip() for m in env_override.split(",") if m.strip()} if env_override else None

    for name, spec in _REGISTRY.items():
        if name == "core":
            spec.enabled = True
            continue

        if env_enabled is not None:
            spec.enabled = name in env_enabled
        else:
            spec.enabled = bool(config.get(name, False))

        logger.info("Module %s: %s", name, "ENABLED" if spec.enabled else "disabled")


def mount_enabled_routes(app) -> None:
    """Mount routes for all enabled modules onto the FastAPI app.

    Called from app lifespan after configure_modules().
    """
    for name, spec in _REGISTRY.items():
        if spec.enabled and spec.routes_factory is not None:
            try:
                router = spec.routes_factory()
                app.include_router(router)
                logger.info("Mounted routes for module: %s", name)
            except Exception as exc:
                logger.warning("Failed to mount routes for module %s: %s", name, exc)


def get_enabled_ui_sections() -> list[str]:
    """Return the union of all enabled modules' UI sections."""
    sections: list[str] = []
    for spec in _REGISTRY.values():
        if spec.enabled:
            sections.extend(spec.ui_sections)
    return sections
