# Spec2Sphere — Project Status

**Last updated:** 2026-04-16
**Version:** 2.0.0
**Sessions completed:** 6/6

## Quick Reference

| Component | Location | Status |
|-----------|----------|--------|
| Code repo | Gitea: atlas/sap-doc-agent, GitHub: hschuettken/sap-doc-agent | Private, mirrored |
| Output repo | Gitea: atlas/sap-doc-agent-output, GitHub: hschuettken/sap-doc-agent-output | Private, mirrored |
| Web server | 192.168.0.50:8260, sap-docu.local.schuettken.net | Running |
| Web UI | https://sap-docu.schuettken.net/ui/dashboard | Password: admin (change it!) |
| BookStack | 192.168.0.50:8253 (admin@admin.com / password) | Running |
| Outline | 192.168.0.50:8250 (SMTP magic link auth) | Running |
| Tests | 926 passing | Green |

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

Provider: Homelab LLM Router (192.168.0.50:8070)
Model: qwen2.5:32b (primary), qwen2.5:14b (fallback)
Mode: direct (agents call LLM autonomously)

## Credentials

All stored in envctl (192.168.0.50:8201). Key ones:
- `SPEC2SPHERE_LLM_ROUTER_URL` — LLM Router endpoint
- `SPEC2SPHERE_SECRET_KEY` — Session signing key
- `BOOKSTACK_TOKEN` — BookStack API token
- `DSP_CLIENT_ID/SECRET/TOKEN_URL` — Horvath DSP OAuth
- `GIT_TOKEN` — Gitea token

## TODO

- [x] All 6 sessions complete
- [x] 926 tests passing
- [x] 6 Horváth standards loaded
- [x] LLM Router integration
- [x] Multi-tenant enabled
- [x] All modules enabled
- [ ] Change UI default password
- [ ] Change BookStack admin password
- [ ] Configure DSP OAuth credentials (BTP service key)
- [ ] Run initial DSP landscape scan
- [ ] M365 Copilot: add knowledge URL + OpenAPI
