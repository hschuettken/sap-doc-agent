# SAP Doc Agent — Project Status

**Last updated:** 2026-04-13

## Quick Reference

| Component | Location | Status |
|-----------|----------|--------|
| Code repo | Gitea: atlas/sap-doc-agent, GitHub: hschuettken/sap-doc-agent | Private, mirrored |
| Output repo | Gitea: atlas/sap-doc-agent-output, GitHub: hschuettken/sap-doc-agent-output | Private, mirrored |
| Web server | 192.168.0.50:8260, sap-docu.local.schuettken.net | Running |
| Web UI | https://sap-docu.schuettken.net/ui/dashboard | Password: admin (change it!) |
| BookStack | 192.168.0.50:8253 (admin@admin.com / password) | Running |
| Outline | 192.168.0.50:8250 (SMTP magic link auth) | Running |
| Spec | SPEC.md in code repo | Complete |
| Tests | 254 passing | Green |

## CLI Usage

```bash
# Quick audit (no SAP access needed)
sap-doc-agent audit --docs ./client-docs/ --client-standard ./guidelines.pdf --name "Client X"

# Full platform
sap-doc-agent platform --config config.yaml --all

# CDP scanner mode
sap-doc-agent platform --config config.yaml --scanner cdp --cdp-data extractions.json --all
```

## Web Server

```bash
# Local dev
python -c "import uvicorn; from sap_doc_agent.web.server import create_app; app = create_app(output_dir='/path/to/output'); uvicorn.run(app, host='0.0.0.0', port=8260)"

# Docker (deployed via ops-bridge)
# atlas/services/sap-doc-agent/docker-compose.yml
# Needs GIT_TOKEN env var for private repo access
```

## URLs (after Cloudflare tunnel)

- Knowledge: https://sap-docu.schuettken.net/
- Sitemap: https://sap-docu.schuettken.net/sitemap.xml
- OpenAPI: https://sap-docu.schuettken.net/openapi.json
- Audit API: POST https://sap-docu.schuettken.net/api/audit
- Search: GET https://sap-docu.schuettken.net/api/search?q=...
- Objects: GET https://sap-docu.schuettken.net/api/objects

## Credentials

All stored in envctl (192.168.0.50:8201). Key ones:
- `GIT_TOKEN` — GitHub PAT (sap-doc-agent service)
- `BOOKSTACK_TOKEN` — BookStack API token
- `DSP_CLIENT_ID/SECRET/TOKEN_URL` — Horvath DSP OAuth

## TODO

- [x] Cloudflare tunnel: sap-docu.schuettken.net
- [ ] Change UI password from default 'admin' (set SAP_DOC_AGENT_UI_PASSWORD_HASH env var)
- [ ] M365 Copilot: add knowledge URL + OpenAPI
- [ ] ABAP install on Horvath BW (see setup/abap/INSTALL_HORVATH_DEMO.md)
- [ ] Deep CDP scan of Horvath DSP (SQL, columns, lineage, screenshots)
- [ ] BTP service key for DSP REST API access
- [ ] Change BookStack admin password
