#!/usr/bin/env bash
# Spec2Sphere backup — dumps postgres + neo4j + redis + portable library.
# Output: timestamped tarball in $BACKUP_DIR (default ./backups/).
#
# Usage:
#   bash scripts/backup.sh
#
# Optional environment:
#   BACKUP_DIR         Destination directory (default: <repo-root>/backups)
#   POSTGRES_USER      Postgres superuser (default: sapdoc)
#   POSTGRES_DB        Postgres database name (default: sapdoc)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$BACKUP_DIR/$STAMP"
mkdir -p "$OUT_DIR"

echo "==> Spec2Sphere backup — $STAMP"
echo "    Output: $BACKUP_DIR/spec2sphere-backup-$STAMP.tar.gz"
echo

# Discover container IDs — empty string if service not running
POSTGRES_CONTAINER="$(docker compose ps -q postgres 2>/dev/null || true)"
NEO4J_CONTAINER="$(docker compose ps -q neo4j 2>/dev/null || true)"
REDIS_CONTAINER="$(docker compose ps -q redis 2>/dev/null || true)"

# --- [1/4] Postgres ---
echo "==> [1/4] Postgres dump"
if [ -n "$POSTGRES_CONTAINER" ]; then
  docker exec "$POSTGRES_CONTAINER" \
    pg_dump -U "${POSTGRES_USER:-sapdoc}" "${POSTGRES_DB:-sapdoc}" \
    > "$OUT_DIR/postgres.sql"
  PG_SIZE="$(wc -c < "$OUT_DIR/postgres.sql")"
  echo "    $PG_SIZE bytes written to postgres.sql"
else
  echo "    (skipped — postgres container not running)"
fi

# --- [2/4] Neo4j ---
echo "==> [2/4] Neo4j dump"
if [ -n "$NEO4J_CONTAINER" ]; then
  # neo4j-admin dump requires the database to be stopped or be a secondary.
  # For community edition running live, use online dump (available since Neo4j 5.x).
  docker exec "$NEO4J_CONTAINER" \
    neo4j-admin database dump neo4j --to-path=/tmp --overwrite-destination=true 2>&1 || true
  if docker cp "$NEO4J_CONTAINER:/tmp/neo4j.dump" "$OUT_DIR/neo4j.dump" 2>/dev/null; then
    NEO_SIZE="$(wc -c < "$OUT_DIR/neo4j.dump")"
    echo "    $NEO_SIZE bytes written to neo4j.dump"
  else
    echo "    (neo4j dump not found at /tmp/neo4j.dump — graph may be empty or dump failed)"
    echo "    Hint: docker compose logs neo4j --tail 20"
  fi
else
  echo "    (skipped — neo4j container not running)"
fi

# --- [3/4] Redis ---
echo "==> [3/4] Redis RDB snapshot"
if [ -n "$REDIS_CONTAINER" ]; then
  docker exec "$REDIS_CONTAINER" redis-cli SAVE >/dev/null 2>&1
  if docker cp "$REDIS_CONTAINER:/data/dump.rdb" "$OUT_DIR/redis.rdb" 2>/dev/null; then
    RDB_SIZE="$(wc -c < "$OUT_DIR/redis.rdb")"
    echo "    $RDB_SIZE bytes written to redis.rdb"
  else
    echo "    (redis dump not found at /data/dump.rdb — Redis may have no persistence enabled)"
  fi
else
  echo "    (skipped — redis container not running)"
fi

# --- [4/4] Portable library export ---
echo "==> [4/4] Portable library export"
if curl -fsS http://localhost:8260/ai-studio/library/export > "$OUT_DIR/library.json" 2>/dev/null; then
  LIB_SIZE="$(wc -c < "$OUT_DIR/library.json")"
  echo "    $LIB_SIZE bytes written to library.json"
else
  echo "    (skipped — studio not reachable on :8260; library not included in backup)"
  rm -f "$OUT_DIR/library.json"
fi

# --- Package tarball ---
TARBALL="$BACKUP_DIR/spec2sphere-backup-$STAMP.tar.gz"
tar -czf "$TARBALL" -C "$BACKUP_DIR" "$STAMP"
rm -rf "$OUT_DIR"

TARBALL_SIZE="$(ls -lh "$TARBALL" | awk '{print $5}')"
echo
echo "Backup complete."
echo "    $TARBALL ($TARBALL_SIZE)"
echo
echo "Restore with:"
echo "    bash scripts/restore.sh $TARBALL"
