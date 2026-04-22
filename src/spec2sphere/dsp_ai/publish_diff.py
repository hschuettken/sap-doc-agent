"""Compute user-impact diff between an active published enhancement and a draft candidate.

Used by the AI Studio publish flow: before writing the "published" status,
call diff() and show the modal. If breaking=True, the UI warns loudly.
"""

from __future__ import annotations

import json

import asyncpg

from .settings import postgres_dsn

# Keys whose change may break downstream SAC stories or widgets
_BREAKING_KEYS = frozenset({"output_schema", "render_hint", "kind", "mode"})


async def diff(enhancement_id: str, candidate_config: dict) -> dict:
    """Return a diff summary between the currently stored config and *candidate_config*.

    Returns::

        {
            "active_users": [user_id, ...],
            "user_count": int,
            "changes": {"key": {"from": old, "to": new}, ...},
            "breaking": bool,
            "summary": ["human sentence", ...],
        }
    """
    conn = await asyncpg.connect(postgres_dsn())
    try:
        enh_row = await conn.fetchrow(
            "SELECT config FROM dsp_ai.enhancements WHERE id = $1::uuid",
            enhancement_id,
        )
        if enh_row is None:
            # New enhancement — no active users, no changes to compare
            return {
                "active_users": [],
                "user_count": 0,
                "changes": {},
                "breaking": False,
                "summary": ["New enhancement — no existing published version to diff against."],
            }

        raw_config = enh_row["config"]
        active_config: dict = raw_config if isinstance(raw_config, dict) else json.loads(raw_config)

        user_rows = await conn.fetch(
            "SELECT DISTINCT user_id FROM dsp_ai.briefings WHERE enhancement_id = $1::uuid",
            enhancement_id,
        )
        active_users = [r["user_id"] for r in user_rows if r["user_id"]]
    finally:
        await conn.close()

    changes = _config_delta(active_config, candidate_config)
    breaking = _is_breaking(changes)
    return {
        "active_users": active_users,
        "user_count": len(active_users),
        "changes": changes,
        "breaking": breaking,
        "summary": _humanize(changes),
    }


def _config_delta(a: dict, b: dict) -> dict:
    out: dict = {}
    for k in set(a) | set(b):
        v_a, v_b = a.get(k), b.get(k)
        if v_a != v_b:
            out[k] = {"from": v_a, "to": v_b}
    return out


def _is_breaking(changes: dict) -> bool:
    return bool(changes.keys() & _BREAKING_KEYS)


def _humanize(changes: dict) -> list[str]:
    msgs: list[str] = []
    for k, v in changes.items():
        if k == "prompt_template":
            msgs.append("Prompt template changed — expect different wording in new outputs.")
        elif k == "render_hint":
            msgs.append(
                f"Render hint: {v['from']!r} → {v['to']!r}. "
                "SAC story widgets may need re-binding."
            )
        elif k == "output_schema":
            msgs.append(
                "Output schema changed — downstream widgets consuming typed fields may break."
            )
        elif k == "kind":
            msgs.append(
                f"Enhancement kind changed: {v['from']!r} → {v['to']!r}. "
                "Existing SAC stories will stop rendering correctly."
            )
        elif k == "mode":
            msgs.append(
                f"Mode changed: {v['from']!r} → {v['to']!r}. "
                "Batch-only enhancements will no longer respond to live requests."
            )
        elif k == "bindings":
            msgs.append("Data or semantic bindings changed — content will shift.")
        else:
            msgs.append(f"{k!r} changed.")
    if not msgs:
        msgs.append("No significant changes detected.")
    return msgs
