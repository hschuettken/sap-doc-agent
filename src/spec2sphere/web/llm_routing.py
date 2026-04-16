"""LLM Routing API — REST endpoints for the quality routing system.

Exposes CRUD operations for model profiles, per-action and per-cluster
quality overrides, and live resolution queries.  All routes live under
/api/llm-routing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from spec2sphere.llm.quality_router import get_quality_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm-routing", tags=["llm-routing"])


# ---------------------------------------------------------------------------
# Request body models


class SetProfileRequest(BaseModel):
    name: str


class ProfileMappingEntry(BaseModel):
    model: str


class SaveProfileRequest(BaseModel):
    Q1: Optional[ProfileMappingEntry] = None
    Q2: Optional[ProfileMappingEntry] = None
    Q3: Optional[ProfileMappingEntry] = None
    Q4: Optional[ProfileMappingEntry] = None
    Q5: Optional[ProfileMappingEntry] = None


class QualityOverrideRequest(BaseModel):
    quality: str  # "Q1" … "Q5"


class ResolveRequest(BaseModel):
    action: str


# ---------------------------------------------------------------------------
# Helper


def _qr():
    """Return the quality router singleton."""
    return get_quality_router()


# ---------------------------------------------------------------------------
# Endpoints


@router.get("/")
async def get_full_state() -> Dict[str, Any]:
    """Return the full routing state: profiles, active profile, overrides, registry."""
    return _qr().get_full_state()


@router.put("/profile")
async def set_active_profile(body: SetProfileRequest) -> Dict[str, Any]:
    """Switch the active model profile by name."""
    try:
        _qr().set_active_profile(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "active_profile": body.name}


@router.put("/profiles/{name}")
async def save_custom_profile(name: str, body: SaveProfileRequest) -> Dict[str, Any]:
    """Create or update a custom model profile.

    Body keys Q1–Q5 each accept ``{"model": "<model-id>"}``.
    """
    mapping: Dict[str, Dict[str, str]] = {}
    for level in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        entry = getattr(body, level, None)
        if entry is not None:
            mapping[level] = {"model": entry.model}
    try:
        _qr().save_custom_profile(name, mapping)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "profile": name}


@router.delete("/profiles/{name}")
async def delete_custom_profile(name: str) -> Dict[str, Any]:
    """Delete a custom profile.  Built-in profiles cannot be deleted."""
    try:
        _qr().delete_custom_profile(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "deleted": name}


@router.put("/actions/{action_id}/override")
async def set_action_override(action_id: str, body: QualityOverrideRequest) -> Dict[str, Any]:
    """Pin a specific action to a quality level, ignoring its default."""
    try:
        _qr().set_action_override(action_id, body.quality)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "action": action_id, "quality": body.quality}


@router.delete("/actions/{action_id}/override")
async def clear_action_override(action_id: str) -> Dict[str, Any]:
    """Remove the quality override for an action, restoring its default."""
    try:
        _qr().clear_action_override(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "action": action_id}


@router.put("/clusters/{cluster_id}/override")
async def set_cluster_override(cluster_id: str, body: QualityOverrideRequest) -> Dict[str, Any]:
    """Pin all actions in a cluster to a quality level."""
    try:
        _qr().set_cluster_override(cluster_id, body.quality)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "cluster": cluster_id, "quality": body.quality}


@router.delete("/clusters/{cluster_id}/override")
async def clear_cluster_override(cluster_id: str) -> Dict[str, Any]:
    """Remove the quality override for a cluster."""
    try:
        _qr().clear_cluster_override(cluster_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "cluster": cluster_id}


@router.post("/reset")
async def reset_all_overrides() -> Dict[str, Any]:
    """Clear all action and cluster overrides, restoring defaults."""
    _qr().reset_all_overrides()
    return {"ok": True}


@router.post("/resolve")
async def resolve_action(body: ResolveRequest) -> Dict[str, Any]:
    """Resolve an action name (or tier) to its current quality level and model.

    Returns ``{"action": "...", "quality": "Q3", "model": "claude-haiku-..."}``.
    """
    qr = _qr()
    quality = qr.resolve_quality(body.action)
    model = qr.resolve(body.action)
    return {"action": body.action, "quality": quality, "model": model}


@router.post("/reload")
async def reload_config() -> Dict[str, Any]:
    """Re-read the routing config from disk without restarting the service."""
    try:
        _qr().reload()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Reload failed: {exc}") from exc
    return {"ok": True}
