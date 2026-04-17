"""Pipeline UI routes for Spec2Sphere — thin aggregator.

This module is kept for backwards compatibility with server.py's import:
    from spec2sphere.web.pipeline_routes import create_pipeline_routes

The actual route implementations live in submodules under
spec2sphere/web/pipeline/:
  - pipeline/shared.py               — shared constants + helper utilities
  - pipeline/requirements_routes.py  — pipeline overview + requirements intake
  - pipeline/architecture_routes.py  — HLA architecture + approvals
  - pipeline/notifications_routes.py — notification centre
  - pipeline/techspec_routes.py      — tech spec generation and review
  - pipeline/blueprint_routes.py     — SAC blueprint generation and review
  - pipeline/testspec_routes.py      — test spec editing and review
"""

from __future__ import annotations

from fastapi import APIRouter

from spec2sphere.web.pipeline.requirements_routes import create_requirements_routes
from spec2sphere.web.pipeline.architecture_routes import create_architecture_routes
from spec2sphere.web.pipeline.notifications_routes import create_notifications_routes
from spec2sphere.web.pipeline.techspec_routes import create_techspec_routes
from spec2sphere.web.pipeline.blueprint_routes import create_blueprint_routes
from spec2sphere.web.pipeline.testspec_routes import create_testspec_routes

# Re-export shared constants so any code that imported them from here still works
from spec2sphere.web.pipeline.shared import (  # noqa: F401
    STATUS_CLASSES,
    PIPELINE_STAGES,
    templates,
    _render,
    _get_llm,
    _get_ctx,
    _status_badge,
    _safe_json,
    _str_ids,
)


def create_pipeline_routes() -> APIRouter:
    """Return an APIRouter with all pipeline + notification UI routes."""
    router = APIRouter()

    for sub in (
        create_requirements_routes(),
        create_architecture_routes(),
        create_notifications_routes(),
        create_techspec_routes(),
        create_blueprint_routes(),
        create_testspec_routes(),
    ):
        router.include_router(sub)

    return router
