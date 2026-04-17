#!/usr/bin/env bash
# Spec2Sphere restore — inverse of backup.sh.
# Extracts a backup tarball and restores Postgres, Neo4j, Redis, and the library.
#
# Usage:
#   bash scripts/restore.sh <path-to-tarball>
#
# IMPORTANT: Services must already be running before restoring.
#   Start them first: docker compose up -d
#
# WARNING: Postgres and Redis restores overwrite existing data.
# Neo4j restore requires the database to be offline (or --overwrite-destination).
#
# Optional environment:
#   POSTGRES_USER      Postgres superuser (default: sapdoc)
#   POSTGRES_DB        Postgres database name (default: sapdoc)
#   SKIP_LIBRARY       Set to 1 to skip the library re-import step

set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "usage: $0 <tarball.tar.gz>"
  exit 1
fi

TARBALL="$1"
if [ ! -f "$TARBALL" ]; then
  echo "ERROR: not found: $TARBALL"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Spec2Sphere restore"
echo "    Source: $TARBALL"
echo

# --- [1/5] Extract ---
echo "==> [1/5] Extracting tarball"
tar -xzf "$TARBALL" -C "$TMP"
STAMP_DIR="$(ls -1 "$TMP" | head -1)"
SRC="$TMP/$STAMP_DIR"

if [ ! -d "$SRC" ]; then
  echo "ERROR: unexpected tarball structure — expected a single top-level directory"
  exit 1
fi
echo "    Extracted: $STAMP_DIR"
echo "    Contents:"
ls -lh "$SRC"
echo

# --- Discover running containers ---
POSTGRES_CONTAINER="$(docker compose ps -q postgres 2>/dev/null || true)"
NEO4J_CONTAINER="$(docker compose ps -q neo4j 2>/dev/null || true)"
REDIS_CONTAINER="$(docker compose ps -q redis 2>/dev/null || true)"

if [ -z "$POSTGRES_CONTAINER" ]; then
  echo "ERROR: postgres container not running."
  echo "Start services first: docker compose up -d"
  exit 1
fi

# --- [2/5] Postgres ---
echo "==> [2/5] Restoring Postgres (overwrites existing data)"
if [ -f "$SRC/postgres.sql" ]; then
  PG_SIZE="$(wc -c < "$SRC/postgres.sql")"
  echo "    Applying $PG_SIZE bytes from postgres.sql..."
  cat "$SRC/postgres.sql" | docker exec -i "$POSTGRES_CONTAINER" \
    psql -U "${POSTGRES_USER:-sapdoc}" "${POSTGRES_DB:-sapdoc}" \
    -v ON_ERROR_STOP=0 > /dev/null
  echo "    Postgres restore done."
else
  echo "    (skipped — postgres.sql not in backup)"
fi

# --- [3/5] Neo4j ---
echo "==> [3/5] Restoring Neo4j"
if [ -f "$SRC/neo4j.dump" ] && [ -n "$NEO4J_CONTAINER" ]; then
  echo "    Copying neo4j.dump into container..."
  docker cp "$SRC/neo4j.dump" "$NEO4J_CONTAINER:/tmp/neo4j.dump"
  # --overwrite-destination requires db to exist; safe on fresh and existing installs
  docker exec "$NEO4J_CONTAINER" sh -c \
    "neo4j-admin database load neo4j --from-path=/tmp --overwrite-destination=true 2>&1" \
    || echo "    WARNING: neo4j load failed — the database may need to be stopped first. See docs."
  echo "    Neo4j restore done (restart neo4j service to activate)."
elif [ -f "$SRC/neo4j.dump" ]; then
  echo "    (skipped — neo4j container not running)"
else
  echo "    (skipped — neo4j.dump not in backup)"
fi

# --- [4/5] Redis ---
echo "==> [4/5] Restoring Redis"
if [ -f "$SRC/redis.rdb" ] && [ -n "$REDIS_CONTAINER" ]; then
  echo "    Copying dump.rdb into container..."
  docker cp "$SRC/redis.rdb" "$REDIS_CONTAINER:/data/dump.rdb"
  docker restart "$REDIS_CONTAINER" >/dev/null
  echo "    Redis restarted with restored RDB."
elif [ -f "$SRC/redis.rdb" ]; then
  echo "    (skipped — redis container not running)"
else
  echo "    (skipped — redis.rdb not in backup)"
fi

# --- [5/5] Library re-import ---
echo "==> [5/5] Re-importing portable library"
if [ "${SKIP_LIBRARY:-0}" = "1" ]; then
  echo "    (skipped — SKIP_LIBRARY=1)"
elif [ ! -f "$SRC/library.json" ]; then
  echo "    (skipped — library.json not in backup)"
else
  # Wait a moment for services to stabilise after Redis restart
  sleep 3
  if curl -fsS http://localhost:8260/ai-studio/library/import \
       -F "file=@$SRC/library.json" \
       -F "mode=replace" \
       >/dev/null 2>&1; then
    echo "    Library import done (mode=replace)."
  else
    echo "    WARNING: library import failed — studio may still be starting up."
    echo "    Retry manually:"
    echo "      curl -X POST http://localhost:8260/ai-studio/library/import \\"
    echo "           -F file=@$SRC/library.json -F mode=replace"
  fi
fi

echo
echo "Restore complete."
echo
echo "Verify with:"
echo "    curl http://localhost:8261/v1/healthz"
echo "    curl http://localhost:8260/ai-studio/"
echo
echo "If Neo4j data is missing, restart the neo4j container:"
echo "    docker compose restart neo4j"
