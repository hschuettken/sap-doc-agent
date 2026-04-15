"""In-app notification system for Spec2Sphere.

Notifications are stored in the notifications table and polled via HTMX (every 30s).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


async def _get_conn() -> asyncpg.Connection:
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to plain dict, serialising timestamps and UUIDs."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "hex") and not isinstance(v, (str, bytes)):
            d[k] = str(v)
    return d


async def create_notification(
    project_id: str,
    user_id: str,
    title: str,
    message: str,
    link: Optional[str] = None,
    notification_type: str = "info",
) -> dict:
    """Create a notification record and return it as a dict."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO notifications (project_id, user_id, title, message, link, notification_type)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            RETURNING *
            """,
            project_id,
            user_id,
            title,
            message,
            link,
            notification_type,
        )
        result = _row_to_dict(row)
        logger.debug("Created notification %s for user %s", result["id"], user_id)
        return result
    finally:
        await conn.close()


async def list_notifications(
    user_id: str,
    unread_only: bool = True,
    limit: int = 20,
) -> list[dict]:
    """List notifications for a user, newest first.

    Args:
        user_id: UUID string of the recipient.
        unread_only: When True (default), only return unread notifications.
        limit: Maximum number of records to return.
    """
    conn = await _get_conn()
    try:
        if unread_only:
            rows = await conn.fetch(
                """
                SELECT * FROM notifications
                WHERE user_id = $1::uuid AND NOT is_read
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM notifications
                WHERE user_id = $1::uuid
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def mark_read(notification_id: str) -> None:
    """Mark a single notification as read."""
    conn = await _get_conn()
    try:
        await conn.execute(
            "UPDATE notifications SET is_read = true WHERE id = $1::uuid",
            notification_id,
        )
    finally:
        await conn.close()


async def mark_all_read(user_id: str) -> None:
    """Mark all notifications for a user as read."""
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "UPDATE notifications SET is_read = true WHERE user_id = $1::uuid AND NOT is_read",
            user_id,
        )
        logger.debug("Marked all read for user %s (%s)", user_id, result)
    finally:
        await conn.close()


async def get_unread_count(user_id: str) -> int:
    """Get count of unread notifications for badge display."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = $1::uuid AND NOT is_read",
            user_id,
        )
        return int(row["cnt"]) if row else 0
    finally:
        await conn.close()
