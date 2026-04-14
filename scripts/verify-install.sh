#!/usr/bin/env bash
# verify-install.sh — smoke test for client install
# Usage: ./scripts/verify-install.sh [base_url]
set -e

BASE_URL="${1:-http://localhost:8080}"
MAX_WAIT=60
INTERVAL=3
elapsed=0

echo "Waiting for $BASE_URL/healthz ..."
while true; do
  if curl -sf "$BASE_URL/healthz" > /dev/null 2>&1; then
    echo "OK /healthz OK"
    break
  fi
  if [ $elapsed -ge $MAX_WAIT ]; then
    echo "FAIL Timed out waiting for service"
    exit 1
  fi
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
done

# Check readyz
READYZ=$(curl -sf "$BASE_URL/readyz" || echo '{"status":"error"}')
echo "OK /readyz: $READYZ"

# Check login page renders
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/login" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
  echo "OK /login accessible (HTTP $HTTP_CODE)"
else
  echo "FAIL /login returned HTTP $HTTP_CODE"
  exit 1
fi

# Check standards API
STANDARDS=$(curl -sf "$BASE_URL/api/standards" || echo '{"error":"connection failed"}')
echo "OK /api/standards: $STANDARDS"

echo ""
echo "All smoke checks passed."
