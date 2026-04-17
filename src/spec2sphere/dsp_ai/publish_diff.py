"""Compute user-impact diff between the last-published config and a candidate."""

from __future__ import annotations

import json

from .db import get_conn


# Keys whose change alters output shape / data binding — breaks downstream widgets.
_BREAKING_KEYS = ("output_schema", "render_hint", "kind", "mode", "data_binding", "semantic_binding")


async def diff(enhancement_id: str) -> dict:
    """Diff the current (candidate) config against the last published version.

    Returns:
        {
          "has_prior_publish": bool,
          "current_status": str,               # draft | published | paused
          "candidate_config": dict,             # the current config (what Publish would activate)
          "active_config": dict | None,         # config at last publish (None if never published)
          "active_users": list[str],            # distinct users who've received a briefing from this id
          "user_count": int,
          "changes": {key: {"from": ..., "to": ...}},
          "breaking": bool,
          "summary": list[str],                 # human-readable messages
        }
    """
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT status, config FROM dsp_ai.enhancements WHERE id = $1::uuid",
            enhancement_id,
        )
        if row is None:
            raise LookupError(enhancement_id)
        candidate = _as_dict(row["config"])

        audit = await conn.fetchrow(
            """
            SELECT before, after, timestamp
              FROM dsp_ai.studio_audit
             WHERE enhancement_id = $1::uuid
               AND action = 'publish'
             ORDER BY timestamp DESC
             LIMIT 1
            """,
            enhancement_id,
        )

        users_rows = await conn.fetch(
            "SELECT DISTINCT user_id FROM dsp_ai.briefings WHERE enhancement_id = $1::uuid",
            enhancement_id,
        )

    active_config = None
    if audit:
        # publish audit stores config_at_publish under 'after' in richer deployments;
        # older rows only store {"status": "published"}. Try to enrich via earlier logic,
        # else fall back to "no snapshot available".
        after = _as_dict(audit["after"])
        if isinstance(after.get("config"), dict):
            active_config = after["config"]

    if active_config is None:
        changes: dict = {}
        breaking = False
        summary: list[str] = []
    else:
        changes = _config_delta(active_config, candidate)
        breaking = _is_breaking(changes)
        summary = _humanize(changes)

    return {
        "has_prior_publish": bool(audit),
        "current_status": row["status"],
        "candidate_config": candidate,
        "active_config": active_config,
        "active_users": [r["user_id"] for r in users_rows],
        "user_count": len(users_rows),
        "changes": changes,
        "breaking": breaking,
        "summary": summary,
    }


def _as_dict(v) -> dict:
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


def _config_delta(a: dict, b: dict) -> dict:
    out: dict = {}
    for k in set(a) | set(b):
        if a.get(k) != b.get(k):
            out[k] = {"from": a.get(k), "to": b.get(k)}
    return out


def _is_breaking(changes: dict) -> bool:
    return any(k in changes for k in _BREAKING_KEYS)


_HUMAN_MESSAGES = {
    "prompt_template": "Prompt template changed — expect different wording in new outputs.",
    "render_hint": "Render hint changed — SAC story widgets may need re-binding.",
    "output_schema": "Output schema changed — downstream widgets consuming typed fields may break.",
    "data_binding": "Data binding (dsp_query) changed — content will shift.",
    "semantic_binding": "Semantic binding changed — Brain-derived context will shift.",
    "adaptive_rules": "Adaptive rules changed — caching / refresh cadence may differ.",
    "kind": "Enhancement kind changed — write-back tables and widget renderer differ.",
    "mode": "Enhancement mode (live vs batch) changed — delivery path differs.",
}


def _humanize(changes: dict) -> list[str]:
    msgs: list[str] = []
    for k, v in changes.items():
        if k in _HUMAN_MESSAGES:
            if k == "render_hint":
                msgs.append(f"Render hint changed: {v['from']} → {v['to']}. SAC widgets may need re-binding.")
            elif k == "kind":
                msgs.append(f"Kind changed: {v['from']} → {v['to']}. This is a BREAKING change.")
            else:
                msgs.append(_HUMAN_MESSAGES[k])
        else:
            msgs.append(f"{k} changed.")
    return msgs
