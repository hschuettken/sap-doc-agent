# Spec2Sphere — Project Status

**Last updated:** 2026-04-17
**Version:** 2.0.0
**Sessions completed:** 6/6 + quality router + privacy session

## Quick Reference

| Component | Location | Status |
|-----------|----------|--------|
| Code repo | Gitea: atlas/sap-doc-agent, GitHub: hschuettken/sap-doc-agent | Private, mirrored |
| Output repo | Gitea: atlas/sap-doc-agent-output, GitHub: hschuettken/sap-doc-agent-output | Private, mirrored |
| Web server | 192.168.0.50:8260, sap-docu.local.schuettken.net | Running |
| Web UI | https://sap-docu.schuettken.net/ui/dashboard | Password: admin (change it!) |
| BookStack | 192.168.0.50:8253 (admin@admin.com / password) | Running |
| Outline | 192.168.0.50:8250 (SMTP magic link auth) | Running |
| Tests | 1095 passing | Green |

## Architecture

8-container Docker Compose stack:
- **web**: FastAPI + HTMX cockpit (port 8260)
- **worker**: Celery (scan + llm queues, 4 concurrent)
- **worker-chrome**: Celery (chrome + sac queues, 1 concurrent)
- **scheduler**: Celery Beat (nightly QA, weekly reports)
- **postgres**: PostgreSQL 16 + pgvector
- **redis**: Redis 7 (queue + cache)
- **chrome**: Containerized Chrome + Xvfb + VNC
- **novnc**: Web VNC viewer (port 6080)

## Modules (All Enabled)

| Module | Status | Description |
|--------|--------|-------------|
| Core | Active | Scanning, knowledge, standards, design system |
| Migration Accelerator | Active | BW semantic interpretation, debt classification |
| DSP Factory | Active | Artifact generation, deployment, reconciliation |
| SAC Factory | Active | Blueprint execution, visual/data/interaction QA |
| Governance | Active | Approvals, confidence scoring, traceability |
| Artifact Lab | Active | Sandbox experimentation, template learning |
| Multi-Tenant | Active | Workspace switching, tenant/customer/project CRUD |

## Supply Chain Security

[![CI Status](https://git.schuettken.net/atlas/sap-doc-agent/actions/workflows/ci.yml/badge.svg)](https://git.schuettken.net/atlas/sap-doc-agent/actions/workflows/ci.yml)

**Gitea Actions workflow** (`.gitea/workflows/ci.yml`) runs on every push:
- ✓ **Test suite** — pytest on 1095+ tests (Python 3.12 via uv)
- ✓ **SBOM generation** — CycloneDX JSON artifact
- ✓ **Trivy filesystem scan** — blocks on HIGH/CRITICAL vulns
- ✓ **Gitleaks detection** — blocks on hardcoded secrets

See `.trivyignore` for known false positives.

## Codebase Scale

- **151 Python modules** across 20 subsystems
- **96 test files**, 1061 tests
- **9 Alembic migrations** (23+ tables)
- **45 Jinja2 templates** (12+ UI pages)
- **14 LLM provider adapters**
- **6 Horváth standards** (3,667 lines of rules)
- **1,244-line ABAP scanner** + 265-line setup program

## M365 Copilot Integration

Pushes Spec2Sphere knowledge into the Microsoft 365 search index and exposes a
Declarative Agent so Copilot for M365 users can query the platform directly.

### Components

| Component | Location | Description |
|-----------|----------|-------------|
| Graph Connector client | `src/spec2sphere/copilot/graph_connector.py` | Azure AD client-credentials auth, upsert items via Graph API |
| Declarative Agent router | `src/spec2sphere/copilot/declarative_agent.py` | Manifest, OpenAPI spec, and three action endpoints |
| Celery sync task | `src/spec2sphere/tasks/m365_sync.py` | Every 4 h; skips silently when env vars unset |

### Environment Variables

| Env Var | Required | Description |
|---------|----------|-------------|
| `M365_TENANT_ID` | Yes | Azure AD tenant ID |
| `M365_CLIENT_ID` | Yes | App registration client ID |
| `M365_CLIENT_SECRET` | Yes | App registration client secret |
| `M365_CONNECTION_ID` | Yes | External connection ID (alphanumeric, max 32 chars) |
| `SPEC2SPHERE_BASE_URL` | No | Public base URL for manifest links (default: `http://localhost:8260`) |

### Azure AD App Registration Setup

1. Register an app in Azure AD with the `ExternalItem.ReadWrite.OwnedBy` Graph API permission.
2. Grant admin consent.
3. Set the four env vars above (via envctl or `.env`).

### Endpoints (Declarative Agent)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/copilot/agent/manifest.yaml` | Copilot agent manifest |
| `GET` | `/api/copilot/agent/openapi.yaml` | OpenAPI spec for agent actions |
| `POST` | `/api/copilot/agent/actions/search_specs` | Full-text search across all sections |
| `GET` | `/api/copilot/agent/actions/list_governance_rules` | Governance + quality pages |
| `GET` | `/api/copilot/agent/actions/get_route/{section_id}__{page_id}` | Full page content |

### Behavior when unconfigured

When `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET`, or `M365_CONNECTION_ID`
are absent, the Celery beat task logs a skip message and exits cleanly — no exception
is raised and no alert is emitted. All other functionality is unaffected.

## File Drop Ingestion

Offline / air-gapped ingestion pipeline for customers who cannot expose a live SAP system.

### Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `FILE_DROP_ENABLED` | `false` | Set to `true` to activate the watcher, Celery beat task, and upload endpoint |
| `FILE_DROP_PATH` | `/var/spec2sphere/drop` | Root directory watched for incoming files |
| `OUTPUT_DIR` | `output` | Where parsed scan output is written (subdirectory `file_drop/` is used) |

### Supported File Types

| Extension | Type | Parser |
|-----------|------|--------|
| `.abap` | ABAP source | Keyword-based class / function module / report detection |
| `.ddls` | CDS view definition | Regex extracts view name from `DEFINE [ROOT] VIEW <name>` |
| `.sql` | DDL SQL | Extracts table or view name; distinguishes `CREATE TABLE` vs `CREATE VIEW` |
| `.zip` | Export bundle | Extracted and each supported member is parsed individually |

Plain-text files (`.txt`) without a recognised extension are content-sniffed (first 256 bytes).

### Directory Layout

```
/var/spec2sphere/drop/
  *.abap / *.ddls / *.sql / *.zip   ← drop files here
  processed/<timestamp>/             ← moved here on success
  errors/                            ← moved here on failure
```

### API Endpoint

`POST /api/ingest/upload` (multipart, field `file`) — only available when `FILE_DROP_ENABLED=true`.

Returns `202 Accepted` with `{"status": "queued", "path": "...", "task_id": "..."}`.

### Celery Tasks

- `spec2sphere.tasks.file_drop_tasks.process_dropped_file(path)` — routed to `scan` queue
- `spec2sphere.tasks.file_drop_tasks.poll_drop_directory()` — beat task every 5 minutes (fallback if inotify events are missed)

## Standards (6 Horváth Standards)

| Standard | File | Focus |
|----------|------|-------|
| Documentation Standard | documentation_standard.yaml | 7 doc types, section requirements |
| Code Quality | code_standard.yaml | ABAP + HANA SQL rules |
| Doc Rules | doc_standard.yaml | Object-level metadata rules |
| SAC Design | sac_design_standard.yaml | 3-tier dashboards, IBCS, modern design |
| DSP Modeling | dsp_modeling_standard.yaml | 4-layer architecture, naming, integration |
| Quality Gates | quality_gates_standard.yaml | 4 gates, checklists, governance |

## LLM Integration

**Quality Router (Q1-Q5):** 16 actions in 5 clusters, 3 built-in profiles (default, all-local, all-claude).
**Privacy by Design:** `data_in_context=True` forces local-only models (13 of 16 callers flagged).
**Profiles:** Q1→qwen2.5:7b, Q2→qwen2.5:14b, Q3→claude-haiku, Q4→claude-sonnet, Q5→claude-sonnet.
**UI:** /ui/llm-routing — profile switching, per-action/cluster overrides, privacy controls.

## Credentials

All stored in envctl (192.168.0.50:8201). Key ones:
- `SPEC2SPHERE_LLM_ROUTER_URL` — LLM Router endpoint
- `SPEC2SPHERE_SECRET_KEY` — Session signing key
- `BOOKSTACK_TOKEN` — BookStack API token
- `DSP_CLIENT_ID/SECRET/TOKEN_URL` — Horvath DSP OAuth
- `GIT_TOKEN` — Gitea token

## Implementation Gaps (vs SPEC.md)

These features are described in SPEC.md or ARCHITECTURE_TARGET.md but NOT yet implemented:

| Feature | Status | Notes |
|---------|--------|-------|
| Doc Sync bidirectional | **DONE** | pull_from_platform, detect_conflicts, sync_bidirectional (2026-04-17) |
| abapGit transport | **DONE** | Full staging+push implementation in z_doc_agent_scan.abap (2026-04-17) |
| GitLab git backend | **DONE** | gitlab_backend.py via httpx REST v4 (2026-04-17) |
| Azure DevOps git backend | **DONE** | azure_devops_backend.py via httpx REST v7.0 (2026-04-17) |
| File Drop transport (Python) | Not implemented | ABAP side works, no Python pickup |
| M365 Copilot Graph Connector | Not implemented | Sitemap exists; no Enterprise connector |
| M365 Copilot Declarative Agent | Not implemented | No manifest, no knowledge URL config |
| OIDC/SAML SSO | Not implemented | bcrypt password auth only |
| OpenTelemetry traces | Not implemented | Prometheus metrics exist, OTel not wired |
| Signed images / SBOM / Trivy | Not implemented | No supply chain CI |
| Setup wizard | Not implemented | SPEC mentions wizard.py; doesn't exist |
| LLM copilot_passthrough mode | Not implemented | Config schema defines it, no agent support |
| Knowledge auto-learning loop | **DONE** | KnowledgeLearner wired into landscape_store (2026-04-17) |
| DSP OAuth credentials | Not configured | Template ready, needs BTP service key |

## TODO

- [x] All 6 sessions complete
- [x] 1095 tests passing
- [x] 6 Horváth standards loaded
- [x] Quality Router (Q1-Q5) with UI
- [x] Privacy by design (local-only with data)
- [x] Structured field storage + versioning
- [x] Multi-tenant enabled
- [x] All modules enabled
- [ ] Change UI default password
- [ ] Change BookStack admin password
- [ ] Configure DSP OAuth credentials (BTP service key)
- [ ] Run initial DSP landscape scan
- [x] Bidirectional doc sync with conflict resolution
- [x] GitLab + Azure DevOps git backends
- [x] abapGit transport backend (ABAP side)
- [x] Knowledge auto-learning loop
- [ ] M365 Copilot: Declarative Agent manifest + knowledge URLs
- [ ] OIDC/SAML SSO (Authlib)
- [ ] OpenTelemetry tracing
- [x] CI: SBOM generation + Trivy vuln scan + Gitleaks secret detection (2026-04-17)
