"""Corporate Brain schema — constraints + indexes.

Idempotent: ``bootstrap()`` is safe to call on every service start.
"""

from __future__ import annotations

from .client import run

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT dsp_object_id IF NOT EXISTS FOR (n:DspObject) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT column_id IF NOT EXISTS FOR (n:Column) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT domain_name IF NOT EXISTS FOR (n:Domain) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT glossary_term IF NOT EXISTS FOR (n:Glossary) REQUIRE n.term IS UNIQUE",
    "CREATE CONSTRAINT user_email IF NOT EXISTS FOR (n:User) REQUIRE n.email IS UNIQUE",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (n:Topic) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:Event) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT enhancement_id IF NOT EXISTS FOR (n:Enhancement) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT generation_id IF NOT EXISTS FOR (n:Generation) REQUIRE n.id IS UNIQUE",
]

INDEXES: list[str] = [
    "CREATE INDEX dsp_object_customer IF NOT EXISTS FOR (n:DspObject) ON (n.customer)",
    "CREATE INDEX event_ts IF NOT EXISTS FOR (n:Event) ON (n.ts)",
]


async def bootstrap() -> None:
    """Ensure all constraints + indexes exist."""
    for stmt in CONSTRAINTS + INDEXES:
        await run(stmt)
