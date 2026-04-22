# Spec2Sphere — Client Install Checklist

Use this checklist when deploying to a new client site.

---

## Prerequisites

- [ ] Docker 24+ and Docker Compose v2 installed on the server
- [ ] 8 GB RAM, 4 vCPUs minimum (16 GB / 8 vCPUs recommended for production)
- [ ] Network access to SAP DSP / BW system (port 30015 or JDBC)
- [ ] PostgreSQL 16 accessible (bundled compose includes one)
- [ ] Redis 7 accessible (bundled)
- [ ] Neo4j 5 accessible (bundled)

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL DSN (`postgresql://spec2sphere:pass@postgres:5432/spec2sphere`) |
| `REDIS_URL` | Yes | Redis URL (`redis://redis:6379/0`) |
| `NEO4J_URI` | Yes | Neo4j bolt URL (`bolt://neo4j:7687`) |
| `NEO4J_USER` / `NEO4J_PASSWORD` | Yes | Neo4j credentials |
| `DSP_CLIENT_ID` / `DSP_CLIENT_SECRET` / `DSP_TOKEN_URL` | Yes | BTP service-key OAuth creds for DSP |
| `DSP_DATABASE_URL` | Yes | Direct DSP HANA DSN (for `dsp_ai` stages) |
| `CUSTOMER` | Yes | Short tenant ID (alphanumeric, e.g. `horvath`) |
| `SECRET_KEY` | Yes | 32+ char random string (session signing) |
| `DSPAI_JWT_SECRET` | Yes | 32+ char random string (widget RBAC tokens) |
| `STUDIO_AUTHOR_EMAILS` | Yes | Comma-separated author email allowlist (empty = allow all) |
| `COST_GUARD_DEFAULT_CAP_USD` | No | Per-enhancement monthly LLM cap (default `25.0`) |
| `COST_GUARD_GLOBAL_CAP_USD` | No | Global monthly cap across all LLM calls (default `100.0`) |
| `OLLAMA_MODEL` | No | Model name for offline profile (default `qwen2.5:14b`) |
| `TLS_MODE` | No | `client_lb` / `caddy` / `self_signed` (default `client_lb`) |
| `M365_TENANT_ID` / `M365_CLIENT_ID` / `M365_CLIENT_SECRET` / `M365_CONNECTION_ID` | No | Azure AD for M365 Copilot connector |
| `FILE_DROP_ENABLED` | No | `true` to activate file-drop ingest pipeline |
| `SPEC2SPHERE_BASE_URL` | No | Public base URL for Copilot manifest links |

---

## Deployment Steps

1. **Clone the repo**
   ```bash
   git clone https://git.schuettken.net/atlas/sap-doc-agent.git
   cd sap-doc-agent
   cp .env.example .env
   # Fill in .env
   ```

2. **Run the first-run setup wizard** (new deployments only)
   ```bash
   SETUP_WIZARD_ENABLED=true docker compose up -d
   # Open http://<host>:8260/ui/setup/welcome and complete all 7 steps
   ```

3. **Or deploy directly** (existing deployments / CI)
   ```bash
   docker compose up -d
   ```

4. **Import a library** (optional)
   ```bash
   curl -X POST http://localhost:8260/ai-studio/library/import \
        -F "file=@libraries/cpg_retail/export.json" \
        -F "mode=merge"
   ```

5. **Verify health**
   ```bash
   curl http://localhost:8260/api/health
   curl http://localhost:8261/v1/readyz
   ```

---

## Rollback Procedure

1. Stop services: `docker compose down`
2. Restore database from backup: see `scripts/restore.sh`
3. Roll back image tag in `docker-compose.yml`
4. Start services: `docker compose up -d`

---

## Offline / Air-Gapped Deployment

```bash
# Pull Ollama image first (on a machine with internet)
docker pull ollama/ollama:latest
docker save ollama/ollama:latest | gzip > ollama.tar.gz
# Transfer to air-gapped server, load:
docker load < ollama.tar.gz

# Start with offline profile
docker compose -f docker-compose.yml -f docker-compose.offline.yml \
    --profile offline up -d
```

---

## SAC Widget Deployment

1. In SAC Admin → Custom Widgets, upload the manifest URL:
   `http://<host>:8260/widget/manifest.json`
2. SAC fetches `main.js` automatically via the manifest.
3. Bind the widget to any SAC story page.
4. Widget calls `/v1/enhance/<id>` with a bearer token issued from AI Studio.

---

## Backup Cadence

Run `scripts/backup.sh` on a cron (daily recommended):
```bash
0 2 * * * cd /opt/sap-doc-agent && ./scripts/backup.sh >> /var/log/spec2sphere-backup.log 2>&1
```
