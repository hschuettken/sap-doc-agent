#!/usr/bin/env bash
# Spec2Sphere backup: pg_dump + neo4j dump + redis save + library export.
# Usage: ./scripts/backup.sh [output_dir]
set -euo pipefail

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="${BACKUP_DIR:-./backups}/${STAMP}"
WEB_PORT="${SPEC2SPHERE_PORT:-8260}"
mkdir -p "$OUT"

echo "▶ Dumping PostgreSQL..."
docker compose exec -T postgres pg_dump -U spec2sphere spec2sphere > "${OUT}/postgres.sql"

echo "▶ Dumping Neo4j..."
docker compose exec -T neo4j neo4j-admin database dump neo4j --to-path=/var/lib/neo4j/backups 2>/dev/null || \
    docker compose exec -T neo4j neo4j-admin dump --database=neo4j --to=/var/lib/neo4j/backups/neo4j.dump 2>/dev/null || \
    echo "  (neo4j dump skipped — check neo4j-admin version)"
docker compose cp neo4j:/var/lib/neo4j/backups/neo4j.dump "${OUT}/neo4j.dump" 2>/dev/null || \
    echo "  (neo4j dump file not copied — continuing)"

echo "▶ Saving Redis..."
docker compose exec -T redis redis-cli SAVE > /dev/null
docker compose cp redis:/data/dump.rdb "${OUT}/redis.rdb" 2>/dev/null || \
    echo "  (redis rdb not copied — continuing)"

echo "▶ Exporting enhancement library..."
curl -fs "http://localhost:${WEB_PORT}/ai-studio/library/export" > "${OUT}/library.json" || \
    echo "  (library export skipped — service may be down)"

echo "▶ Creating tarball..."
tar -czf "${OUT}.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
rm -rf "$OUT"

echo "→ Backup: ${OUT}.tar.gz"
