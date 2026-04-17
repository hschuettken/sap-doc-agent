# Spec2Sphere — Client Deployment Checklist

> **Audience:** Customer IT / deployment engineer.
> Work through every section in order. Items marked **[REQUIRED]** block startup if skipped.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [First Boot](#3-first-boot)
4. [Load Reference Library (optional)](#4-load-reference-library-optional)
5. [LLM Selection](#5-llm-selection)
6. [SAC Widget Wiring](#6-sac-widget-wiring)
7. [Backup Schedule](#7-backup-schedule)
8. [TLS](#8-tls)
9. [Rollback](#9-rollback)
10. [Troubleshooting](#10-troubleshooting)
11. [Session C Safety Notes](#11-session-c-safety-notes)

---

## 1. Prerequisites

### Software

| Requirement | Minimum version | Check |
|---|---|---|
| Docker Engine | 24.0 | `docker version` |
| Docker Compose plugin | 2.20 | `docker compose version` |
| `curl` | any | `curl --version` |
| `openssl` | any | `openssl version` |

### Hardware

| Resource | Minimum | Notes |
|---|---|---|
| RAM | 16 GB | Neo4j + Postgres + worker each claim ~2 GB |
| Disk | 20 GB free | +15 GB if using the **offline Ollama profile** |
| CPU | 4 cores | 2-core minimum but slow for LLM generation |

### Network ports

The following ports must be free on the host before starting:

| Port | Service | Mandatory |
|---|---|---|
| **8260** | Spec2Sphere Studio (web UI) | Yes |
| **8261** | DSP-AI API / widget endpoint | Yes |
| 5900 | noVNC VNC port (Chrome debug) | Optional |
| 6080 | noVNC HTTP (Chrome debug) | Optional |
| 11434 | Ollama (offline profile only) | Only if `--profile offline` |

### LLM access

You need **one** of the following before continuing:

- Homelab LLM Router (internal URL + API key)
- OpenAI API key
- Azure OpenAI endpoint + key + deployment name
- Local Ollama — use the offline Docker Compose profile (see §5)

---

## 2. Environment Setup

### 2a. Copy the template **[REQUIRED]**

```bash
cp .env.example .env
```

Open `.env` in an editor. The sections below list every variable you need to review.

---

### 2b. Core variables

| Variable | Default | Action required |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://sapdoc:sapdoc@postgres:5432/sapdoc` | Fine as-is for Docker Compose internal Postgres. Change only if pointing to an external PG. |
| `REDIS_URL` | `redis://redis:6379/0` | Fine as-is. |
| `SECRET_KEY` | `change-me-…` | **[REQUIRED in prod]** Generate: `openssl rand -hex 32` |
| `NEO4J_PASSWORD` | `change-me` | **[REQUIRED]** Set any strong password before first boot. |

---

### 2c. LLM provider (choose one — see §5 for full details)

```bash
# Homelab Router (default)
LLM_PROVIDER=router
LLM_ROUTER_URL=http://192.168.0.50:8070
LLM_ROUTER_API_KEY=your-key

# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Azure OpenAI
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Offline Ollama (bundled) — see §5 for startup command
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:14b
```

---

### 2d. Session C variables

These variables were introduced in Session C (multi-tenant, JWT RBAC, cost guardrails).

| Variable | Default | Notes |
|---|---|---|
| `CUSTOMER` | `default` | Tenant identifier for Postgres RLS and Neo4j scoping. Set per customer deployment. |
| `DSPAI_JWT_SECRET` | *(not set)* | **[REQUIRED in prod]** HS256 signing key for Studio JWTs. Generate: `openssl rand -hex 32`. If unset, `DSPAI_AUTH_ENFORCED` defaults to `false` (dev mode). |
| `DSPAI_AUTH_ENFORCED` | `false` | Set `true` in production to require a valid JWT on all `/v1/*` routes. |
| `STUDIO_AUTHOR_EMAILS` | *(empty)* | Comma-separated list of email addresses that receive the `author` role in Studio. Others get `viewer`. Example: `alice@corp.com,bob@corp.com`. |
| `COST_GUARD_DEFAULT_CAP_USD` | `25.0` | Per-enhancement monthly USD cap. Requests above this are rejected. |
| `COST_GUARD_GLOBAL_CAP_USD` | `100.0` | Global monthly USD cap across all enhancements. |
| `COST_GUARD_ENFORCED` | `true` | Set `false` in dev/demo environments to disable cap enforcement while still tracking spend. |
| `WIDGET_ALLOWED_ORIGINS` | *(empty)* | SAC tenant URL for CORS. Example: `https://your-tenant.eu10.hcs.cloud.sap`. Multiple origins: comma-separated. |

---

### 2e. SAP DSP credentials (optional — required only if the DSP fetcher is enabled)

```bash
DSP_CLIENT_ID=your-client-id
DSP_CLIENT_SECRET=your-secret
DSP_TOKEN_URL=https://your-tenant.authentication.eu10.hana.ondemand.com/oauth/token
```

---

## 3. First Boot

### 3a. Start services

```bash
docker compose up -d
```

Services start in dependency order. Postgres and Neo4j have healthchecks — the application containers wait for them automatically.

### 3b. Wait for readiness

Allow ~30 seconds for Postgres and Neo4j to initialise. Alembic migrations run automatically via the entrypoint — no manual migration step required.

### 3c. Verify Studio

```bash
curl http://localhost:8260/
# Expected: HTML page with "Spec2Sphere" in the title
```

### 3d. Verify DSP-AI API

```bash
curl http://localhost:8261/v1/healthz
# Expected: {"status":"ok"}
```

### 3e. Check container health

```bash
docker compose ps
# All services should show "healthy" or "running"
```

If any container is in a restart loop:

```bash
docker compose logs <service-name> --tail 50
```

---

## 4. Load Reference Library (optional)

The CPG / Retail reference library ships with the repo at `libraries/cpg_retail/export.json` (8 pre-built enhancement templates).

### Automated (recommended for demo)

```bash
bash scripts/demo_bootstrap.sh
```

This script starts the stack, waits for readiness, imports the library, and prints the demo URLs.

### Manual import

```bash
curl -X POST http://localhost:8260/ai-studio/library/import \
     -F "file=@libraries/cpg_retail/export.json" \
     -F "mode=merge" \
     -H "X-User-Email: you@example.com"
```

`mode=merge` leaves existing enhancements untouched and only imports new ones. Use `mode=replace` for a clean slate.

---

## 5. LLM Selection

### Option A — Homelab LLM Router (default, internal)

```bash
LLM_PROVIDER=router
LLM_ROUTER_URL=http://192.168.0.50:8070
LLM_ROUTER_API_KEY=your-key
```

Routes through OpenClaw / LLM Router with automatic model selection and metering.

### Option B — Offline profile (Ollama bundled)

Adds a local Ollama container. Downloads the model on first start (~8 GB for `qwen2.5:14b`). Requires 15 GB additional disk and a GPU or fast CPU.

```bash
# Start with offline profile
docker compose -f docker-compose.yml -f docker-compose.offline.yml --profile offline up -d

# Required env vars
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:14b   # or qwen2.5:7b for smaller hardware
```

First boot will pull the model — wait until you see `ollama` show as healthy before testing.

### Option C — OpenAI

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o   # optional, defaults to gpt-4o
```

### Option D — Azure OpenAI

```bash
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

---

## 6. SAC Widget Wiring

### 6a. Widget manifest

The widget manifest is served at:

```
http://your-host:8261/widget/manifest.json
```

No extra configuration is needed — the path is hardcoded in the compose service.

### 6b. CORS

Set `WIDGET_ALLOWED_ORIGINS` in `.env` to your SAC tenant URL:

```bash
WIDGET_ALLOWED_ORIGINS=https://your-tenant.eu10.hcs.cloud.sap
```

Multiple tenants:

```bash
WIDGET_ALLOWED_ORIGINS=https://tenant1.eu10.hcs.cloud.sap,https://tenant2.eu10.hcs.cloud.sap
```

After changing `.env`, restart the DSP-AI service:

```bash
docker compose restart dsp-ai
```

### 6c. Import into SAC Analytics Designer

1. Open SAC → Analytics Designer → Custom Widget Management
2. Click **Add** → enter the manifest URL: `https://your-host:8261/widget/manifest.json`
3. The widget appears in the widget panel as **DSP AI Enhancement**
4. Drag into a story canvas and configure `enhancementId` in the properties panel

> **TLS note:** SAC will refuse to load a widget over plain HTTP from a public hostname. See `docs/deploy/tls.md` for Caddy or reverse-proxy setup.

---

## 7. Backup Schedule

### Cron entry

Add to the host's crontab (`crontab -e`):

```cron
0 3 * * * /absolute/path/to/sap-doc-agent/scripts/backup.sh >> /var/log/spec2sphere-backup.log 2>&1
```

This runs daily at 03:00 UTC.

### What is backed up

| Component | Method | File in tarball |
|---|---|---|
| Postgres | `pg_dump` | `postgres.sql` |
| Neo4j | `neo4j-admin database dump` | `neo4j.dump` |
| Redis | `SAVE` + `cp dump.rdb` | `redis.rdb` |
| Library | `/ai-studio/library/export` API | `library.json` |

### Storage location

Default: `./backups/spec2sphere-backup-<TIMESTAMP>.tar.gz`

Override with:

```bash
BACKUP_DIR=/mnt/nas/spec2sphere-backups bash scripts/backup.sh
```

### Retention

The backup script does **not** delete old tarballs. Implement retention externally, for example:

```bash
# Keep 30 days
find /path/to/backups -name "spec2sphere-backup-*.tar.gz" -mtime +30 -delete
```

### Restore

```bash
bash scripts/restore.sh backups/spec2sphere-backup-20260101T030000Z.tar.gz
```

See `scripts/restore.sh` for full details.

---

## 8. TLS

See [`docs/deploy/tls.md`](./tls.md) for all three supported TLS modes:

- `TLS_MODE=client_lb` — your existing reverse proxy (nginx / Traefik / AWS ALB / Cloudflare) terminates TLS (default)
- `TLS_MODE=caddy` — Caddy sidecar with automatic Let's Encrypt
- `TLS_MODE=self_signed` — self-signed cert for isolated demo (not suitable for SAC widget)

---

## 9. Rollback

### Tag-based rollback

```bash
docker compose down
git checkout <previous-tag>   # e.g. v2.3.0
docker compose up -d --build
```

### Backup-based rollback

```bash
docker compose down
docker compose up -d          # get Postgres + Neo4j running first
bash scripts/restore.sh backups/spec2sphere-backup-<TIMESTAMP>.tar.gz
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Neo4j container exits immediately | `NEO4J_PASSWORD` not set or too short | Set `NEO4J_PASSWORD` in `.env` (min 8 chars); `docker compose up -d neo4j` |
| `curl :8260` returns connection refused | `web` container still starting | Wait 30 s; check `docker compose logs web --tail 20` |
| `curl :8261/v1/healthz` returns 500 | Database migration failed | `docker compose logs dsp-ai --tail 50`; common cause: wrong `DATABASE_URL` |
| Port 8260 or 8261 already in use | Another service on the host | Change host-side port in `docker-compose.yml` or stop the conflicting service |
| Migration error: `relation already exists` | Stale DB from a previous install | `docker compose down -v && docker compose up -d` (drops all volumes) |
| Widget not loading in SAC | CORS rejected | Check `WIDGET_ALLOWED_ORIGINS` matches exact SAC origin including `https://`; restart `dsp-ai` |
| Ollama model pull stalls | Disk full | Free at least 15 GB before starting offline profile |
| Neo4j password change after first boot | Neo4j ignores env on existing data | `docker compose down -v neo4j && docker compose up -d neo4j` (wipes graph — back up first) |
| `docker compose logs worker` shows LLM timeout | LLM provider unreachable | Verify `LLM_PROVIDER` and endpoint vars; check network connectivity from inside container: `docker compose exec worker curl $LLM_ROUTER_URL/health` |

---

## 11. Session C Safety Notes

### Multi-tenant RLS

- The `CUSTOMER` env var scopes all `dsp_ai.*` Postgres reads/writes via Row-Level Security policies.
- Every query runs as a tenant-specific role. Changing `CUSTOMER` after data is written requires a data migration.
- Do not set `CUSTOMER=default` in a real customer deployment — use their tenant identifier.

### Cost guardrails

- Enforced by default (`COST_GUARD_ENFORCED=true`).
- Monthly caps reset at 00:00 UTC on the 1st of each month.
- If a cap is reached, the enhancement returns a 402 response and logs the event.
- Set `COST_GUARD_ENFORCED=false` in `.env` for development or demo environments where real spend should not block requests.

### JWT authentication

- `DSPAI_AUTH_ENFORCED=false` is the default — all `/v1/*` routes are open (suitable for internal LAN demo).
- Set `DSPAI_AUTH_ENFORCED=true` and a strong `DSPAI_JWT_SECRET` before exposing the API on the internet or to SAC.
- `STUDIO_AUTHOR_EMAILS` controls who gets the `author` role; all other authenticated users are `viewer`.

---

*Last updated: Session C, Task 10*
