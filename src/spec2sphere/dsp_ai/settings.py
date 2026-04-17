"""Runtime settings accessors for the dsp_ai package.

Kept deliberately small — the existing spec2sphere.config module is
YAML-driven and doesn't expose a DSN object, so this provides the
DSN/URL helpers dsp_ai stages need without refactoring the global
config.
"""

from __future__ import annotations

import os


def _normalize_pg(url: str) -> str:
    """Strip SQLAlchemy driver prefixes — asyncpg needs a plain postgresql:// URL."""
    return (
        url.replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )


def postgres_dsn() -> str:
    """DSN for the spec2sphere Postgres (hosts dsp_ai.* schema)."""
    return _normalize_pg(os.environ.get("DATABASE_URL", ""))


def dsp_dsn() -> str:
    """DSN for the customer's DSP direct-DB connection.

    Falls back to the primary DATABASE_URL so dev + smoke tests can run
    without a separate DSP tenant. Production deploys override via
    ``DSP_DATABASE_URL``.
    """
    return _normalize_pg(os.environ.get("DSP_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))
