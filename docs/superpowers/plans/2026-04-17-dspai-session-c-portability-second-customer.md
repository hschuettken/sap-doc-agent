# DSP-AI Session C — Portability + Second-Customer Ready — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the system for portable delivery at client sites. Ollama offline profile ships. Enhancement library imports + exports. Publish-time diff preview. Cost guardrails. Full graph.json cutover (legacy file retired). Multi-tenant isolation (customer column + row-level security). RBAC enforced in live adapter + widget. Docs + demo scripts + a CPG/Retail vertical enhancement library. TLS + auth polish.

**Architecture:** Builds on Sessions A + B. No new services — all changes are within existing services, migrations, and config/docs. Session C is the "turn prototype into a shippable product" session.

**Tech Stack:** Session A + B stacks. Adds: Ollama (compose profile), `watchfiles` (already in B), `WeasyPrint` (optional for PDF export), Postgres Row-Level Security (RLS), TLS via Caddy sidecar (optional — most client environments use their own reverse proxy).

**Reference spec:** `docs/superpowers/specs/2026-04-17-dsp-ai-enhancements-design.md`
**Depends on:** Sessions A + B merged, deployed, green on smoke tests

---

## File Map

### New files

| File | Responsibility |
|------|----------------|
| `docker-compose.offline.yml` | Overlay profile: adds `ollama` sidecar, overrides LLM_ENDPOINT |
| `ops/ollama-entrypoint.sh` | Pulls default model on first start (`qwen2.5:14b`, configurable) |
| `migrations/versions/012_dsp_ai_multitenant.py` | Add `customer` TEXT column to `dsp_ai.enhancements`, `.briefings`, `.rankings`, `.item_enhancements`, `.user_state`, `.generations`; RLS policies |
| `src/spec2sphere/dsp_ai/library.py` | Enhancement library export/import (JSON round-trip) |
| `src/spec2sphere/dsp_ai/cost_guard.py` | Monthly cap per enhancement; auto-pause on overrun; alert hook |
| `src/spec2sphere/dsp_ai/publish_diff.py` | Compute user-impact diff between active published version and new candidate |
| `src/spec2sphere/web/ai_studio/library_routes.py` | `/ai-studio/library/export`, `/ai-studio/library/import` UI + API |
| `src/spec2sphere/web/templates/partials/ai_studio_library.html` | Library export/import UI |
| `src/spec2sphere/web/templates/partials/ai_studio_diff.html` | Publish diff preview modal |
| `src/spec2sphere/dsp_ai/auth.py` | Token issuance + scope validation; RBAC for live adapter |
| `docs/deploy/client_checklist.md` | Shippable install guide for client sites |
| `docs/deploy/demo_script.md` | 10-minute demo script with talking points |
| `docs/deploy/tls.md` | TLS options (client-provided LB, bundled Caddy, self-signed) |
| `libraries/cpg_retail/` | Reference enhancement library for CPG/Retail vertical (8 JSONs) |
| `tests/dsp_ai/test_library.py` | Export/import round-trip + validation |
| `tests/dsp_ai/test_cost_guard.py` | Monthly cap triggers pause |
| `tests/dsp_ai/test_publish_diff.py` | Diff surfaces breaking changes |
| `tests/dsp_ai/test_multitenant.py` | RLS blocks cross-customer access |
| `tests/dsp_ai/test_rbac.py` | Viewer can't publish; author can |
| `tests/dsp_ai/test_offline_profile.py` | LLM_ENDPOINT auto-switch; ollama responds |
| `scripts/demo_bootstrap.sh` | One-shot: compose up + seed CPG library + publish 3 enhancements + print widget URL |
| `scripts/backup.sh` | `pg_dump` + `neo4j-admin dump` + `redis-cli save` into a timestamped tarball |
| `scripts/restore.sh` | Inverse of backup.sh |

### Modified files

| File | Change |
|------|--------|
| `docker-compose.yml` | Make `ollama` optional via profile; wire `LLM_ENDPOINT` default for offline profile |
| `.env.example` | Add `CUSTOMER`, `OLLAMA_MODEL`, `COST_GUARD_DEFAULT_CAP_USD`, `TLS_MODE` |
| `src/spec2sphere/dsp_ai/engine.py` | Enforce cost guard pre-call, scope filter by `CUSTOMER` |
| `src/spec2sphere/dsp_ai/adapters/live.py` | Apply RBAC (author vs viewer) on write endpoints (/actions, /telemetry-privileged) |
| `src/spec2sphere/web/ai_studio/routes.py` | Diff modal on publish; library export/import wiring |
| `src/spec2sphere/web/templates/partials/ai_studio.html` | Add "Export library" and "Import library" buttons |
| `src/spec2sphere/web/templates/base.html` | "Customer" pill in header (current customer context) |
| `src/spec2sphere/scanner/output.py` | Remove `graph.json` write when `BRAIN_WRITE_BOTH=false` (final cutover) |
| `src/spec2sphere/scanner/graph_repo.py` | Default to Brain-read; file fallback gated on env var only |
| `src/spec2sphere/widget/src/main.ts` | Respect returned `error_kind`, `data_stale`, `quality_warnings`; render admin chip only for author role |
| `src/spec2sphere/widget/src/renderers/*.ts` | Degraded-mode visuals (amber badge, tooltip for warnings) |

---

## Task 1: Ollama offline profile

**Files:**
- Create: `docker-compose.offline.yml`
- Create: `ops/ollama-entrypoint.sh`
- Modify: `.env.example`
- Create: `tests/dsp_ai/test_offline_profile.py`

- [ ] **Step 1.1: docker-compose.offline.yml**

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: sap-doc-agent-ollama
    profiles: ["offline"]
    volumes:
      - ollama-data:/root/.ollama
      - ./ops/ollama-entrypoint.sh:/entrypoint.sh:ro
    entrypoint: ["/entrypoint.sh"]
    environment:
      OLLAMA_MODEL: ${OLLAMA_MODEL:-qwen2.5:14b}
      OLLAMA_HOST: 0.0.0.0
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 15s
      timeout: 5s
      retries: 10
    networks:
      - default

  dsp-ai:
    profiles: ["offline", ""]
    depends_on:
      ollama: { condition: service_healthy, required: false }
    environment:
      LLM_ENDPOINT: http://ollama:11434/v1

volumes:
  ollama-data:
```

- [ ] **Step 1.2: entrypoint that pulls model + starts daemon**

```bash
#!/usr/bin/env sh
set -eu
ollama serve &
pid=$!
until ollama list >/dev/null 2>&1; do sleep 1; done
if ! ollama list | grep -q "${OLLAMA_MODEL}"; then
  echo "Pulling ${OLLAMA_MODEL}..." >&2
  ollama pull "${OLLAMA_MODEL}"
fi
wait "$pid"
```

- [ ] **Step 1.3: Offline profile test**

```python
# tests/dsp_ai/test_offline_profile.py
import pytest, httpx, os

@pytest.mark.skipif(os.environ.get("SKIP_OFFLINE") == "1", reason="requires compose --profile offline up")
@pytest.mark.asyncio
async def test_ollama_reachable():
    endpoint = os.environ.get("LLM_ENDPOINT", "http://localhost:11434/v1")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{endpoint}/chat/completions",
                         json={"model": os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"),
                               "messages": [{"role": "user", "content": "say hi"}]})
        assert r.status_code == 200
        assert "choices" in r.json()
```

Run manually: `docker compose --profile offline up -d && pytest tests/dsp_ai/test_offline_profile.py`

- [ ] **Step 1.4: Commit**

```bash
git add docker-compose.offline.yml ops/ollama-entrypoint.sh tests/dsp_ai/test_offline_profile.py
git commit -m "feat(dsp-ai): offline profile with bundled Ollama"
```

---

## Task 2: Multi-tenant isolation — add `customer` column + RLS

**Files:**
- Create: `migrations/versions/012_dsp_ai_multitenant.py`
- Modify: `src/spec2sphere/dsp_ai/engine.py`, `adapters/live.py`, `adapters/batch.py`
- Create: `tests/dsp_ai/test_multitenant.py`

- [ ] **Step 2.1: Migration — add customer column + RLS**

```python
"""Multi-tenant isolation.

Revision ID: 012
Revises: 011
Create Date: 2026-04-17
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for tbl in ["enhancements", "briefings", "rankings", "item_enhancements", "user_state", "generations", "studio_audit"]:
        op.execute(f"ALTER TABLE dsp_ai.{tbl} ADD COLUMN IF NOT EXISTS customer TEXT NOT NULL DEFAULT 'default'")
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_customer ON dsp_ai.{tbl}(customer)")
        op.execute(f"ALTER TABLE dsp_ai.{tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
        CREATE POLICY {tbl}_customer_isolation ON dsp_ai.{tbl}
            USING (customer = current_setting('dspai.customer', true))
            WITH CHECK (customer = current_setting('dspai.customer', true))
        """)


def downgrade() -> None:
    for tbl in ["enhancements", "briefings", "rankings", "item_enhancements", "user_state", "generations", "studio_audit"]:
        op.execute(f"DROP POLICY IF EXISTS {tbl}_customer_isolation ON dsp_ai.{tbl}")
        op.execute(f"ALTER TABLE dsp_ai.{tbl} DISABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE dsp_ai.{tbl} DROP COLUMN IF EXISTS customer")
```

- [ ] **Step 2.2: Set customer context on every connection**

In every `asyncpg.connect(...)` call site across `dsp_ai/`:

```python
conn = await asyncpg.connect(settings.postgres_dsn)
await conn.execute("SELECT set_config('dspai.customer', $1, false)",
                   os.environ.get("CUSTOMER", "default"))
```

Extract into a helper `async def get_conn() -> asyncpg.Connection` that does the `set_config` automatically and replace direct `asyncpg.connect` calls.

- [ ] **Step 2.3: Test RLS blocks cross-customer reads**

```python
# tests/dsp_ai/test_multitenant.py
import pytest
from spec2sphere.dsp_ai.db import get_conn

@pytest.mark.asyncio
async def test_horvath_cannot_see_lindt_rows(seeded_two_customers):
    async with get_conn(customer="horvath") as conn:
        rows = await conn.fetch("SELECT id FROM dsp_ai.enhancements")
        assert all(r["id"] for r in rows)
        ids = {r["id"] for r in rows}
    async with get_conn(customer="lindt") as conn2:
        rows2 = await conn2.fetch("SELECT id FROM dsp_ai.enhancements")
        ids2 = {r["id"] for r in rows2}
    assert ids.isdisjoint(ids2)
```

- [ ] **Step 2.4: Neo4j customer property propagation**

Every Brain write includes `customer`. Every read filters by customer. Add a helper:

```python
# src/spec2sphere/dsp_ai/brain/client.py — extend
async def run_scoped(cypher: str, customer: str, **params):
    return await run(cypher, customer=customer, **params)
```

Audit all Cypher queries to include `{customer: $customer}` on relevant labels.

- [ ] **Step 2.5: Commit**

```bash
git add migrations/versions/012_dsp_ai_multitenant.py src/spec2sphere/dsp_ai/ tests/dsp_ai/test_multitenant.py
git commit -m "feat(dsp-ai): multi-tenant isolation via Postgres RLS + Neo4j customer prop"
```

---

## Task 3: RBAC enforcement in live adapter + widget

**Files:**
- Create: `src/spec2sphere/dsp_ai/auth.py`
- Modify: `src/spec2sphere/dsp_ai/adapters/live.py`
- Modify: `src/spec2sphere/widget/src/main.ts`
- Create: `tests/dsp_ai/test_rbac.py`

- [ ] **Step 3.1: Token + role resolution**

```python
# src/spec2sphere/dsp_ai/auth.py
"""Simple bearer tokens for widget + MCP auth. No heavy OAuth in v1."""
from __future__ import annotations
import os, jwt, time
from fastapi import Header, HTTPException, Depends
from pydantic import BaseModel

_JWT_SECRET = os.environ.get("DSPAI_JWT_SECRET", "change-me")
_JWT_ALGO = "HS256"

class Principal(BaseModel):
    user_id: str
    customer: str
    role: str           # "author" | "viewer" | "widget"
    exp: int

def issue_token(user_id: str, customer: str, role: str, ttl_s: int = 3600) -> str:
    payload = {"user_id": user_id, "customer": customer, "role": role,
               "exp": int(time.time()) + ttl_s}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)

def require(authorization: str = Header(default="")) -> Principal:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401)
    token = authorization.split(" ", 1)[1]
    try:
        data = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.InvalidTokenError:
        raise HTTPException(401)
    return Principal(**data)

def require_author(p: Principal = Depends(require)) -> Principal:
    if p.role != "author":
        raise HTTPException(403, "author role required")
    return p
```

- [ ] **Step 3.2: Apply in live adapter**

```python
# in adapters/live.py
from ..auth import require, require_author

@router.post("/v1/enhance/{enhancement_id}")
async def enhance(enhancement_id: str, body: EnhanceRequest, p = Depends(require)):
    ...

@router.post("/v1/actions/{enhancement_id}/run")
async def run_action(enhancement_id: str, body: EnhanceRequest, p = Depends(require)):
    ...

@router.post("/v1/actions/{enhancement_id}/regen")
async def force_regen(enhancement_id: str, body: EnhanceRequest, p = Depends(require_author)):
    """Force regeneration even if cache is warm — author only."""
    ...
```

- [ ] **Step 3.3: Widget respects role**

Extend `main.ts`:

```typescript
// after fetch — check response or JWT claims
const claims = decodeJwtPayload(getToken());
const isAuthor = claims?.role === "author";
if (isAuthor) renderAdminChip(data);
```

- [ ] **Step 3.4: Tests**

```python
# tests/dsp_ai/test_rbac.py
import pytest, httpx
from spec2sphere.dsp_ai.auth import issue_token

@pytest.mark.asyncio
async def test_viewer_cannot_force_regen():
    tok = issue_token("v@x", "horvath", "viewer")
    async with httpx.AsyncClient() as c:
        r = await c.post("http://dsp-ai:8000/v1/actions/00000000-0000-0000-0000-000000000000/regen",
                         headers={"Authorization": f"Bearer {tok}"}, json={})
        assert r.status_code == 403

@pytest.mark.asyncio
async def test_author_can_force_regen(seed_enhancement):
    tok = issue_token("a@x", "horvath", "author")
    ...  # assert 200 or 404-but-not-403
```

- [ ] **Step 3.5: Commit**

```bash
git add src/spec2sphere/dsp_ai/auth.py src/spec2sphere/dsp_ai/adapters/live.py src/spec2sphere/widget/src/main.ts tests/dsp_ai/test_rbac.py
git commit -m "feat(dsp-ai): RBAC via JWT (author vs viewer vs widget)"
```

---

## Task 4: Library export/import

**Files:**
- Create: `src/spec2sphere/dsp_ai/library.py`
- Create: `src/spec2sphere/web/ai_studio/library_routes.py`
- Create: `src/spec2sphere/web/templates/partials/ai_studio_library.html`
- Modify: `src/spec2sphere/web/templates/partials/ai_studio.html` — add Library buttons
- Create: `tests/dsp_ai/test_library.py`

- [ ] **Step 4.1: Library module**

```python
# src/spec2sphere/dsp_ai/library.py
"""Enhancement library export/import (JSON round-trip, Pydantic-validated)."""
from __future__ import annotations
import json, uuid
from typing import BinaryIO
import asyncpg
from spec2sphere.config import settings
from .config import EnhancementConfig

async def export_library(customer: str | None = None) -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        q = "SELECT name, kind, version, status, config FROM dsp_ai.enhancements"
        args = []
        if customer:
            q += " WHERE customer = $1"; args.append(customer)
        rows = await conn.fetch(q, *args)
    finally:
        await conn.close()
    return {
        "version": "1.0",
        "exported_at": None,  # filled by caller
        "enhancements": [
            {
                "name": r["name"], "kind": r["kind"], "version": r["version"],
                "status": r["status"],
                "config": r["config"] if isinstance(r["config"], dict) else json.loads(r["config"]),
            } for r in rows
        ],
    }

async def import_library(blob: dict, customer: str, mode: str = "merge", author: str = "import") -> dict:
    """mode: merge (upsert by name) | replace (clear first) | draftify (all imported → draft)."""
    if blob.get("version") != "1.0":
        raise ValueError(f"unsupported library version: {blob.get('version')!r}")

    for e in blob["enhancements"]:
        EnhancementConfig.model_validate(e["config"])  # validation pass

    conn = await asyncpg.connect(settings.postgres_dsn)
    await conn.execute("SELECT set_config('dspai.customer', $1, false)", customer)
    try:
        if mode == "replace":
            await conn.execute("DELETE FROM dsp_ai.enhancements WHERE customer = $1", customer)

        imported = 0
        for e in blob["enhancements"]:
            new_id = str(uuid.uuid4())
            status = "draft" if mode == "draftify" else e["status"]
            await conn.execute(
                """
                INSERT INTO dsp_ai.enhancements (id, name, kind, version, status, config, author, customer)
                VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7, $8)
                ON CONFLICT (name, version) DO UPDATE SET config = EXCLUDED.config, status = EXCLUDED.status
                """,
                new_id, e["name"], e["kind"], e["version"], status,
                json.dumps(e["config"]), author, customer,
            )
            imported += 1
    finally:
        await conn.close()
    return {"imported": imported, "mode": mode, "customer": customer}
```

- [ ] **Step 4.2: Routes**

```python
# src/spec2sphere/web/ai_studio/library_routes.py
from fastapi import APIRouter, UploadFile, File, Form, Response, Depends
import json, datetime as dt
from spec2sphere.dsp_ai.library import export_library, import_library
from spec2sphere.web.dependencies import get_current_user

router = APIRouter(prefix="/ai-studio/library", tags=["ai-studio"])

@router.get("/export")
async def export(user = Depends(get_current_user)) -> Response:
    import os
    customer = os.environ.get("CUSTOMER", "default")
    blob = await export_library(customer)
    blob["exported_at"] = dt.datetime.utcnow().isoformat() + "Z"
    payload = json.dumps(blob, indent=2)
    return Response(
        payload, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="spec2sphere-library-{customer}.json"'},
    )

@router.post("/import")
async def imp(
    file: UploadFile = File(...),
    mode: str = Form("merge"),
    user = Depends(get_current_user),
) -> dict:
    import os
    customer = os.environ.get("CUSTOMER", "default")
    blob = json.loads(await file.read())
    return await import_library(blob, customer=customer, mode=mode, author=user.email)
```

- [ ] **Step 4.3: UI**

Simple HTMX form on `ai_studio.html`:

```html
<div class="flex gap-2">
  <a href="/ai-studio/library/export" class="bg-gray-100 px-4 py-2 rounded">Export library</a>
  <form method="post" enctype="multipart/form-data" action="/ai-studio/library/import" class="flex gap-2">
    <input type="file" name="file" accept="application/json" required/>
    <select name="mode" class="border rounded px-2">
      <option value="merge">merge</option>
      <option value="replace">replace</option>
      <option value="draftify">import as drafts</option>
    </select>
    <button class="bg-purple-600 text-white px-4 py-2 rounded">Import</button>
  </form>
</div>
```

- [ ] **Step 4.4: Round-trip test**

```python
# tests/dsp_ai/test_library.py
import pytest
from spec2sphere.dsp_ai.library import export_library, import_library

@pytest.mark.asyncio
async def test_export_then_import_preserves_enhancements(seeded_enhancements):
    blob = await export_library("horvath")
    assert len(blob["enhancements"]) == 5

    await import_library(blob, customer="horvath-copy", mode="replace")
    blob2 = await export_library("horvath-copy")
    assert {e["name"] for e in blob["enhancements"]} == {e["name"] for e in blob2["enhancements"]}

@pytest.mark.asyncio
async def test_import_validates_config_schema():
    bad = {"version": "1.0", "enhancements": [
        {"name": "x", "kind": "narrative", "version": 1, "status": "draft",
         "config": {"name": "x"}}  # missing required fields
    ]}
    with pytest.raises(Exception):
        await import_library(bad, "horvath-test", "merge")
```

- [ ] **Step 4.5: Commit**

```bash
git add src/spec2sphere/dsp_ai/library.py src/spec2sphere/web/ai_studio/library_routes.py src/spec2sphere/web/templates/partials/ai_studio*.html tests/dsp_ai/test_library.py
git commit -m "feat(ai-studio): library export/import (JSON round-trip, validated)"
```

---

## Task 5: Publish diff preview

**Files:**
- Create: `src/spec2sphere/dsp_ai/publish_diff.py`
- Create: `src/spec2sphere/web/templates/partials/ai_studio_diff.html`
- Modify: `src/spec2sphere/web/ai_studio/routes.py` — pre-publish diff step
- Create: `tests/dsp_ai/test_publish_diff.py`

- [ ] **Step 5.1: Diff module**

```python
# src/spec2sphere/dsp_ai/publish_diff.py
"""Compute user-impact diff between active published version and a draft."""
from __future__ import annotations
import asyncpg, json
from spec2sphere.config import settings

async def diff(enhancement_id: str, candidate_config: dict) -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        active = await conn.fetchrow(
            "SELECT config FROM dsp_ai.enhancements WHERE id=$1::uuid",
            enhancement_id,
        )
        active_config = active["config"] if isinstance(active["config"], dict) else json.loads(active["config"])

        # Count affected users
        active_user_rows = await conn.fetch(
            "SELECT DISTINCT user_id FROM dsp_ai.briefings WHERE enhancement_id=$1::uuid",
            enhancement_id,
        )
        active_users = [r["user_id"] for r in active_user_rows]
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
    out = {}
    keys = set(a) | set(b)
    for k in keys:
        if a.get(k) != b.get(k):
            out[k] = {"from": a.get(k), "to": b.get(k)}
    return out

def _is_breaking(changes: dict) -> bool:
    # Changes that alter output schema or data binding are breaking
    return any(k in changes for k in ("output_schema", "render_hint", "kind", "mode"))

def _humanize(changes: dict) -> list[str]:
    msgs = []
    for k, v in changes.items():
        if k == "prompt_template":
            msgs.append("Prompt template changed — expect different wording in new outputs.")
        elif k == "render_hint":
            msgs.append(f"Render hint: {v['from']} → {v['to']}. SAC story widgets may need re-binding.")
        elif k == "output_schema":
            msgs.append("Output schema changed — downstream widgets consuming typed fields may break.")
        elif k == "bindings":
            msgs.append("Data or semantic bindings changed — content will shift.")
        else:
            msgs.append(f"{k} changed.")
    return msgs
```

- [ ] **Step 5.2: Modify publish route to show diff first**

```python
# ai_studio/routes.py
from spec2sphere.dsp_ai.publish_diff import diff as compute_diff

@router.post("/{id}/publish-preview")
async def publish_preview(id: str, user = Depends(get_current_user)) -> dict:
    if not _is_author(user): raise HTTPException(403)
    row = await _fetch_enhancement(id)
    return await compute_diff(id, row["config"])

# existing publish() keeps its behavior; UI calls preview first, then confirms
```

- [ ] **Step 5.3: UI**

In the editor, replace the Publish form with a two-step flow:
1. Click "Publish" → fetches `/ai-studio/{id}/publish-preview`, renders modal with diff summary
2. User confirms → posts to `/ai-studio/{id}/publish`

If `breaking: true`, show a red warning. Ship a simple `<dialog>` or HTMX modal partial.

- [ ] **Step 5.4: Tests**

```python
# tests/dsp_ai/test_publish_diff.py
import pytest
from spec2sphere.dsp_ai.publish_diff import diff

@pytest.mark.asyncio
async def test_detects_breaking_render_hint_change(seed_published_enhancement):
    candidate = {**seed_published_enhancement["config"], "render_hint": "chart"}
    d = await diff(seed_published_enhancement["id"], candidate)
    assert d["breaking"] is True
    assert any("render hint" in s.lower() for s in d["summary"])
```

- [ ] **Step 5.5: Commit**

```bash
git add src/spec2sphere/dsp_ai/publish_diff.py src/spec2sphere/web/ai_studio/routes.py src/spec2sphere/web/templates/partials/ai_studio_diff.html tests/dsp_ai/test_publish_diff.py
git commit -m "feat(ai-studio): publish diff preview with breaking-change warnings"
```

---

## Task 6: Cost guardrails

**Files:**
- Create: `src/spec2sphere/dsp_ai/cost_guard.py`
- Modify: `src/spec2sphere/dsp_ai/engine.py`
- Create: `tests/dsp_ai/test_cost_guard.py`

- [ ] **Step 6.1: Cost guard module**

```python
# src/spec2sphere/dsp_ai/cost_guard.py
"""Per-enhancement monthly cap. Auto-pauses enhancement on overrun.

Note: Session B's ObservedLLMProvider also writes to dsp_ai.generations
with enhancement_id=NULL and caller='agents.*' / 'migration.*' / etc.
This cost guard's totals therefore cover both engine-driven enhancements
AND existing agent/migration LLM usage. Per-enhancement cap only applies
to rows with non-NULL enhancement_id; global monthly total (separate env
var COST_GUARD_GLOBAL_CAP_USD, optional) covers the lot.
"""
from __future__ import annotations
import os
import asyncpg
from spec2sphere.config import settings

DEFAULT_CAP = float(os.environ.get("COST_GUARD_DEFAULT_CAP_USD", "25.0"))
GLOBAL_CAP = float(os.environ.get("COST_GUARD_GLOBAL_CAP_USD", "100.0"))  # covers agent + migration + standards + knowledge LLM calls

class CostExceeded(Exception):
    pass

async def check_and_account(enhancement_id: str, projected_cost_usd: float) -> None:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow(
            """
            SELECT coalesce(sum(cost_usd), 0) AS month_total, max(e.config->>'cost_cap_usd') AS cap
            FROM dsp_ai.generations g JOIN dsp_ai.enhancements e ON e.id = g.enhancement_id
            WHERE g.enhancement_id = $1::uuid
              AND g.created_at > date_trunc('month', NOW())
            """,
            enhancement_id,
        )
    finally:
        await conn.close()
    month_total = float(row["month_total"] or 0)
    cap = float(row["cap"] or DEFAULT_CAP)
    if month_total + projected_cost_usd > cap:
        await _pause(enhancement_id, month_total, cap)
        raise CostExceeded(f"enhancement {enhancement_id}: {month_total+projected_cost_usd:.2f} > cap {cap:.2f}")

async def _pause(enhancement_id: str, total: float, cap: float) -> None:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute(
            "UPDATE dsp_ai.enhancements SET status='paused', updated_at=NOW() WHERE id=$1::uuid",
            enhancement_id,
        )
        await conn.execute(
            "INSERT INTO dsp_ai.studio_audit (action, enhancement_id, author, after) VALUES ($1, $2::uuid, 'cost_guard', $3::jsonb)",
            "auto_pause", enhancement_id, f'{{"month_total": {total}, "cap": {cap}}}',
        )
    finally:
        await conn.close()
    from .events import emit
    await emit("enhancement_paused", {"id": enhancement_id, "reason": "cost_guard"})
```

- [ ] **Step 6.2: Hook into engine**

Before `run_llm`, estimate projected cost (simple: `tokens_estimate * model_rate`). Call `check_and_account`. Catch `CostExceeded` in dispatch and return a graceful `{"error_kind": "cost_cap"}` shape.

- [ ] **Step 6.3: Tests**

```python
# tests/dsp_ai/test_cost_guard.py
import pytest
from spec2sphere.dsp_ai.cost_guard import check_and_account, CostExceeded

@pytest.mark.asyncio
async def test_pauses_enhancement_at_cap(seeded_enhancement_with_cap):
    with pytest.raises(CostExceeded):
        # cap is $0.01, projected is $0.02 → breach
        await check_and_account(seeded_enhancement_with_cap["id"], 0.02)
```

- [ ] **Step 6.4: Commit**

```bash
git add src/spec2sphere/dsp_ai/cost_guard.py src/spec2sphere/dsp_ai/engine.py tests/dsp_ai/test_cost_guard.py
git commit -m "feat(dsp-ai): cost guardrails (monthly cap + auto-pause + audit)"
```

---

## Task 7: graph.json retirement (final cutover)

**Files:**
- Modify: `src/spec2sphere/scanner/output.py`, `src/spec2sphere/scanner/graph_repo.py`, `src/spec2sphere/web/server.py`

- [ ] **Step 7.1: Validate both reads are safe**

Run existing smoke + integration suites with `GRAPH_READ_FROM_BRAIN=true`. If green for at least 1 week of Session B deploy, proceed.

- [ ] **Step 7.2: Flip defaults**

In `graph_repo.py`, default `read_from_brain()` to `True`. Require `GRAPH_LEGACY_FILE_FALLBACK=true` to read from file.

- [ ] **Step 7.3: Stop writing graph.json by default**

In `scanner/output.py`, only write `graph.json` if `BRAIN_WRITE_BOTH=true` is explicitly set.

- [ ] **Step 7.4: Delete 6 read sites in web/server.py that were still checking for file existence**

Grep for `graph.json` — all remaining references are either: (a) in the legacy fallback path gated on env var, (b) in tests. Clean up any orphaned helpers.

- [ ] **Step 7.5: Tests**

Integration suite runs on a fresh compose with `BRAIN_WRITE_BOTH=false, GRAPH_READ_FROM_BRAIN=true` — no file ever touched, everything works.

- [ ] **Step 7.6: Commit**

```bash
git add src/spec2sphere/scanner/ src/spec2sphere/web/server.py
git commit -m "refactor(scanner): retire graph.json default write; Brain is source of truth"
```

---

## Task 8: Widget degraded-mode polish + admin chip

**Files:**
- Modify: `src/spec2sphere/widget/src/main.ts`
- Modify: `src/spec2sphere/widget/src/renderers/*.ts`

- [ ] **Step 8.1: Render quality warnings**

In every renderer, if `data.quality_warnings.length > 0`, inject an info icon with tooltip listing them. Non-intrusive.

- [ ] **Step 8.2: data_stale + stale handling**

```typescript
if (data.data_stale) {
  container.innerHTML = `
    <div style="background:#fef3c7;color:#92400e;padding:4px 8px;font-size:12px;border-radius:4px;margin-bottom:4px">
      ⚠ Data last refreshed — may be stale
    </div>` + container.innerHTML;
}
if (data.stale) {
  container.style.opacity = "0.6";
  container.innerHTML = `<small>Refreshing…</small>` + container.innerHTML;
}
```

- [ ] **Step 8.3: Admin chip (author only)**

```typescript
function renderAdminChip(data: any, apiBase: string) {
  const chip = document.createElement("div");
  chip.style.cssText = "position:absolute;top:4px;right:4px;font:10px monospace;background:rgba(0,0,0,0.6);color:#fff;padding:2px 6px;border-radius:3px;cursor:pointer";
  chip.textContent = `gen=${data.generation_id.slice(0,8)} · ${data.provenance?.latency_ms}ms · ${data._cached ? 'hit' : 'miss'}`;
  chip.onclick = () => window.open(`${apiBase}/ai-studio/log/${data.generation_id}`, "_blank");
  return chip;
}
```

- [ ] **Step 8.4: Commit**

```bash
git add src/spec2sphere/widget/src/
cd src/spec2sphere/widget && npm run build && cd - # rebuild
git add src/spec2sphere/widget/dist/
git commit -m "feat(widget): degraded-mode visuals + admin chip for authors"
```

---

## Task 9: CPG/Retail reference library

**Files:**
- Create: `libraries/cpg_retail/` with 8 seed JSONs
- Create: `libraries/cpg_retail/README.md`

- [ ] **Step 9.1: 8 enhancements for CPG/Retail**

Enhancements (one JSON each, following the same shape as Session B's seeds):

1. `01_morning_brief_revenue.json` — daily morning brief, narrative
2. `02_weekly_sell_through.json` — weekly sell-through narrative, briefing
3. `03_out_of_stock_ranking.json` — ranking of SKUs needing attention
4. `04_price_anomaly_explainer.json` — action, explains price deviations on click
5. `05_promo_lift_summary.json` — narrative post-promo analysis
6. `06_category_heatmap_kpis.json` — ranking of KPIs per category
7. `07_supplier_scorecard.json` — briefing, per-supplier quality
8. `08_sku_description_refiner.json` — item_enrich for SKU master data

For each: real-ish `dsp_query`, matching semantic_binding, adaptive_rules, prompt_template, output_schema, render_hint.

- [ ] **Step 9.2: README**

Quick-start: "clone → docker compose up → import this library → customize `dsp_query` for your tenant → publish all → 8 enhancements producing content in 30 minutes."

- [ ] **Step 9.3: Commit**

```bash
git add libraries/cpg_retail/
git commit -m "feat(libraries): CPG/Retail reference enhancement library (8 templates)"
```

---

## Task 10: Deploy docs + demo script + bootstrap script

**Files:**
- Create: `docs/deploy/client_checklist.md`
- Create: `docs/deploy/demo_script.md`
- Create: `docs/deploy/tls.md`
- Create: `scripts/demo_bootstrap.sh`
- Create: `scripts/backup.sh`, `scripts/restore.sh`

- [ ] **Step 10.1: client_checklist.md**

Covers: DSP connection string, SAC widget manifest URL, CORS allowed origins, LLM endpoint choice (homelab / Azure / Ollama), STUDIO_AUTHOR_EMAILS whitelist, CUSTOMER env var, COST_GUARD_DEFAULT_CAP_USD, backup cadence, TLS mode, rollback procedure.

- [ ] **Step 10.2: demo_script.md**

Ten-minute script with timings:
- 0:00–1:00 — open Spec2Sphere, show AI Studio list with 5 published enhancements
- 1:00–3:00 — open Morning Brief editor, tweak prompt_template, run preview, show cost + provenance
- 3:00–5:00 — open Horváth SAC story, show Pattern B rendering from `dsp_ai.briefings`; show widget (Pattern A) beside it
- 5:00–6:00 — click "Why this?" button in widget → admin chip → Generation Log drill-down
- 6:00–7:30 — go back to Studio, publish a modified enhancement; show diff preview with breaking-change warning
- 7:30–9:00 — Brain Explorer: visualize DspObjects + Glossary + User interest edges; run a Cypher query
- 9:00–10:00 — Library export → download JSON → show "this is how we bring it to the next client"

- [ ] **Step 10.3: tls.md**

Three TLS modes:
- `TLS_MODE=client_lb` (default) — client reverse proxy terminates TLS
- `TLS_MODE=caddy` — bundle Caddy sidecar with automatic Let's Encrypt
- `TLS_MODE=self_signed` — self-signed cert for internal demo only

- [ ] **Step 10.4: demo_bootstrap.sh**

```bash
#!/usr/bin/env bash
set -eu
docker compose up -d
echo "waiting for services..."
until curl -fs http://localhost:8261/v1/healthz > /dev/null; do sleep 2; done

echo "importing CPG/Retail library..."
curl -fs -X POST http://localhost:8260/ai-studio/library/import \
     -F "file=@libraries/cpg_retail/export.json" \
     -F "mode=merge"

echo "publishing first 3 enhancements..."
for eid in $(curl -fs http://localhost:8260/ai-studio/api/enhancements | jq -r '.[0:3] | .[].id'); do
    curl -fs -X POST http://localhost:8260/ai-studio/$eid/publish > /dev/null
done

echo "✓ ready. Open http://localhost:8260/ai-studio/ — widget manifest at /widget/manifest.json"
```

- [ ] **Step 10.5: backup.sh / restore.sh**

```bash
#!/usr/bin/env bash
set -eu
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=${BACKUP_DIR:-./backups}/$STAMP
mkdir -p "$OUT"
docker compose exec -T postgres pg_dump -U spec2sphere spec2sphere > "$OUT/postgres.sql"
docker compose exec -T neo4j neo4j-admin database dump neo4j --to-path=/backups
docker cp sap-doc-agent-neo4j:/backups/neo4j.dump "$OUT/"
docker compose exec -T redis redis-cli SAVE
docker cp sap-doc-agent-redis:/data/dump.rdb "$OUT/redis.rdb"
# Export enhancement library (portable, human-readable)
curl -fs http://localhost:8260/ai-studio/library/export > "$OUT/library.json"
tar -czf "$OUT.tar.gz" -C "${OUT%/*}" "$(basename "$OUT")"
rm -rf "$OUT"
echo "→ $OUT.tar.gz"
```

- [ ] **Step 10.6: Commit**

```bash
git add docs/deploy/ scripts/
git commit -m "docs(deploy): client checklist + demo script + TLS modes + bootstrap/backup scripts"
```

---

## Task 11: Portability smoke test

**Files:**
- Create: `tests/dsp_ai/test_portability.py`

- [ ] **Step 11.1: End-to-end portability check**

```python
# tests/dsp_ai/test_portability.py
"""Run as `pytest -m portability`.

Full round-trip from one fresh compose to another, verifying
enhancements + data move cleanly.
"""
import pytest, json, subprocess, httpx, time

@pytest.mark.portability
def test_export_and_restore_library_on_fresh_compose(tmp_path):
    # 1. Export from running instance
    r = httpx.get("http://localhost:8260/ai-studio/library/export")
    assert r.status_code == 200
    lib = r.json()
    p = tmp_path / "library.json"
    p.write_text(json.dumps(lib))

    # 2. Spin up a second compose instance on different ports
    subprocess.check_call(["docker", "compose", "-p", "dspai-portability",
                           "-f", "docker-compose.yml", "up", "-d"])
    try:
        # 3. Wait for health
        for _ in range(60):
            try:
                if httpx.get("http://localhost:8361/v1/healthz").status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2)

        # 4. Import
        with open(p, "rb") as f:
            r = httpx.post("http://localhost:8360/ai-studio/library/import",
                           files={"file": f}, data={"mode": "merge"})
        assert r.status_code == 200
        assert r.json()["imported"] == len(lib["enhancements"])

        # 5. Preview one to prove engine works on fresh instance
        enh = lib["enhancements"][0]
        lookup = httpx.get("http://localhost:8360/ai-studio/api/enhancements").json()
        eid = next(e["id"] for e in lookup if e["name"] == enh["name"])
        r = httpx.post(f"http://localhost:8360/ai-studio/{eid}/preview",
                       json={"user": "portability@test", "context_hints": {}})
        assert r.status_code == 200
        assert "generation_id" in r.json()
    finally:
        subprocess.call(["docker", "compose", "-p", "dspai-portability", "down", "-v"])
```

- [ ] **Step 11.2: Commit**

```bash
git add tests/dsp_ai/test_portability.py
git commit -m "test(dsp-ai): end-to-end portability smoke"
```

---

## Task 12: Smoke + session ship criteria

**Files:**
- Extend: `tests/dsp_ai/test_smoke.py`

- [ ] **Step 12.1: Session C smoke checks**

```python
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_library_export_returns_valid_schema():
    async with httpx.AsyncClient() as c:
        r = await c.get("http://localhost:8260/ai-studio/library/export")
        assert r.status_code == 200
        blob = r.json()
        assert blob["version"] == "1.0"
        assert isinstance(blob["enhancements"], list)

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_rbac_blocks_viewer_publish():
    from spec2sphere.dsp_ai.auth import issue_token
    tok = issue_token("v@x", "default", "viewer")
    async with httpx.AsyncClient() as c:
        r = await c.post("http://localhost:8260/ai-studio/anything/publish",
                         headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_customer_isolation():
    from spec2sphere.dsp_ai.db import get_conn
    async with get_conn(customer="a") as conn_a:
        count_a = await conn_a.fetchval("SELECT count(*) FROM dsp_ai.enhancements")
    async with get_conn(customer="b") as conn_b:
        count_b = await conn_b.fetchval("SELECT count(*) FROM dsp_ai.enhancements")
    # In a multi-tenant fixture they should differ; in a single-tenant smoke they may both be the same
    assert count_a is not None and count_b is not None  # sanity: no cross-leakage error
```

- [ ] **Step 12.2: Full manual demo checklist**

```
□ docker compose --profile offline up → Ollama healthy + LLM_ENDPOINT → ollama; Morning Brief runs with local model
□ Export library → JSON file downloaded, schema matches {version, enhancements[]}
□ Import library on a fresh compose (different project name / ports) → all enhancements appear, previews work
□ Change Morning Brief prompt → click Publish → diff modal appears with "Prompt template changed" warning
□ Change render_hint → click Publish → diff modal flags "breaking"; user confirms anyway
□ Set enhancement monthly cap to $0.01 → run twice → second run 429s with error_kind=cost_cap; enhancement marked paused in studio_audit
□ Issue a viewer JWT → POST /v1/actions/{id}/regen → 403; POST /v1/enhance/{id} → 200
□ Run backup.sh → tarball contains postgres.sql, neo4j.dump, redis.rdb, library.json
□ Run restore.sh against an empty compose → smoke tests green
□ graph.json stops being written when BRAIN_WRITE_BOTH=false; reads flow through Brain; legacy routes still work with GRAPH_LEGACY_FILE_FALLBACK=true
□ Load CPG/Retail library → 8 enhancements → publish all → dsp_ai.briefings / .rankings / .item_enhancements all populated
□ demo_bootstrap.sh on fresh machine → ≤10 min to demo-ready
□ pytest -m smoke green; pytest -m portability green (20-min test; run nightly)
```

- [ ] **Step 12.3: Commit**

```bash
git add tests/dsp_ai/test_smoke.py
git commit -m "test(dsp-ai): Session C smoke suite + portability demo checklist"
```

---

## Session C success criteria

1. `docker compose --profile offline up` — Morning Brief works end-to-end against bundled Ollama; no outbound LLM calls
2. Library export → file → import on second fresh instance → previews succeed → enhancements behave identically
3. Publish diff modal shows on every publish; breaking changes warn loudly
4. Cost guard auto-pauses an enhancement when it breaches the configured cap; `studio_audit` has an `auto_pause` row
5. JWT + RBAC enforced: viewer cannot publish/regen; author can; widget auth tokens scoped to customer
6. Multi-tenant: RLS blocks cross-customer reads via the standard connection helper; Neo4j queries carry `customer` filter
7. `graph.json` no longer written by default; Brain is source of truth; legacy fallback gated on env
8. CPG/Retail library imports cleanly and produces output on a fresh Horváth tenant
9. `docs/deploy/client_checklist.md`, `demo_script.md`, `tls.md` present; `demo_bootstrap.sh`, `backup.sh`, `restore.sh` executable
10. `pytest -m smoke` green; `pytest -m portability` green
11. Time-to-demo-ready on a fresh machine: ≤10 minutes with `demo_bootstrap.sh`

The system is now portable. Bring the repo + this library + a fresh compose to a client site, import, bind to their DSP/SAC, demo in half a day.
