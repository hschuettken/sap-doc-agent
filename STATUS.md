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
