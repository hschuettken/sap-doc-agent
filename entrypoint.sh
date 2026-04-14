#!/bin/sh
set -e

# Run Alembic migrations if DATABASE_URL is set and this is the web process
if [ -n "$DATABASE_URL" ] && echo "$@" | grep -q "uvicorn"; then
    echo "[entrypoint] Running database migrations..."
    # Convert psycopg URL to standard postgresql for alembic
    export ALEMBIC_DB_URL=$(echo "$DATABASE_URL" | sed 's|postgresql+psycopg://|postgresql://|' | sed 's|postgresql+asyncpg://|postgresql://|')
    python -c "
import subprocess, sys, os
try:
    result = subprocess.run(
        ['alembic', 'upgrade', 'head'],
        capture_output=True, text=True, timeout=30,
        cwd='/app'
    )
    if result.returncode == 0:
        print('[entrypoint] Migrations complete')
    else:
        print(f'[entrypoint] Migration warning: {result.stderr}', file=sys.stderr)
except Exception as e:
    print(f'[entrypoint] Migration skipped: {e}', file=sys.stderr)
" 2>&1 || true
fi

exec "$@"
