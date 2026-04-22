#!/usr/bin/env bash
# Demo bootstrap: bring up Spec2Sphere, import the CPG/Retail library, publish 3 enhancements.
# Usage: ./scripts/demo_bootstrap.sh [--offline]
set -euo pipefail

COMPOSE_CMD="docker compose"
WEB_PORT="${SPEC2SPHERE_PORT:-8260}"
DSPAI_PORT="${DSPAI_PORT:-8261}"
EXTRA_FILES=""

if [[ "${1:-}" == "--offline" ]]; then
    EXTRA_FILES="-f docker-compose.offline.yml --profile offline"
    echo "▶ Starting in offline mode (Ollama bundled)"
fi

echo "▶ Starting Spec2Sphere..."
$COMPOSE_CMD $EXTRA_FILES up -d

echo "▶ Waiting for web service..."
until curl -fs "http://localhost:${WEB_PORT}/api/health" > /dev/null 2>&1; do
    sleep 2
done

echo "▶ Waiting for dsp-ai service..."
until curl -fs "http://localhost:${DSPAI_PORT}/v1/healthz" > /dev/null 2>&1; do
    sleep 2
done

echo "▶ Importing CPG/Retail library..."
curl -fs -X POST "http://localhost:${WEB_PORT}/ai-studio/library/import" \
     -F "file=@libraries/cpg_retail/export.json" \
     -F "mode=merge" \
     -H "X-User-Email: bootstrap@spec2sphere" | python3 -m json.tool

echo "▶ Publishing first 3 enhancements..."
ENHANCEMENTS=$(curl -fs "http://localhost:${WEB_PORT}/ai-studio/api/enhancements" 2>/dev/null | \
    python3 -c "import json,sys; data=json.load(sys.stdin); [print(e['id']) for e in data[:3]]" 2>/dev/null || echo "")

if [[ -z "$ENHANCEMENTS" ]]; then
    echo "  (no enhancements found via API — publish manually in the Studio)"
else
    while IFS= read -r eid; do
        [[ -z "$eid" ]] && continue
        curl -fs -X POST "http://localhost:${WEB_PORT}/ai-studio/${eid}/publish" \
             -H "X-User-Email: bootstrap@spec2sphere" > /dev/null && echo "  published: $eid"
    done <<< "$ENHANCEMENTS"
fi

echo ""
echo "✓ Spec2Sphere is ready."
echo "  Studio:        http://localhost:${WEB_PORT}/ai-studio/"
echo "  Widget manifest: http://localhost:${WEB_PORT}/widget/manifest.json"
echo "  DSP-AI health:  http://localhost:${DSPAI_PORT}/v1/readyz"
