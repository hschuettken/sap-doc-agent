# SAP Doc Agent — Migration and Extension Plan

Status: 2026-04-14. Six independently shippable phases.  
Reference architecture: `docs/ARCHITECTURE_TARGET.md`

---

## Current state baseline

| Dimension | Current |
|---|---|
| Container topology | Single container on docker2, port 8260 |
| LLM | `DirectLLMProvider` calling homelab LLM Router at `:8070` via config mode `direct` |
| Secrets | envctl injection at deploy time |
| Dockerfile | Clones from Gitea `192.168.0.64:3000` at build (no COPY) |
| Job execution | Scanner/agent calls run in-process inside the web uvicorn process |
| Config | YAML file (`config.yaml`) + env-var-resolved fields at adapter init time |
| Doc platform | BookStack at `:8253`, pluggable via adapter pattern (already correct) |
| LLM abstraction | `LLMProvider` ABC with `generate` / `generate_json` / `is_available` — interface is clean |
| Tests | 254 tests across 18 test files |
| UI pages | 9 pages (Dashboard, Objects, Object Detail, Quality, Graph, Reports, Audit, Scanner, Settings) |
| Frontend | Jinja2 + HTMX + Tailwind CDN + vis.js — server-rendered |
| Auth | bcrypt password hash + itsdangerous session cookies |

---

## Phase 1 — LLM Provider Abstraction

**Goal:** Any client can point the tool at their LLM of choice. The homelab LLM Router stays the default; it becomes one backend among several. Long-running prompt work degrades gracefully on smaller/slower models.

**Complexity:** M

### What to build

#### New adapters (all in `src/sap_doc_agent/llm/`)

| File | Provider | Auth |
|---|---|---|
| `azure_openai.py` | Azure OpenAI Service | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` |
| `openai.py` | OpenAI API | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `anthropic.py` | Anthropic Claude API | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| `vllm.py` | vLLM (OpenAI-compatible) | `VLLM_BASE_URL`, `VLLM_MODEL`, `VLLM_API_KEY` (optional) |
| `ollama.py` | Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| `router.py` | Homelab LLM Router | `LLM_ROUTER_URL`, `LLM_ROUTER_API_KEY` (rename current `direct.py` logic) |

The `azure_openai.py`, `openai.py`, and `vllm.py` adapters all call the same `/chat/completions` shape — extract a shared `OpenAICompatibleAdapter` base class in `base.py` to avoid duplication. `anthropic.py` uses the Messages API directly (not OpenAI-compatible).

#### Factory changes (`src/sap_doc_agent/llm/__init__.py`)

Replace config-mode dispatch with an env-var-driven factory:

```python
LLM_PROVIDER=azure | openai | anthropic | vllm | ollama | router | none | copilot_passthrough
```

`create_llm_provider()` reads `LLM_PROVIDER` from env, instantiates the correct adapter, validates required env vars are present. Config YAML `llm.mode` stays for backward compat but env var takes precedence when set.

#### Structured output layer (`src/sap_doc_agent/llm/structured.py`)

`generate_json` currently embeds the schema in the system prompt and does a `json.loads()`. This breaks on models that wrap JSON in markdown fences or add commentary. Add:

- `extract_json_from_response(text)` — strips markdown fences, handles leading/trailing text
- `generate_json_with_retry(provider, prompt, schema, system, max_retries=2)` — on parse failure, re-prompts with the raw response and asks the model to correct it

#### Prompt degradation helpers (`src/sap_doc_agent/llm/chunking.py`)

Large ABAP programs and DSP objects can exceed context windows of on-prem models. Add:

- `chunk_text(text, max_tokens, overlap)` — splits on logical boundaries (ABAP form/method, SQL statement)
- `chunk_and_aggregate(provider, prompt_template, chunks, schema)` — runs generate_json on each chunk, merges results
- Callers (agents) use this when `LLM_CHUNK_SIZE_TOKENS` env var is set

#### Rate limiting + circuit breaker (`src/sap_doc_agent/llm/limits.py`)

- `TokenBudgetCircuitBreaker` — tracks tokens spent this hour, opens circuit at `LLM_TOKEN_BUDGET_PER_HOUR` (default: unlimited / env opt-in)
- `ProviderRateLimiter` — async semaphore wrapping each provider call, max concurrency from `LLM_MAX_CONCURRENT` (default 4)
- Both are thin wrappers around the provider; compose them at factory time

#### Config changes (`src/sap_doc_agent/config.py`)

Extend `LLMConfig`:
- Add `provider` field (replaces `mode`, keep `mode` alias for compat)
- Add `chunk_size_tokens: Optional[int]`
- Add `token_budget_per_hour: Optional[int]`
- Add `max_concurrent: int = 4`

### Files to create/modify

- Create: `src/sap_doc_agent/llm/azure_openai.py`
- Create: `src/sap_doc_agent/llm/openai.py`
- Create: `src/sap_doc_agent/llm/anthropic.py`
- Create: `src/sap_doc_agent/llm/vllm.py`
- Create: `src/sap_doc_agent/llm/ollama.py`
- Create: `src/sap_doc_agent/llm/router.py` (rename/refactor current `direct.py`)
- Create: `src/sap_doc_agent/llm/structured.py`
- Create: `src/sap_doc_agent/llm/chunking.py`
- Create: `src/sap_doc_agent/llm/limits.py`
- Modify: `src/sap_doc_agent/llm/__init__.py` (env-var factory)
- Modify: `src/sap_doc_agent/llm/base.py` (add `OpenAICompatibleAdapter` base)
- Modify: `src/sap_doc_agent/config.py` (extend `LLMConfig`)
- Modify: `pyproject.toml` (add `anthropic>=0.25` as optional dep under `[project.optional-dependencies].anthropic`)

### Tests to write

- `tests/test_llm_providers.py` — one test class per adapter using `respx` to mock HTTP; verify `generate()` returns content, `generate_json()` parses JSON, failure returns `None` not exception
- `tests/test_llm_structured.py` — test `extract_json_from_response` with fenced, bare, and malformed inputs; test retry logic
- `tests/test_llm_chunking.py` — test chunking at boundary, overlap, aggregation merging
- `tests/test_llm_limits.py` — test circuit breaker opens and resets; test semaphore blocks at concurrency cap

### Key decisions

- Keep `direct.py` as a thin shim pointing to `router.py` for backward compat during transition — delete once config references are updated
- `anthropic` SDK dependency is optional; adapter raises `ImportError` with a clear message if not installed
- All adapters implement the same `LLMProvider` ABC; no adapter imports another adapter

### Definition of done

- `LLM_PROVIDER=openai` and `LLM_PROVIDER=azure` configs work end-to-end with a live call (confirmed manually in homelab or with a mock)
- `LLM_PROVIDER=router` is the default when env var is unset (backward compat)
- All existing 254 tests still pass
- New tests for all adapters pass with mocked HTTP
- No hardcoded `192.168.` URL in any adapter file

---

## Phase 2 — Job Queue + Celery

**Goal:** Web process never blocks on long-running work. Scanner runs, agent chains, and LLM calls move into a Celery task queue backed by Redis. Priority lanes and per-target rate limiting are enforced at the queue level.

**Complexity:** L

### What to build

#### Dependencies

Add to `pyproject.toml`:
- `celery[redis]>=5.3`
- `redis>=5.0`
- `flower>=2.0` (optional extras group `monitoring`)

#### Celery app (`src/sap_doc_agent/tasks/celery_app.py`)

- `celery_app = Celery("sapdoc", broker=REDIS_URL, backend=REDIS_URL)`
- Three queues: `scan`, `llm`, `chrome`
- `task_routes` mapping: scanner tasks → `scan`, agent tasks with LLM calls → `llm`, CDP/Playwright → `chrome`
- `task_acks_late = True` — don't ack until task completes
- `task_reject_on_worker_lost = True`
- Per-queue concurrency set via env: `WORKER_CONCURRENCY_SCAN`, `WORKER_CONCURRENCY_LLM`, `WORKER_CONCURRENCY_CHROME` (defaults: 4, 2, 1)

#### Task definitions

`src/sap_doc_agent/tasks/scan_tasks.py`:
- `run_scan(scanner_type: str, config_path: str, run_id: str)` — wraps orchestrator scan calls
- `run_abap_scan(system_name: str, config_path: str, run_id: str)`
- `run_dsp_api_scan(system_name: str, config_path: str, run_id: str)`
- `run_cdp_scan(system_name: str, config_path: str, run_id: str)` → routes to `chrome` queue

`src/sap_doc_agent/tasks/agent_tasks.py`:
- `run_doc_review(object_id: str, config_path: str)` → `llm` queue
- `run_qa_check(object_id: str, config_path: str)` → `llm` queue
- `run_pdf_ingest(file_path: str, config_path: str)` → `llm` queue
- `run_report_generator(scope: str, config_path: str)` → `llm` queue
- `run_brs_traceability(brs_id: str, config_path: str)` → `llm` queue

#### Job state tracking (`src/sap_doc_agent/tasks/job_state.py`)

All task IDs and their status stored in Redis with a `sapdoc:job:` prefix and 24h TTL. Web API returns `task_id` immediately; polling endpoint checks Celery task state.

New API endpoints (added to `web/server.py`):
- `POST /api/scan/start` → enqueues `run_scan()`, returns `{"task_id": "...", "status": "queued"}`
- `GET /api/scan/status/{task_id}` → returns Celery task state + result preview
- `POST /api/agent/{agent_name}/run` → enqueues agent task, returns `task_id`
- `GET /api/jobs` → lists recent jobs from Redis (last 50)

#### Priority lanes

Celery task priority via `apply_async(priority=n)`:
- UI-triggered (user presses Scan button): priority 9 (highest)
- Nightly QA runs from scheduler: priority 5
- Bulk backfill / re-scan all: priority 1 (lowest)

Priority passed as a task kwarg, not baked into the task function.

#### Per-target SAP rate limiting

`src/sap_doc_agent/tasks/rate_limit.py`:
- `SAPRateLimiter` — Redis-backed sliding window per `system_name`
- Default: 10 SAP API requests/second per target (env: `SAP_RATE_LIMIT_RPS`)
- Scanner tasks call `rate_limiter.acquire(system_name)` before each SAP request
- On 429 from SAP: Celery retry with `countdown=60`

#### Retry policy

Default for all tasks:
- `max_retries = 3`
- `retry_backoff = True` (exponential, base 30s, max 300s)
- `autoretry_for = (httpx.HTTPError, ConnectionError)`

SAP scanner tasks additionally retry on HTTP 429 and 503.

#### Flower

Run Flower as a separate process in the worker container (same image, different CMD). Expose at `:5555` internally. Not exposed externally by default — document how to expose via reverse proxy if client ops team needs it.

### Files to create/modify

- Create: `src/sap_doc_agent/tasks/__init__.py`
- Create: `src/sap_doc_agent/tasks/celery_app.py`
- Create: `src/sap_doc_agent/tasks/scan_tasks.py`
- Create: `src/sap_doc_agent/tasks/agent_tasks.py`
- Create: `src/sap_doc_agent/tasks/job_state.py`
- Create: `src/sap_doc_agent/tasks/rate_limit.py`
- Modify: `src/sap_doc_agent/web/server.py` (add enqueue endpoints, remove blocking scan routes)
- Modify: `src/sap_doc_agent/web/templates/partials/scanner.html` (HTMX polling on task_id)
- Modify: `pyproject.toml` (add celery, redis, flower)

### Tests to write

- `tests/test_tasks.py` — mock Celery with `celery.contrib.pytest`; verify task routing (`scan` → scan queue, `cdp_scan` → chrome queue); verify retry on HTTP error; verify priority kwarg is passed
- `tests/test_job_state.py` — mock Redis; verify job registration, status polling, TTL
- `tests/test_rate_limit.py` — mock Redis; verify sliding window enforces RPS limit; verify retry on 429
- Update `tests/test_web_server.py` — `POST /api/scan/start` returns 202 with task_id, no longer runs scan inline

### Key decisions

- Use Celery's own result backend (Redis) for task state — no separate job table in Postgres for now (simpler; revisit if the client needs long-term job history)
- Scanner YAML config path is passed to tasks as a string (file path), not serialized config — workers read the same config file from the mounted volume
- Keep `sap-doc-agent audit` CLI mode working synchronously (no Celery) for one-shot runs — CLI users don't need a Redis instance

### Definition of done

- `POST /api/scan/start` returns immediately with `task_id`
- Worker picks up the task, executes the scan, stores result
- `GET /api/scan/status/{task_id}` transitions from `queued` → `running` → `success`
- Web process stays responsive (no blocking) during an active scan
- All new task tests pass
- Existing 254 tests still pass (CLI path unaffected)

---

## Phase 3 — Container Split

**Goal:** Three containers from one image: `web`, `worker`, `scheduler`. Chrome/CDP isolated in its own pool. Structured logging and health endpoints ship in this phase.

**Complexity:** M

### What to build

#### Single image, three entrypoints

`Dockerfile` at project root. Builds the full package. Entrypoint selected by `CMD`:

```dockerfile
FROM python:3.12-slim AS base
# install playwright/chromium for chrome worker pool
# install build deps
COPY . /app
WORKDIR /app
RUN pip install --prefer-binary -e ".[all]"

# Default: web
CMD ["uvicorn", "sap_doc_agent.web.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
```

`docker-compose.yml` overrides per service:
```yaml
web:
  command: uvicorn sap_doc_agent.web.server:create_app --factory --host 0.0.0.0 --port 8080
worker:
  command: celery -A sap_doc_agent.tasks.celery_app worker -Q scan,llm -c 4
scheduler:
  command: celery -A sap_doc_agent.tasks.celery_app beat --loglevel=info
```

A separate `docker-compose.yml` entry for the chrome pool:
```yaml
worker-chrome:
  command: celery -A sap_doc_agent.tasks.celery_app worker -Q chrome -c 1
```

#### Celery Beat schedules (`src/sap_doc_agent/tasks/schedules.py`)

- Nightly QA: `crontab(hour=2, minute=0)` → `run_qa_check` for all scanned objects
- Weekly report: `crontab(day_of_week=1, hour=6, minute=0)` → `run_report_generator(scope="all")`
- Periodic re-scan: controlled by `SCAN_CRON_SCHEDULE` env var (default disabled)

All schedules loaded from this file into `celery_app.conf.beat_schedule`.

#### Health endpoints

Add to `web/server.py`:
- `GET /healthz` — liveness; returns `{"status": "ok"}` always (200)
- `GET /readyz` — readiness; checks DB connection and Redis connection; returns `{"status": "ok", "checks": {...}}` or 503

Worker readiness: Celery worker health exposed via Flower (internal) and via `celery inspect ping`.

#### Structured JSON logging (`src/sap_doc_agent/logging.py`)

- Replace `logging.basicConfig` with a JSON formatter
- Each log record includes: `timestamp`, `level`, `logger`, `message`, `correlation_id` (from request context var)
- `correlation_id` injected in FastAPI middleware (random UUID per request, passed to Celery task via task headers)
- Worker logs include the task_id as correlation_id

#### OpenTelemetry skeleton (`src/sap_doc_agent/telemetry.py`)

Stub only in Phase 3 (full instrumentation deferred to post-MVP):
- `init_telemetry()` — reads `OTEL_EXPORTER_OTLP_ENDPOINT`; if set, configures OTLP exporter; if not set, no-ops
- `get_tracer()` — returns the app tracer
- One span wrapper: `@trace_span("scan.run")` decorator used in scan tasks

#### Prometheus metrics (`src/sap_doc_agent/metrics.py`)

Basic counters and histograms:
- `sapdoc_scan_duration_seconds` — histogram by scanner type
- `sapdoc_llm_tokens_total` — counter by provider
- `sapdoc_queue_depth` — gauge per queue (polled from Redis)
- `sapdoc_scan_errors_total` — counter by scanner + error type

Exposed at `GET /metrics` (Prometheus scrape format) on the web container.

#### docker-compose.yml (full)

```
services: web, worker, worker-chrome, scheduler, postgres, redis
```
- `postgres` uses `POSTGRES_*` env vars, with a named volume
- `redis` minimal config
- All services share an `app-network` bridge network
- `web` depends_on `postgres` + `redis` with healthchecks
- `worker` depends_on `redis`
- `scheduler` depends_on `redis` + `postgres`

### Files to create/modify

- Create: `Dockerfile` (project root)
- Create: `docker-compose.yml` (project root)
- Create: `src/sap_doc_agent/tasks/schedules.py`
- Create: `src/sap_doc_agent/logging.py`
- Create: `src/sap_doc_agent/telemetry.py`
- Create: `src/sap_doc_agent/metrics.py`
- Modify: `src/sap_doc_agent/web/server.py` (add /healthz, /readyz, /metrics)
- Modify: `src/sap_doc_agent/__main__.py` (entrypoint routing for worker/scheduler modes)
- Modify: `pyproject.toml` (add `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, `prometheus-client`)

### Tests to write

- `tests/test_health.py` — mock DB + Redis; `/healthz` always 200; `/readyz` 503 when DB unreachable
- `tests/test_logging.py` — verify JSON format, correlation_id propagation
- `tests/test_metrics.py` — verify Prometheus text format at `/metrics`, counters increment

### Key decisions

- One image simplifies build pipeline and dependency management at Phase 3 — no need for a slim web image until client demands it
- Playwright/Chromium installed in the base image; in the chrome worker it's active, in web/scheduler it consumes no RAM
- Celery Beat in the scheduler container uses file-based schedule persistence (`--schedule /tmp/celerybeat-schedule`) — simpler than DB backend for v1

### Definition of done

- `docker compose up` starts all services cleanly
- `/healthz` returns 200, `/readyz` returns 503 when Redis is stopped
- Worker picks up tasks from Phase 2
- All logs are valid JSON with correlation_id
- `/metrics` returns valid Prometheus text

---

## Phase 4 — Standards Upload + Knowledge Management

**Goal:** Clients can upload their own documentation standards (PDF/Word) and the system extracts rules from them using LLM. Tenant knowledge accumulates from scans and can be manually overridden. Doc Review Agent uses a blended score.

**Complexity:** L

### What to build

#### Database tables (new Alembic migration)

`migrations/versions/xxxx_customer_standards.py`:

```sql
customer_standards (
  id UUID PK DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  uploaded_at TIMESTAMPTZ DEFAULT now(),
  status TEXT DEFAULT 'processing',   -- processing | ready | error
  parsed_rules JSONB,
  raw_text TEXT,
  error_message TEXT
)

customer_standard_files (
  id UUID PK DEFAULT gen_random_uuid(),
  standard_id UUID REFERENCES customer_standards(id) ON DELETE CASCADE,
  file_data BYTEA NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INT
)

tenant_knowledge (
  id UUID PK DEFAULT gen_random_uuid(),
  category TEXT NOT NULL,   -- namespace | space | prefix | exception | org
  key TEXT NOT NULL,
  value JSONB NOT NULL,
  source TEXT NOT NULL,     -- scan | upload | manual
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(category, key)
)
```

#### Text extraction pipeline (`src/sap_doc_agent/standards/extractor.py`)

- `extract_text(file_data: bytes, content_type: str) -> str`
- PDF: `pdfplumber` — page-by-page, concatenate
- Word (.docx): `python-docx`
- YAML / Markdown: decode as UTF-8 directly
- Returns extracted text, raises `UnsupportedFileType` for other content types

#### Rule extraction agent (`src/sap_doc_agent/standards/rule_extractor.py`)

- `extract_rules(text: str, llm: LLMProvider) -> dict` — LLM pass using `generate_json_with_retry`
- Output schema: `{"sections": [...], "naming_rules": [...], "field_requirements": [...], "custom_rules": [...]}`
- Uses `chunk_and_aggregate` from Phase 1 when document is large
- Returns partial results on LLM failure (not None)

#### Celery tasks (add to `agent_tasks.py`)

- `process_standard_upload(standard_id: str, config_path: str)` → `llm` queue
  1. Load file from `customer_standard_files`
  2. Extract text
  3. Run rule extractor
  4. Update `customer_standards.parsed_rules` + `status=ready`
  5. On error: set `status=error`, `error_message`

- `process_knowledge_upload(knowledge_id: str, config_path: str)` → `llm` queue

#### Postgres adapter (`src/sap_doc_agent/standards/db.py`)

Thin async wrapper using `asyncpg`:
- `create_standard(name, filename, content_type) -> str`
- `store_standard_file(standard_id, file_data, filename, content_type) -> None`
- `update_standard_rules(standard_id, parsed_rules, raw_text, status) -> None`
- `list_standards() -> list[dict]`
- `get_standard(standard_id) -> dict`
- `delete_standard(standard_id) -> None`
- `upsert_knowledge(category, key, value, source) -> None`
- `list_knowledge(category=None) -> list[dict]`
- `delete_knowledge(knowledge_id) -> None`

#### API endpoints (add to `web/server.py`)

12 new endpoints as specified in the architecture doc:
```
POST   /api/standards/upload
GET    /api/standards
GET    /api/standards/{id}
PUT    /api/standards/{id}/rules
DELETE /api/standards/{id}
GET    /api/standards/{id}/download

GET    /api/knowledge
POST   /api/knowledge
PUT    /api/knowledge/{id}
DELETE /api/knowledge/{id}
POST   /api/knowledge/upload
```

`POST /api/standards/upload` — multipart/form-data, max 50MB (configurable via `UPLOAD_MAX_MB` env). Enqueues `process_standard_upload`, returns 202 + task_id.

#### Dashboard UI changes

Add a "Standards & Knowledge" section below the existing stats cards in `dashboard.html`.

Two cards side by side:

**Customer Standards card:**
- File drop zone (`<input type="file" accept=".pdf,.docx,.yaml,.md">`)
- HTMX `hx-post="/api/standards/upload"` with progress indicator
- Below: list of uploaded standards with status badges (`processing`, `ready`, `error`)
- Each row has an "Edit rules" link → opens parsed_rules in an inline edit form (HTMX swap)
- Approve / reject per rule (checkbox per rule, `PUT /api/standards/{id}/rules`)

**Tenant Knowledge card:**
- Table of current knowledge entries (category / key / value / source)
- "Add entry" button → inline form row
- "Upload landscape doc" → same upload flow as standards
- Manual entries shown with `source=manual` badge; scan-discovered with `source=scan`

#### Doc Review Agent changes (`src/sap_doc_agent/agents/doc_review.py`)

- Load active customer standards at agent init via `db.list_standards(status="ready")`
- Dual evaluation:
  1. Evaluate against Horvath standard (unchanged)
  2. Evaluate against merged `parsed_rules` from all active customer standards
  3. `final_score = horvath_score * weights.horvath + customer_score * weights.customer`
  4. `weights` configurable via env: `SCORE_WEIGHT_HORVATH` (default 0.7), `SCORE_WEIGHT_CUSTOMER` (default 0.3)
- Report output includes both scores + `customer_compliance_gap` flag
- If no active customer standards: customer_score = None, weight falls back entirely to Horvath

### Files to create/modify

- Create: `migrations/versions/xxxx_customer_standards.py`
- Create: `src/sap_doc_agent/standards/__init__.py`
- Create: `src/sap_doc_agent/standards/extractor.py`
- Create: `src/sap_doc_agent/standards/rule_extractor.py`
- Create: `src/sap_doc_agent/standards/db.py`
- Modify: `src/sap_doc_agent/tasks/agent_tasks.py` (add process_standard_upload, process_knowledge_upload)
- Modify: `src/sap_doc_agent/web/server.py` (12 new endpoints)
- Modify: `src/sap_doc_agent/web/templates/partials/dashboard.html` (Standards & Knowledge section)
- Modify: `src/sap_doc_agent/agents/doc_review.py` (dual evaluation)
- Modify: `pyproject.toml` (add `pdfplumber>=0.11`, `python-docx>=1.1`, `asyncpg>=0.29`)

### Tests to write

- `tests/test_standards_extractor.py` — fixture PDFs and docx files; verify text extraction; test unsupported type raises
- `tests/test_standards_rule_extractor.py` — mock LLM; verify schema structure; test chunking path for large doc
- `tests/test_standards_api.py` — full API round-trip with test DB; upload → status processing → rules patch → download
- `tests/test_doc_review_dual.py` — mock customer standards in DB; verify blended score calculation; verify customer_compliance_gap flag; verify fallback when no standards

### Key decisions

- File data stored as BYTEA in Postgres (not filesystem) for portability — no S3/MinIO dependency in v1
- File size cap enforced at FastAPI layer, not Celery (fail fast)
- Rule approval is per-rule (JSONB array edit), not per-standard — lets clients reject individual noisy rules without deleting the whole upload
- Scanner writes to `tenant_knowledge` with `source=scan` using `ON CONFLICT (category, key) DO UPDATE` — manual overrides (`source=manual`) survive re-scan because the trigger only upserts `source=scan` rows, never overwrites `source=manual`

### Definition of done

- Upload a real PDF documentation standard → rules extracted → visible in UI
- Approve a subset of rules → blended score changes in Doc Review output
- Manual knowledge entry survives a re-scan
- All 12 API endpoints return correct status codes with no auth
- New tests pass; existing 254 tests unaffected

---

## Phase 5 — Portability

**Goal:** Remove all homelab-specific coupling from the build and runtime. The Docker image is self-contained, ships to a registry, and requires no homelab infrastructure to run.

**Complexity:** M

### What to build

#### Dockerfile: COPY instead of Gitea clone

Current Dockerfile (in the MCP tools subdirectory) clones from Gitea. Replace with:

```dockerfile
COPY . /app
WORKDIR /app
RUN pip install --prefer-binary -e ".[all]"
```

This means the image is built from the local working tree. CI builds it from the git checkout. No Gitea token needed at build time.

#### Remove envctl dependency

Audit every place where config is read:
- `config.py`: already reads env vars via field `*_env` names — this is already correct
- `web/server.py`: check for any direct `os.environ.get("HOMELAB_*")` calls — remove or guard
- `Dockerfile` / `docker-compose.yml`: remove any envctl loader scripts

Add a thin optional loader (`src/sap_doc_agent/secrets/envctl_loader.py`) that, if `ENVCTL_URL` is set, fetches vars from envctl and injects them into `os.environ` before app startup. This keeps the homelab deploy working without making envctl a hard dependency.

#### Pluggable secrets interface (`src/sap_doc_agent/secrets/`)

```
secrets/
  __init__.py       — get_secret(key) dispatcher
  env_backend.py    — reads from os.environ (default)
  vault_backend.py  — HashiCorp Vault stub (raises NotImplementedError with helpful message)
  azure_kv_backend.py — Azure Key Vault stub
  aws_sm_backend.py — AWS Secrets Manager stub
  envctl_loader.py  — optional homelab loader
```

`SECRETS_BACKEND=env | vault | azure-kv | aws-sm | envctl` (default: `env`)

All adapters implement `get(key: str) -> str | None`. App calls `get_secret("DSP_CLIENT_ID")` instead of `os.environ.get("DSP_CLIENT_ID")` in the three places that need it.

#### .env.example

Document all config vars with descriptions, types, defaults, and which phase introduced them. Group by category:

```ini
# === Database ===
DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/sapdoc

# === Queue ===
REDIS_URL=redis://localhost:6379/0

# === LLM — pick one provider ===
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# === Doc platform — pick one ===
DOC_BACKEND=bookstack
BOOKSTACK_URL=http://bookstack:80
BOOKSTACK_TOKEN=...
# ...etc
```

#### Remove 192.168.x references

Grep the entire codebase for `192.168.` and `0.50`, `0.64`, `0.73`, `0.80`, `0.78`. Each hit: either delete (dead code), replace with env var, or gate behind `if os.environ.get("HOMELAB_MODE")`. Document which IPs were removed and what replaced them.

#### CI — GHCR publish + supply chain

`.github/workflows/publish.yml` (or Gitea equivalent `gitea/workflows/publish.yaml`):
1. `docker build -t ghcr.io/atlas/sap-doc-agent:${sha}` on push to `main`
2. `cosign sign` — image signing (requires `COSIGN_KEY` secret)
3. `syft ghcr.io/atlas/sap-doc-agent:${sha} -o spdx-json > sbom.json` — SBOM
4. `trivy image --exit-code 1 --severity CRITICAL ghcr.io/atlas/sap-doc-agent:${sha}` — vuln gate
5. Push `:latest` tag on success

For Gitea CI: use `gitea/workflows/publish.yaml` (act-runner). Follow patterns in `.github/` equivalent for the homelab runner.

### Files to create/modify

- Modify: `Dockerfile` (COPY instead of clone)
- Create: `src/sap_doc_agent/secrets/__init__.py`
- Create: `src/sap_doc_agent/secrets/env_backend.py`
- Create: `src/sap_doc_agent/secrets/vault_backend.py`
- Create: `src/sap_doc_agent/secrets/azure_kv_backend.py`
- Create: `src/sap_doc_agent/secrets/aws_sm_backend.py`
- Create: `src/sap_doc_agent/secrets/envctl_loader.py`
- Create: `.env.example`
- Create: `.gitea/workflows/publish.yaml` (or `.github/workflows/publish.yml`)
- Modify: `src/sap_doc_agent/config.py` (remove any hardcoded URLs)
- Modify: `src/sap_doc_agent/web/server.py` (remove hardcoded homelab refs)

### Tests to write

- `tests/test_secrets.py` — env backend returns var; missing var returns None; backend dispatch from `SECRETS_BACKEND` env var
- CI test: `trivy` scan must pass before image is tagged `:latest`
- Manual verification: `docker build .` succeeds from a clean directory with no homelab network access

### Key decisions

- Vault/Azure KV/AWS SM backends raise `NotImplementedError` with a clear message — they are interface stubs, not implementations. A client that needs them will implement them (likely a one-day engagement).
- `envctl_loader.py` only activates when `ENVCTL_URL` is explicitly set — no implicit homelab detection
- CI runs on Gitea act-runner using the existing runner setup (see `reference_gitea_act_runner_ci` memory)

### Definition of done

- `docker build .` succeeds from project root with no Gitea access
- Container starts with only `.env` vars (no envctl, no homelab network)
- No `192.168.` in any Python source file
- `.env.example` covers all required vars with comments
- CI pipeline publishes to GHCR on push to `main`
- Trivy scan finds no CRITICAL vulnerabilities (or has documented exceptions)

---

## Phase 6 — Client Install Package

**Goal:** A client's platform team can install the tool on a clean VM by following a README. Upgrade and backup procedures are documented and tested.

**Complexity:** S

### What to build

#### Client docker-compose.yml

A compose file designed for client install — separate from the dev compose. Located at `deploy/docker-compose.client.yml`:

- `web`, `worker`, `worker-chrome`, `scheduler`, `postgres`, `redis`
- All image references point to `ghcr.io/atlas/sap-doc-agent:latest` (client mirrors to their own registry)
- Named volumes for Postgres data and uploaded files
- Clear port binding: web on `8080` (client puts their reverse proxy in front)
- No homelab-specific networks or labels
- `restart: unless-stopped` on all services

#### Auth layer designed for SSO swap

Current: bcrypt hash in `UI_PASSWORD_HASH` env var, itsdangerous session cookie.

Introduce an auth provider interface (`src/sap_doc_agent/web/auth_provider.py`):

```python
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, request: Request) -> Optional[str]:
        """Returns user identifier or None if not authenticated."""

    @abstractmethod
    def get_login_response(self) -> Response:
        """Returns the appropriate login redirect/challenge."""
```

Two implementations shipped:
- `PasswordAuthProvider` — current bcrypt logic, moved here
- `OIDCAuthProvider` — stub that raises `NotImplementedError` with a note pointing to Authlib

`AUTH_PROVIDER=password | oidc` (default: `password`). Swap is a one-var change.

#### Install documentation

`docs/INSTALL.md`:
1. Prerequisites (Docker 24+, compose v2, 4GB RAM, 20GB disk)
2. Clone or download release archive
3. Copy `.env.example` → `.env`, fill in values (guided walkthrough of each var)
4. `docker compose -f deploy/docker-compose.client.yml up -d`
5. Open `http://<host>:8080`, log in with the password hash from step 3
6. Connect your SAP system (link to SAP setup guide in `setup/`)
7. Run initial scan

`docs/UPGRADE.md`:
1. Pull new image: `docker pull ghcr.io/atlas/sap-doc-agent:X.Y.Z`
2. Update `docker-compose.client.yml` image tag
3. Run Alembic migrations: `docker compose run --rm web alembic upgrade head`
4. `docker compose up -d`

`docs/BACKUP.md`:
1. Postgres: `docker compose exec postgres pg_dump -U sapdoc sapdoc > backup.sql`
2. Restore: `psql` into a fresh DB
3. Uploaded files: already in Postgres (BYTEA) — covered by pg_dump

#### Clean VM verification test

`tests/test_client_install.py` (or a shell script `scripts/verify-install.sh`):
- Start compose stack from `deploy/docker-compose.client.yml` with a minimal `.env`
- Wait for `/readyz` to return 200
- Hit `/healthz`
- Confirm login page renders
- Confirm `/api/standards` returns empty list (not 500)

This test runs in CI on every release candidate tag.

### Files to create/modify

- Create: `deploy/docker-compose.client.yml`
- Create: `deploy/.env.client.example` (subset of `.env.example`, install-focused)
- Create: `src/sap_doc_agent/web/auth_provider.py`
- Modify: `src/sap_doc_agent/web/auth.py` (use `AuthProvider`, keep bcrypt as default)
- Modify: `src/sap_doc_agent/web/server.py` (inject auth provider)
- Create: `docs/INSTALL.md`
- Create: `docs/UPGRADE.md`
- Create: `docs/BACKUP.md`
- Create: `scripts/verify-install.sh`
- Modify: `.gitea/workflows/publish.yaml` (add release-candidate CI step)

### Tests to write

- `tests/test_auth_provider.py` — PasswordAuthProvider authenticates correct hash, rejects wrong password, rejects missing cookie
- `tests/test_client_install.py` — compose stack smoke test (requires Docker in CI environment)

### Key decisions

- OIDCAuthProvider is a stub in v1 — swapping in Authlib is a known future engagement, not a current requirement
- Client compose does not include Flower or any monitoring — document as optional
- Alembic migrations run as a compose `run` step (not automatic on startup) — explicit, auditable, safe for production

### Definition of done

- A developer with no homelab access can run `docker compose -f deploy/docker-compose.client.yml up -d` on a clean Ubuntu 24 VM, fill in `.env`, and reach a working web UI
- Upgrade procedure works: start v1, run v2 migrations, start v2, no data loss
- `scripts/verify-install.sh` exits 0

---

## Dependency and ordering notes

These phases are designed to be independently shippable, but natural dependencies exist:

- Phase 2 (Celery) requires at least a `redis:6379` to be reachable during development — use `docker compose up redis -d` from the Phase 3 compose
- Phase 3 (container split) should be committed to git before Phase 4 (standards upload) because Phase 4 uses the Celery tasks introduced in Phase 3
- Phase 4 (standards upload) requires Postgres to have the migration from Phase 4 applied — run `alembic upgrade head` before testing
- Phase 5 (portability) can be done in parallel with Phase 4 since they touch different layers, but test both together before calling Phase 5 done
- Phase 6 (client package) depends on Phase 5 (portability) being complete

Phases 1–3 give the running homelab a proper production-grade architecture. Phases 4–6 make it a deliverable artifact.

---

## Test strategy across phases

| What | Strategy |
|---|---|
| LLM adapters | `respx` mock for HTTP; one test class per adapter |
| Celery tasks | `celery.contrib.pytest` with in-memory broker |
| DB operations | Real Postgres in CI (fixture DB with Alembic migrations applied) |
| Web endpoints | FastAPI `TestClient`; mock Celery `.apply_async` |
| Integration | Phase 3+ compose stack spun up in CI as a service |
| Client install | `scripts/verify-install.sh` in CI on release tags |

The 254 existing tests use `pytest-httpx` and `respx` for HTTP mocking. New tests follow the same pattern. No new test frameworks introduced without a strong reason.
