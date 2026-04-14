# SAP Doc Agent — Migration Session Prompt

Paste this prompt into a Claude Code session to execute the migration plan. The agent will work one phase at a time and ask for confirmation before proceeding.

---

## Prompt (copy everything below this line)

---

You are implementing the SAP Doc Agent migration plan. The goal is to take the tool from a single-container homelab-coupled service to a portable, enterprise-ready three-container application.

**Start by reading these files in order:**

1. `/home/hesch/dev/projects/sap-doc-agent/docs/ARCHITECTURE_TARGET.md` — the target architecture
2. `/home/hesch/dev/projects/sap-doc-agent/docs/plans/MIGRATION_PLAN.md` — the phased implementation plan with exact files, tests, and definitions of done
3. `/home/hesch/dev/projects/sap-doc-agent/CLAUDE.md` if it exists — project-specific rules
4. `/home/hesch/dev/CLAUDE.md` — workspace rules (integration oracle, deploy workflow, etc.)

**Project location:** `/home/hesch/dev/projects/sap-doc-agent`

**What the project is:** A FastAPI + Jinja2 + HTMX web application that scans SAP BW/4HANA and Datasphere systems, generates documentation, runs quality checks, and produces audit reports. Frontend is server-rendered (no separate React build). Backend is a single Python package under `src/sap_doc_agent/`. 254 tests under `tests/`.

---

## Infrastructure context (for homelab deploys)

| Service | Address | Notes |
|---|---|---|
| docker2 (deploy target) | 192.168.0.50 | Ops-bridge only — never SSH directly |
| Ops-Bridge | 192.168.0.50:9090 | All deploys go through here |
| Gitea | 192.168.0.64:3000 | Push changes here; ops-bridge pulls from here |
| envctl | 192.168.0.50:8201 | Secrets store — used NOW, phased out in Phase 5 |
| LLM Router | 192.168.0.50:8070 | Current LLM backend — kept as `router` provider in Phase 1 |
| BookStack | 192.168.0.50:8253 | Doc platform |
| PostgreSQL | 192.168.0.80:5432 | Primary DB — LXC, not Docker |
| Redis | 192.168.0.78:6379 | Queue + cache |

Deploy workflow: commit and push to Gitea → `POST http://192.168.0.50:9090/deploy/{repo}` via ops-bridge. The current service runs at `192.168.0.50:8260`.

---

## Technology stack

- Python 3.12, FastAPI, uvicorn
- Jinja2 + HTMX (server-rendered, no React)
- Tailwind CDN + vis.js (already in templates)
- Postgres (asyncpg for new code, no SQLAlchemy — match existing pattern)
- Redis for queue + cache
- Celery (introduced in Phase 2)
- Alembic for migrations (if DB tables are added)
- `pytest` + `pytest-asyncio` + `respx` + `pytest-httpx` for tests
- `ruff` for linting

---

## Rules

- Read the MIGRATION_PLAN.md before writing any code. It has exact file lists, test requirements, and definitions of done for each phase.
- Work one phase at a time. After completing a phase, run the test suite (`python -m pytest tests/ -v`), then stop and report results before asking whether to continue to the next phase.
- Commit after each phase with a message like `feat: phase-1 llm provider abstraction`. Do not bundle multiple phases into one commit.
- Push to Gitea and deploy via ops-bridge after each phase if instructed. Do not deploy automatically unless told to.
- Do not skip tests. Each phase has tests listed in the migration plan — write them and make them pass before declaring the phase done.
- Do not break existing tests. The 254 existing tests must still pass after every phase.
- Query the Integration Oracle before any significant new feature or service call: `curl -s -X POST http://192.168.0.50:8225/oracle/query -H "Content-Type: application/json" -d '{"intent": "..."}'`
- No hardcoded homelab IPs in Python source files (except envctl_loader.py which is explicitly optional).
- No SQLAlchemy — use asyncpg directly for any new Postgres queries.
- No paho/aiomqtt — this project does not use MQTT.
- Frontend: always use the existing Tailwind CDN + HTMX pattern. No new JS frameworks.

---

## How to start

Read the four files listed above. Then confirm you have understood the current state of the codebase and the target, and tell me:

1. Which phase you will start with
2. The first three files you will create or modify
3. Any blockers you see before starting

Then begin Phase 1.
