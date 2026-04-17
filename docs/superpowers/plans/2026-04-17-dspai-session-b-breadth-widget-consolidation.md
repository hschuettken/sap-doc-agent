# DSP-AI Session B — Breadth + Widget + Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand from vertical slice to a full-breadth system. All 5 enhancement kinds ship. The SAC Custom Widget (Pattern A) is deployed, runs against live dsp-ai endpoints, and feeds behavior back into the Corporate Brain. Studio gains template library, Generation Log, and Brain Explorer. Consolidation: `graph.json` migrates to Neo4j, Copilot ContentHub merges into the Brain, Spec2Sphere Copilot MCP exposes Studio tools, **and every existing LLM call (agents, migration, standards, knowledge) logs to `dsp_ai.generations` for unified cost + quality observability**.

**Architecture:** Builds on Session A's engine and schema. Adds: live-adapter endpoints (`/v1/actions`, `/v1/stream` SSE, `/v1/why`, `/v1/telemetry`), behavior feeder, dispatch paths for ranking/item_enrich/action, SAC widget (TypeScript + esbuild, served from FastAPI static route), Studio polish, Neo4j write-both bridge for `graph.json`, ContentHub replacement.

**Tech Stack:** Session A stack + TypeScript 5, esbuild, Vitest, `happy-dom`, SSE via Starlette `EventSourceResponse`, Monaco Editor (CDN-lazy-loaded per HTMX pattern).

**Reference spec:** `docs/superpowers/specs/2026-04-17-dsp-ai-enhancements-design.md`
**Depends on:** `docs/superpowers/plans/2026-04-17-dspai-session-a-foundation-vertical-slice.md` (must be completed + deployed)

---

## File Map

### New files

| File | Responsibility |
|------|----------------|
| `migrations/versions/011_dsp_ai_breadth.py` | Indexes/columns needed for Session B (generation.preview default true for new drafts, rankings index tuning) |
| `src/spec2sphere/dsp_ai/adapters/live.py` (extended) | Add `/v1/actions/{id}/run`, `/v1/stream/{id}/{user}`, `/v1/why/{gen_id}`, `/v1/telemetry` |
| `src/spec2sphere/dsp_ai/stages/dispatch.py` (extended) | Add `_write_ranking`, `_write_item_enhancement`, `_write_action_result` |
| `src/spec2sphere/dsp_ai/brain/feeders/behavior.py` | Consume telemetry → Postgres `user_state` + Brain OPENED/DWELLED_ON edges + nightly Topic synthesis |
| `src/spec2sphere/widget/package.json` | NPM project for SAC Custom Widget |
| `src/spec2sphere/widget/tsconfig.json` | TS config |
| `src/spec2sphere/widget/esbuild.config.mjs` | Build pipeline (ES2020 target, IIFE) |
| `src/spec2sphere/widget/manifest.template.json` | SAC Custom Widget manifest with `{{API_BASE}}` placeholder |
| `src/spec2sphere/widget/src/main.ts` | Custom Element entry |
| `src/spec2sphere/widget/src/api.ts` | dsp-ai HTTP client (fetch + EventSource) |
| `src/spec2sphere/widget/src/telemetry.ts` | Post widget.rendered/dwelled/clicked/declined |
| `src/spec2sphere/widget/src/sac_context.ts` | Resolve SAC-provided user/story/filters |
| `src/spec2sphere/widget/src/renderers/narrative.ts` | narrative_text renderer |
| `src/spec2sphere/widget/src/renderers/ranked_list.ts` | ranked_list renderer |
| `src/spec2sphere/widget/src/renderers/callout.ts` | callout renderer |
| `src/spec2sphere/widget/src/renderers/button.ts` | action button renderer |
| `src/spec2sphere/widget/src/renderers/brief.ts` | Morning Brief composite |
| `src/spec2sphere/widget/src/renderers/chart.ts` | Minimal chart renderer |
| `src/spec2sphere/widget/src/types.ts` | Shared types (mirrors Python Pydantic) |
| `src/spec2sphere/widget/tests/renderers.test.ts` | Vitest Shadow DOM snapshot tests |
| `src/spec2sphere/widget/tests/lifecycle.test.ts` | Vitest mount/unmount/SSE tests |
| `src/spec2sphere/web/ai_studio/generation_log.py` | Route + template for `dsp_ai.generations` queryable log |
| `src/spec2sphere/web/ai_studio/brain_explorer.py` | Route + template using vis-network.js |
| `src/spec2sphere/web/ai_studio/templates_library.py` | Route + template for seed/template catalog |
| `src/spec2sphere/web/templates/partials/ai_studio_log.html` | Generation Log UI |
| `src/spec2sphere/web/templates/partials/ai_studio_brain.html` | Brain Explorer UI |
| `src/spec2sphere/web/templates/partials/ai_studio_templates.html` | Template library UI |
| `src/spec2sphere/web/widget_routes.py` | `/widget/main.js`, `/widget/manifest.json`, `/widget/main.js.map` static serving with CORS + integrity |
| `templates/seeds/narrative_overlay.json` | Seed: narrative overlay on a sales view |
| `templates/seeds/anomaly_explainer.json` | Seed: per-item action that re-runs when clicked |
| `templates/seeds/column_title_gen.json` | Seed: item_enrich on DspObject columns |
| `templates/seeds/kpi_suggester.json` | Seed: ranking of suggested KPIs |
| `src/spec2sphere/copilot/studio_tools.py` | MCP tools: `studio.list_enhancements`, `.get`, `.create`, `.update`, `.preview`, `.publish`, `.rollback`, `.query_brain`, `.generation_log` |
| `tests/dsp_ai/test_live_adapter_v1b.py` | Contract tests for actions/stream/why/telemetry |
| `tests/dsp_ai/test_behavior_feeder.py` | Telemetry → user_state + Brain edges |
| `tests/dsp_ai/test_ranking_dispatch.py` | Dispatch writes to dsp_ai.rankings |
| `tests/dsp_ai/test_item_enrich_dispatch.py` | Dispatch writes to dsp_ai.item_enhancements |
| `tests/dsp_ai/test_graph_cutover.py` | Neo4j write-both mode + cutover flag |
| `tests/dsp_ai/test_mcp_studio_tools.py` | MCP tool invocations |
| `migrations/versions/013_dsp_ai_generations_nullable_enh.py` | Alembic: `enhancement_id` nullable + add `caller TEXT` column for non-engine LLM calls |
| `src/spec2sphere/llm/observed.py` | `ObservedLLMProvider` — thin wrapper that logs every `generate()` / `generate_json()` call to `dsp_ai.generations` |
| `tests/dsp_ai/test_observed_llm.py` | Wrapper records provider calls with caller + tokens + model |

### Modified files

| File | Change |
|------|--------|
| `src/spec2sphere/dsp_ai/adapters/live.py` | Add new endpoints |
| `src/spec2sphere/dsp_ai/stages/dispatch.py` | Add ranking + item_enrich + action paths |
| `src/spec2sphere/web/ai_studio/routes.py` | Mount sub-routers (generation_log, brain_explorer, templates_library) + new `PUT /{id}/config` |
| `src/spec2sphere/web/templates/partials/ai_studio_editor.html` | Add Monaco (CDN lazy-load pattern), session preview budget meter, Admin chip link |
| `src/spec2sphere/web/templates/base.html` | Expand AI Studio nav with sub-tabs |
| `src/spec2sphere/scanner/output.py` | Write graph.json + also feed Neo4j (controlled by `BRAIN_WRITE_BOTH=true`) |
| `src/spec2sphere/web/server.py` | Add `GRAPH_READ_FROM_BRAIN` flag — routes that read graph.json consult Brain when flag true |
| `src/spec2sphere/scanner/chain_builder.py` | Dual read path: parse graph.json OR run Cypher based on flag |
| `src/spec2sphere/copilot/content_hub.py` | Query Brain for topics/objects instead of filesystem walking |
| `src/spec2sphere/copilot/mcp_server.py` | Register studio_tools |
| `src/spec2sphere/app.py` | Mount widget_routes |
| `src/spec2sphere/llm/__init__.py` | `create_llm_provider()` wraps its result in `ObservedLLMProvider` — one-line change, every call site gets observability |
| `src/spec2sphere/llm/base.py` | Optional `caller: str \| None = None` kwarg on `generate()` / `generate_json()` — default-compatible with all existing signatures |

---

## Task 1: Expand dispatch for ranking + item_enrich + action

**Files:**
- Modify: `src/spec2sphere/dsp_ai/stages/dispatch.py`
- Create: `tests/dsp_ai/test_ranking_dispatch.py`
- Create: `tests/dsp_ai/test_item_enrich_dispatch.py`

- [ ] **Step 1.1: Add `_write_ranking` and `_write_item_enhancement`**

Append to `dispatch.py`:

```python
async def _write_ranking(conn, enh, user_id, context_key, shaped) -> None:
    items = shaped["content"].get("items", []) if isinstance(shaped["content"], dict) else []
    # Replace-all semantics per (enh, user, ctx)
    await conn.execute(
        "DELETE FROM dsp_ai.rankings WHERE enhancement_id=$1::uuid AND user_id=$2 AND context_key=$3",
        enh.id, user_id, context_key,
    )
    for i, item in enumerate(items):
        await conn.execute(
            """
            INSERT INTO dsp_ai.rankings
                (enhancement_id, user_id, context_key, item_id, rank, score, reason,
                 generated_at, generation_id)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, NOW(), $8::uuid)
            """,
            enh.id, user_id, context_key, item["item_id"], i + 1,
            item.get("score", 0.0), item.get("reason"), shaped["generation_id"],
        )

async def _write_item_enhancement(conn, enh, user_id, shaped) -> None:
    enrichments = shaped["content"].get("enrichments", []) if isinstance(shaped["content"], dict) else []
    for e in enrichments:
        await conn.execute(
            """
            INSERT INTO dsp_ai.item_enhancements
                (object_type, object_id, user_id, title_suggested, description_suggested,
                 tags, kpi_suggestions, generated_at, enhancement_id, generation_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, NOW(), $8::uuid, $9::uuid)
            ON CONFLICT (object_type, object_id, user_id) DO UPDATE SET
                title_suggested = EXCLUDED.title_suggested,
                description_suggested = EXCLUDED.description_suggested,
                tags = EXCLUDED.tags,
                kpi_suggestions = EXCLUDED.kpi_suggestions,
                generation_id = EXCLUDED.generation_id
            """,
            e["object_type"], e["object_id"], user_id,
            e.get("title"), e.get("description"),
            json.dumps(e.get("tags", [])), json.dumps(e.get("kpi_suggestions", [])),
            enh.id, shaped["generation_id"],
        )
```

- [ ] **Step 1.2: Expand `dispatch()` dispatcher**

```python
async def dispatch(enh, shaped, *, mode, user_id, context_key, preview=False):
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await _insert_generation(conn, enh, user_id, context_key, shaped, preview)
        if mode in (EnhancementMode.BATCH, EnhancementMode.BOTH) and not preview:
            rh = enh.config.render_hint
            if rh in (RenderHint.NARRATIVE_TEXT, RenderHint.BRIEF, RenderHint.CALLOUT):
                await _write_briefing(conn, enh, user_id or "_global", context_key or "default", shaped)
            elif rh == RenderHint.RANKED_LIST:
                await _write_ranking(conn, enh, user_id or "_global", context_key or "default", shaped)
            elif enh.config.kind == EnhancementKind.ITEM_ENRICH:
                await _write_item_enhancement(conn, enh, user_id, shaped)
            # action & button: no batch persistence; live only (see action endpoint)
            await emit("briefing_generated", {
                "enhancement_id": enh.id, "user_id": user_id, "context_key": context_key,
            })
        return shaped
    finally:
        await conn.close()
```

- [ ] **Step 1.3: Tests for ranking + item_enrich paths**

Fixture: seed an enhancement with `render_hint=ranked_list` and mocked LLM returning `{"items":[{"item_id":"x","score":0.9,"reason":"r1"},{"item_id":"y","score":0.8,"reason":"r2"}]}`. Assert `dsp_ai.rankings` has 2 rows with correct ranks.

Similar for item_enrich with `render_hint=callout, kind=item_enrich` — assert `dsp_ai.item_enhancements` row.

- [ ] **Step 1.4: Commit**

```bash
git add src/spec2sphere/dsp_ai/stages/dispatch.py tests/dsp_ai/test_ranking_dispatch.py tests/dsp_ai/test_item_enrich_dispatch.py
git commit -m "feat(dsp-ai): ranking + item_enrich dispatch paths"
```

---

## Task 2: Live adapter — actions, stream (SSE), why, telemetry

**Files:**
- Modify: `src/spec2sphere/dsp_ai/adapters/live.py`
- Create: `tests/dsp_ai/test_live_adapter_v1b.py`

- [ ] **Step 2.1: Add `/v1/actions/{id}/run`**

```python
@router.post("/v1/actions/{enhancement_id}/run")
async def run_action(enhancement_id: str, body: EnhanceRequest = Body(...)) -> dict:
    """Synchronous click-to-run. No cache. Returns fully shaped output."""
    try:
        return await run_engine(
            enhancement_id,
            user_id=body.user,
            context_hints=body.context_hints,
            context_key=body.context_key,
            mode_override=EnhancementMode.LIVE,
        )
    except LookupError:
        raise HTTPException(404, "enhancement not found")
```

- [ ] **Step 2.2: Add `/v1/stream/{enhancement_id}/{user_id}` (SSE)**

```python
from sse_starlette.sse import EventSourceResponse
from ..events import subscribe

@router.get("/v1/stream/{enhancement_id}/{user_id}")
async def stream(enhancement_id: str, user_id: str):
    async def gen():
        async for ev in subscribe("briefing_generated"):
            if ev.get("enhancement_id") == enhancement_id and ev.get("user_id") == user_id:
                yield {"event": "briefing_generated", "data": json.dumps(ev)}
    return EventSourceResponse(gen())
```

Add `sse-starlette` to `pyproject.toml` / `requirements.txt`.

- [ ] **Step 2.3: Add `/v1/why/{generation_id}`**

```python
@router.post("/v1/why/{generation_id}")
async def why(generation_id: str) -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        gen = await conn.fetchrow(
            "SELECT g.*, e.name AS enh_name, e.version AS enh_version "
            "FROM dsp_ai.generations g JOIN dsp_ai.enhancements e ON e.id = g.enhancement_id "
            "WHERE g.id = $1::uuid", generation_id,
        )
    finally:
        await conn.close()
    if gen is None: raise HTTPException(404)

    input_ids = gen["input_ids"] or []
    hop = []
    if input_ids:
        from ..brain.client import run as brain_run
        hop = await brain_run(
            "MATCH (n) WHERE n.id IN $ids "
            "OPTIONAL MATCH (n)-[r]-(m) "
            "RETURN n, collect({edge: type(r), other: m.id}) AS neighbors LIMIT 20",
            ids=input_ids,
        )

    narrative = (
        f"Generated by `{gen['model']}` (quality {gen['quality_level']}) at {gen['created_at']}. "
        f"Took {gen['latency_ms']}ms. Fed by {len(input_ids)} Brain nodes."
    )
    if gen["quality_warnings"]:
        narrative += f" Warnings: {gen['quality_warnings']}."

    return {
        "generation_id": generation_id,
        "enhancement": {"name": gen["enh_name"], "version": gen["enh_version"]},
        "narrative": narrative,
        "provenance": dict(gen),
        "brain_one_hop": hop,
    }
```

- [ ] **Step 2.4: Add `/v1/telemetry`**

```python
class TelemetryEvent(BaseModel):
    kind: str                  # widget.rendered | widget.dwelled | widget.clicked | widget.declined
    user_id: str
    enhancement_id: str | None = None
    object_id: str | None = None
    duration_s: float | None = None
    details: dict = {}

@router.post("/v1/telemetry")
async def telemetry(body: TelemetryEvent) -> dict:
    from ..brain.feeders.behavior import record_event
    await record_event(body)
    return {"ok": True}
```

- [ ] **Step 2.5: Contract tests**

Tests covering:
- `/v1/actions/{id}/run` — 404 on unknown id; 200 on existing id with mocked engine
- `/v1/stream/{id}/{user}` — connect, emit NOTIFY from a test, receive event within 2s, disconnect cleanly
- `/v1/why/{gen_id}` — 404 on unknown; 200 on existing with narrative non-empty
- `/v1/telemetry` — 200 + event recorded (mock `record_event`)

- [ ] **Step 2.6: Commit**

```bash
git add src/spec2sphere/dsp_ai/adapters/live.py tests/dsp_ai/test_live_adapter_v1b.py
git commit -m "feat(dsp-ai): live adapter breadth (actions + SSE + why + telemetry)"
```

---

## Task 3: Behavior feeder

**Files:**
- Create: `src/spec2sphere/dsp_ai/brain/feeders/behavior.py`
- Create: `tests/dsp_ai/test_behavior_feeder.py`

- [ ] **Step 3.1: record_event**

```python
# src/spec2sphere/dsp_ai/brain/feeders/behavior.py
"""Telemetry → user_state (Postgres) + behavior edges (Brain)."""
from __future__ import annotations
import datetime as dt
import asyncpg
from spec2sphere.config import settings
from ..client import run as brain_run

async def record_event(ev) -> None:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute(
            """
            INSERT INTO dsp_ai.user_state (user_id, last_visited_at, updated_at)
            VALUES ($1, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                last_visited_at = EXCLUDED.last_visited_at,
                updated_at = EXCLUDED.updated_at
            """,
            ev.user_id,
        )
    finally:
        await conn.close()

    if ev.object_id:
        if ev.kind == "widget.rendered":
            await brain_run(
                """
                MERGE (u:User {email: $email})
                MERGE (o:DspObject {id: $oid})
                MERGE (u)-[r:OPENED]->(o)
                SET r.ts = datetime($ts)
                """,
                email=ev.user_id, oid=ev.object_id, ts=dt.datetime.utcnow().isoformat(),
            )
        elif ev.kind == "widget.dwelled":
            await brain_run(
                """
                MERGE (u:User {email: $email})
                MERGE (o:DspObject {id: $oid})
                MERGE (u)-[r:DWELLED_ON]->(o)
                SET r.duration_s = coalesce(r.duration_s, 0.0) + $d
                """,
                email=ev.user_id, oid=ev.object_id, d=ev.duration_s or 0.0,
            )
```

- [ ] **Step 3.2: Nightly topic synthesis (LLM pass)**

Add `synthesize_topics()` as a Celery task triggered by a separate Beat entry `0 3 * * *` (03:00 daily). It:
1. Queries Brain for recent `OPENED` + `DWELLED_ON` per user
2. Clusters DSP object ids into topics via a single LLM call per user
3. Writes `Topic` nodes + `INTERESTED_IN` edges with weights

Test with a small fake LLM and 3 synthetic users.

- [ ] **Step 3.3: Tests**

```python
# tests/dsp_ai/test_behavior_feeder.py
import pytest, asyncpg
from spec2sphere.config import settings
from spec2sphere.dsp_ai.brain.feeders.behavior import record_event
from spec2sphere.dsp_ai.brain.client import run as brain_run
from spec2sphere.dsp_ai.adapters.live import TelemetryEvent

@pytest.mark.asyncio
async def test_rendered_event_creates_user_state_and_opened_edge(clean_brain_and_db):
    ev = TelemetryEvent(kind="widget.rendered", user_id="h@x", object_id="s.sales.daily")
    await record_event(ev)

    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow("SELECT user_id, last_visited_at FROM dsp_ai.user_state WHERE user_id=$1", "h@x")
        assert row is not None and row["last_visited_at"] is not None
    finally:
        await conn.close()

    rows = await brain_run(
        "MATCH (u:User {email:'h@x'})-[:OPENED]->(o:DspObject {id:'s.sales.daily'}) RETURN count(*) AS n"
    )
    assert rows[0]["n"] == 1
```

- [ ] **Step 3.4: Commit**

```bash
git add src/spec2sphere/dsp_ai/brain/feeders/behavior.py tests/dsp_ai/test_behavior_feeder.py
git commit -m "feat(dsp-ai): behavior feeder + nightly topic synthesis"
```

---

## Task 4: SAC Custom Widget — build pipeline + renderers

**Files:**
- Create: `src/spec2sphere/widget/package.json`, `tsconfig.json`, `esbuild.config.mjs`
- Create: `src/spec2sphere/widget/src/main.ts`, `api.ts`, `telemetry.ts`, `sac_context.ts`, `types.ts`
- Create: 6 renderer files under `src/spec2sphere/widget/src/renderers/`
- Create: Vitest config + tests
- Create: `src/spec2sphere/widget/manifest.template.json`

- [ ] **Step 4.1: package.json + tsconfig + esbuild**

```json
{
  "name": "spec2sphere-ai-widget",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "build": "node esbuild.config.mjs",
    "test": "vitest run"
  },
  "devDependencies": {
    "esbuild": "0.21.4",
    "typescript": "5.4.5",
    "vitest": "1.6.0",
    "happy-dom": "14.12.0",
    "@types/node": "20.12.12"
  }
}
```

```js
// esbuild.config.mjs
import { build } from "esbuild";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";

mkdirSync("dist", { recursive: true });
await build({
  entryPoints: ["src/main.ts"],
  bundle: true,
  minify: true,
  sourcemap: true,
  target: ["es2020"],
  format: "iife",
  outfile: "dist/main.js",
});

const js = readFileSync("dist/main.js");
const integrity = "sha384-" + createHash("sha384").update(js).digest("base64");
const manifest = readFileSync("manifest.template.json", "utf-8")
  .replace("{{INTEGRITY}}", integrity);
writeFileSync("dist/manifest.json", manifest);
console.log("widget built, integrity:", integrity);
```

- [ ] **Step 4.2: types.ts (mirrors server shape)**

```typescript
// src/spec2sphere/widget/src/types.ts
export type RenderHint = "narrative_text" | "ranked_list" | "callout" | "button" | "brief" | "chart";
export interface Provenance {
  prompt_hash: string;
  model?: string;
  quality_level?: string;
  latency_ms?: number;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number;
  input_ids?: string[];
}
export interface EnhanceResponse {
  generation_id: string;
  enhancement_id: string;
  render_hint: RenderHint;
  content: Record<string, unknown> | string;
  quality_warnings: string[];
  provenance: Provenance;
  _cached?: boolean;
  stale?: boolean;
  data_stale?: boolean;
  error_kind?: string;
}
```

- [ ] **Step 4.3: main.ts Custom Element**

```typescript
// src/spec2sphere/widget/src/main.ts
import { fetchEnhancement, openStream, runAction } from "./api";
import { postTelemetry } from "./telemetry";
import { resolveContext } from "./sac_context";
import { renderByHint } from "./renderers";

class Spec2SphereAiWidget extends HTMLElement {
  static get observedAttributes() { return ["enhancementid", "apibase", "authmode"]; }
  private root: ShadowRoot;
  private evtSource: EventSource | null = null;
  private lastResponse: any = null;
  private mountedAt = performance.now();

  constructor() {
    super();
    this.root = this.attachShadow({ mode: "open" });
  }

  async connectedCallback() {
    const enhancementId = this.getAttribute("enhancementid") || "";
    const apiBase = this.getAttribute("apibase") || "";
    if (!enhancementId || !apiBase) { this.renderError("missing enhancementId/apiBase"); return; }
    const ctx = await resolveContext();
    try {
      this.lastResponse = await fetchEnhancement(apiBase, enhancementId, ctx);
      this.render(this.lastResponse);
      this.dispatch("onGenerated", { generation_id: this.lastResponse.generation_id });
      postTelemetry(apiBase, { kind: "widget.rendered", user_id: ctx.user, enhancement_id: enhancementId });
      this.evtSource = openStream(apiBase, enhancementId, ctx.user, async () => {
        this.lastResponse = await fetchEnhancement(apiBase, enhancementId, ctx);
        this.render(this.lastResponse);
      });
    } catch (e: any) {
      this.renderError(e?.message || "render_failed");
      this.dispatch("onError", { message: String(e) });
    }
  }

  disconnectedCallback() {
    if (this.evtSource) { this.evtSource.close(); this.evtSource = null; }
    const ctx = { user: this.lastResponse?.provenance?.user || "_" };
    const durS = (performance.now() - this.mountedAt) / 1000;
    const apiBase = this.getAttribute("apibase") || "";
    const enhancementId = this.getAttribute("enhancementid") || "";
    if (apiBase) postTelemetry(apiBase, {
      kind: "widget.dwelled", user_id: ctx.user, enhancement_id: enhancementId, duration_s: durS,
    });
  }

  private render(data: any) {
    this.root.innerHTML = "";
    const container = document.createElement("div");
    container.innerHTML = renderByHint(data);
    this.root.appendChild(container);
  }

  private renderError(msg: string) {
    this.root.innerHTML = `<div style="padding:12px;color:#64748b;font:14px system-ui">Content temporarily unavailable.<br><small>${msg}</small></div>`;
  }

  private dispatch(name: string, detail: any) {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }
}
customElements.define("spec2sphere-ai-widget", Spec2SphereAiWidget);
```

- [ ] **Step 4.4: api.ts + telemetry.ts + sac_context.ts**

Compact implementations of:
- `fetchEnhancement(apiBase, id, ctx)` → `POST /v1/enhance/{id}`
- `runAction(apiBase, id, ctx)` → `POST /v1/actions/{id}/run`
- `openStream(apiBase, id, user, onEvent)` → `new EventSource` to `/v1/stream/{id}/{user}`
- `postTelemetry(apiBase, event)` → `POST /v1/telemetry` (fire-and-forget, no await)
- `resolveContext()` → calls SAC globals if available (`globalThis?.sap?.bi?.designer?.currentStoryId`), falls back to widget properties

- [ ] **Step 4.5: Renderers**

One file per render_hint. Each exports a `render(data): string` that returns safe HTML (sanitize markdown via a tiny inline renderer — no external deps). `renderers/index.ts` dispatches by `data.render_hint`.

- [ ] **Step 4.6: manifest.template.json**

```json
{
  "name": "com.spec2sphere.ai-widget",
  "version": "1.0.0",
  "description": "Spec2Sphere AI enhancement renderer",
  "webcomponents": [{
    "kind": "main",
    "tag": "spec2sphere-ai-widget",
    "url": "{{API_BASE}}/widget/main.js",
    "integrity": "{{INTEGRITY}}",
    "ignoreIntegrity": false
  }],
  "properties": {
    "enhancementId": { "type": "string", "description": "UUID of the enhancement" },
    "contextHints":  { "type": "string", "description": "JSON overrides" },
    "fallbackUser":  { "type": "string" },
    "apiBase":       { "type": "string" },
    "authMode":      { "type": "string", "enum": ["bearer", "oauth"] }
  },
  "methods": {
    "refresh": { "description": "Force re-fetch" },
    "setUser": { "parameters": [{ "name": "userId", "type": "string" }] }
  },
  "events": { "onGenerated": {}, "onError": {}, "onInteraction": {} }
}
```

- [ ] **Step 4.7: Vitest tests**

```typescript
// src/spec2sphere/widget/tests/renderers.test.ts
import { describe, it, expect } from "vitest";
import { renderByHint } from "../src/renderers";

describe("renderers", () => {
  it("narrative_text renders markdown", () => {
    const html = renderByHint({
      render_hint: "narrative_text",
      content: { narrative_text: "**hello** world" },
    });
    expect(html).toContain("<strong>hello</strong>");
  });

  it("ranked_list renders items with rank + reason", () => {
    const html = renderByHint({
      render_hint: "ranked_list",
      content: { items: [{ item_id: "A", score: 0.9, reason: "top" }, { item_id: "B", score: 0.5 }] },
    });
    expect(html).toContain("A");
    expect(html).toContain("top");
    expect(html).toContain("B");
  });
});
```

Lifecycle test with `happy-dom` mounting the custom element + mocking `fetch` to return canned responses.

- [ ] **Step 4.8: Build + run tests**

```bash
cd src/spec2sphere/widget
npm install
npm run build
npm test
```

Expected: `dist/main.js` <50 KB, `dist/manifest.json` with computed integrity; all tests pass.

- [ ] **Step 4.9: Commit**

```bash
git add src/spec2sphere/widget/
git commit -m "feat(widget): SAC Custom Widget (TS, esbuild, renderers, tests)"
```

---

## Task 5: Widget hosting routes + CORS

**Files:**
- Create: `src/spec2sphere/web/widget_routes.py`
- Modify: `src/spec2sphere/app.py`

- [ ] **Step 5.1: Serve widget assets**

```python
# src/spec2sphere/web/widget_routes.py
"""Serve the SAC Custom Widget bundle + manifest with CORS + integrity."""
import os
from pathlib import Path
from fastapi import APIRouter, Response, HTTPException
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/widget", tags=["widget"])
WIDGET_DIR = Path(__file__).resolve().parents[2] / "widget" / "dist"

def _cors_headers() -> dict:
    origins = os.environ.get("WIDGET_ALLOWED_ORIGINS", "*")
    return {"Access-Control-Allow-Origin": origins}

@router.get("/manifest.json")
async def manifest() -> Response:
    path = WIDGET_DIR / "manifest.json"
    if not path.exists(): raise HTTPException(503, "widget not built")
    text = path.read_text().replace("{{API_BASE}}", os.environ.get("PUBLIC_API_BASE", ""))
    return Response(content=text, media_type="application/json", headers=_cors_headers())

@router.get("/main.js")
async def main_js() -> FileResponse:
    path = WIDGET_DIR / "main.js"
    if not path.exists(): raise HTTPException(503, "widget not built")
    return FileResponse(path, media_type="application/javascript", headers=_cors_headers())

@router.get("/main.js.map")
async def main_js_map() -> FileResponse:
    path = WIDGET_DIR / "main.js.map"
    if not path.exists(): raise HTTPException(503, "widget not built")
    return FileResponse(path, media_type="application/json", headers=_cors_headers())
```

- [ ] **Step 5.2: Mount + build-at-docker-build**

Modify `src/spec2sphere/app.py`:

```python
from spec2sphere.web.widget_routes import router as widget_router
app.include_router(widget_router)
```

Update `Dockerfile` stage to run `cd src/spec2sphere/widget && npm ci && npm run build` during image build. Outputs copied into the runtime image.

- [ ] **Step 5.3: Contract test**

Smoke tests for `/widget/manifest.json` and `/widget/main.js` returning 200 with correct CORS header.

- [ ] **Step 5.4: Commit**

```bash
git add src/spec2sphere/web/widget_routes.py src/spec2sphere/app.py Dockerfile tests/dsp_ai/test_widget_hosting.py
git commit -m "feat(widget): host bundle + manifest with CORS + build in Docker"
```

---

## Task 6: Studio polish — template library, Generation Log, Brain Explorer, Admin chip

**Files:**
- Create: `src/spec2sphere/web/ai_studio/templates_library.py`, `generation_log.py`, `brain_explorer.py`
- Create: 3 HTML partials under `templates/partials/`
- Modify: `ai_studio_editor.html` — Monaco integration (lazy-load) + session preview budget meter + Admin chip link

- [ ] **Step 6.1: Template library**

`GET /ai-studio/templates/` lists `templates/seeds/*.json`. Click "Fork" → POSTs to `/ai-studio/` creating a new draft pre-filled from the seed.

- [ ] **Step 6.2: Generation Log**

`GET /ai-studio/log` with filters: enhancement_id, user_id, since, model, error_kind.
Table: `id | enhancement | user | ctx | model | latency | cost | warnings | preview?`
Click row → `GET /ai-studio/log/{gen_id}` — full provenance drill-down calling `/v1/why/{gen_id}`.

- [ ] **Step 6.3: Brain Explorer**

`GET /ai-studio/brain` with `vis-network.js` (lazy-loaded CDN per HTMX pattern). Initial query returns 50 nodes + edges. Cypher console below (text input + "Run" button) that POSTs to `/ai-studio/brain/query` — server-side allowlist on Cypher verbs (`MATCH`, `RETURN`, no `CREATE` / `DELETE` / `SET`).

"Seed from landscape" button triggers schema_semantic feeder from the latest graph.json.

- [ ] **Step 6.4: Monaco editor for prompt_template in the Editor**

Swap the `<textarea>` for Monaco using the HTMX lazy-load pattern. Check `typeof monaco`, inject `<script src="//cdn.../loader.js">`, `onload` → `require(['vs/editor/editor.main'], ...)`. Falls back to `<textarea>` if CDN unreachable.

- [ ] **Step 6.5: Session preview budget meter**

Track preview count per session in `sessionStorage`. Default 20 max. Every preview click decrements and re-renders. Reset button. Server-side enforcement lives in `/ai-studio/{id}/preview` (reject with 429 if session has exceeded budget — pass session id in a header).

- [ ] **Step 6.6: Admin chip link in preview render**

When the preview JSON has `generation_id`, show `[generation_id] [ms] [model]` as a small clickable pill → links to `/ai-studio/log/{gen_id}`.

- [ ] **Step 6.7: Commit**

```bash
git add src/spec2sphere/web/ai_studio/ src/spec2sphere/web/templates/partials/ai_studio_*.html
git commit -m "feat(ai-studio): template library + Generation Log + Brain Explorer + Monaco + admin chip"
```

---

## Task 7: Seed 4 more templates

**Files:**
- Create: 4 seed JSONs under `templates/seeds/`

- [ ] **Step 7.1: Narrative Overlay**

```json
// templates/seeds/narrative_overlay.json
{
  "name": "Narrative Overlay — Sales",
  "kind": "narrative",
  "mode": "batch",
  "bindings": {
    "data": { "dsp_query": "SELECT date_trunc('day', order_date) AS d, SUM(amount) AS rev FROM public.sales WHERE order_date >= NOW() - INTERVAL '30 days' GROUP BY 1 ORDER BY 1", "parameters": {} },
    "semantic": { "cypher": "MATCH (g:Glossary)-[:DESCRIBES]->(o:DspObject {id:$obj}) RETURN g.term, g.definition_source", "parameters": {"obj":"public.sales"} }
  },
  "adaptive_rules": { "per_user": true, "per_delta": true },
  "prompt_template": "Describe the 30-day sales trend in ≤3 bullets for {{ user_id }}. Data:\n{% for r in dsp_data %}- {{ r.d }}: {{ r.rev }}\n{% endfor %}\n\nRelevant terms: {% for b in brain_nodes %}{{ b.term }}; {% endfor %}\n\nReturn JSON {narrative_text:string, key_points:string[]}.",
  "output_schema": {"type":"object","required":["narrative_text","key_points"],"properties":{"narrative_text":{"type":"string"},"key_points":{"type":"array","items":{"type":"string"}}}},
  "render_hint": "narrative_text",
  "ttl_seconds": 1800
}
```

- [ ] **Step 7.2: Anomaly Explainer (action)**

```json
// templates/seeds/anomaly_explainer.json
{
  "name": "Anomaly Explainer",
  "kind": "action",
  "mode": "live",
  "bindings": {
    "data": { "dsp_query": "SELECT * FROM public.sales_anomalies WHERE object_id = $1 ORDER BY detected_at DESC LIMIT 5", "parameters": {"object_id":""} }
  },
  "adaptive_rules": { "per_user": false },
  "prompt_template": "Explain the anomalies for {{ dsp_data[0].object_id }} in plain language. Data:\n{{ dsp_data | tojson }}\n\nReturn JSON {explanation:string, suspected_causes:string[]}.",
  "output_schema": {"type":"object","required":["explanation","suspected_causes"],"properties":{"explanation":{"type":"string"},"suspected_causes":{"type":"array","items":{"type":"string"}}}},
  "render_hint": "callout",
  "ttl_seconds": 0
}
```

- [ ] **Step 7.3: Column Title Gen (item_enrich)**

```json
// templates/seeds/column_title_gen.json
{
  "name": "Column Title Gen",
  "kind": "item_enrich",
  "mode": "batch",
  "bindings": {
    "data": { "dsp_query": "SELECT object_id, column_name, dtype FROM v_unlabeled_columns LIMIT 20", "parameters": {} },
    "semantic": { "cypher": "MATCH (c:Column)-[:DESCRIBES]-(g:Glossary) RETURN c.id, g.term LIMIT 50", "parameters": {} }
  },
  "adaptive_rules": { "per_user": false },
  "prompt_template": "For each column below, propose a business-friendly title + one-sentence description + 2–3 tags.\nColumns: {{ dsp_data | tojson }}\nHints from glossary: {{ brain_nodes | tojson }}\nReturn JSON { enrichments: [ { object_type:'Column', object_id, title, description, tags:[...], kpi_suggestions:[] } ] }.",
  "output_schema": {"type":"object","required":["enrichments"],"properties":{"enrichments":{"type":"array","items":{"type":"object","required":["object_type","object_id","title"]}}}},
  "render_hint": "callout",
  "ttl_seconds": 86400
}
```

- [ ] **Step 7.4: KPI Suggester (ranking)**

```json
// templates/seeds/kpi_suggester.json
{
  "name": "KPI Suggester",
  "kind": "ranking",
  "mode": "both",
  "bindings": {
    "data": { "dsp_query": "SELECT object_id, column_name FROM v_candidate_kpi_columns LIMIT 30", "parameters": {} },
    "semantic": { "cypher": "MATCH (u:User {email:$user})-[:INTERESTED_IN]->(t:Topic) RETURN t.name", "parameters": {"user":"henning@x"} }
  },
  "adaptive_rules": { "per_user": true },
  "prompt_template": "Pick the 5 most useful KPIs to monitor for {{ user_id }}.\nCandidates: {{ dsp_data | tojson }}\nUser interests: {{ brain_nodes | tojson }}\nReturn JSON { items: [ { item_id, score, reason } ] }.",
  "output_schema": {"type":"object","required":["items"],"properties":{"items":{"type":"array","items":{"type":"object","required":["item_id","score","reason"]}}}},
  "render_hint": "ranked_list",
  "ttl_seconds": 3600
}
```

- [ ] **Step 7.5: Commit**

```bash
git add templates/seeds/
git commit -m "feat(dsp-ai): seed 4 more enhancement templates (narrative, action, item_enrich, ranking)"
```

---

## Task 8: `graph.json` → Neo4j write-both + cutover

**Files:**
- Modify: `src/spec2sphere/scanner/output.py` — write-both under `BRAIN_WRITE_BOTH=true`
- Modify: `src/spec2sphere/web/server.py`, `scanner/chain_builder.py` — dual read path under `GRAPH_READ_FROM_BRAIN=true`
- Create: `tests/dsp_ai/test_graph_cutover.py`

- [ ] **Step 8.1: Dual write in scanner/output.py**

After writing `graph.json`, if `BRAIN_WRITE_BOTH` is true, also call `schema_semantic.feed_from_graph_json(customer, graph_file)`. This keeps file as source of truth during the transition.

- [ ] **Step 8.2: Dual read path**

Introduce a small `graph_repo` helper:

```python
# src/spec2sphere/scanner/graph_repo.py
import os, json
from pathlib import Path
from ..dsp_ai.brain.client import run as brain_run

def read_from_brain() -> bool:
    return os.environ.get("GRAPH_READ_FROM_BRAIN", "false").lower() == "true"

async def list_objects(customer: str) -> list[dict]:
    if read_from_brain():
        rows = await brain_run(
            "MATCH (o:DspObject {customer: $c}) "
            "OPTIONAL MATCH (o)-[:HAS_COLUMN]->(c:Column) "
            "RETURN o.id AS id, o.kind AS kind, collect({name:c.id}) AS columns",
            c=customer,
        )
        return [dict(r) for r in rows]
    # legacy file read
    path = Path("output") / "graph.json"
    return json.loads(path.read_text()).get("objects", []) if path.exists() else []
```

Every call site in `server.py` + `chain_builder.py` goes through `graph_repo.list_objects` / `get_chains`. One grep-and-replace pass.

- [ ] **Step 8.3: Tests**

```python
# tests/dsp_ai/test_graph_cutover.py
import os, json, pytest
from pathlib import Path
from spec2sphere.scanner.graph_repo import list_objects

@pytest.mark.asyncio
async def test_read_from_file_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_READ_FROM_BRAIN", "false")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "graph.json").write_text(json.dumps({"objects": [{"id": "x"}]}))
    objs = await list_objects("horvath")
    assert any(o["id"] == "x" for o in objs)

@pytest.mark.asyncio
async def test_read_from_brain_when_flag_on(monkeypatch, seeded_brain):
    monkeypatch.setenv("GRAPH_READ_FROM_BRAIN", "true")
    objs = await list_objects("horvath")
    assert any(o["id"] == "seed.obj" for o in objs)
```

- [ ] **Step 8.4: Gradual flip**

1. Deploy Session B with `BRAIN_WRITE_BOTH=true, GRAPH_READ_FROM_BRAIN=false` → writes go both places, reads stay on file
2. Smoke test for 1 week
3. Flip `GRAPH_READ_FROM_BRAIN=true` → reads flow through Brain
4. After 1 more week of stability, remove the legacy file path (Session C cleanup)

- [ ] **Step 8.5: Commit**

```bash
git add src/spec2sphere/scanner/graph_repo.py src/spec2sphere/scanner/output.py src/spec2sphere/scanner/chain_builder.py src/spec2sphere/web/server.py tests/dsp_ai/test_graph_cutover.py
git commit -m "feat(dsp-ai): graph.json → Neo4j write-both bridge + dual read path"
```

---

## Task 9: Copilot ContentHub → Corporate Brain

**Files:**
- Modify: `src/spec2sphere/copilot/content_hub.py`

- [ ] **Step 9.1: Replace filesystem walks with Brain queries**

ContentHub's topic + object listing today walks `output/objects/*.md`. Replace with:

```python
from spec2sphere.dsp_ai.brain.client import run as brain_run

async def list_topics() -> list[dict]:
    rows = await brain_run("MATCH (t:Topic) RETURN t.name AS name, t.vector AS vector")
    return [dict(r) for r in rows]

async def objects_for_topic(topic: str) -> list[dict]:
    rows = await brain_run(
        "MATCH (o:DspObject)-[:CORRELATED_WITH]-(t:Topic {name:$t}) RETURN o.id AS id",
        t=topic,
    )
    return [dict(r) for r in rows]
```

Keep the filesystem walker as a fallback for `.md` blobs (consultant-facing docs still live as files).

- [ ] **Step 9.2: Regression tests**

Existing ContentHub tests should continue to pass. If they depended on filesystem walks, switch them to seed the Brain instead and assert the same shape returns.

- [ ] **Step 9.3: Commit**

```bash
git add src/spec2sphere/copilot/content_hub.py tests/copilot/
git commit -m "refactor(copilot): ContentHub reads from Corporate Brain (one graph, two consumers)"
```

---

## Task 10: MCP Studio tools

**Files:**
- Create: `src/spec2sphere/copilot/studio_tools.py`
- Modify: `src/spec2sphere/copilot/mcp_server.py`
- Create: `tests/dsp_ai/test_mcp_studio_tools.py`

- [ ] **Step 10.1: Tool definitions**

Expose 9 tools against the existing Spec2Sphere MCP server:

```python
# src/spec2sphere/copilot/studio_tools.py
"""MCP tools for AI Studio. Registered by mcp_server.register_tools()."""
from __future__ import annotations
import json, uuid
import asyncpg, httpx
from spec2sphere.config import settings

async def list_enhancements(status: str | None = None) -> list[dict]:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        q = "SELECT id::text, name, kind, version, status FROM dsp_ai.enhancements"
        args: list = []
        if status:
            q += " WHERE status = $1"; args.append(status)
        q += " ORDER BY updated_at DESC"
        rows = await conn.fetch(q, *args)
        return [dict(r) for r in rows]
    finally:
        await conn.close()

async def get_enhancement(enhancement_id: str) -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT id::text, name, kind, version, status, config "
            "FROM dsp_ai.enhancements WHERE id = $1::uuid", enhancement_id,
        )
        if row is None: raise LookupError(enhancement_id)
        return {**dict(row), "config": row["config"] if isinstance(row["config"], dict) else json.loads(row["config"])}
    finally:
        await conn.close()

async def create_enhancement(name: str, kind: str, config: dict, author: str = "mcp") -> dict:
    new_id = str(uuid.uuid4())
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author) VALUES ($1::uuid, $2, $3, $4::jsonb, $5)",
            new_id, name, kind, json.dumps(config), author,
        )
    finally:
        await conn.close()
    return {"id": new_id, "status": "draft"}

async def update_enhancement(enhancement_id: str, patch: dict) -> dict:
    current = await get_enhancement(enhancement_id)
    merged = {**current["config"], **patch}
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute(
            "UPDATE dsp_ai.enhancements SET config = $2::jsonb, updated_at=NOW() WHERE id=$1::uuid",
            enhancement_id, json.dumps(merged),
        )
    finally:
        await conn.close()
    return {"id": enhancement_id, "ok": True}

async def preview(enhancement_id: str, user: str = "mcp", context_hints: dict | None = None) -> dict:
    import os
    base = os.environ.get("DSPAI_URL", "http://dsp-ai:8000")
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(f"{base}/v1/enhance/{enhancement_id}",
                            json={"user": user, "context_hints": context_hints or {}, "preview": True})
        resp.raise_for_status()
        return resp.json()

async def publish(enhancement_id: str) -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute(
            "UPDATE dsp_ai.enhancements SET status='published', updated_at=NOW() WHERE id=$1::uuid",
            enhancement_id,
        )
    finally:
        await conn.close()
    from spec2sphere.dsp_ai.events import emit
    await emit("enhancement_published", {"id": enhancement_id})
    return {"id": enhancement_id, "status": "published"}

async def query_brain(cypher: str, parameters: dict | None = None) -> list[dict]:
    verb = cypher.strip().split()[0].upper()
    if verb not in ("MATCH", "RETURN", "CALL", "WITH", "UNWIND"):
        raise ValueError(f"read-only only; got {verb}")
    from spec2sphere.dsp_ai.brain.client import run as brain_run
    return await brain_run(cypher, **(parameters or {}))

async def generation_log(enhancement_id: str | None = None, user_id: str | None = None, limit: int = 50) -> list[dict]:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        q = "SELECT id::text, enhancement_id::text, user_id, model, latency_ms, cost_usd, quality_warnings, preview, created_at FROM dsp_ai.generations"
        filters = []; args: list = []
        if enhancement_id: filters.append("enhancement_id = $" + str(len(args)+1) + "::uuid"); args.append(enhancement_id)
        if user_id: filters.append("user_id = $" + str(len(args)+1)); args.append(user_id)
        if filters: q += " WHERE " + " AND ".join(filters)
        q += " ORDER BY created_at DESC LIMIT " + str(limit)
        rows = await conn.fetch(q, *args)
        return [dict(r) for r in rows]
    finally:
        await conn.close()

async def rollback(enhancement_id: str, to_version: int) -> dict:
    # re-stamp older config as current — archive current, insert with new version
    # (simplified — fill in according to your version strategy)
    raise NotImplementedError("rollback ships in Session C with full version history")
```

- [ ] **Step 10.2: Register in mcp_server.py**

```python
from spec2sphere.copilot import studio_tools

def register_tools(mcp):
    mcp.tool(studio_tools.list_enhancements)
    mcp.tool(studio_tools.get_enhancement)
    mcp.tool(studio_tools.create_enhancement)
    mcp.tool(studio_tools.update_enhancement)
    mcp.tool(studio_tools.preview)
    mcp.tool(studio_tools.publish)
    mcp.tool(studio_tools.query_brain)
    mcp.tool(studio_tools.generation_log)
```

- [ ] **Step 10.3: Tests**

Each tool: create a fixture scenario, call the tool, assert observable side effect (Postgres row / LLM mock invoked / NOTIFY fired). `query_brain` test: assert `CREATE` is rejected with ValueError.

- [ ] **Step 10.4: Commit**

```bash
git add src/spec2sphere/copilot/studio_tools.py src/spec2sphere/copilot/mcp_server.py tests/dsp_ai/test_mcp_studio_tools.py
git commit -m "feat(copilot): MCP tools for AI Studio (8 tools)"
```

---

## Task 11: Remove remaining frontend polling

**Files:**
- Modify: `src/spec2sphere/web/templates/partials/browser_viewer.html`
- Modify: `src/spec2sphere/web/templates/partials/agent_terminal.html`
- Create: SSE endpoints in `src/spec2sphere/web/server.py` for the events these pages polled

- [ ] **Step 11.1: Identify the two `setInterval` / `setTimeout` pollers**

From the Session B kickoff grep:
- `browser_viewer.html:61` — `setInterval(...)` polling
- `agent_terminal.html:339` — `setTimeout(fetchSessionList, 5000)` loop

- [ ] **Step 11.2: Add SSE endpoints**

```python
# in web/server.py
from sse_starlette.sse import EventSourceResponse
from spec2sphere.dsp_ai.events import subscribe

@router.get("/events/browser")
async def browser_events():
    async def gen():
        async for ev in subscribe("browser_state_changed"):
            yield {"event": "update", "data": json.dumps(ev)}
    return EventSourceResponse(gen())

@router.get("/events/agent-sessions")
async def agent_session_events():
    async def gen():
        async for ev in subscribe("agent_session_changed"):
            yield {"event": "update", "data": json.dumps(ev)}
    return EventSourceResponse(gen())
```

- [ ] **Step 11.3: Publishers emit NOTIFY on state change**

Find every place in the browser/agent code that mutates state and append `emit("browser_state_changed", {...})` / `emit("agent_session_changed", {...})`.

- [ ] **Step 11.4: Swap frontend to EventSource**

```html
<!-- Inside {% block content %} — replaces setInterval -->
<script>
(function() {
  var es = new EventSource('/events/browser');
  es.addEventListener('update', function(e) {
    var data = JSON.parse(e.data);
    // refresh the relevant DOM
  });
  window.addEventListener('beforeunload', function() { es.close(); });
})();
</script>
```

- [ ] **Step 11.5: Commit**

```bash
git add src/spec2sphere/web/templates/partials/browser_viewer.html src/spec2sphere/web/templates/partials/agent_terminal.html src/spec2sphere/web/server.py
git commit -m "refactor(web): replace frontend polling with SSE over Postgres LISTEN/NOTIFY"
```

---

## Task 12: file_drop filesystem poll → inotify

**Files:**
- Modify: `src/spec2sphere/tasks/file_drop_tasks.py`
- Modify: `src/spec2sphere/tasks/schedules.py` — remove 5-min poll entry

- [ ] **Step 12.1: Replace scheduled poll with inotify listener**

```python
# src/spec2sphere/tasks/file_drop_tasks.py — new long-running task replaces the 5-min poll
import asyncio
from watchfiles import awatch   # pip install watchfiles
from ..dsp_ai.events import emit

async def watch_drops(drop_dir: str):
    async for changes in awatch(drop_dir):
        for kind, path in changes:
            if kind.name in ("added", "modified"):
                await emit("file_dropped", {"path": path})
```

Another Celery task subscribes to `file_dropped` NOTIFY and runs `process_drop(path)`.

- [ ] **Step 12.2: Remove the 5-min Beat entry**

Delete the `file-drop-poll` block from `schedules.py`.

- [ ] **Step 12.3: Run a small integration test**

Drop a file into the watched dir, assert the Celery task fires within 2 seconds.

- [ ] **Step 12.4: Commit**

```bash
git add src/spec2sphere/tasks/file_drop_tasks.py src/spec2sphere/tasks/schedules.py
git commit -m "refactor(tasks): file_drop 5-min poll → inotify + NOTIFY"
```

---

## Task 13: Universal LLM observability — every call lands in `dsp_ai.generations`

**Why this task:** Existing Spec2Sphere modules (`agents/*`, `migration/*`, `core/standards/*`, `core/knowledge/*`, `standards/rule_extractor.py`) go through `LLMProvider.generate()` / `generate_json()` and never touch `dsp_ai.generations`. Without this task, Session C's cost guard covers only engine-driven enhancements — a large observability gap. This closes it with a single factory change; no call sites modified.

**Files:**
- Create: `migrations/versions/013_dsp_ai_generations_nullable_enh.py`
- Create: `src/spec2sphere/llm/observed.py`
- Modify: `src/spec2sphere/llm/base.py` — add optional `caller` kwarg (default-compatible)
- Modify: `src/spec2sphere/llm/__init__.py` — wrap in factory
- Create: `tests/dsp_ai/test_observed_llm.py`

- [ ] **Step 13.1: Migration — relax FK, add caller column**

```python
# migrations/versions/013_dsp_ai_generations_nullable_enh.py
"""Allow non-engine LLM calls to log into dsp_ai.generations."""
from alembic import op

revision = "013"
down_revision = "012"   # after Session C's 012 — order carefully; if C hasn't run yet, adjust down_revision to 011
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE dsp_ai.generations ALTER COLUMN enhancement_id DROP NOT NULL")
    op.execute("ALTER TABLE dsp_ai.generations ADD COLUMN IF NOT EXISTS caller TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS idx_generations_caller ON dsp_ai.generations(caller) WHERE caller IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS dsp_ai.idx_generations_caller")
    op.execute("ALTER TABLE dsp_ai.generations DROP COLUMN IF EXISTS caller")
    op.execute("UPDATE dsp_ai.generations SET enhancement_id = gen_random_uuid() WHERE enhancement_id IS NULL")
    op.execute("ALTER TABLE dsp_ai.generations ALTER COLUMN enhancement_id SET NOT NULL")
```

*Note:* Session C's migration 012 is later in Session C's plan. If Session B merges before Session C's 012 runs on prod, renumber this as 012 and Session C's as 013. Resolve during Session B task execution.

- [ ] **Step 13.2: `base.py` — add optional `caller` kwarg**

```python
# In src/spec2sphere/llm/base.py — update abstract method signatures

class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
        caller: str | None = None,      # NEW — identifies the call site for observability
    ) -> Optional[str]: ...

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
        caller: str | None = None,      # NEW
    ) -> Optional[dict]: ...
```

Update each concrete provider (`anthropic.py`, `azure_openai.py`, `direct.py`, `gemini.py`, `ollama.py`, `openai.py`, `vllm.py`, `passthrough.py`, `noop.py`, `router.py`) to accept `caller` — simplest: add `caller: str | None = None` to every override, ignore the value (the wrapper logs it, not the concrete provider).

- [ ] **Step 13.3: `ObservedLLMProvider` wrapper**

```python
# src/spec2sphere/llm/observed.py
"""Wraps any LLMProvider and logs every call into dsp_ai.generations.

Applied in create_llm_provider() so every Spec2Sphere caller benefits
without code changes.
"""
from __future__ import annotations
import hashlib, json, time, uuid, logging
from typing import Any, Optional
import asyncpg
from spec2sphere.config import settings
from .base import LLMProvider, DEFAULT_TIER

logger = logging.getLogger(__name__)

# tier → quality_level mapping (for dsp_ai.generations.quality_level)
_TIER_TO_Q = {"small": "Q1", "medium": "Q2", "large": "Q3", "reasoning": "Q5"}


class ObservedLLMProvider(LLMProvider):
    def __init__(self, inner: LLMProvider):
        self._inner = inner
        self._model_hint = getattr(inner, "model", None) or inner.__class__.__name__

    async def generate(self, prompt, system="", *, tier=DEFAULT_TIER, data_in_context=False, caller=None) -> Optional[str]:
        t0 = time.time()
        try:
            result = await self._inner.generate(
                prompt, system, tier=tier, data_in_context=data_in_context, caller=caller,
            )
        except Exception:
            await self._log(prompt, tier, caller, t0, error="exception")
            raise
        await self._log(prompt, tier, caller, t0, output=result)
        return result

    async def generate_json(self, prompt, schema, system="", *, tier=DEFAULT_TIER, data_in_context=False, caller=None) -> Optional[dict]:
        t0 = time.time()
        try:
            result = await self._inner.generate_json(
                prompt, schema, system, tier=tier, data_in_context=data_in_context, caller=caller,
            )
        except Exception:
            await self._log(prompt, tier, caller, t0, error="exception")
            raise
        await self._log(prompt, tier, caller, t0, output=result)
        return result

    async def _log(self, prompt: str, tier: str, caller: str | None, t0: float,
                   *, output: Any = None, error: str | None = None) -> None:
        latency_ms = int((time.time() - t0) * 1000)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        try:
            conn = await asyncpg.connect(settings.postgres_dsn)
            try:
                await conn.execute(
                    """
                    INSERT INTO dsp_ai.generations
                        (id, enhancement_id, user_id, context_key, prompt_hash, input_ids,
                         model, quality_level, latency_ms, tokens_in, tokens_out, cost_usd,
                         cached, quality_warnings, error_kind, preview, caller)
                    VALUES ($1::uuid, NULL, NULL, NULL, $2, '[]'::jsonb,
                            $3, $4, $5, NULL, NULL, NULL,
                            FALSE, NULL, $6, FALSE, $7)
                    """,
                    str(uuid.uuid4()), prompt_hash, self._model_hint,
                    _TIER_TO_Q.get(tier, "Q3"), latency_ms, error, caller or "unknown",
                )
            finally:
                await conn.close()
        except Exception:
            logger.exception("observed_llm: failed to log generation (non-fatal)")
```

The wrapper is **best-effort**: logging failures never break the underlying LLM call.

- [ ] **Step 13.4: Factory wraps automatically**

```python
# At the bottom of create_llm_provider() in src/spec2sphere/llm/__init__.py

from .observed import ObservedLLMProvider

def create_llm_provider(cfg: LLMConfig, output_dir: Optional[Path] = None) -> LLMProvider:
    # ... existing branches that build `provider` ...
    return ObservedLLMProvider(provider)
```

- [ ] **Step 13.5: Test the wrapper**

```python
# tests/dsp_ai/test_observed_llm.py
import pytest, asyncpg
from spec2sphere.config import settings
from spec2sphere.llm.observed import ObservedLLMProvider
from spec2sphere.llm.base import LLMProvider


class _FakeProvider(LLMProvider):
    model = "fake-model"
    async def generate(self, prompt, system="", *, tier="large", data_in_context=False, caller=None):
        return "ok"
    async def generate_json(self, prompt, schema, system="", *, tier="large", data_in_context=False, caller=None):
        return {"ok": True}


@pytest.mark.asyncio
async def test_wrapper_records_generate_call(clean_generations):
    wrapped = ObservedLLMProvider(_FakeProvider())
    out = await wrapped.generate("hi", caller="agents.doc_review")
    assert out == "ok"
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT caller, enhancement_id, model FROM dsp_ai.generations "
            "WHERE caller='agents.doc_review' ORDER BY created_at DESC LIMIT 1"
        )
        assert row is not None
        assert row["caller"] == "agents.doc_review"
        assert row["enhancement_id"] is None
        assert row["model"] == "fake-model"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_wrapper_records_generate_json_call(clean_generations):
    wrapped = ObservedLLMProvider(_FakeProvider())
    out = await wrapped.generate_json("hi", {"type":"object"}, caller="migration.classifier")
    assert out == {"ok": True}
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT caller FROM dsp_ai.generations WHERE caller='migration.classifier' ORDER BY created_at DESC LIMIT 1"
        )
        assert row is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_wrapper_does_not_swallow_provider_exceptions():
    class _Broken(LLMProvider):
        async def generate(self, prompt, system="", *, tier="large", data_in_context=False, caller=None):
            raise RuntimeError("boom")
        async def generate_json(self, prompt, schema, system="", *, tier="large", data_in_context=False, caller=None):
            raise RuntimeError("boom")
    wrapped = ObservedLLMProvider(_Broken())
    with pytest.raises(RuntimeError):
        await wrapped.generate("x", caller="test")
```

- [ ] **Step 13.6: Optional — populate caller at call sites**

Not strictly required (wrapper logs `caller="unknown"` if not passed), but one-liners across the high-traffic call sites make the Generation Log vastly more useful:

```python
# examples (apply in a best-effort pass — don't block the session on this)
# agents/doc_review.py
result = await llm.generate(prompt, caller="agents.doc_review")

# agents/doc_qa.py
result = await llm.generate_json(prompt, schema, caller="agents.doc_qa")

# migration/classifier.py
result = await llm.generate_json(prompt, schema, caller="migration.classifier")

# migration/generator.py
result = await llm.generate(prompt, caller="migration.generator")

# core/standards/intake.py
result = await llm.generate_json(prompt, schema, caller="standards.intake")

# core/knowledge/knowledge_service.py
result = await llm.generate_json(prompt, schema, caller="knowledge.service")
```

Grep for `\.generate\(` and `\.generate_json\(` inside `src/spec2sphere/` to find them all — ~15–25 call sites. Add `caller=...` positionally or as kwarg. Zero behavioral risk since `caller` defaults to None.

- [ ] **Step 13.7: Smoke check**

Run any existing agent path (e.g., trigger a doc_review from the pipeline) and verify a row lands in `dsp_ai.generations` with `enhancement_id IS NULL` and the expected `caller`.

- [ ] **Step 13.8: Commit**

```bash
git add migrations/versions/013_dsp_ai_generations_nullable_enh.py src/spec2sphere/llm/observed.py src/spec2sphere/llm/__init__.py src/spec2sphere/llm/base.py src/spec2sphere/llm/*.py src/spec2sphere/agents/ src/spec2sphere/migration/ src/spec2sphere/core/ tests/dsp_ai/test_observed_llm.py
git commit -m "feat(llm): universal observability — every LLM call logs to dsp_ai.generations"
```

---

## Task 14: Integration smoke + ship criteria

**Files:**
- Extend: `tests/dsp_ai/test_smoke.py`

- [ ] **Step 14.1: Session B smoke checks**

```python
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_all_five_kinds_have_at_least_one_published():
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        kinds = await conn.fetch(
            "SELECT DISTINCT kind FROM dsp_ai.enhancements WHERE status='published'",
        )
        present = {r["kind"] for r in kinds}
        assert present >= {"narrative", "ranking", "item_enrich", "action", "briefing"}
    finally:
        await conn.close()

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_widget_manifest_served():
    async with httpx.AsyncClient() as c:
        r = await c.get("http://dsp-ai:8000/widget/manifest.json")
        assert r.status_code == 200
        j = r.json()
        assert j["name"] == "com.spec2sphere.ai-widget"
        assert j["webcomponents"][0]["integrity"].startswith("sha384-")

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_sse_stream_delivers_event_within_2s():
    import asyncio
    async with httpx.AsyncClient(timeout=5) as c:
        async with c.stream("GET", "http://dsp-ai:8000/v1/stream/00000000-0000-0000-0000-000000000000/test") as resp:
            # fire a matching NOTIFY from the test side via a raw psql connection
            import asyncpg
            conn = await asyncpg.connect(settings.postgres_dsn)
            await conn.execute("SELECT pg_notify('briefing_generated', $1)",
                               json.dumps({"enhancement_id":"00000000-0000-0000-0000-000000000000","user_id":"test"}))
            await conn.close()
            async for line in resp.aiter_lines():
                if "briefing_generated" in line:
                    return
```

- [ ] **Step 14.2: Manual demo checklist**

```
□ All 5 seed templates published; each has at least one generation row
□ Widget /widget/manifest.json returns integrity-hashed JSON
□ Widget /widget/main.js loads, <100 KB
□ SAC story: install widget using manifest URL; property-bind enhancementId; render succeeds
□ Click AI button → action result shows in Studio Generation Log within 2s
□ Close + reopen SAC story → widget picks up new batch-generated content on SSE
□ /ai-studio/log shows rows with per-enhancement cost + latency graphs
□ /ai-studio/brain renders network graph; Cypher console answers "MATCH (o:DspObject) RETURN count(o)"
□ MCP studio_tools accessible from Claude Code (via Spec2Sphere MCP server)
□ graph.json reads still work with BRAIN_READ_FROM_BRAIN=false (rollback path safe)
□ /events/browser SSE delivers updates within 1s of state change (no more 5s polling)
□ After triggering any existing agent path (doc_review, classifier, etc.), a new row appears in dsp_ai.generations with caller='agents.X' or similar + enhancement_id=NULL
```

- [ ] **Step 14.3: Commit**

```bash
git add tests/dsp_ai/test_smoke.py
git commit -m "test(dsp-ai): Session B smoke suite + demo checklist"
```

---

## Session B success criteria

1. All 5 enhancement kinds published + producing rows in their respective `dsp_ai.*` tables
2. SAC Custom Widget: manifest + bundle served; installs in Horváth SAC; renders one enhancement; emits telemetry back that lands in `dsp_ai.user_state` + Brain edges
3. Studio: Template library, Generation Log, Brain Explorer all live; Monaco editor works; admin chip links jump from preview to Log drill-down
4. MCP Studio tools callable from Claude Code; `create → preview → publish` round-trip via MCP
5. `graph.json` write-both flag on; read-from-brain flag can be toggled without breaking existing pages (tests prove both paths)
6. Copilot ContentHub queries Brain; existing Copilot questions still answered
7. Browser + agent-terminal polling replaced with SSE; file_drop uses inotify
8. `pytest -m smoke` green against a running compose with all Session B additions
9. Provenance works end-to-end: click admin chip in a widget render → jumps to Generation Log → `/v1/why/{gen}` narrative explains inputs
10. Every existing LLM call across `agents/`, `migration/`, `core/standards/`, `core/knowledge/` logs to `dsp_ai.generations` via the `ObservedLLMProvider` wrapper — Generation Log shows rows with `caller='agents.doc_review'` etc. alongside engine rows

Anything below is Session C territory.
