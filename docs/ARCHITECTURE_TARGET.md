# SAP Doc Agent — Target Architecture

Status: proposal, 2026-04-14. Goal: make the tool deliverable to Horvath (or any
client) without dragging Henning's homelab along with it.

## Motivation

Current deployment works but is tangled with personal infra:

- LLM calls hard-routed through homelab LLM Router (`192.168.0.50:8070`)
- Secrets pulled from `envctl` at deploy time
- Docker image builds by cloning from Gitea at `192.168.0.64:3000`
- DNS via Pi-hole, ingress via Traefik + Cloudflare tunnel on a homelab LXC
- BookStack instance on `docker2:8253`
- Web UI, API, and scanner all co-located in one container — scanner jobs
  block the web process, Chrome/CDP eats RAM next to the UI

None of this is portable. A client install currently means "rebuild Henning's
homelab."

## Target shape

Three services, one database, one queue. Everything configured by plain env
vars. No hard dependency on any homelab component.

```
                    ┌───────────────────────┐
  browser ────────► │  web (FastAPI + UI)   │  :8080
                    │  Jinja + HTMX, auth,  │
                    │  REST API, enqueues   │
                    │  jobs                 │
                    └──────┬────────────┬───┘
                           │            │
                           ▼            ▼
                  ┌────────────┐   ┌─────────┐
                  │ Postgres   │   │ Redis   │
                  │ (state,    │   │ (queue, │
                  │  scans,    │   │  cache) │
                  │  audits)   │   └────┬────┘
                  └─────┬──────┘        │
                        │               │
                        │        ┌──────┴────────────────┐
                        │        │                       │
                        ▼        ▼                       ▼
                  ┌──────────────────┐         ┌──────────────────┐
                  │ worker           │         │ scheduler        │
                  │ (scanners,       │         │ (cron: periodic  │
                  │  agents, LLM,    │         │  scans, QA runs) │
                  │  Chrome/CDP)     │         └──────────────────┘
                  └──────────────────┘
```

### Service responsibilities

**web**
- FastAPI + Jinja + HTMX (unchanged)
- Auth, session cookies, all 9 UI pages
- REST API for dashboard/objects/quality/etc.
- Enqueues long-running work to Redis, never runs it in-process
- Stateless — horizontally scalable, though 1 replica is fine

**worker**
- Pulls jobs off Redis queue (**Celery** — priorities, rate limiting,
  retries, Flower dashboard; see Enterprise readiness below)
- Separate worker pools per queue (`scan`, `llm`, `chrome`) with
  independent concurrency caps
- Runs all scanners (ABAP, DSP REST, CDP deep scan), all agents (Doc Review,
  PDF Ingestor, QA, BRS Traceability, Report Generator), all LLM calls
- Chrome/Playwright runs in its own worker pool — isolates heavy RAM + crash
  surface from both the web process and lighter jobs
- Stateless, horizontally scalable

**scheduler**
- **Celery Beat** in its own container
- Enqueues cron jobs (nightly QA, weekly report, periodic re-scan)
- Independent lifecycle from workers — stop/restart/upgrade without
  touching the job processors

### Shared state

- **Postgres** — single DB, already the source of truth for scanned objects,
  audit results, quality scores, users. Runs as a container in the compose,
  or points at client's existing PG.
- **Redis** — queue + short-lived cache (object metadata, LLM response cache).
  Small footprint.

## Portability changes

| Current | Target |
|---|---|
| LLM Router `:8070` hardcoded | `LLM_PROVIDER=openai\|azure\|anthropic\|router` with provider-specific env vars. Router becomes one of several backends. |
| envctl injection at deploy | Plain `.env` file + env vars; optional Vault/1Password/AWS-SM adapters later |
| Dockerfile clones from Gitea | `COPY . /app` from build context; publish image to a registry (GHCR or client's) |
| BookStack URL hardcoded | Already pluggable — keep adapter pattern, document Outline + Confluence paths |
| Pi-hole + Traefik + Cloudflare tunnel | Ship a `docker-compose.yml` that exposes `:8080`; client puts their own reverse proxy in front |
| Single container does everything | Split per above; one image, three entrypoints (`web`, `worker`, `scheduler`) |

Single image with entrypoints is simpler than three images — same code, same
deps, different `CMD`.

## Config surface (what a client sets)

```
# Database
DATABASE_URL=postgresql+psycopg://user:pw@host:5432/sapdoc

# Queue + cache
REDIS_URL=redis://redis:6379/0

# LLM — pick one
LLM_PROVIDER=azure           # azure | openai | anthropic | vllm | ollama | router
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=...
# …or for on-prem:
# LLM_PROVIDER=vllm
# VLLM_BASE_URL=http://vllm.internal:8000/v1
# VLLM_MODEL=Qwen2.5-Coder-32B-Instruct

# Doc backend — pick one
DOC_BACKEND=bookstack        # or outline, confluence
BOOKSTACK_URL=...
BOOKSTACK_TOKEN=...

# SAP
DSP_CLIENT_ID=...
DSP_CLIENT_SECRET=...
DSP_TOKEN_URL=...

# Web
UI_PASSWORD_HASH=...         # bcrypt
SECRET_KEY=...
```

No reference to 192.168.x, no homelab URLs, no envctl.

## Migration path

Non-breaking, incremental. Each step ships independently.

1. **Introduce LLM provider abstraction** — wrap current router call in a
   provider interface; add OpenAI + Azure adapters; keep router as default.
2. **Introduce job queue** — add Redis + RQ; move scanner entrypoints behind
   `enqueue_scan()`; web process no longer blocks on scans.
3. **Split worker container** — same image, `CMD ["rq", "worker"]`; web
   container drops scanner deps from runtime path.
4. **Remove Gitea-clone-at-build** — switch Dockerfile to `COPY . /app`;
   publish image; restart stops re-cloning.
5. **Replace envctl with env vars** — read from environment directly; keep
   envctl as an optional loader for the homelab deploy, not a requirement.
6. **Document client install** — single `docker-compose.yml` + `.env.example`
   + README section; verify on a clean VM.

Steps 1–3 give us the container split and unblock production use on the
homelab. Steps 4–6 make it a shippable artifact.

## Standards & knowledge storage model

Two categories of reference material, with different lifecycles:

### Horvath standard (our IP, ships with the product)

```
standards/horvath/
  documentation_standard.yaml   ← 7-section doc structure + scoring
  doc_standard.yaml             ← object-level QA rules (naming, fields)
  code_standard.yaml            ← ABAP/SQL coding rules
knowledge/shared/
  best_practices.md             ← 4-layer architecture, persistence, naming
  dsp_quirks.md, hana_sql.md    ← platform knowledge
```

- Lives in git, baked into the Docker image, read-only at runtime
- Versioned with releases — when we improve the standard, every customer
  gets it on next upgrade
- The Doc Review Agent **always** evaluates against this

### Customer material (uploaded at runtime via UI)

Two types, both managed through the web UI dashboard:

**Customer documentation guidelines** — the client's own standards PDF/Word
doc that they want their SAP documentation to also comply with.

**Customer tenant knowledge** — accumulated context about the client's
specific BW/DSP landscape: naming quirks, org structure, space layout,
known exceptions.

#### Storage

```
┌─────────────────────────────────────────────────────────┐
│ Postgres                                                │
│                                                         │
│ customer_standards                                      │
│   id, name, filename, content_type, uploaded_at,        │
│   status (processing|ready|error),                      │
│   parsed_rules JSONB,        ← LLM-extracted rules     │
│   raw_text TEXT               ← extracted full text     │
│                                                         │
│ customer_standard_files                                 │
│   id, standard_id FK, file_data BYTEA,                  │
│   filename, content_type, size_bytes                    │
│                                                         │
│ tenant_knowledge                                        │
│   id, category, key, value JSONB,                       │
│   source (scan|upload|manual), updated_at               │
│   ← naming overrides, space mappings, known exceptions  │
└─────────────────────────────────────────────────────────┘
```

Original files stored in Postgres (BYTEA) for simplicity — no external
object store needed for v1. A large client with hundreds of PDFs can
graduate to S3/MinIO later by swapping the file storage adapter.

#### Upload flow (UI)

Dashboard gets a new **"Standards & Knowledge"** section with two cards:

**Customer Standards card:**
1. Drag-and-drop or file picker (PDF, Word, YAML, Markdown)
2. Upload hits `POST /api/standards/upload` → stores file, sets
   status=`processing`
3. Celery worker picks up the job:
   - PDF/Word → text extraction (pdfplumber / python-docx)
   - LLM pass → extracts structured rules (section requirements, naming
     conventions, field expectations) into `parsed_rules` JSONB
   - Sets status=`ready`
4. UI shows parsed rules for review — user can edit/approve/reject
   individual rules before they become active
5. Active rules feed into the Doc Review Agent as a second evaluation pass

**Tenant Knowledge card:**
1. Two input modes:
   - **Upload** — client provides a landscape doc, org chart, or naming
     convention sheet → same extract pipeline
   - **Manual** — key-value editor for quick overrides ("our RAW prefix is
     `SRC_` not `01_`", "ignore space X for QA scoring")
2. Knowledge also accumulates automatically from scans — the scanner
   writes discovered patterns (spaces, prefixes, object counts) into
   `tenant_knowledge` with `source=scan`
3. Manual entries override scan-discovered entries

#### Dual evaluation in Doc Review Agent

```
Score = horvath_score × 0.7 + customer_score × 0.3
```

- Horvath standard always evaluated (baseline quality)
- Customer standard evaluated only if active rules exist
- Weights configurable per install
- Report shows both scores side by side with per-section breakdown
- Items that pass Horvath but fail customer standard flagged as
  "customer compliance gap" (not a quality failure)

#### API endpoints (new)

```
POST   /api/standards/upload          ← multipart file upload
GET    /api/standards                 ← list all uploaded standards
GET    /api/standards/{id}            ← detail + parsed rules
PUT    /api/standards/{id}/rules      ← edit parsed rules
DELETE /api/standards/{id}            ← remove standard
GET    /api/standards/{id}/download   ← original file

GET    /api/knowledge                 ← list tenant knowledge entries
POST   /api/knowledge                 ← manual entry
PUT    /api/knowledge/{id}            ← update entry
DELETE /api/knowledge/{id}            ← remove entry
POST   /api/knowledge/upload          ← upload landscape doc for extraction
```

## What stays the same

- Jinja + HTMX UI — server-rendered is the right call for a tool like this
- Horvath branding, 9 pages, 254 tests
- BookStack/Outline/Confluence adapter pattern
- CLI (`audit`, `platform` modes) — still useful for one-shot runs
- Postgres as source of truth

## Enterprise readiness

Target: a tool that a client's platform team will actually run against their
production BW/Datasphere. Large BW systems hold tens of thousands of objects,
so the architecture has to handle scale, and the security/ops story has to
pass a procurement review.

### Queue — Celery, not RQ

A large BW/DSP install means tens of thousands of objects and long-running
deep scans. We need:

- **Priority lanes** — UI-triggered scan > nightly QA > bulk backfill
- **Per-target rate limiting** — don't hammer the client's DSP / BW
- **Retries with exponential backoff** — SAP systems flake under load
- **Visible dashboard** — Flower (or similar) for ops
- **Beat scheduler** — first-class, with future leader-election if HA

RQ covers none of this cleanly. Celery is the default.

### Scheduler — separate container

Celery Beat runs as its own container. Ops can stop/restart/upgrade the
scheduler independently of workers, and a future HA deployment can add
leader election without re-architecting.

### Registry & supply chain

- Build/publish to **GHCR** (private) as the canonical image.
- At client install: mirror into their registry (Harbor, Azure Container
  Registry, Artifactory — whichever their platform team runs).
- CI must produce: **signed images** (cosign), **SBOM** (syft), and a
  **vuln scan** (Trivy) gate. Cheap to add now, expensive to retrofit under
  procurement pressure.

### AuthN / AuthZ

- **Target:** SSO via OIDC (Azure AD / Entra) and SAML, with RBAC roles
  (admin / reviewer / viewer). Group-to-role mapping configurable.
- **Demo/dev (current):** keep the bcrypt password + session cookie. Ship
  SSO as a later phase — design the auth layer now so swapping the backend
  is a provider change, not a rewrite.

### Secrets

Pluggable secrets backend behind a single interface:

- `env` (default — plain env vars, fine for demo + most installs)
- `vault` (HashiCorp Vault)
- `azure-kv` (Azure Key Vault)
- `aws-sm` (AWS Secrets Manager)

No envctl. No plaintext in config files beyond `.env.example`.

### Observability

Non-negotiable for anything that talks to a production BW:

- **OpenTelemetry traces** — every scan, every LLM call, every SAP request
- **Prometheus metrics** — queue depth, scan duration, LLM token spend,
  SAP request rate, error rates per target
- **Structured JSON logs** — correlation IDs across web → queue → worker
- **Health endpoints** — `/healthz` (liveness), `/readyz` (readiness,
  including DB/Redis/LLM-provider checks)

### LLM providers — cloud and on-prem, first-class

The provider abstraction must support both paths as equal citizens. Many BW
customers will refuse to send ABAP / DSP code to a cloud LLM for IP,
compliance, or data-residency reasons.

Supported backends:

- **Cloud** — Azure OpenAI (default for most enterprise installs), OpenAI,
  Anthropic
- **On-prem** — vLLM (OpenAI-compatible API, GPU) and Ollama (lighter, CPU
  or small GPU). Both behind an OpenAI-compatible adapter so switching is a
  URL + model-name change.
- **Homelab router** — kept as one of the backends so our dev/demo env
  stays fast; not required for client installs.

Design implications:

- **Prompt footprint matters** — on-prem models (even 32B-class) have
  smaller context windows and weaker instruction-following than GPT-4-class.
  Prompts must degrade gracefully: chunking, structured-output retries,
  shorter system prompts.
- **No hard dependency on any single provider's features** (e.g. no
  OpenAI-only JSON mode assumptions) — use a structured-output layer that
  works against any OpenAI-compatible endpoint.
- **Per-provider rate limiting and token-budget circuit breakers** — on-prem
  is slow, cloud is metered; both need guards.
- **Recommended on-prem model tier**: Qwen2.5-Coder-32B or Llama-3.1-70B for
  scanning/QA; smaller models acceptable for classification tasks.

### Scale-out

- **web** — stateless, N replicas behind the client's load balancer
- **worker** — stateless, N replicas; separate worker pools per queue
  (e.g. `scan`, `llm`, `chrome`) with independent concurrency caps
- **chrome/CDP pool** — isolated worker pool with a hard concurrency cap
  (Chrome is RAM-hungry and crash-prone; don't mix with LLM or light work)
- **LLM calls** — rate-limited per provider, with a token-budget circuit
  breaker so a runaway scan can't burn the client's OpenAI quota

### Data & lifecycle

- Postgres migrations via Alembic, forward-only, tested upgrade path
- Documented backup/restore procedure (pg_dump + object-store artifacts)
- Version-pinned image tags; documented upgrade runbook

## Open questions

1. **Multi-tenant?** Out of scope for v1 — single-tenant per install. A
   large client may want multiple isolated instances (dev/test/prod);
   solve that with separate deployments, not in-app tenancy.
2. **Which OIDC/SAML library?** Defer until we actually implement SSO;
   Authlib is the likely default.
3. **LLM provider priority** — which backend do we certify first for
   Horvath? Probably Azure OpenAI (enterprise-standard).
