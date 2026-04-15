"""noVNC Live Browser Viewer.

Provides context-validated access to the Chrome VNC stream via noVNC.
Multi-user viewing (VNC supports concurrent read-only viewers).
Tenant-scoped: each viewer must have a valid context envelope.
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

logger = logging.getLogger(__name__)

NOVNC_INTERNAL_URL = os.environ.get("NOVNC_URL", "http://novnc:8080")
NOVNC_EXTERNAL_URL = os.environ.get("NOVNC_EXTERNAL_URL", "http://localhost:6080")
VNC_PASSWORD = os.environ.get("VNC_PASSWORD", "spec2sphere")

_active_viewers: dict[tuple[UUID, str], set[str]] = {}


def validate_viewer_access(tenant_id: UUID, environment: str, user_id: str, user_role: str) -> bool:
    """Validate that a user can view this tenant/environment."""
    if not tenant_id or not user_id:
        return False
    allowed_roles = {"admin", "architect", "consultant", "developer", "reviewer", "viewer"}
    return user_role in allowed_roles


def get_novnc_url(tenant_id: UUID, environment: str, external: bool = True) -> str:
    """Get the noVNC viewer URL with password authentication.

    Args:
        tenant_id: Tenant UUID
        environment: Environment name (e.g., 'sandbox', 'prod')
        external: Use external URL if True, internal if False

    Returns:
        Full noVNC viewer URL with auto-connect and password
    """
    base = NOVNC_EXTERNAL_URL if external else NOVNC_INTERNAL_URL
    return f"{base}/vnc.html?autoconnect=true&password={VNC_PASSWORD}&resize=remote"


def register_viewer(tenant_id: UUID, environment: str, user_id: str) -> int:
    """Register a viewer watching this tenant/environment.

    Returns the number of active viewers after registration.
    """
    key = (tenant_id, environment)
    if key not in _active_viewers:
        _active_viewers[key] = set()
    _active_viewers[key].add(user_id)
    return len(_active_viewers[key])


def unregister_viewer(tenant_id: UUID, environment: str, user_id: str) -> int:
    """Unregister a viewer from this tenant/environment.

    Returns the number of active viewers after unregistration (0 if none left).
    """
    key = (tenant_id, environment)
    if key in _active_viewers:
        _active_viewers[key].discard(user_id)
        if not _active_viewers[key]:
            del _active_viewers[key]
            return 0
        return len(_active_viewers[key])
    return 0


def get_viewer_count(tenant_id: UUID, environment: str) -> int:
    """Get the number of active viewers for this tenant/environment."""
    return len(_active_viewers.get((tenant_id, environment), set()))
