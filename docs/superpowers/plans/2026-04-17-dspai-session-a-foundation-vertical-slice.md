# DSP-AI Session A — Foundation + Vertical Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship ONE enhancement producing a narrative natively in a Horváth SAC story via Pattern B (write-back). Studio create/preview/publish loop works end-to-end. Bootstrap wizard takes a fresh compose to first preview in <15 minutes.

**Architecture:** New portable microservice `dsp-ai` (FastAPI) + bundled Neo4j + bundled SearXNG inside Spec2Sphere's docker-compose. Corporate Brain in Neo4j, seeded from the existing DSP scanner. `dsp_ai.*` Postgres schema for write-back. Minimal AI Studio UI (enhancement list + split-pane editor + preview). Event bus via Postgres `LISTEN/NOTIFY`.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, neo4j-python-driver, Celery, Jinja2 + HTMX, Alembic, Pydantic v2, PostgreSQL 16, Neo4j 5 Community, Redis 7, SearXNG.

**Reference spec:** `docs/superpowers/specs/2026-04-17-dsp-ai-enhancements-design.md`

---

## File Map

### New files

| File | Responsibility |
|------|----------------|
| `docker-compose.yml` (modified) | Add `neo4j`, `searxng`, `dsp-ai` services |
| `.env.example` (modified) | Add LLM_ENDPOINT, NEO4J_PASSWORD, SEARXNG_ENABLED, WIDGET_ALLOWED_ORIGINS, STUDIO_AUTHOR_EMAILS, BATCH_CRON, BRAIN_FEEDER_CRON |
| `migrations/versions/010_dsp_ai_core.py` | Alembic migration: `dsp_ai.briefings`, `rankings`, `item_enhancements`, `user_state`, `generations`, `enhancements`, `studio_audit` |
| `src/spec2sphere/dsp_ai/__init__.py` | Package init |
| `src/spec2sphere/dsp_ai/config.py` | Pydantic models: `Enhancement`, `EnhancementBindings`, `AdaptiveRules`, `RenderHint` |
| `src/spec2sphere/dsp_ai/engine.py` | 7-stage orchestrator |
| `src/spec2sphere/dsp_ai/stages/resolve.py` | Stage 1: load enhancement from Postgres |
| `src/spec2sphere/dsp_ai/stages/gather.py` | Stage 2: DspFetcher + BrainFetcher + ExternalFetcher + UserStateFetcher (asyncio.gather) |
| `src/spec2sphere/dsp_ai/stages/adaptive_rules.py` | Stage 3: pure-Python filter/weight/re-rank |
| `src/spec2sphere/dsp_ai/stages/compose_prompt.py` | Stage 4: Jinja render |
| `src/spec2sphere/dsp_ai/stages/run_llm.py` | Stage 5: delegate to quality_router, structured output |
| `src/spec2sphere/dsp_ai/stages/shape_output.py` | Stage 6: normalize + attach provenance |
| `src/spec2sphere/dsp_ai/stages/dispatch.py` | Stage 7: batch write vs live return |
| `src/spec2sphere/dsp_ai/brain/client.py` | Neo4j driver singleton + query helpers |
| `src/spec2sphere/dsp_ai/brain/schema.py` | Cypher: constraints, indexes, bootstrap |
| `src/spec2sphere/dsp_ai/brain/feeders/schema_semantic.py` | Feeds DspObject + Column + Domain + Glossary from scanner |
| `src/spec2sphere/dsp_ai/brain/feeders/dsp_data.py` | Feeds Event nodes for row-count + schema deltas |
| `src/spec2sphere/dsp_ai/adapters/batch.py` | Celery task + NOTIFY event handlers for regeneration triggers |
| `src/spec2sphere/dsp_ai/adapters/live.py` | FastAPI router: `/v1/enhance`, `/v1/healthz`, `/v1/readyz` |
| `src/spec2sphere/dsp_ai/events.py` | Postgres LISTEN/NOTIFY helpers (`emit`, `subscribe`) |
| `src/spec2sphere/dsp_ai/cache.py` | Redis wrapper for enhancement output cache |
| `src/spec2sphere/dsp_ai/service.py` | FastAPI app entry point for the dsp-ai service |
| `src/spec2sphere/web/ai_studio/__init__.py` | Package init |
| `src/spec2sphere/web/ai_studio/routes.py` | Routes: list, create, edit, preview, publish |
| `src/spec2sphere/web/templates/partials/ai_studio.html` | Enhancement list + "New" button |
| `src/spec2sphere/web/templates/partials/ai_studio_editor.html` | Split-pane editor with preview |
| `templates/seeds/morning_brief_revenue.json` | One enhancement seed for bootstrap wizard |
| `tests/dsp_ai/conftest.py` | Shared fixtures: fake LLM, fake DSP, mock Brain, preview contexts |
| `tests/dsp_ai/test_engine_stages.py` | Unit tests for each stage |
| `tests/dsp_ai/test_engine_integration.py` | Integration: full engine run against fixtures |
| `tests/dsp_ai/test_brain_client.py` | Neo4j integration tests |
| `tests/dsp_ai/test_events.py` | LISTEN/NOTIFY round-trip |
| `tests/dsp_ai/test_live_adapter.py` | /v1/enhance endpoint contract |
| `tests/dsp_ai/test_batch_adapter.py` | Celery task writes dsp_ai.* rows |
| `tests/dsp_ai/test_studio_routes.py` | Studio CRUD + preview + publish |
| `tests/dsp_ai/test_bootstrap.py` | First-run wizard happy path |
| `tests/dsp_ai/test_smoke.py` | Marked `smoke` — post-deploy verification |

### Modified files

| File | Change |
|------|--------|
| `src/spec2sphere/app.py` | Mount AI Studio routes; include dsp-ai live adapter in separate service binary |
| `src/spec2sphere/modules.py` | Register `ai_studio` module |
| `src/spec2sphere/tasks/celery_app.py` | Add `ai-batch` queue |
| `src/spec2sphere/tasks/schedules.py` | Add `BATCH_CRON` and `BRAIN_FEEDER_CRON` Beat schedules |
| `src/spec2sphere/web/setup_wizard.py` | Extend with AI Studio bootstrap steps (LLM endpoint, Brain seed, template fork, publish) |
| `src/spec2sphere/web/templates/base.html` | Add "AI Studio" nav entry |
| `src/spec2sphere/llm/quality_router.py` | Expose `async def resolve_and_call(action, prompt, data_in_context, schema)` — programmatic API for dsp-ai |
| `src/spec2sphere/scanner/output.py` | Emit `pg_notify('scan_completed', ...)` at end of scan (consumed by schema_semantic feeder) |

---

## Task 1: Compose + env scaffolding

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1.1: Add neo4j service to docker-compose.yml**

Inside the `services:` block:

```yaml
  neo4j:
    image: neo4j:5-community
    container_name: sap-doc-agent-neo4j
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:?must_be_set}
      NEO4J_server_memory_heap_max__size: 2G
      NEO4J_server_memory_pagecache_size: 512M
    volumes:
      - neo4j-data:/data
      - neo4j-logs:/logs
    healthcheck:
      test: ["CMD-SHELL", "wget --quiet --tries=1 --spider http://localhost:7474 || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
    networks:
      - default
```

Add `neo4j-data:` and `neo4j-logs:` to the top-level `volumes:`.

- [ ] **Step 1.2: Add searxng service**

```yaml
  searxng:
    image: searxng/searxng:latest
    container_name: sap-doc-agent-searxng
    environment:
      SEARXNG_BASE_URL: http://searxng:8080/
      SEARXNG_SECRET: ${SEARXNG_SECRET:-change-me}
    volumes:
      - ./searxng:/etc/searxng:ro
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--spider", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Create `searxng/settings.yml` minimal config (just JSON format + rate limiting off in dev).

- [ ] **Step 1.3: Add dsp-ai service**

```yaml
  dsp-ai:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: sap-doc-agent-dsp-ai
    command: ["python", "-m", "spec2sphere.dsp_ai.service"]
    environment:
      <<: *common-env  # anchor to existing env block
      DSPAI_MODE: live
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_started }
      neo4j:    { condition: service_healthy }
      searxng:  { condition: service_started }
    ports:
      - "8261:8000"
    networks:
      - default
```

(Port 8261 chosen to avoid collision with existing 8260 web.)

- [ ] **Step 1.4: Append new vars to .env.example**

```
# --- dsp-ai ---
LLM_ENDPOINT=http://llm-router:8070/v1
LLM_API_KEY=
NEO4J_PASSWORD=change-me
SEARXNG_ENABLED=true
SEARXNG_SECRET=change-me
WIDGET_ALLOWED_ORIGINS=
STUDIO_AUTHOR_EMAILS=
BATCH_CRON=0 6 * * 1-5
BRAIN_FEEDER_CRON=0 */4 * * *
```

- [ ] **Step 1.5: Commit**

```bash
git add docker-compose.yml .env.example searxng/settings.yml
git commit -m "feat(dsp-ai): scaffold compose services (neo4j + searxng + dsp-ai)"
```

---

## Task 2: Alembic migration 010 — dsp_ai schema

**Files:**
- Create: `migrations/versions/010_dsp_ai_core.py`

- [ ] **Step 2.1: Write the migration**

```python
"""dsp_ai core tables.

Revision ID: 010
Revises: 009
Create Date: 2026-04-17
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS dsp_ai")
    op.execute("""
    CREATE TABLE dsp_ai.enhancements (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        version INT NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'draft',
        config JSONB NOT NULL,
        author TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (name, version)
    );
    CREATE TABLE dsp_ai.generations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        user_id TEXT,
        context_key TEXT,
        prompt_hash TEXT NOT NULL,
        input_ids JSONB NOT NULL,
        model TEXT NOT NULL,
        quality_level TEXT NOT NULL,
        latency_ms INT NOT NULL,
        tokens_in INT,
        tokens_out INT,
        cost_usd NUMERIC(10,6),
        cached BOOLEAN NOT NULL DEFAULT FALSE,
        quality_warnings JSONB,
        error_kind TEXT,
        preview BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX idx_generations_enhancement_time ON dsp_ai.generations (enhancement_id, created_at DESC);
    CREATE INDEX idx_generations_user_time        ON dsp_ai.generations (user_id, created_at DESC);

    CREATE TABLE dsp_ai.briefings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        user_id TEXT NOT NULL,
        context_key TEXT NOT NULL,
        generated_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ,
        narrative_text TEXT NOT NULL,
        key_points JSONB,
        suggested_actions JSONB,
        render_hint TEXT NOT NULL,
        generation_id UUID NOT NULL REFERENCES dsp_ai.generations(id),
        UNIQUE (enhancement_id, user_id, context_key)
    );
    CREATE TABLE dsp_ai.rankings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        user_id TEXT NOT NULL,
        context_key TEXT NOT NULL,
        item_id TEXT NOT NULL,
        rank INT NOT NULL,
        score FLOAT NOT NULL,
        reason TEXT,
        generated_at TIMESTAMPTZ NOT NULL,
        generation_id UUID NOT NULL REFERENCES dsp_ai.generations(id)
    );
    CREATE INDEX idx_rankings_lookup ON dsp_ai.rankings (enhancement_id, user_id, context_key, rank);

    CREATE TABLE dsp_ai.item_enhancements (
        object_type TEXT NOT NULL,
        object_id TEXT NOT NULL,
        user_id TEXT,
        title_suggested TEXT,
        description_suggested TEXT,
        tags JSONB,
        kpi_suggestions JSONB,
        generated_at TIMESTAMPTZ NOT NULL,
        enhancement_id UUID NOT NULL REFERENCES dsp_ai.enhancements(id),
        generation_id UUID NOT NULL REFERENCES dsp_ai.generations(id),
        PRIMARY KEY (object_type, object_id, user_id)
    );

    CREATE TABLE dsp_ai.user_state (
        user_id TEXT PRIMARY KEY,
        last_visited_at TIMESTAMPTZ,
        last_briefed_at TIMESTAMPTZ,
        topics_of_interest JSONB,
        preferences JSONB,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE dsp_ai.studio_audit (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        action TEXT NOT NULL,
        enhancement_id UUID,
        author TEXT NOT NULL,
        before JSONB,
        after JSONB,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS dsp_ai CASCADE")
```

- [ ] **Step 2.2: Run migration in dev**

```bash
docker compose run --rm web alembic upgrade head
```

Expected: `010` shown as current head.

- [ ] **Step 2.3: Commit**

```bash
git add migrations/versions/010_dsp_ai_core.py
git commit -m "feat(dsp-ai): add dsp_ai.* Postgres schema (migration 010)"
```

---

## Task 3: Pydantic config models

**Files:**
- Create: `src/spec2sphere/dsp_ai/__init__.py` (empty)
- Create: `src/spec2sphere/dsp_ai/config.py`

- [ ] **Step 3.1: Write the config models**

```python
# src/spec2sphere/dsp_ai/config.py
"""Enhancement configuration models (Pydantic v2)."""
from __future__ import annotations
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field

class EnhancementKind(str, Enum):
    NARRATIVE = "narrative"
    RANKING = "ranking"
    ITEM_ENRICH = "item_enrich"
    ACTION = "action"
    BRIEFING = "briefing"

class RenderHint(str, Enum):
    NARRATIVE_TEXT = "narrative_text"
    RANKED_LIST = "ranked_list"
    CALLOUT = "callout"
    BUTTON = "button"
    BRIEF = "brief"
    CHART = "chart"

class EnhancementMode(str, Enum):
    BATCH = "batch"
    LIVE = "live"
    BOTH = "both"

class DataBinding(BaseModel):
    dsp_query: str           # raw SQL or DSL resolved by DspFetcher
    parameters: dict[str, Any] = Field(default_factory=dict)

class SemanticBinding(BaseModel):
    cypher: str              # Corporate Brain query
    parameters: dict[str, Any] = Field(default_factory=dict)

class ExternalBinding(BaseModel):
    searxng_query: str       # Jinja-templatable
    categories: list[str] = Field(default_factory=lambda: ["news"])
    max_results: int = 5

class AdaptiveRules(BaseModel):
    per_user: bool = False
    per_time: bool = False
    per_delta: bool = False
    delta_lookback_seconds: int = 86400

class EnhancementBindings(BaseModel):
    data: DataBinding
    semantic: SemanticBinding | None = None
    external: ExternalBinding | None = None

class EnhancementConfig(BaseModel):
    name: str
    kind: EnhancementKind
    mode: EnhancementMode = EnhancementMode.BATCH
    bindings: EnhancementBindings
    adaptive_rules: AdaptiveRules = Field(default_factory=AdaptiveRules)
    prompt_template: str     # Jinja
    output_schema: dict[str, Any] | None = None    # JSON Schema
    render_hint: RenderHint
    schedule: str | None = None                    # cron
    ttl_seconds: int = 600

class Enhancement(BaseModel):
    id: str
    version: int
    status: Literal["draft", "staging", "published", "archived"]
    author: str | None = None
    config: EnhancementConfig
```

- [ ] **Step 3.2: Write unit tests**

```python
# tests/dsp_ai/test_config.py
from spec2sphere.dsp_ai.config import (
    EnhancementConfig, EnhancementKind, EnhancementMode,
    DataBinding, EnhancementBindings, RenderHint,
)

def test_enhancement_config_minimal_valid():
    cfg = EnhancementConfig(
        name="test",
        kind=EnhancementKind.NARRATIVE,
        bindings=EnhancementBindings(data=DataBinding(dsp_query="SELECT 1")),
        prompt_template="hi",
        render_hint=RenderHint.NARRATIVE_TEXT,
    )
    assert cfg.mode == EnhancementMode.BATCH
    assert cfg.ttl_seconds == 600
    assert cfg.adaptive_rules.per_user is False

def test_enhancement_config_rejects_bad_kind():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        EnhancementConfig(
            name="test", kind="nonsense",
            bindings=EnhancementBindings(data=DataBinding(dsp_query="SELECT 1")),
            prompt_template="hi", render_hint=RenderHint.NARRATIVE_TEXT,
        )
```

- [ ] **Step 3.3: Run tests**

```bash
pytest tests/dsp_ai/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 3.4: Commit**

```bash
git add src/spec2sphere/dsp_ai/__init__.py src/spec2sphere/dsp_ai/config.py tests/dsp_ai/test_config.py
git commit -m "feat(dsp-ai): Enhancement Pydantic config models"
```

---

## Task 4: LISTEN/NOTIFY events module

**Files:**
- Create: `src/spec2sphere/dsp_ai/events.py`
- Create: `tests/dsp_ai/test_events.py`

- [ ] **Step 4.1: Write events helper**

```python
# src/spec2sphere/dsp_ai/events.py
"""Postgres LISTEN/NOTIFY wrapper.

Usage:
    await emit("enhancement_published", {"id": "..."})

    async for event in subscribe("briefing_generated"):
        handle(event)
"""
from __future__ import annotations
import asyncio, json
from typing import AsyncIterator, Any
import asyncpg
from spec2sphere.config import settings

_listeners: dict[str, asyncio.Queue] = {}
_listen_conn: asyncpg.Connection | None = None
_listen_task: asyncio.Task | None = None

async def emit(channel: str, payload: dict[str, Any]) -> None:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute("SELECT pg_notify($1, $2)", channel, json.dumps(payload))
    finally:
        await conn.close()

async def _listen_loop() -> None:
    global _listen_conn
    while True:
        try:
            _listen_conn = await asyncpg.connect(settings.postgres_dsn)
            async def _cb(_conn, _pid, channel, payload):
                q = _listeners.get(channel)
                if q is not None:
                    q.put_nowait(json.loads(payload))
            for chan in list(_listeners):
                await _listen_conn.add_listener(chan, _cb)
            while True:
                await asyncio.sleep(3600)
        except Exception:
            await asyncio.sleep(2)  # reconnect

async def subscribe(channel: str) -> AsyncIterator[dict[str, Any]]:
    global _listen_task
    q = _listeners.setdefault(channel, asyncio.Queue())
    if _listen_task is None or _listen_task.done():
        _listen_task = asyncio.create_task(_listen_loop())
    if _listen_conn is not None:
        try:
            await _listen_conn.add_listener(channel, _cb_wrapper(channel))
        except Exception:
            pass
    while True:
        yield await q.get()

def _cb_wrapper(channel: str):
    async def cb(_c, _p, _chan, payload):
        _listeners[channel].put_nowait(json.loads(payload))
    return cb
```

- [ ] **Step 4.2: Write round-trip test**

```python
# tests/dsp_ai/test_events.py
import asyncio, pytest
from spec2sphere.dsp_ai.events import emit, subscribe

@pytest.mark.asyncio
async def test_notify_round_trip():
    async def consume():
        async for ev in subscribe("test_channel"):
            return ev
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.2)  # give LISTEN time to attach
    await emit("test_channel", {"hello": "world"})
    result = await asyncio.wait_for(task, timeout=2.0)
    assert result == {"hello": "world"}
```

- [ ] **Step 4.3: Run test against compose postgres**

```bash
docker compose up -d postgres
pytest tests/dsp_ai/test_events.py -v
```

Expected: 1 passed.

- [ ] **Step 4.4: Commit**

```bash
git add src/spec2sphere/dsp_ai/events.py tests/dsp_ai/test_events.py
git commit -m "feat(dsp-ai): Postgres LISTEN/NOTIFY event bus"
```

---

## Task 5: Neo4j Brain client + schema bootstrap

**Files:**
- Create: `src/spec2sphere/dsp_ai/brain/__init__.py` (empty)
- Create: `src/spec2sphere/dsp_ai/brain/client.py`
- Create: `src/spec2sphere/dsp_ai/brain/schema.py`
- Create: `tests/dsp_ai/test_brain_client.py`

- [ ] **Step 5.1: Brain client wrapper**

```python
# src/spec2sphere/dsp_ai/brain/client.py
"""Neo4j driver singleton + async helpers."""
from __future__ import annotations
import os
from neo4j import AsyncGraphDatabase, AsyncDriver

_driver: AsyncDriver | None = None

def _url() -> str:
    return os.environ.get("NEO4J_URL", "bolt://neo4j:7687")

def _auth() -> tuple[str, str]:
    return ("neo4j", os.environ["NEO4J_PASSWORD"])

async def driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(_url(), auth=_auth())
    return _driver

async def run(cypher: str, **params):
    d = await driver()
    async with d.session() as s:
        result = await s.run(cypher, **params)
        return [r async for r in result]

async def close() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
```

- [ ] **Step 5.2: Schema bootstrap**

```python
# src/spec2sphere/dsp_ai/brain/schema.py
from .client import run

CONSTRAINTS = [
    "CREATE CONSTRAINT dsp_object_id IF NOT EXISTS FOR (n:DspObject) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT column_id IF NOT EXISTS FOR (n:Column) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT domain_name IF NOT EXISTS FOR (n:Domain) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT glossary_term IF NOT EXISTS FOR (n:Glossary) REQUIRE n.term IS UNIQUE",
    "CREATE CONSTRAINT user_email IF NOT EXISTS FOR (n:User) REQUIRE n.email IS UNIQUE",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (n:Topic) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:Event) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT enhancement_id IF NOT EXISTS FOR (n:Enhancement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT generation_id IF NOT EXISTS FOR (n:Generation) REQUIRE n.id IS UNIQUE",
]
INDEXES = [
    "CREATE INDEX dsp_object_customer IF NOT EXISTS FOR (n:DspObject) ON (n.customer)",
    "CREATE INDEX event_ts IF NOT EXISTS FOR (n:Event) ON (n.ts)",
]

async def bootstrap() -> None:
    for c in CONSTRAINTS + INDEXES:
        await run(c)
```

- [ ] **Step 5.3: Integration test**

```python
# tests/dsp_ai/test_brain_client.py
import pytest
from spec2sphere.dsp_ai.brain import client, schema

@pytest.mark.asyncio
async def test_bootstrap_creates_constraints():
    await schema.bootstrap()
    rows = await client.run("SHOW CONSTRAINTS")
    names = {r["name"] for r in rows}
    assert "dsp_object_id" in names
    assert "generation_id" in names

@pytest.mark.asyncio
async def test_write_and_read_dsp_object():
    await client.run("MATCH (n:DspObject {id: 'test.foo'}) DETACH DELETE n")
    await client.run(
        "CREATE (n:DspObject {id: $id, kind: 'Table', customer: 'horvath'})",
        id="test.foo",
    )
    rows = await client.run("MATCH (n:DspObject {id: $id}) RETURN n.customer AS c", id="test.foo")
    assert rows[0]["c"] == "horvath"
```

- [ ] **Step 5.4: Run tests**

```bash
docker compose up -d neo4j
export NEO4J_URL=bolt://localhost:7687 NEO4J_PASSWORD=$(grep NEO4J_PASSWORD .env | cut -d= -f2)
pytest tests/dsp_ai/test_brain_client.py -v
```

Expected: 2 passed.

- [ ] **Step 5.5: Commit**

```bash
git add src/spec2sphere/dsp_ai/brain/ tests/dsp_ai/test_brain_client.py
git commit -m "feat(dsp-ai): Neo4j brain client + schema bootstrap"
```

---

## Task 6: Brain feeders (schema_semantic + dsp_data)

**Files:**
- Create: `src/spec2sphere/dsp_ai/brain/feeders/__init__.py` (empty)
- Create: `src/spec2sphere/dsp_ai/brain/feeders/schema_semantic.py`
- Create: `src/spec2sphere/dsp_ai/brain/feeders/dsp_data.py`
- Create: `tests/dsp_ai/test_feeders.py`
- Modify: `src/spec2sphere/scanner/output.py` — emit `pg_notify('scan_completed', ...)` at end

- [ ] **Step 6.1: schema_semantic feeder**

```python
# src/spec2sphere/dsp_ai/brain/feeders/schema_semantic.py
"""Populates DspObject, Column, HAS_COLUMN, and optional Domain/Glossary edges
from the Spec2Sphere scanner's JSON output.

Runs on pg_notify('scan_completed', {customer}) and on cron BRAIN_FEEDER_CRON.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from ..client import run

async def feed_from_graph_json(customer: str, graph_path: Path) -> dict[str, int]:
    data = json.loads(graph_path.read_text())
    counts = {"objects": 0, "columns": 0}
    for obj in data.get("objects", []):
        await run(
            """
            MERGE (o:DspObject {id: $id})
            SET o.kind = $kind, o.customer = $customer
            """,
            id=obj["id"], kind=obj.get("kind", "Unknown"), customer=customer,
        )
        counts["objects"] += 1
        for col in obj.get("columns", []):
            col_id = f"{obj['id']}.{col['name']}"
            await run(
                """
                MATCH (o:DspObject {id: $oid})
                MERGE (c:Column {id: $cid})
                SET c.dtype = $dtype, c.nullable = $nullable
                MERGE (o)-[:HAS_COLUMN]->(c)
                """,
                oid=obj["id"], cid=col_id,
                dtype=col.get("dtype", "?"), nullable=col.get("nullable", True),
            )
            counts["columns"] += 1
    return counts
```

- [ ] **Step 6.2: dsp_data feeder (skeleton)**

```python
# src/spec2sphere/dsp_ai/brain/feeders/dsp_data.py
"""Creates Event nodes for DSP data changes (row-count deltas, schema changes).

Runs hourly via Celery Beat (BRAIN_FEEDER_CRON is the schema cadence; this one
uses its own 1h cadence added in schedules.py).
"""
from __future__ import annotations
import uuid, datetime as dt
from ..client import run

async def record_row_count_delta(object_id: str, old: int, new: int) -> str:
    eid = str(uuid.uuid4())
    await run(
        """
        MERGE (o:DspObject {id: $oid})
        CREATE (e:Event {id: $eid, kind: 'data_change', ts: datetime($ts),
                         old_value: $old, new_value: $new, metric: 'row_count'})
        MERGE (o)-[:CHANGED_AT]->(e)
        """,
        oid=object_id, eid=eid, ts=dt.datetime.utcnow().isoformat(),
        old=old, new=new,
    )
    return eid
```

- [ ] **Step 6.3: Emit scan_completed from scanner/output.py**

Find the end of `write_graph(...)` in `src/spec2sphere/scanner/output.py`. After the `json.dumps(...)` write, append:

```python
from spec2sphere.dsp_ai.events import emit
import asyncio
try:
    asyncio.get_event_loop().run_until_complete(
        emit("scan_completed", {"customer": customer, "graph_path": str(graph_file)})
    )
except RuntimeError:  # if inside async context already
    asyncio.create_task(
        emit("scan_completed", {"customer": customer, "graph_path": str(graph_file)})
    )
```

Use a module-level function to keep the diff minimal and recoverable. Keep the existing scanner API unchanged.

- [ ] **Step 6.4: Write feeder tests**

```python
# tests/dsp_ai/test_feeders.py
import json, tempfile, pytest
from pathlib import Path
from spec2sphere.dsp_ai.brain import schema, client
from spec2sphere.dsp_ai.brain.feeders.schema_semantic import feed_from_graph_json

@pytest.fixture(autouse=True)
async def clean_brain():
    await schema.bootstrap()
    await client.run("MATCH (n) DETACH DELETE n")

@pytest.mark.asyncio
async def test_feed_from_graph_json_creates_objects_and_columns(tmp_path: Path):
    graph = {"objects": [
        {"id": "space.sales.daily", "kind": "View",
         "columns": [{"name": "region", "dtype": "TEXT", "nullable": False},
                     {"name": "revenue", "dtype": "NUMERIC", "nullable": True}]},
    ]}
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(graph))
    counts = await feed_from_graph_json("horvath", p)
    assert counts == {"objects": 1, "columns": 2}
    rows = await client.run("MATCH (o:DspObject)-[:HAS_COLUMN]->(c) RETURN count(c) AS n")
    assert rows[0]["n"] == 2
```

- [ ] **Step 6.5: Run + commit**

```bash
pytest tests/dsp_ai/test_feeders.py -v
git add src/spec2sphere/dsp_ai/brain/feeders/ src/spec2sphere/scanner/output.py tests/dsp_ai/test_feeders.py
git commit -m "feat(dsp-ai): Brain feeders (schema_semantic + dsp_data)"
```

---

## Task 7: Engine stages (Resolve, Gather, AdaptiveRules, Compose, RunLLM, Shape, Dispatch)

**Files:** one file per stage under `src/spec2sphere/dsp_ai/stages/`, plus `engine.py` that chains them.

- [ ] **Step 7.1: Stage 1 — Resolve**

```python
# src/spec2sphere/dsp_ai/stages/resolve.py
"""Stage 1: load enhancement config from Postgres."""
from __future__ import annotations
import json
import asyncpg
from spec2sphere.config import settings
from ..config import Enhancement, EnhancementConfig

async def resolve(enhancement_id: str) -> Enhancement:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT id::text AS id, version, status, author, config "
            "FROM dsp_ai.enhancements WHERE id = $1",
            enhancement_id,
        )
        if row is None:
            raise LookupError(f"enhancement {enhancement_id} not found")
        return Enhancement(
            id=row["id"],
            version=row["version"],
            status=row["status"],
            author=row["author"],
            config=EnhancementConfig.model_validate(json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]),
        )
    finally:
        await conn.close()
```

- [ ] **Step 7.2: Stage 2 — Gather**

```python
# src/spec2sphere/dsp_ai/stages/gather.py
"""Stage 2: parallel context fetchers."""
from __future__ import annotations
import asyncio, os, httpx, asyncpg
from dataclasses import dataclass, field
from typing import Any
from ..config import Enhancement
from ..brain.client import run as brain_run
from spec2sphere.config import settings

@dataclass
class GatheredContext:
    dsp_data: list[dict] = field(default_factory=list)
    brain_nodes: list[dict] = field(default_factory=list)
    external_info: list[dict] = field(default_factory=list)
    user_state: dict[str, Any] = field(default_factory=dict)
    quality_warnings: list[str] = field(default_factory=list)

async def _dsp_fetch(enh: Enhancement) -> list[dict]:
    conn = await asyncpg.connect(settings.dsp_dsn)
    try:
        rows = await conn.fetch(enh.config.bindings.data.dsp_query, *enh.config.bindings.data.parameters.values())
        return [dict(r) for r in rows]
    finally:
        await conn.close()

async def _brain_fetch(enh: Enhancement) -> list[dict]:
    sb = enh.config.bindings.semantic
    if sb is None:
        return []
    return await brain_run(sb.cypher, **sb.parameters)

async def _external_fetch(enh: Enhancement, context: dict) -> list[dict]:
    eb = enh.config.bindings.external
    if eb is None or os.environ.get("SEARXNG_ENABLED", "true") != "true":
        return []
    url = os.environ.get("SEARXNG_URL", "http://searxng:8080/search")
    from jinja2 import Template
    query = Template(eb.searxng_query).render(**context)
    async with httpx.AsyncClient(timeout=8.0) as c:
        resp = await c.get(url, params={"q": query, "format": "json", "categories": ",".join(eb.categories)})
        data = resp.json() if resp.status_code == 200 else {}
        return data.get("results", [])[:eb.max_results]

async def _user_state(user_id: str) -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT last_visited_at, last_briefed_at, topics_of_interest, preferences "
            "FROM dsp_ai.user_state WHERE user_id = $1", user_id,
        )
        return dict(row) if row else {}
    finally:
        await conn.close()

async def gather(enh: Enhancement, user_id: str | None, context_hints: dict) -> GatheredContext:
    ctx = GatheredContext()
    tasks = {
        "dsp": asyncio.create_task(_dsp_fetch(enh)),
        "brain": asyncio.create_task(_brain_fetch(enh)),
        "external": asyncio.create_task(_external_fetch(enh, context_hints)),
    }
    if user_id:
        tasks["user"] = asyncio.create_task(_user_state(user_id))

    for name, task in tasks.items():
        try:
            result = await asyncio.wait_for(task, timeout=10.0)
            if name == "dsp": ctx.dsp_data = result
            elif name == "brain": ctx.brain_nodes = result
            elif name == "external": ctx.external_info = result
            elif name == "user": ctx.user_state = result
        except Exception:
            ctx.quality_warnings.append(f"{name}_context_missing")
    return ctx
```

- [ ] **Step 7.3: Stage 3 — AdaptiveRules**

```python
# src/spec2sphere/dsp_ai/stages/adaptive_rules.py
"""Stage 3: pure-Python filter/weight/re-rank on gathered context.

Deterministic, no LLM. Tests should pin behavior.
"""
from __future__ import annotations
import datetime as dt
from ..config import Enhancement
from .gather import GatheredContext

def apply(enh: Enhancement, ctx: GatheredContext, user_id: str | None, now: dt.datetime) -> GatheredContext:
    rules = enh.config.adaptive_rules
    if rules.per_delta and user_id and ctx.user_state.get("last_visited_at"):
        lv = ctx.user_state["last_visited_at"]
        # Keep brain Events newer than lv, and flag rows in dsp_data that changed since lv
        ctx.brain_nodes = [
            n for n in ctx.brain_nodes
            if not (isinstance(n, dict) and n.get("ts") and n["ts"] < lv)
        ]
    if rules.per_time:
        hour = now.hour
        ctx.user_state["time_bucket"] = (
            "morning" if 5 <= hour < 12 else
            "afternoon" if 12 <= hour < 17 else
            "evening" if 17 <= hour < 22 else
            "night"
        )
    return ctx
```

- [ ] **Step 7.4: Stage 4 — ComposePrompt**

```python
# src/spec2sphere/dsp_ai/stages/compose_prompt.py
"""Stage 4: Jinja render of prompt_template with gathered context."""
from __future__ import annotations
from jinja2 import Environment, StrictUndefined
from ..config import Enhancement
from .gather import GatheredContext

_env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)

def compose(enh: Enhancement, ctx: GatheredContext, user_id: str | None) -> str:
    tpl = _env.from_string(enh.config.prompt_template)
    return tpl.render(
        dsp_data=ctx.dsp_data,
        brain_nodes=ctx.brain_nodes,
        external_info=ctx.external_info,
        user_state=ctx.user_state,
        user_id=user_id,
        render_hint=enh.config.render_hint.value,
    )
```

- [ ] **Step 7.5: Stage 5 — RunLLM**

```python
# src/spec2sphere/dsp_ai/stages/run_llm.py
"""Stage 5: delegate to quality_router for model selection and call.

Returns (shaped_output, metadata) — metadata carries model/tokens/latency/cost
used by Stage 6 + 7 for provenance.
"""
from __future__ import annotations
import time
from typing import Any
from ..config import Enhancement
from spec2sphere.llm.quality_router import resolve_and_call

async def run(enh: Enhancement, prompt: str, data_in_context: bool = False) -> tuple[Any, dict]:
    t0 = time.time()
    out, meta = await resolve_and_call(
        action=enh.config.name,
        prompt=prompt,
        data_in_context=data_in_context,
        schema=enh.config.output_schema,
    )
    return out, {**meta, "latency_ms": int((time.time() - t0) * 1000)}
```

Note: `resolve_and_call` must be added to `quality_router.py` in Task 10. Placeholder for now.

- [ ] **Step 7.6: Stage 6 — ShapeOutput**

```python
# src/spec2sphere/dsp_ai/stages/shape_output.py
"""Stage 6: normalize output and attach provenance."""
from __future__ import annotations
import hashlib, uuid
from typing import Any
from ..config import Enhancement
from .gather import GatheredContext

def shape(enh: Enhancement, raw_output: Any, meta: dict, ctx: GatheredContext, prompt: str) -> dict:
    gen_id = str(uuid.uuid4())
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    input_ids = [n.get("id") for n in ctx.brain_nodes if isinstance(n, dict) and n.get("id")]
    return {
        "generation_id": gen_id,
        "enhancement_id": enh.id,
        "render_hint": enh.config.render_hint.value,
        "content": raw_output,
        "quality_warnings": ctx.quality_warnings,
        "provenance": {
            "prompt_hash": prompt_hash,
            "model": meta.get("model"),
            "quality_level": meta.get("quality_level"),
            "latency_ms": meta.get("latency_ms"),
            "tokens_in": meta.get("tokens_in"),
            "tokens_out": meta.get("tokens_out"),
            "cost_usd": meta.get("cost_usd"),
            "input_ids": input_ids,
        },
    }
```

- [ ] **Step 7.7: Stage 7 — Dispatch**

```python
# src/spec2sphere/dsp_ai/stages/dispatch.py
"""Stage 7: write to dsp_ai.* (batch) or return JSON (live)."""
from __future__ import annotations
import json
import asyncpg
from spec2sphere.config import settings
from ..config import Enhancement, EnhancementMode, RenderHint
from ..events import emit

async def _insert_generation(conn, enh: Enhancement, user_id: str | None, context_key: str | None,
                              shaped: dict, preview: bool) -> None:
    prov = shaped["provenance"]
    await conn.execute(
        """
        INSERT INTO dsp_ai.generations
            (id, enhancement_id, user_id, context_key, prompt_hash, input_ids,
             model, quality_level, latency_ms, tokens_in, tokens_out, cost_usd,
             cached, quality_warnings, preview)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12, $13, $14::jsonb, $15)
        """,
        shaped["generation_id"], enh.id, user_id, context_key,
        prov["prompt_hash"], json.dumps(prov.get("input_ids", [])),
        prov.get("model") or "unknown", prov.get("quality_level") or "Q3",
        prov.get("latency_ms") or 0, prov.get("tokens_in"), prov.get("tokens_out"),
        prov.get("cost_usd"), False, json.dumps(shaped.get("quality_warnings", [])), preview,
    )

async def _write_briefing(conn, enh: Enhancement, user_id: str, context_key: str, shaped: dict) -> None:
    c = shaped["content"] if isinstance(shaped["content"], dict) else {"narrative_text": str(shaped["content"])}
    await conn.execute(
        """
        INSERT INTO dsp_ai.briefings
            (enhancement_id, user_id, context_key, generated_at, narrative_text,
             key_points, suggested_actions, render_hint, generation_id)
        VALUES ($1::uuid, $2, $3, NOW(), $4, $5::jsonb, $6::jsonb, $7, $8::uuid)
        ON CONFLICT (enhancement_id, user_id, context_key) DO UPDATE SET
            generated_at = EXCLUDED.generated_at,
            narrative_text = EXCLUDED.narrative_text,
            key_points = EXCLUDED.key_points,
            suggested_actions = EXCLUDED.suggested_actions,
            generation_id = EXCLUDED.generation_id
        """,
        enh.id, user_id, context_key,
        c.get("narrative_text", ""),
        json.dumps(c.get("key_points", [])),
        json.dumps(c.get("suggested_actions", [])),
        enh.config.render_hint.value, shaped["generation_id"],
    )

async def dispatch(enh: Enhancement, shaped: dict, *, mode: EnhancementMode,
                   user_id: str | None, context_key: str | None, preview: bool = False) -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await _insert_generation(conn, enh, user_id, context_key, shaped, preview)
        if mode in (EnhancementMode.BATCH, EnhancementMode.BOTH) and not preview:
            if enh.config.render_hint in (RenderHint.NARRATIVE_TEXT, RenderHint.BRIEF, RenderHint.CALLOUT):
                await _write_briefing(conn, enh, user_id or "_global", context_key or "default", shaped)
            # ranked_list + item_enrich writes added in Session B
            await emit("briefing_generated", {
                "enhancement_id": enh.id, "user_id": user_id, "context_key": context_key,
            })
        return shaped
    finally:
        await conn.close()
```

- [ ] **Step 7.8: engine.py chaining**

```python
# src/spec2sphere/dsp_ai/engine.py
"""7-stage engine orchestrator."""
from __future__ import annotations
import datetime as dt
from typing import Any
from .config import Enhancement, EnhancementMode
from .stages.resolve import resolve
from .stages.gather import gather
from .stages.adaptive_rules import apply as apply_rules
from .stages.compose_prompt import compose
from .stages.run_llm import run as run_llm
from .stages.shape_output import shape
from .stages.dispatch import dispatch

async def run_engine(enhancement_id: str, *, user_id: str | None = None,
                     context_hints: dict[str, Any] | None = None,
                     context_key: str | None = None,
                     mode_override: EnhancementMode | None = None,
                     preview: bool = False) -> dict:
    enh = await resolve(enhancement_id)
    mode = mode_override or enh.config.mode
    ctx = await gather(enh, user_id, context_hints or {})
    ctx = apply_rules(enh, ctx, user_id, dt.datetime.utcnow())
    prompt = compose(enh, ctx, user_id)
    raw, meta = await run_llm(enh, prompt)
    shaped = shape(enh, raw, meta, ctx, prompt)
    return await dispatch(enh, shaped, mode=mode, user_id=user_id,
                          context_key=context_key, preview=preview)
```

- [ ] **Step 7.9: Unit tests per stage**

Write `tests/dsp_ai/test_engine_stages.py` with one test class per stage, mocking dependencies. Key tests:

- Resolve raises LookupError on missing id
- Gather returns quality_warnings when DSP connection fails
- AdaptiveRules filters brain_nodes by ts < last_visited_at when per_delta=True
- Compose renders a simple template with placeholders
- ShapeOutput hashes prompt correctly and collects input_ids

- [ ] **Step 7.10: Commit**

```bash
git add src/spec2sphere/dsp_ai/stages/ src/spec2sphere/dsp_ai/engine.py tests/dsp_ai/test_engine_stages.py
git commit -m "feat(dsp-ai): 7-stage engine with per-stage unit tests"
```

---

## Task 8: Cache + Live adapter

**Files:**
- Create: `src/spec2sphere/dsp_ai/cache.py`
- Create: `src/spec2sphere/dsp_ai/adapters/__init__.py` (empty)
- Create: `src/spec2sphere/dsp_ai/adapters/live.py`
- Create: `src/spec2sphere/dsp_ai/service.py`
- Create: `tests/dsp_ai/test_live_adapter.py`

- [ ] **Step 8.1: Redis cache wrapper**

```python
# src/spec2sphere/dsp_ai/cache.py
"""Enhancement output cache (Redis)."""
from __future__ import annotations
import hashlib, json, os
from typing import Any
from redis.asyncio import Redis

_redis: Redis | None = None

def _get() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    return _redis

def key_for(enhancement_id: str, user_id: str | None, context_hints: dict) -> str:
    h = hashlib.sha256(json.dumps(context_hints, sort_keys=True).encode()).hexdigest()[:16]
    return f"dspai:enhance:{enhancement_id}:{user_id or '_'}:{h}"

async def get(k: str) -> dict | None:
    v = await _get().get(k)
    return json.loads(v) if v else None

async def set_(k: str, v: dict, ttl: int) -> None:
    await _get().set(k, json.dumps(v), ex=ttl)

async def invalidate_prefix(prefix: str) -> int:
    r = _get()
    cursor = 0
    total = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=f"{prefix}*", count=200)
        if keys:
            await r.delete(*keys)
            total += len(keys)
        if cursor == 0:
            break
    return total
```

- [ ] **Step 8.2: Live adapter router**

```python
# src/spec2sphere/dsp_ai/adapters/live.py
"""FastAPI router for live adapter: /v1/enhance, /v1/healthz, /v1/readyz."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Any
from ..engine import run_engine
from ..config import EnhancementMode
from .. import cache

router = APIRouter()

class EnhanceRequest(BaseModel):
    user: str | None = None
    context_hints: dict[str, Any] = {}
    context_key: str | None = None
    preview: bool = False

@router.post("/v1/enhance/{enhancement_id}")
async def enhance(enhancement_id: str, body: EnhanceRequest = Body(...)) -> dict:
    k = cache.key_for(enhancement_id, body.user, body.context_hints)
    if not body.preview:
        cached = await cache.get(k)
        if cached:
            cached["_cached"] = True
            return cached
    try:
        result = await run_engine(
            enhancement_id,
            user_id=body.user,
            context_hints=body.context_hints,
            context_key=body.context_key,
            mode_override=EnhancementMode.LIVE if body.preview else None,
            preview=body.preview,
        )
    except LookupError:
        raise HTTPException(404, "enhancement not found")
    if not body.preview:
        await cache.set_(k, result, ttl=600)
    return result

@router.get("/v1/healthz")
async def healthz() -> dict:
    return {"status": "ok"}

@router.get("/v1/readyz")
async def readyz() -> dict:
    warnings: list[str] = []
    # best-effort pings; missing pieces are warnings, not failures
    try:
        import asyncpg
        from spec2sphere.config import settings
        conn = await asyncpg.connect(settings.postgres_dsn); await conn.close()
    except Exception:
        warnings.append("postgres")
    return {"status": "ok", "warnings": warnings}
```

- [ ] **Step 8.3: Service entry**

```python
# src/spec2sphere/dsp_ai/service.py
"""dsp-ai FastAPI service — live adapter only (batch runs under Celery)."""
import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .adapters.live import router as live_router

def create_app() -> FastAPI:
    app = FastAPI(title="dsp-ai")
    origins = [o.strip() for o in os.environ.get("WIDGET_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],  # dev default
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(live_router)
    return app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 8.4: Contract tests**

```python
# tests/dsp_ai/test_live_adapter.py
import pytest
from httpx import AsyncClient, ASGITransport
from spec2sphere.dsp_ai.service import app

@pytest.mark.asyncio
async def test_healthz():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/healthz")
        assert r.status_code == 200 and r.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_enhance_404_on_unknown_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/enhance/00000000-0000-0000-0000-000000000000", json={})
        assert r.status_code == 404
```

- [ ] **Step 8.5: Run + commit**

```bash
pytest tests/dsp_ai/test_live_adapter.py -v
git add src/spec2sphere/dsp_ai/cache.py src/spec2sphere/dsp_ai/adapters/ src/spec2sphere/dsp_ai/service.py tests/dsp_ai/test_live_adapter.py
git commit -m "feat(dsp-ai): live adapter + Redis cache + service entry"
```

---

## Task 9: Batch adapter (Celery)

**Files:**
- Create: `src/spec2sphere/dsp_ai/adapters/batch.py`
- Modify: `src/spec2sphere/tasks/celery_app.py` — add `ai-batch` queue routing
- Modify: `src/spec2sphere/tasks/schedules.py` — add Beat entries for BATCH_CRON + brain_feeder_hourly
- Create: `tests/dsp_ai/test_batch_adapter.py`

- [ ] **Step 9.1: Celery task**

```python
# src/spec2sphere/dsp_ai/adapters/batch.py
"""Batch adapter — Celery tasks that run enhancements on schedule / event."""
from __future__ import annotations
import asyncio
import asyncpg
from celery import shared_task
from spec2sphere.config import settings
from ..engine import run_engine

async def _active_users(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT user_id FROM dsp_ai.user_state "
        "WHERE last_visited_at > NOW() - INTERVAL '14 days'"
    )
    return [r["user_id"] for r in rows] or ["_default"]

async def _published_batch_enhancements(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT id::text FROM dsp_ai.enhancements "
        "WHERE status = 'published' AND (config->>'mode' IN ('batch', 'both'))"
    )
    return [r["id"] for r in rows]

@shared_task(name="spec2sphere.dsp_ai.run_batch_enhancements", queue="ai-batch")
def run_batch_enhancements() -> dict:
    return asyncio.run(_run_batch_enhancements_async())

async def _run_batch_enhancements_async() -> dict:
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        enh_ids = await _published_batch_enhancements(conn)
        users = await _active_users(conn)
    finally:
        await conn.close()

    ran = 0
    for eid in enh_ids:
        for u in users:
            try:
                await run_engine(eid, user_id=u, context_hints={}, context_key="default")
                ran += 1
            except Exception:
                continue
    return {"enhancements": len(enh_ids), "users": len(users), "ran": ran}
```

- [ ] **Step 9.2: Register queue in celery_app.py**

Add to `task_routes`:

```python
"spec2sphere.dsp_ai.run_batch_enhancements": {"queue": "ai-batch"},
```

- [ ] **Step 9.3: Add Beat schedules**

In `src/spec2sphere/tasks/schedules.py`, append:

```python
# Morning Brief — batch generation
BEAT_SCHEDULE["ai-batch-morning"] = {
    "task": "spec2sphere.dsp_ai.run_batch_enhancements",
    "schedule": crontab.from_env_or_default("BATCH_CRON", "0 6 * * 1-5"),
    "options": {"priority": 5, "queue": "ai-batch"},
}
```

(Implement `crontab.from_env_or_default` as a small helper or inline the cron parse.)

- [ ] **Step 9.4: Integration test**

```python
# tests/dsp_ai/test_batch_adapter.py
import json, uuid, pytest, asyncpg
from spec2sphere.config import settings
from spec2sphere.dsp_ai.adapters.batch import _run_batch_enhancements_async

@pytest.mark.asyncio
async def test_batch_skips_when_no_published(clean_db):
    result = await _run_batch_enhancements_async()
    assert result["ran"] == 0

@pytest.mark.asyncio
async def test_batch_runs_one_published_enhancement(seed_enhancement, mock_llm, mock_dsp):
    result = await _run_batch_enhancements_async()
    assert result["ran"] >= 1
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        count = await conn.fetchval("SELECT count(*) FROM dsp_ai.briefings")
        assert count >= 1
    finally:
        await conn.close()
```

(fixtures `clean_db`, `seed_enhancement`, `mock_llm`, `mock_dsp` go into `tests/dsp_ai/conftest.py` — create them as needed.)

- [ ] **Step 9.5: Run + commit**

```bash
pytest tests/dsp_ai/test_batch_adapter.py -v
git add src/spec2sphere/dsp_ai/adapters/batch.py src/spec2sphere/tasks/ tests/dsp_ai/test_batch_adapter.py
git commit -m "feat(dsp-ai): batch adapter + Celery Beat schedules"
```

---

## Task 10: Extend quality_router with programmatic API

**Files:**
- Modify: `src/spec2sphere/llm/quality_router.py`

- [ ] **Step 10.1: Add `resolve_and_call`**

```python
# Append to src/spec2sphere/llm/quality_router.py

async def resolve_and_call(
    action: str,
    prompt: str,
    *,
    data_in_context: bool = False,
    schema: dict | None = None,
) -> tuple[dict | str, dict]:
    """Resolve quality level + model, call $LLM_ENDPOINT, return (output, meta).

    meta keys: model, quality_level, tokens_in, tokens_out, cost_usd, latency_ms (set by caller).
    """
    import os, httpx, time
    router = _qr()
    quality = router.resolve_quality(action)
    model = router.resolve(action, data_in_context=data_in_context)
    endpoint = os.environ.get("LLM_ENDPOINT")
    api_key = os.environ.get("LLM_API_KEY", "")

    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if schema is not None:
        payload["response_format"] = {"type": "json_schema", "json_schema": {"name": action, "schema": schema}}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    t0 = time.time()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.post(f"{endpoint.rstrip('/')}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    try:
        import json as _json
        parsed = _json.loads(content) if schema else content
    except Exception:
        parsed = {"raw": content}

    meta = {
        "model": model,
        "quality_level": quality,
        "tokens_in": usage.get("prompt_tokens"),
        "tokens_out": usage.get("completion_tokens"),
        "cost_usd": None,  # priced later; keep None in v1
    }
    return parsed, meta
```

- [ ] **Step 10.2: Smoke test**

```python
# tests/dsp_ai/test_quality_router_api.py
import pytest, respx, httpx
from spec2sphere.llm.quality_router import resolve_and_call

@pytest.mark.asyncio
async def test_resolve_and_call_returns_parsed(monkeypatch):
    monkeypatch.setenv("LLM_ENDPOINT", "http://fake/v1")
    import os; os.environ["LLM_ENDPOINT"] = "http://fake/v1"
    with respx.mock(base_url="http://fake/v1") as m:
        m.post("/chat/completions").respond(200, json={
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        out, meta = await resolve_and_call("test_action", "hello", schema={"type":"object"})
        assert out == {"ok": True}
        assert meta["tokens_in"] == 10 and meta["tokens_out"] == 5
```

- [ ] **Step 10.3: Commit**

```bash
git add src/spec2sphere/llm/quality_router.py tests/dsp_ai/test_quality_router_api.py
git commit -m "feat(llm): programmatic resolve_and_call API for dsp-ai"
```

---

## Task 11: AI Studio routes + templates

**Files:**
- Create: `src/spec2sphere/web/ai_studio/__init__.py` (empty)
- Create: `src/spec2sphere/web/ai_studio/routes.py`
- Create: `src/spec2sphere/web/templates/partials/ai_studio.html`
- Create: `src/spec2sphere/web/templates/partials/ai_studio_editor.html`
- Modify: `src/spec2sphere/web/templates/base.html` — add nav entry
- Modify: `src/spec2sphere/app.py` — mount router
- Modify: `src/spec2sphere/modules.py` — register module
- Create: `tests/dsp_ai/test_studio_routes.py`

- [ ] **Step 11.1: Routes — list / create / edit / preview / publish**

```python
# src/spec2sphere/web/ai_studio/routes.py
"""AI Studio web routes (author-facing)."""
from __future__ import annotations
import json, os, uuid
from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import asyncpg, httpx
from spec2sphere.config import settings
from spec2sphere.web.dependencies import get_templates, get_current_user  # existing deps

router = APIRouter(prefix="/ai-studio", tags=["ai-studio"])

def _is_author(user) -> bool:
    allowlist = [e.strip().lower() for e in os.environ.get("STUDIO_AUTHOR_EMAILS", "").split(",") if e.strip()]
    return not allowlist or user.email.lower() in allowlist

@router.get("/", response_class=HTMLResponse)
async def list_enhancements(request: Request, user = Depends(get_current_user)):
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        rows = await conn.fetch(
            "SELECT id::text, name, kind, version, status, updated_at "
            "FROM dsp_ai.enhancements ORDER BY updated_at DESC"
        )
    finally:
        await conn.close()
    return get_templates().TemplateResponse(
        request, "partials/ai_studio.html",
        {"enhancements": rows, "is_author": _is_author(user)},
    )

@router.get("/{id}/edit", response_class=HTMLResponse)
async def edit(request: Request, id: str, user = Depends(get_current_user)):
    if not _is_author(user): raise HTTPException(403)
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT id::text, name, kind, version, status, config FROM dsp_ai.enhancements WHERE id = $1",
            id,
        )
    finally:
        await conn.close()
    if row is None: raise HTTPException(404)
    return get_templates().TemplateResponse(
        request, "partials/ai_studio_editor.html",
        {"enh": dict(row), "config_json": json.dumps(dict(row)["config"], indent=2)},
    )

@router.post("/")
async def create(name: str = Form(...), kind: str = Form(...), user = Depends(get_current_user)):
    if not _is_author(user): raise HTTPException(403)
    new_id = str(uuid.uuid4())
    default_config = {
        "name": name, "kind": kind, "mode": "batch",
        "bindings": {"data": {"dsp_query": "SELECT 1", "parameters": {}}},
        "adaptive_rules": {"per_user": False, "per_time": False, "per_delta": False},
        "prompt_template": "You are a helpful assistant. Context: {{ dsp_data }}",
        "render_hint": "narrative_text",
        "ttl_seconds": 600,
    }
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author) "
            "VALUES ($1::uuid, $2, $3, $4::jsonb, $5)",
            new_id, name, kind, json.dumps(default_config), user.email,
        )
    finally:
        await conn.close()
    return RedirectResponse(f"/ai-studio/{new_id}/edit", status_code=303)

@router.post("/{id}/preview")
async def preview(id: str, body: dict, user = Depends(get_current_user)):
    if not _is_author(user): raise HTTPException(403)
    dsp_ai_base = os.environ.get("DSPAI_URL", "http://dsp-ai:8000")
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(f"{dsp_ai_base}/v1/enhance/{id}", json={**body, "preview": True})
    return JSONResponse(resp.json(), status_code=resp.status_code)

@router.post("/{id}/publish")
async def publish(id: str, user = Depends(get_current_user)):
    if not _is_author(user): raise HTTPException(403)
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        await conn.execute(
            "UPDATE dsp_ai.enhancements SET status='published', updated_at=NOW() WHERE id=$1::uuid", id,
        )
        await conn.execute(
            "INSERT INTO dsp_ai.studio_audit (action, enhancement_id, author) VALUES ($1, $2::uuid, $3)",
            "publish", id, user.email,
        )
    finally:
        await conn.close()
    from spec2sphere.dsp_ai.events import emit
    await emit("enhancement_published", {"id": id})
    return RedirectResponse(f"/ai-studio/{id}/edit", status_code=303)
```

- [ ] **Step 11.2: Templates**

`src/spec2sphere/web/templates/partials/ai_studio.html`:

```html
{% extends "base.html" %}
{% block title %}AI Studio — Spec2Sphere{% endblock %}
{% block page_title %}AI Studio{% endblock %}
{% block content %}
<div class="space-y-4">
  {% if is_author %}
  <form method="post" action="/ai-studio/" class="bg-white rounded-lg shadow p-4 flex gap-2">
    <input name="name" required placeholder="Enhancement name"
           class="border rounded px-3 py-2 flex-1"/>
    <select name="kind" class="border rounded px-3 py-2">
      <option value="narrative">narrative</option>
      <option value="ranking">ranking</option>
      <option value="item_enrich">item_enrich</option>
      <option value="action">action</option>
      <option value="briefing">briefing</option>
    </select>
    <button class="bg-purple-600 text-white px-4 py-2 rounded">+ New</button>
  </form>
  {% endif %}

  <table class="min-w-full bg-white rounded-lg shadow">
    <thead><tr class="text-xs text-gray-500 uppercase">
      <th class="px-4 py-2 text-left">Name</th><th>Kind</th><th>Version</th>
      <th>Status</th><th>Updated</th><th></th>
    </tr></thead>
    <tbody>
      {% for e in enhancements %}
      <tr class="border-t">
        <td class="px-4 py-2">{{ e.name }}</td>
        <td class="text-center">{{ e.kind }}</td>
        <td class="text-center">v{{ e.version }}</td>
        <td class="text-center"><span class="px-2 py-0.5 rounded-full text-xs
          {% if e.status == 'published' %}bg-green-100 text-green-700
          {% elif e.status == 'staging' %}bg-amber-100 text-amber-700
          {% else %}bg-gray-100 text-gray-600{% endif %}">{{ e.status }}</span>
        </td>
        <td class="text-center text-xs text-gray-500">{{ e.updated_at }}</td>
        <td class="text-right pr-4">
          <a href="/ai-studio/{{ e.id }}/edit" class="text-purple-600 hover:underline">Edit</a>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

`src/spec2sphere/web/templates/partials/ai_studio_editor.html`:

Split-pane editor. Left: a `<textarea>` with the `config_json` for MVP (Monaco wiring in Session B). Right: a preview `<pre>` populated via fetch.

Key scripts go inside `{% block content %}` as an **IIFE** (not DOMContentLoaded — per the HTMX feedback memory):

```html
{% extends "base.html" %}
{% block title %}Edit "{{ enh.name }}" — AI Studio{% endblock %}
{% block page_title %}Edit: {{ enh.name }} <span class="text-gray-400 text-sm">v{{ enh.version }} · {{ enh.status }}</span>{% endblock %}
{% block content %}
<div class="grid grid-cols-2 gap-4">
  <div class="bg-white rounded-lg shadow p-4">
    <label class="block text-sm font-medium text-gray-700 mb-2">Config JSON</label>
    <textarea id="config-editor" class="w-full h-96 font-mono text-sm border rounded p-2">{{ config_json }}</textarea>
    <div class="mt-3 flex gap-2">
      <button id="btn-save" class="bg-gray-100 px-4 py-2 rounded">Save draft</button>
      <button id="btn-preview" class="bg-purple-600 text-white px-4 py-2 rounded">Run preview</button>
      <form method="post" action="/ai-studio/{{ enh.id }}/publish" class="ml-auto">
        <button class="bg-emerald-600 text-white px-4 py-2 rounded">Publish</button>
      </form>
    </div>
  </div>
  <div class="bg-white rounded-lg shadow p-4">
    <h3 class="font-medium text-gray-700 mb-2">Preview</h3>
    <pre id="preview-output" class="text-sm bg-gray-50 p-3 rounded h-96 overflow-auto">— no preview yet —</pre>
  </div>
</div>

<script>
(function() {
  const ENH_ID = {{ enh.id|tojson }};
  const out = document.getElementById('preview-output');
  document.getElementById('btn-preview').addEventListener('click', async () => {
    out.textContent = 'running…';
    const resp = await fetch(`/ai-studio/${ENH_ID}/preview`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user: '{{ user.email if user else "henning@preview" }}',
                            context_hints: {}})
    });
    const data = await resp.json();
    out.textContent = JSON.stringify(data, null, 2);
  });
  document.getElementById('btn-save').addEventListener('click', async () => {
    const body = document.getElementById('config-editor').value;
    try { JSON.parse(body); } catch (e) { alert('invalid JSON'); return; }
    await fetch(`/ai-studio/${ENH_ID}/config`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body,
    });
    alert('saved');
  });
})();
</script>
{% endblock %}
```

(Add a `PUT /ai-studio/{id}/config` route that parses the JSON and updates the row. Reject if the parsed JSON fails Pydantic validation.)

- [ ] **Step 11.3: Nav entry**

Modify `src/spec2sphere/web/templates/base.html` — add between "Copilot" and "Settings":

```html
<a href="/ai-studio/" class="{% if request.url.path.startswith('/ai-studio') %}nav-active{% endif %} nav-item">AI Studio</a>
```

- [ ] **Step 11.4: Mount in app.py**

```python
# src/spec2sphere/app.py — in router wiring
from spec2sphere.web.ai_studio.routes import router as ai_studio_router
app.include_router(ai_studio_router)
```

Register in `modules.py` in the same style as other modules.

- [ ] **Step 11.5: Tests**

Smoke tests covering:
- GET `/ai-studio/` returns 200 with "AI Studio" title
- POST `/ai-studio/` with form → 303 redirect to `/ai-studio/{id}/edit`
- GET `/ai-studio/{id}/edit` → 200, contains config JSON
- POST `/ai-studio/{id}/publish` → 303 + row status flips to published
- POST non-author (not in STUDIO_AUTHOR_EMAILS) → 403

- [ ] **Step 11.6: Commit**

```bash
git add src/spec2sphere/web/ai_studio/ src/spec2sphere/web/templates/partials/ai_studio*.html src/spec2sphere/web/templates/base.html src/spec2sphere/app.py src/spec2sphere/modules.py tests/dsp_ai/test_studio_routes.py
git commit -m "feat(ai-studio): list + editor + preview + publish (minimal UI)"
```

---

## Task 12: Seed template + bootstrap wizard extension

**Files:**
- Create: `templates/seeds/morning_brief_revenue.json`
- Modify: `src/spec2sphere/web/setup_wizard.py`
- Create: `tests/dsp_ai/test_bootstrap.py`

- [ ] **Step 12.1: Seed Morning Brief template**

```json
{
  "name": "Morning Brief — Revenue",
  "kind": "briefing",
  "mode": "batch",
  "bindings": {
    "data": {
      "dsp_query": "SELECT date_trunc('day', order_date) AS d, region, SUM(amount) AS rev FROM public.sales WHERE order_date >= NOW() - INTERVAL '7 days' GROUP BY 1,2 ORDER BY 1 DESC LIMIT 50",
      "parameters": {}
    },
    "semantic": {
      "cypher": "MATCH (o:DspObject)-[:DOMAIN_OF]->(d:Domain {name:'Sales'}) RETURN o.id AS id, d.name AS domain LIMIT 20",
      "parameters": {}
    },
    "external": {
      "searxng_query": "{{ user_state.get('topics_of_interest', []) | default(['revenue']) | first }} news",
      "categories": ["news"],
      "max_results": 3
    }
  },
  "adaptive_rules": { "per_user": true, "per_time": true, "per_delta": true },
  "prompt_template": "You are a business analyst writing a morning briefing for {{ user_id }}.\nTime of day: {{ user_state.get('time_bucket', 'morning') }}.\nSince last visit ({{ user_state.get('last_visited_at') }}), here are the changes:\n\nRecent sales:\n{% for row in dsp_data %}- {{ row.d }}: {{ row.region }} {{ row.rev }}\n{% endfor %}\n\nRelated news:\n{% for n in external_info %}- {{ n.title }} — {{ n.url }}\n{% endfor %}\n\nReturn a JSON object with keys: narrative_text (markdown, max 120 words), key_points (array of 2–4 bullets), suggested_actions (array of 0–3 imperative short sentences).",
  "output_schema": {
    "type": "object",
    "required": ["narrative_text", "key_points", "suggested_actions"],
    "properties": {
      "narrative_text": {"type": "string"},
      "key_points": {"type": "array", "items": {"type": "string"}},
      "suggested_actions": {"type": "array", "items": {"type": "string"}}
    }
  },
  "render_hint": "brief",
  "ttl_seconds": 3600
}
```

- [ ] **Step 12.2: Extend setup_wizard.py**

Add a new step "AI Studio bootstrap" to the existing wizard:

1. Test LLM endpoint (POST to `$LLM_ENDPOINT/chat/completions` with a 1-token ping)
2. Scan DSP (reuse existing scanner action) → on `scan_completed` NOTIFY, run `schema_semantic.feed_from_graph_json(customer, graph_path)`
3. Fork seed template: read `templates/seeds/morning_brief_revenue.json`, INSERT into `dsp_ai.enhancements` as draft
4. Run preview: call `/v1/enhance/{id}` with `preview=true`
5. If preview succeeds → offer "Publish now" button

All of this in the existing wizard step/state pattern.

- [ ] **Step 12.3: Bootstrap test**

Integration test that:
1. Spins up a fresh DB (via `conftest` fixture)
2. Calls wizard's bootstrap endpoints in order
3. Asserts: Brain has at least one DspObject, one Enhancement row exists, at least one Generation row exists

- [ ] **Step 12.4: Commit**

```bash
git add templates/seeds/ src/spec2sphere/web/setup_wizard.py tests/dsp_ai/test_bootstrap.py
git commit -m "feat(dsp-ai): Morning Brief seed + bootstrap wizard extension"
```

---

## Task 13: SAC Analytic Model SQL snippet + deploy doc

**Files:**
- Create: `docs/sac/analytic_model_briefings.sql`
- Create: `docs/sac/README.md`

- [ ] **Step 13.1: Analytic Model SQL**

```sql
-- docs/sac/analytic_model_briefings.sql
-- Create a view inside DSP that SAC can bind as an Analytic Model.
-- Publishes the latest briefing per (enhancement, user, context) for native SAC consumption.

CREATE OR REPLACE VIEW dsp_ai.latest_briefings AS
SELECT
    b.enhancement_id,
    e.name AS enhancement_name,
    b.user_id,
    b.context_key,
    b.narrative_text,
    b.key_points,
    b.suggested_actions,
    b.generated_at,
    b.generation_id,
    e.config->>'render_hint' AS render_hint
FROM dsp_ai.briefings b
JOIN dsp_ai.enhancements e ON e.id = b.enhancement_id
WHERE b.expires_at IS NULL OR b.expires_at > NOW();

COMMENT ON VIEW dsp_ai.latest_briefings IS 'SAC-facing view. Filter by user_id via SAC session variable, then by enhancement_name or context_key.';

GRANT SELECT ON dsp_ai.latest_briefings TO sac_service_user;  -- replace with actual SAC reader role
```

- [ ] **Step 13.2: Deploy doc**

Write `docs/sac/README.md` covering:
1. How to install the Analytic Model in SAC (paste SQL, bind as Live Data Model from DSP)
2. How to filter by current user (SAC session variable `$user`)
3. How to render narrative_text as a rich-text widget in a SAC Story
4. Troubleshooting: empty rows, stale content, session-variable not resolving

- [ ] **Step 13.3: Commit**

```bash
git add docs/sac/
git commit -m "docs(sac): Analytic Model SQL + consumption guide for Pattern B"
```

---

## Task 14: Smoke test + ship criteria check

**Files:**
- Create: `tests/dsp_ai/test_smoke.py`

- [ ] **Step 14.1: Smoke suite**

```python
# tests/dsp_ai/test_smoke.py
"""Post-deploy smoke — run as `pytest -m smoke`.

Verifies the full vertical slice: bootstrap → preview → publish → batch write → row visible.
"""
import pytest, httpx, asyncpg, asyncio
from spec2sphere.config import settings

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_healthz():
    async with httpx.AsyncClient() as c:
        r = await c.get("http://dsp-ai:8000/v1/healthz")
        assert r.status_code == 200

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_brief_available_for_default_user():
    conn = await asyncpg.connect(settings.postgres_dsn)
    try:
        count = await conn.fetchval("SELECT count(*) FROM dsp_ai.briefings")
        assert count >= 1, "expected at least one briefing row after batch run"
    finally:
        await conn.close()
```

- [ ] **Step 14.2: Manual demo checklist (put in plan doc, not code)**

```
□ docker compose up → all services healthy within 2 minutes
□ open http://localhost:8260 → wizard runs, LLM ping green
□ click "Scan DSP" → graph.json generated, Brain seeded (visible in /ai-studio/brain in Session B; in this session verify via neo4j-admin shell)
□ fork "Morning Brief — Revenue" template → enhancement exists as draft
□ click "Run preview" in editor → preview renders narrative_text JSON
□ click "Publish" → status flips to published, NOTIFY fired, Celery picks up batch task
□ query dsp_ai.briefings → at least one row present
□ paste analytic_model_briefings.sql into Horváth DSP → create Analytic Model
□ build SAC Story → bind narrative_text → user sees narrative inside SAC
```

- [ ] **Step 14.3: Commit**

```bash
git add tests/dsp_ai/test_smoke.py docs/superpowers/plans/2026-04-17-dspai-session-a-foundation-vertical-slice.md
git commit -m "test(dsp-ai): smoke suite + demo checklist"
```

---

## Session A success criteria

1. Health: `curl http://localhost:8261/v1/healthz` → `200 {"status": "ok"}`
2. Morning Brief seed template published and producing at least one row in `dsp_ai.briefings` for the default user
3. Studio: create a new (blank) enhancement, preview it, see rendered JSON back (even if minimal), publish it — all via the UI
4. Brain: after a DSP scan, `cypher MATCH (o:DspObject) RETURN count(o)` returns >0
5. NOTIFY: publishing an enhancement emits `enhancement_published` visible via `psql -c "LISTEN enhancement_published"`
6. `pytest -m smoke` green against a running compose
7. Fresh `docker compose down -v && docker compose up` → bootstrap wizard → first preview within 15 minutes

Anything else is Session B territory.
