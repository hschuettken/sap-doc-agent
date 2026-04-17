#!/usr/bin/env bash
# Spec2Sphere demo bootstrap — compose up + import CPG library + publish 3 enhancements.
# Target: fresh machine, ≤10 minutes to demo-ready.
#
# Usage:
#   bash scripts/demo_bootstrap.sh
#
# Optional environment:
#   STUDIO_AUTHOR_EMAIL  Email used in import API header (default: author@example.com)
#   SKIP_COMPOSE         Set to 1 to skip docker compose up (stack already running)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> [1/5] Checking prerequisites"
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose plugin missing"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found"; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl not found"; exit 1; }
echo "   prerequisites OK"

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example (review and fill in secrets)"
  cp .env.example .env
fi

# Ensure NEO4J_PASSWORD is set (neo4j will fail with an empty or missing password)
if ! grep -qE '^NEO4J_PASSWORD=.+' .env 2>/dev/null; then
  NEO4J_PASS="$(openssl rand -hex 16)"
  echo "NEO4J_PASSWORD=${NEO4J_PASS}" >> .env
  echo "==> Generated random NEO4J_PASSWORD and appended to .env"
fi

# Ensure DSPAI_JWT_SECRET is set (auth will be disabled without it, which is fine for demo)
if ! grep -qE '^DSPAI_JWT_SECRET=.+' .env 2>/dev/null; then
  JWT_SECRET="$(openssl rand -hex 32)"
  echo "DSPAI_JWT_SECRET=${JWT_SECRET}" >> .env
  echo "==> Generated random DSPAI_JWT_SECRET and appended to .env"
fi

echo "==> [2/5] Starting services"
if [ "${SKIP_COMPOSE:-0}" = "1" ]; then
  echo "   SKIP_COMPOSE=1 — skipping docker compose up"
else
  docker compose up -d
fi

echo "==> [3/5] Waiting for dsp-ai to be healthy (max 120s)..."
READY=0
for i in $(seq 1 60); do
  if curl -sf http://localhost:8261/v1/healthz >/dev/null 2>&1; then
    echo "   dsp-ai ready after $((i * 2))s"
    READY=1
    break
  fi
  sleep 2
done

if [ "$READY" = "0" ]; then
  echo "ERROR: dsp-ai did not become ready within 120s"
  echo "Hint: docker compose logs dsp-ai --tail 50"
  exit 1
fi

# Also wait for Studio (web) to be accessible
WEB_READY=0
for i in $(seq 1 30); do
  if curl -sf http://localhost:8260/ >/dev/null 2>&1; then
    echo "   studio web ready after $((i * 2))s"
    WEB_READY=1
    break
  fi
  sleep 2
done
if [ "$WEB_READY" = "0" ]; then
  echo "WARNING: studio web did not become ready within 60s — continuing anyway"
fi

echo "==> [4/5] Importing CPG reference library"
LIBRARY="libraries/cpg_retail/export.json"
if [ -f "$LIBRARY" ]; then
  IMPORT_RESULT="$(curl -fsS -X POST http://localhost:8260/ai-studio/library/import \
       -F "file=@${LIBRARY}" \
       -F "mode=merge" \
       -H "X-User-Email: ${STUDIO_AUTHOR_EMAIL:-author@example.com}" \
       2>&1)" || true
  echo "   $IMPORT_RESULT"
else
  echo "   (skipped — $LIBRARY not found)"
fi

echo "==> [5/5] Publishing first 3 enhancements"
# If DSPAI_AUTO_PUBLISH_SEEDS is set in .env, seeds auto-publish on startup.
# Otherwise, print guidance — the publish endpoint requires an enhancement ID.
if grep -qE '^DSPAI_AUTO_PUBLISH_SEEDS=true' .env 2>/dev/null; then
  echo "   DSPAI_AUTO_PUBLISH_SEEDS=true detected — seeds published on startup"
else
  echo "   Tip: add DSPAI_AUTO_PUBLISH_SEEDS=true to .env and restart to auto-publish seeds"
  echo "   Or publish manually via Studio: http://localhost:8260/ai-studio/"
fi

echo
echo "============================================"
echo " Demo ready."
echo ""
echo "   Studio:  http://localhost:8260/ai-studio/"
echo "   API:     http://localhost:8261"
echo "   Health:  http://localhost:8261/v1/healthz"
echo "   Widget:  http://localhost:8261/widget/manifest.json"
echo ""
echo "   Author login: set STUDIO_AUTHOR_EMAILS=your@email.com in .env"
echo "   Demo script:  docs/deploy/demo_script.md"
echo "============================================"
