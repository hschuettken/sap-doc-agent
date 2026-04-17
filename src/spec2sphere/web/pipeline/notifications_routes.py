"""Pipeline UI routes: notification centre."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .shared import _get_ctx, _render, _str_ids

logger = logging.getLogger(__name__)


def create_notifications_routes() -> APIRouter:
    """Return an APIRouter with notification centre routes."""
    router = APIRouter()

    # ── Notifications ─────────────────────────────────────────────────────────

    @router.get("/ui/notifications", response_class=HTMLResponse)
    async def notifications_list(request: Request):
        """Notification list — HTMX partial."""
        notifications: list[dict] = []
        unread_count: int = 0
        error: Optional[str] = None
        unread_only = request.query_params.get("unread_only", "false") == "true"

        try:
            from spec2sphere.governance.notifications import list_notifications, get_unread_count

            ctx = await _get_ctx()
            uid = str(ctx.user_id)
            notifications = await list_notifications(
                user_id=uid,
                unread_only=unread_only,
                limit=30,
            )
            unread_count = await get_unread_count(uid)
            for n in notifications:
                _str_ids(n)
        except Exception as exc:
            logger.warning("Notifications load error: %s", exc)
            error = str(exc)

        return _render(
            request,
            "partials/notifications.html",
            {
                "active_page": "notifications",
                "notifications": notifications,
                "unread_count": unread_count,
                "unread_only": unread_only,
                "error": error,
            },
        )

    @router.get("/ui/notifications/badge", response_class=HTMLResponse)
    async def notifications_badge(request: Request):
        """Badge count fragment — polled by topbar every 30s."""
        try:
            from spec2sphere.governance.notifications import get_unread_count

            ctx = await _get_ctx()
            count = await get_unread_count(str(ctx.user_id))
            if count > 0:
                return HTMLResponse(
                    f'<a href="/ui/notifications" class="relative inline-flex">'
                    f'<svg class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                    f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" '
                    f'd="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>'
                    f"</svg>"
                    f'<span class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center font-bold">'
                    f"{min(count, 9)}{'+' if count > 9 else ''}"
                    f"</span>"
                    f"</a>"
                )
            return HTMLResponse(
                '<svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" '
                'd="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>'
                "</svg>"
            )
        except Exception:
            return HTMLResponse("")

    @router.post("/ui/notifications/{notif_id}/read", response_class=HTMLResponse)
    async def mark_notification_read(notif_id: str, request: Request):
        """Mark a notification as read. Returns empty — HTMX outerHTML swap removes it."""
        try:
            from spec2sphere.governance.notifications import mark_read

            await mark_read(notif_id)
        except Exception as exc:
            logger.warning("Mark read %s failed: %s", notif_id, exc)
        return HTMLResponse("")

    return router
