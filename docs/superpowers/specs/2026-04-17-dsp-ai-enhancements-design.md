# DSP-AI Enhancements — Design Spec

**Status:** Approved 2026-04-17
**Author:** Henning + Claude (brainstorming session)
**Intended target:** Horváth SAC + DSP demo tenants first; Lindt and future customers second

---

## 1. Goal

Add an **"AI enabled"** capability to Spec2Sphere that produces adaptive, self-adjusting content inside a customer's SAP Analytics Cloud (SAC) experience, sourced from their SAP Datasphere (DSP) data, enriched with semantics extracted by Spec2Sphere, and optionally with external info (news, web). The whole system is a **portable, self-contained add-on** — one `docker compose up` at a client site — with zero dependency on the homelab infrastructure except the configurable LLM endpoint.

### What "AI enabled" produces

Five kinds of enhancements:

| Kind | Example |
|---|---|
| `narrative` | 3-bullet summary of what changed since last visit |
| `ranking` | Top-N items ordered by relevance to the current user |
| `item_enrich` | AI-suggested title / description / tags on a DSP object |
| `action` | A button the user clicks → triggers an AI action → updates content |
| `briefing` | Morning Brief composite (narrative + list + callouts) |

Every enhancement is **self-adjusting per user, per time, per delta** — same dashboard entry, different content on every open.

### What this is NOT

- Not an auto-generator of new DSP views or SAC stories
- Not an island service — it augments existing Spec2Sphere capabilities
- Not dependent on homelab infra (Neo4j, NATS, Redis, Scout, etc. — all bundled into the portable compose)

---

## 2. Users

Primary user for v1: **Henning**, using the system as a tight feedback loop while prototyping at the Horváth SAC + DSP demo tenant. Secondary users (Phase 4): SAC viewers at client sites (read-only consumption of the enhancements).

---

## 3. High-level architecture

```
┌────────────────────── Spec2Sphere compose (portable) ──────────────────────┐
│                                                                            │
│  Spec2Sphere web + AI Studio     dsp-ai (FastAPI)                          │
│  postgres  redis                 neo4j (own, scoped)                       │
│  searxng (bundled)               [ollama (optional, --profile offline)]    │
│  chrome + novnc (existing CDP)   celery worker + beat (existing)           │
└────────────────────────────────────────────────────────────────────────────┘
                 │                                       │
                 ▼                                       ▼
         Client's DSP tenant                Client's LLM endpoint
         (Horváth demo, Lindt, …)           ($LLM_ENDPOINT env var)
                 │
                 ▼
         Client's SAC tenant
         (Pattern B: dsp_ai.* tables consumed natively via Analytic Models)
         (Pattern A: one custom widget deployed, configuration-driven)
```

### Two integration patterns, coexisting

- **Pattern B (write-back to DSP).** `dsp-ai` writes structured output (narratives, rankings, deltas) into a dedicated `dsp_ai.*` schema in DSP. SAC consumes it natively via Analytic Models. **Zero SAC customization.**
- **Pattern A (live widget).** One SAC Custom Widget, configuration-driven, calls `dsp-ai`'s live adapter on render. Used for interactive actions (AI buttons, live regeneration), sub-second personalization, and content that must push on new data.

Choose per enhancement. Same engine backs both.

### Portability constraints (non-negotiable)

- Everything in one `docker-compose.yml` with profiles
- Zero hardcoded homelab IPs; all `192.168.x.x` references become env vars
- No dependency on envctl / Ops-Bridge / Bifrost / Integration Oracle / homelab NATS / homelab Neo4j / homelab Redis / homelab Scout
- First-boot wizard — no hand-edited config
- LLM endpoint configurable per-deploy (`$LLM_ENDPOINT`): homelab router, client OpenAI-compatible, or bundled Ollama
- Enhancement library export/import via JSON round-trip
- `pg_dump` + `neo4j-admin dump` + `redis-cli save` = full backup

---

## 4. Corporate Brain

**Store:** Neo4j Community, bundled in compose (`dsp-ai-brain`), 2 GB heap, exposed only on the internal docker network.

### Nodes

| Label | Keys | Notes |
|---|---|---|
| `DspObject` | `id` (space.schema.name), `kind` (Table/View/LocalTable/Pipeline), `customer` | One per DSP artifact |
| `Column` | `id` (object.column), `dtype`, `nullable` | Fan-out from DspObject |
| `Domain` | `name` (Sales, Finance, Logistics, …) | Learned from docu agent |
| `Glossary` | `term`, `definition_source` | Business glossary entries |
| `User` | `email`, `role` | SAC identity |
| `Topic` | `name`, `vector` | Derived from user behavior + content |
| `Event` | `id`, `kind` (data_change / news / schema_change), `ts` | Time-stamped |
| `Enhancement` | `id`, `kind`, `version` | Authoring artifact |
| `Generation` | `id`, `enhancement_id`, `ts`, `provenance` | Every AI output is a node — audit trail |

### Edges

| Edge | From → To | Semantic |
|---|---|---|
| `HAS_COLUMN` | DspObject → Column | structural |
| `DESCRIBES` | Glossary → DspObject/Column | semantic enrichment |
| `DOMAIN_OF` | DspObject → Domain | classification |
| `OPENED` | User → DspObject (timestamped) | behavior |
| `DWELLED_ON` | User → DspObject (duration_s) | behavior |
| `INTERESTED_IN` | User → Topic (weight) | derived preference |
| `CHANGED_AT` | DspObject → Event | data/schema change history |
| `CORRELATED_WITH` | Event → Topic | external info linkage |
| `GENERATED_FROM` | Generation → (anything) | every AI output records its inputs |

### Feeders (three, all inside the portable compose)

1. **Schema/Semantic feeder** — extends the existing docu agent. Writes `DspObject`, `Column`, `Domain`, `Glossary`, `DESCRIBES`, `DOMAIN_OF`. Runs on DSP schema change + daily cron.
2. **DSP data feeder** — scanner hitting DSP direct DB. Produces `Event` nodes for row-count deltas, distribution shifts, null-rate changes. Hourly.
3. **Behavior feeder** — two inputs: (a) the SAC Custom Widget (live pattern) posts `OPENED` / `DWELLED_ON` / `widget.clicked` events, (b) Spec2Sphere Studio logs design-time opens. `INTERESTED_IN` / `Topic` nodes derived nightly by a small LLM pass over recent behavior edges.

**Explainability for free:** every `Generation` node `GENERATED_FROM` its inputs. A 1-hop Cypher returns plain-English provenance.

---

## 5. dsp-ai engine

### The Enhancement (unit of work)

```python
Enhancement {
    id, name, version, status (draft | staging | published),
    kind       : narrative | ranking | item_enrich | action | briefing,
    mode       : batch | live | both,
    bindings   : {
        data     : DSP query — which objects/columns/filters,
        semantic : Cypher — which Brain nodes/edges to pull,
        external : SearXNG query template — optional,
    },
    adaptive_rules : {
        per_user   : filter/weight by user_id + last_visited_at,
        per_time   : morning/afternoon/evening variants,
        per_delta  : only surface objects with CHANGED_AT since last visit,
    },
    prompt_template : Jinja — placeholders for all gathered context,
    output_schema   : JSON schema (structured output) — guides LLM,
    render_hint     : narrative_text | ranked_list | callout | button | chart | brief,
    schedule        : cron (batch only),
    ttl_seconds     : cache window (live only),
}
```

### Seven-stage engine (shared by both adapters)

```
┌────────────────────────────────────────────────────────────────────┐
│  1. ResolveEnhancement   — load config from Postgres               │
│  2. GatherContext  (asyncio.gather in parallel)                    │
│      ├─ DspFetcher      — direct DB query per data_binding         │
│      ├─ BrainFetcher    — Cypher per semantic_binding              │
│      ├─ ExternalFetcher — SearXNG per external_binding (optional)  │
│      └─ UserStateFetcher — dsp_ai.user_state                       │
│  3. ApplyAdaptiveRules   — pure Python: filter / weight / re-rank  │
│  4. ComposePrompt        — Jinja render                            │
│  5. RunLLM               — via quality_router → $LLM_ENDPOINT      │
│  6. ShapeOutput          — normalize + attach provenance           │
│  7. Dispatch                                                       │
│      ├─ batch mode  → INSERT dsp_ai.* + NOTIFY briefing_generated  │
│      └─ live  mode  → return JSON to caller                        │
└────────────────────────────────────────────────────────────────────┘
```

Every stage is async + instrumented + cached-where-idempotent + graceful-degradation.

### Adapters

**Batch adapter** — Triggered by Celery Beat (scheduled) or Postgres `LISTEN` (`dsp_changed`, `brain_updated`, `enhancement_published`). For each enhancement × active_user × context, runs the engine, UPSERTs into `dsp_ai.*`, emits `NOTIFY briefing_generated`.

**Live adapter** — FastAPI service exposing:

- `POST /v1/enhance/{enhancement_id}` — body `{user, context_hints, filter_overrides}`. Checks Redis cache; hits return <50ms; misses run engine in-band up to 10s; >2s returns 202 + SSE follow.
- `POST /v1/actions/{action_id}/run` — synchronous click-to-run actions.
- `POST /v1/why/{generation_id}` — returns plain-English provenance from the ledger + Brain 1-hop.
- `GET /v1/stream/{enhancement_id}/{user_id}` — SSE channel, fires on `NOTIFY briefing_generated` for this key.
- `POST /v1/telemetry` — widget posts `widget.rendered / dwelled / clicked / declined` events → behavior feeder.

### LLM routing

- dsp-ai → Spec2Sphere's existing `llm/quality_router.py`
- quality_router picks Q1–Q5 level + concrete model + privacy flag
- Calls go to `$LLM_ENDPOINT` (env-configurable)
- Privacy-sensitive enhancements pin to local models via `data_in_context=true`

### Caching + invalidation

Redis holds:
- Enhancement output cache (TTL from config; invalidated on `enhancement_published` or selective `dsp_changed`)
- Brain query cache (60s TTL)
- User state snapshot (5min TTL; invalidated on `user_state_changed`)

### Failure modes

| Fetcher fails | Engine behavior |
|---|---|
| DSP unreachable | Serve cached result + `data_stale=true`. Widget shows amber badge. |
| Neo4j down | Proceed without semantic/behavior context. `quality_warnings: ["semantic_context_missing"]`. |
| SearXNG timeout | Skip external enrichment (don't block on it). Warning logged. |
| LLM timeout/error | Fall back to previous generation with `stale=true`. If none, return graceful empty shape with `error_kind`. |
| Postgres NOTIFY publish fails | Log + retry once. Best-effort — events are cache-invalidations, not source of truth. |

**Invariant:** no single dependency can 500 the engine. Outputs always include `quality_warnings[]`.

---

## 6. DSP write-back schema (`dsp_ai.*`)

Own schema in DSP. Service-principal isolated (only `dsp-ai` has write permission).

```sql
-- Narrative content (narrative, callout, brief render_hints)
CREATE TABLE dsp_ai.briefings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enhancement_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    context_key TEXT NOT NULL,          -- e.g., "morning" | "region=FR"
    generated_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    narrative_text TEXT NOT NULL,
    key_points JSONB,
    suggested_actions JSONB,
    render_hint TEXT NOT NULL,
    generation_id UUID NOT NULL,        -- FK to generations
    UNIQUE (enhancement_id, user_id, context_key)
);

-- Ranked lists (ranking render_hint)
CREATE TABLE dsp_ai.rankings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enhancement_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    context_key TEXT NOT NULL,
    item_id TEXT NOT NULL,
    rank INT NOT NULL,
    score FLOAT NOT NULL,
    reason TEXT,
    generated_at TIMESTAMPTZ NOT NULL,
    generation_id UUID NOT NULL
);

-- Per-DSP-object AI enrichments
CREATE TABLE dsp_ai.item_enhancements (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    user_id TEXT,                       -- NULL = global
    title_suggested TEXT,
    description_suggested TEXT,
    tags JSONB,
    kpi_suggestions JSONB,
    generated_at TIMESTAMPTZ NOT NULL,
    enhancement_id UUID NOT NULL,
    generation_id UUID NOT NULL,
    PRIMARY KEY (object_type, object_id, user_id)
);

-- Per-user ambient state
CREATE TABLE dsp_ai.user_state (
    user_id TEXT PRIMARY KEY,
    last_visited_at TIMESTAMPTZ,
    last_briefed_at TIMESTAMPTZ,
    topics_of_interest JSONB,
    preferences JSONB,
    updated_at TIMESTAMPTZ NOT NULL
);

-- Audit / provenance ledger (the metrics store)
CREATE TABLE dsp_ai.generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enhancement_id UUID NOT NULL,
    user_id TEXT,
    context_key TEXT,
    prompt_hash TEXT NOT NULL,
    input_ids JSONB NOT NULL,           -- Brain node IDs, DSP object IDs
    model TEXT NOT NULL,
    quality_level TEXT NOT NULL,        -- Q1..Q5
    latency_ms INT NOT NULL,
    tokens_in INT, tokens_out INT,
    cost_usd NUMERIC(10,6),
    cached BOOLEAN NOT NULL DEFAULT FALSE,
    quality_warnings JSONB,
    error_kind TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_generations_enhancement_time ON dsp_ai.generations (enhancement_id, created_at DESC);
CREATE INDEX idx_generations_user_time ON dsp_ai.generations (user_id, created_at DESC);

-- Enhancement definitions (authoring)
CREATE TABLE dsp_ai.enhancements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',    -- draft | staging | published | archived
    config JSONB NOT NULL,                   -- full Enhancement config
    author TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, version)
);

-- Author audit log
CREATE TABLE dsp_ai.studio_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action TEXT NOT NULL,               -- create | edit | publish | rollback
    enhancement_id UUID,
    author TEXT NOT NULL,
    before JSONB, after JSONB,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Every AI output row FK's to `generations`. That's the "Why this?" substrate.

---

## 7. AI Studio (Spec2Sphere design-time UI)

New top-level nav entry **"AI Studio"** in Spec2Sphere web, peer to Landscape / Tech Spec / Pipeline / Copilot / Settings.

Four sub-pages:

- **Enhancements** — list/filter/create, version history
- **Editor** — split-pane (declarative config | live preview) — preview uses the live adapter internally
- **Generation Log** — queryable `dsp_ai.generations` ledger with drill-down to full provenance
- **Brain Explorer** — visual Neo4j navigator (extends existing `vis-network.js`), Cypher console, "seed from landscape" button

### Editor split-pane

Left: declarative config (name / kind / mode / bindings / adaptive rules / prompt template [Monaco/Jinja] / output schema / render hint / schedule / TTL).

Right: live preview — "Preview as: [user]" + "At time: [time]" + gathered context (expandable) + composed prompt + LLM response + rendered output + cost + latency + provenance breakdown. Session preview budget (20 previews default) prevents runaway token burn; context cached between tweaks within a session.

**"Henning mode" toggle** — on: shows prompt/model/tokens/cost; off: clean consultant UI (just the output + publish button).

### Publish workflow

```
draft ─────► staging ─────► published
   ▲            │               │
   │            │               ▼
   └──── rollback ◄──── new edits auto-fork to new draft
```

Drafts mutable; published immutable; new edits auto-fork to new draft. Staging = preview-only widget URL for pre-publish sanity check. On publish: `NOTIFY enhancement_published` → cache invalidation + batch backfill enqueue.

### MCP exposure (unprompted win)

Extend Spec2Sphere's Copilot MCP server with Studio tools:

```
studio.list_enhancements        studio.get_enhancement(id)
studio.create_enhancement       studio.update_enhancement(id, patch)
studio.preview(id, context)     studio.publish(id)
studio.rollback(id, version)    studio.query_brain(cypher)
studio.generation_log(filter)
```

Claude Code + web UI share state via Postgres. Iterate via chat or form — same result.

### Import/export

Every enhancement = one JSON doc. "Export" (single or library), "Import" (paste or upload), rebind data sources to target tenant. Library travels with Henning to any client site.

### RBAC

Two roles for MVP: `author` (full edit) and `viewer` (read + regenerate, no publish). `STUDIO_AUTHOR_EMAILS` env var whitelist.

### Safety rails

| Rail | Behavior |
|---|---|
| Session preview budget | Default 20/session, configurable |
| Destructive publish check | Warns if breaking schema change affects active live-adapter clients |
| Cost guard | Per-enhancement monthly cap; auto-pause on overrun; alert |
| RBAC | Author vs viewer enforced in UI + API |

---

## 8. SAC Custom Widget (Pattern A)

**One widget, zero logic.** Configuration-driven. Thin renderer delegating every decision to `dsp-ai`.

### Manifest

```json
{
    "name": "com.spec2sphere.ai-widget",
    "version": "1.x.x",
    "webcomponents": [{
        "kind": "main",
        "tag": "spec2sphere-ai-widget",
        "url": "https://<host>/widget/main.js",
        "integrity": "sha384-...",
        "ignoreIntegrity": false
    }],
    "properties": {
        "enhancementId":  {"type": "string"},
        "contextHints":   {"type": "string"},
        "fallbackUser":   {"type": "string"},
        "apiBase":        {"type": "string"},
        "authMode":       {"type": "string", "enum": ["bearer", "oauth"]}
    },
    "methods": {
        "refresh": {},
        "setUser": {"parameters": [{"name": "userId", "type": "string"}]}
    },
    "events": { "onGenerated": {}, "onError": {}, "onInteraction": {} }
}
```

esbuild → <50 KB bundle. Integrity baked at build time.

### Render modes (driven by `render_hint`)

| `render_hint` | Widget renders |
|---|---|
| `narrative_text` | Markdown block respecting SAC theme |
| `ranked_list` | Top-N items with rank + score + reason |
| `callout` | Colored card (info/warn/critical) + headline + body |
| `button` | AI action button → `/v1/actions/{id}/run` |
| `brief` | Multi-section composite |
| `chart` | Minimal chart for `{series, values}` shape |

Single Shadow DOM root isolates styles.

### Lifecycle

```
Mount → resolve properties + SAC context (user_id, story_id, filters)
  → authenticate (bearer | OAuth)
  → POST /v1/enhance/{id}
  → render by render_hint, emit onGenerated
  → open EventSource /v1/stream/{id}/{user}
  → POST /v1/telemetry {widget.rendered}
Interact → POST /v1/actions/{id}/run → emit onInteraction
SSE event → re-fetch → soft swap re-render
Unmount → close EventSource, POST telemetry {dwelled}
```

### Degraded rendering

| Response flag | Visual |
|---|---|
| `quality_warnings: [...]` | Subtle `i` icon with tooltip — content still renders |
| `data_stale: true` | Amber "last refreshed Xh ago" badge |
| `stale: true` | Soft dim + "Refreshing…" subtitle |
| `error_kind: *` (no prior) | Empty-state illustration + "Content temporarily unavailable" |
| `dsp-ai unreachable` | Cached last-known render + offline badge |

Widget NEVER shows SAC a 500.

### "Admin chip" (author role only)

Absolute-positioned chip: `live | enh=<name> v<n> | gen=<short> | ms=<latency> | cache=<hit|miss>`. Click → jumps to Studio Generation Log filtered by `generation_id`. Viewers never see it.

### Behavior feedback loop

Widget posts `widget.rendered / dwelled / clicked / declined` to `/v1/telemetry`. Land in `dsp_ai.user_state` + Brain `OPENED` / `DWELLED_ON` / `INTERESTED_IN` edges. Next generation's `ApplyAdaptiveRules` uses it — the system gets better as it's used.

---

## 9. Data flows (canonical sequences)

### Authoring

```
Henning → Studio → dsp-ai (preview=true) → engine 1-7 → rendered preview
                                                       → stored in generations (preview flag)
Henning → Studio → publish → UPDATE enhancements SET status='published'
                          → pg_notify('enhancement_published', {id})
                          → dsp-ai evicts cache keys
                          → Celery enqueues batch backfill for active users
```

### Batch generation

```
Celery Beat (06:00) → worker → dsp-ai batch adapter
  → SELECT enhancements WHERE status='published' AND mode IN (batch, both)
  → for enh × active_users × contexts:
      if fresh → skip
      else run engine 1-7
        → UPSERT dsp_ai.briefings / rankings / item_enhancements
        → INSERT dsp_ai.generations
        → pg_notify('briefing_generated', {key})
  → SAC stories reading dsp_ai.* via Analytic Model pick up new rows on next refresh
  → Pattern-A widgets subscribed to the (enh, user) SSE channel re-fetch and re-render
```

### Live render

```
SAC story load → widget instantiates
  → resolve SAC context (user_id, story_id, filters)
  → POST /v1/enhance/{id}
      cache hit → <50ms response
      cache miss → engine 1-7 → cache → response
      slow (>2s) → 202 + SSE follow
  → render by render_hint
  → open EventSource /v1/stream/{id}/{user}
  → POST /v1/telemetry {widget.rendered}
user interacts → POST /v1/actions/{id}/run → render ack
async later → SSE briefing_generated → re-fetch → soft re-render
unmount → close EventSource, post telemetry {dwelled}
```

---

## 10. First-run experience (bootstrap wizard)

**Goal:** `docker compose up` → first successful preview in <15 min (clean tenant), <5 min (with template).

Extends existing `setup_wizard.py`. Six steps:

1. **LLM endpoint** — picker (homelab / client OpenAI-compatible / bundled Ollama), test button
2. **DSP tenant** — reuse existing scanner config, "Scan now" seeds Brain
3. **External info** — SearXNG toggle (default ON); airgap = OFF
4. **Enhancement library** — pick templates (Morning Brief / Narrative Overlay / Anomaly Explainer / Column Title Gen / KPI Suggester), fork as drafts
5. **SAC integration** — copy widget manifest URL, download `dsp_ai.*` Analytic Model SQL, validate CORS
6. **Publish** — tick enhancements to publish → NOTIFY fires → batch backfills

### Deployment profiles

| Profile | What's different |
|---|---|
| `default` (dev) | LLM → homelab router; SearXNG on; real DSP |
| `--profile offline` | Adds `ollama` with pre-pulled model, LLM_ENDPOINT auto → ollama; SearXNG optional |
| `--profile demo` | Seeds demo tenant + sample enhancements; read-only consultant mode |
| `--profile production` | Stricter CORS, enforced RBAC, cost guardrails, OTel exporter |

### `.env.example` surface

```
RUN_MODE=dev                                # dev | demo | production
LLM_ENDPOINT=http://llm-router:8070/v1      # override per deploy
LLM_API_KEY=                                # optional
DSP_CONNECTION_STRING=                      # direct DB
SAC_TENANT_URL=                             # drives CORS allow-origin
NEO4J_PASSWORD=                             # auto-generated if empty
POSTGRES_PASSWORD=                          # existing Spec2Sphere var
REDIS_URL=redis://redis:6379/0
SEARXNG_ENABLED=true
STUDIO_AUTHOR_EMAILS=h.schuettken@gmail.com
WIDGET_ALLOWED_ORIGINS=https://<sac-host>
BRAIN_FEEDER_CRON=0 */4 * * *
BATCH_CRON=0 6 * * 1-5                      # Morning Brief weekdays 06:00
```

---

## 11. Consolidation (broader cleanup unlocked by the new infra)

Since we're adding Neo4j + Postgres use + Redis use, fold in existing pain:

| Today | Post-MVP |
|---|---|
| `output/graph.json` per customer + file-lock hack | Neo4j with `customer` property. Queryable, transactional, incremental. |
| `scanner/chain_builder.py` walking JSON in memory | 3–4 Cypher queries |
| `output/objects/*.md` | Keep files (consultant-facing) + mirror structured fields into Postgres for search/filter |
| Copilot `ContentHub` filesystem walker | Collapse into Corporate Brain. One graph, two consumers. |
| `file_drop_tasks.poll_drop_directory` (5-min poll) | `inotify` → `NOTIFY file_dropped` → Celery fires instantly |
| Frontend `setInterval` polling (browser_viewer, agent_terminal) | SSE endpoints backed by `LISTEN/NOTIFY` |
| Implicit scan coordination | Explicit NOTIFY channels: `scan_completed`, `brain_updated`, `enhancement_published`, `briefing_generated`, `dsp_changed`, `user_state_changed` |
| `standards/*.yaml` | Stay as files; loaded into Postgres on boot for runtime lookup |
| `config.yaml`, secrets | Stay as files |

Celery + its Redis broker stay — job orchestration is the right tool. LISTEN/NOTIFY is for *events*, not jobs.

---

## 12. Observability

- `dsp_ai.generations` IS the metrics store. No InfluxDB dependency.
- Structured logs via existing `telemetry.py`. `correlation_id = generation_id`.
- OpenTelemetry exporter (optional) — noop unless `OTEL_EXPORTER_OTLP_ENDPOINT` set. Portable.
- Health: `/healthz` (liveness), `/readyz` (sweeps all fetchers; degrades gracefully), `/metrics` (Prometheus format, optional)
- In-app dashboards = Studio Generation Log (cost / latency / cache-hit / quality-warnings / error-rate).

---

## 13. Testing strategy

| Layer | Stack | Scope |
|---|---|---|
| Unit | pytest / Vitest | engine stages, rule evaluators, prompt rendering, output shapers, widget render modes (Shadow DOM snapshots), Studio state reducers |
| Integration | pytest vs real compose (LLM mocked) | engine end-to-end, batch adapter writes + NOTIFY, live adapter cache, LISTEN/NOTIFY round-trip, bootstrap wizard |
| Contract | shared JSON Schema fixtures | widget ↔ dsp-ai. Same fixtures power Python + TS tests. |
| E2E | Playwright | against Studio preview (Phase 1); against SAC tenant (Phase 2) |
| Smoke | pytest marker `smoke` | bootstrap wizard → preview → NOTIFY → DSP row visible |
| Prompt regression | golden files | prompt drift fails build |
| Output regression | replay generations | quality drift detectable |
| Load | `hey` / `locust` | P50 <500ms cached, P99 <10s cold, >80% cache hit |

---

## 14. Rollout (3 compressed dev sessions)

### Session A — Foundation + Vertical Slice (Phase 0 + Phase 1)

Ships: ONE enhancement producing a narrative natively in a Horváth SAC story via Pattern B. Studio create/preview/publish loop works. Bootstrap wizard brings fresh compose to first preview.

File: `docs/superpowers/plans/2026-04-17-dspai-session-a-foundation-vertical-slice.md`

### Session B — Breadth + Widget + Consolidation (Phase 2)

Ships: all 5 enhancement kinds, Pattern A widget deployed, SSE, behavior feeder, Studio template library + Generation Log + Brain Explorer, `graph.json` cutover to Neo4j, Copilot ContentHub merged, MCP Studio tools exposed.

File: `docs/superpowers/plans/2026-04-17-dspai-session-b-breadth-widget-consolidation.md`

### Session C — Portability + Second-Customer Ready (Phase 3 + Phase 4)

Ships: `--profile offline` with Ollama, library import/export, publish diff preview, cost guardrails, "Why this?" UX, polling cleanups (browser_viewer, agent_terminal, file_drop → inotify), multi-tenant isolation, RBAC hardening, docs, demo scripts.

File: `docs/superpowers/plans/2026-04-17-dspai-session-c-portability-second-customer.md`

---

## 15. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SAC Custom Widget SDK friction | Medium | Blocks Pattern A | Early spike in Session B; Pattern B covers 70% without widget; Studio preview is fallback |
| Batch LLM cost blow-up | Medium | Financial | Per-enhancement monthly cap; auto-pause; cost dashboard; start with 1 enh × 1 user |
| Prompt drift | **High** | Subtle | Golden-file regression; replay tests; alerts on output divergence |
| PII → external LLM | Medium | Compliance | `data_in_context` flag pins local; prompt template lint; publish-time warning |
| DSP schema changes break enhancements | Medium | Operational | Schema-change events → stale-binding badge in Studio |
| Neo4j ops burden | Low | Ops cost | Community edition, small heap, `neo4j-admin dump` backup |
| `graph.json` cutover regressions | Medium | Existing features break | Write-both mode 2 weeks; feature flag; comprehensive integration tests |
| SearXNG upstream rate-limits | Low | External info quality | 4h cache; graceful skip on fail; 1-line swap to Tavily |

---

## 16. Phase 2+ roadmap (explicitly deferred from MVP)

| Idea | Trigger to revisit |
|---|---|
| N8N bidirectional governance | When non-technical ops want visual scheduling |
| Python-Dash sketch surface | When demand for non-SAC dashboards appears |
| SAC Story auto-generation (inverted flow) | When Pattern A + B are proven and manual SAC design becomes the bottleneck |
| Thumbs-up/down feedback → fine-tuning | When Generation Log has ~1000+ entries |
| Multi-tenant SaaS | When >3 customers and per-instance ops is painful |
| Agentic enhancement chaining | When single enhancements stop being expressive enough |
| pgvector semantic search in Brain | When glossary >500 terms |
| "Active monitoring" — unprompted insights | After Phase 3, once users trust scheduled outputs |
| Chat-based enhancement creator | When library has enough patterns |

---

## 17. MVP ship criteria

1. Morning Brief renders natively in a Horváth SAC story from `dsp_ai.briefings` (Pattern B) — provenance clickable from Studio
2. One live widget enhancement (Narrative Overlay or action button) works in Studio preview; widget deployed to Horváth SAC if access confirmed, otherwise preview-only
3. Studio: create → preview → publish → see result in SAC, end-to-end, one real enhancement
4. Bootstrap wizard brings a fresh compose to first preview in <15 min on a new machine
5. Five template enhancements authored, published, and producing output
6. Cost and latency targets met on Phase 1 traffic levels
7. Portability test: `pg_dump` + `neo4j dump` + library JSON export from homelab → restore on fresh compose → same outputs reproduced

---

## Appendix A — File map (new or modified, indicative)

### New packages

```
src/spec2sphere/dsp_ai/                 # the engine + adapters
    __init__.py
    config.py                           # Enhancement config model (Pydantic)
    engine.py                           # 7-stage orchestrator
    stages/
        resolve.py
        gather.py                       # DspFetcher, BrainFetcher, ExternalFetcher, UserStateFetcher
        adaptive_rules.py
        compose_prompt.py
        run_llm.py
        shape_output.py
        dispatch.py
    adapters/
        batch.py                        # Celery task + NOTIFY handlers
        live.py                         # FastAPI router (/v1/enhance, /v1/actions, /v1/stream, /v1/why, /v1/telemetry)
    brain/
        client.py                       # Neo4j driver wrapper
        schema.py                       # Cypher for node/edge bootstrapping
        feeders/
            schema_semantic.py
            dsp_data.py
            behavior.py
    events.py                           # Postgres LISTEN/NOTIFY helpers (shared by Spec2Sphere too)
    cache.py                            # Redis cache wrapper

src/spec2sphere/web/ai_studio/          # Studio UI routes + templates
    routes.py
    templates/partials/
        ai_studio.html                  # list + nav
        ai_studio_editor.html           # split-pane editor
        ai_studio_generations.html      # generation log
        ai_studio_brain.html            # brain explorer

src/spec2sphere/widget/                 # SAC Custom Widget source
    package.json
    tsconfig.json
    src/
        main.ts                         # web component entry
        renderers/
            narrative.ts
            ranked_list.ts
            callout.ts
            button.ts
            brief.ts
            chart.ts
        api.ts                          # dsp-ai client
        telemetry.ts
        sac_context.ts
    manifest.template.json
    esbuild.config.mjs
```

### Modified files

```
docker-compose.yml                      # add neo4j, searxng, dsp-ai, [ollama profile]
docker-compose.offline.yml              # overlay: ollama + env overrides
.env.example                            # new env vars
migrations/versions/010_dsp_ai_core.py  # dsp_ai.* tables (continues after existing 009)
migrations/versions/011_dsp_ai_widget.py
src/spec2sphere/app.py                  # mount dsp-ai live router, MCP Studio tools
src/spec2sphere/modules.py              # register ai_studio module
src/spec2sphere/tasks/celery_app.py     # add ai-batch queue
src/spec2sphere/tasks/schedules.py      # Beat: BATCH_CRON, BRAIN_FEEDER_CRON
src/spec2sphere/web/setup_wizard.py     # extend with AI Studio bootstrap steps
src/spec2sphere/web/templates/base.html # add "AI Studio" nav entry
src/spec2sphere/copilot/mcp_server.py   # add studio.* tools
src/spec2sphere/llm/quality_router.py   # expose programmatic API for dsp-ai
src/spec2sphere/scanner/output.py       # write-both to Neo4j during graph.json cutover
src/spec2sphere/copilot/content_hub.py  # read from Brain instead of filesystem (Session B)
```

---

## Appendix B — Glossary

- **Enhancement** — a declarative AI-action config authored in Studio
- **Corporate Brain** — Neo4j graph holding semantic, behavioral, change, and provenance edges
- **Pattern A** — SAC Custom Widget calls dsp-ai at render time (live)
- **Pattern B** — dsp-ai writes to `dsp_ai.*` schema; SAC consumes natively (batch)
- **Generation** — one LLM call + its provenance row in `dsp_ai.generations`
- **Quality warning** — non-fatal degradation flag on an engine output (e.g., `semantic_context_missing`)
- **Active user** — user with any widget/Studio activity in the last 14 days
- **Context key** — deterministic partition key for cached/batch outputs (e.g., `"morning"`, `"region=FR"`)
