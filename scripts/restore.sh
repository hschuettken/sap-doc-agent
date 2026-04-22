#!/usr/bin/env bash
# Spec2Sphere restore from backup tarball.
# Usage: ./scripts/restore.sh <backup.tar.gz>
set -euo pipefail

TARBALL="${1:-}"
if [[ -z "$TARBALL" || ! -f "$TARBALL" ]]; then
    echo "Usage: $0 <backup.tar.gz>" >&2
    exit 1
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "▶ Extracting ${TARBALL}..."
tar -xzf "$TARBALL" -C "$TMPDIR"
BACKUP_DIR=$(ls -d "$TMPDIR"/*)

echo "▶ Restoring PostgreSQL..."
docker compose exec -T postgres psql -U spec2sphere -c "DROP SCHEMA IF EXISTS dsp_ai CASCADE;" spec2sphere > /dev/null 2>&1 || true
docker compose exec -T postgres psql -U spec2sphere spec2sphere < "${BACKUP_DIR}/postgres.sql"

if [[ -f "${BACKUP_DIR}/neo4j.dump" ]]; then
    echo "▶ Restoring Neo4j..."
    docker compose cp "${BACKUP_DIR}/neo4j.dump" neo4j:/var/lib/neo4j/backups/neo4j.dump
    docker compose exec -T neo4j neo4j-admin database load neo4j \
        --from-path=/var/lib/neo4j/backups --overwrite-destination 2>/dev/null || \
        docker compose exec -T neo4j neo4j-admin load --database=neo4j \
        --from=/var/lib/neo4j/backups/neo4j.dump --force 2>/dev/null || \
        echo "  (neo4j restore skipped — check neo4j-admin version)"
fi

if [[ -f "${BACKUP_DIR}/redis.rdb" ]]; then
    echo "▶ Restoring Redis..."
    docker compose stop redis
    docker compose cp "${BACKUP_DIR}/redis.rdb" redis:/data/dump.rdb
    docker compose start redis
fi

echo "✓ Restore complete. Run 'docker compose restart' if services were stopped."
