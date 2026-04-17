"""Knowledge learner — extracts patterns from scan results and writes to knowledge base.

Analyses a ScanResult (naming conventions, layer distribution, object type inventory,
SQL patterns, dependency graph shape) and upserts the findings as knowledge_items
with source="scan_auto".  No LLM calls — pure counting and regex.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict
from typing import Optional

import asyncpg

from spec2sphere.scanner.models import ScanResult
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB helper — same pattern used throughout the scanner package
# ---------------------------------------------------------------------------


async def _get_conn() -> asyncpg.Connection:
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


# ---------------------------------------------------------------------------
# Learner
# ---------------------------------------------------------------------------


class KnowledgeLearner:
    """Analyzes scan results and auto-generates knowledge items."""

    # Confidence levels (no LLM — these are factual counts or heuristic patterns)
    _CONFIDENCE_FACTUAL: float = 0.9  # inventories: counts are exact
    _CONFIDENCE_PATTERN: float = 0.7  # conventions / patterns: inferred by regex/heuristic

    def __init__(self) -> None:
        # No db_url stored — we open a fresh connection per upsert call so the
        # learner stays stateless and thread-safe without a connection pool.
        pass

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def learn_from_scan(
        self,
        ctx: ContextEnvelope,
        result: ScanResult,
    ) -> dict:
        """Extract and persist patterns from a scan result.

        Returns: {"patterns_found": int, "patterns_new": int, "patterns_updated": int}
        """
        if not result.objects:
            return {"patterns_found": 0, "patterns_new": 0, "patterns_updated": 0}

        patterns: list[dict] = []
        patterns.extend(self._extract_naming_conventions(result))
        patterns.extend(self._extract_layer_distribution(result))
        patterns.extend(self._extract_object_type_inventory(result))
        patterns.extend(self._extract_sql_patterns(result))
        patterns.extend(self._extract_dependency_patterns(result))

        new_count = 0
        updated_count = 0

        for item in patterns:
            created = await self._upsert_knowledge_item(
                ctx=ctx,
                title=item["title"],
                content=item["content"],
                category=item["category"],
                confidence=item["confidence"],
            )
            if created:
                new_count += 1
            else:
                updated_count += 1

        logger.info(
            "knowledge_learner: patterns_found=%d new=%d updated=%d customer=%s project=%s",
            len(patterns),
            new_count,
            updated_count,
            ctx.customer_id,
            ctx.project_id,
        )
        return {
            "patterns_found": len(patterns),
            "patterns_new": new_count,
            "patterns_updated": updated_count,
        }

    # ------------------------------------------------------------------
    # Extraction helpers — pure logic, no I/O
    # ------------------------------------------------------------------

    def _extract_naming_conventions(self, result: ScanResult) -> list[dict]:
        """Detect naming prefix patterns per layer."""
        # Group objects by layer, find common 2–8 character uppercase prefixes
        by_layer: dict[str, list[str]] = defaultdict(list)
        for obj in result.objects:
            layer = obj.layer or "unknown"
            name = obj.technical_name or obj.name
            by_layer[layer].append(name)

        items: list[dict] = []
        for layer, names in by_layer.items():
            if len(names) < 2:
                continue

            prefix_counts: Counter = Counter()
            for name in names:
                uname = name.upper()
                # SAP BW names often start with digits (e.g. "01_LT_SALES").
                # Try two patterns: plain alpha prefix, then digit+underscore+alpha prefix.
                m = re.match(r"^([A-Z]{2,8}[_/]?)", uname) or re.match(r"^(\d{1,2}[_/][A-Z]{2,8}[_/]?)", uname)
                if m:
                    prefix_counts[m.group(1)] += 1

            if not prefix_counts:
                continue

            dominant_prefix, count = prefix_counts.most_common(1)[0]
            pct = count / len(names)
            if pct < 0.4:
                # No dominant prefix — not a noteworthy convention
                continue

            items.append(
                {
                    "title": f"Naming convention: {layer} layer prefix '{dominant_prefix}'",
                    "content": (
                        f"In the '{layer}' architecture layer, {count} of {len(names)} objects "
                        f"({pct:.0%}) use the naming prefix '{dominant_prefix}'. "
                        f"Sample objects: {', '.join(names[:5])}."
                    ),
                    "category": "convention",
                    "confidence": self._CONFIDENCE_PATTERN,
                }
            )

        return items

    def _extract_layer_distribution(self, result: ScanResult) -> list[dict]:
        """Summarize object distribution across architecture layers."""
        layer_counts: Counter = Counter()
        for obj in result.objects:
            layer_counts[obj.layer or "unknown"] += 1

        total = len(result.objects)
        lines = [
            f"Total objects scanned: {total}",
            "",
            "Distribution by architecture layer:",
        ]
        anomalies: list[str] = []
        for layer, count in sorted(layer_counts.items(), key=lambda x: -x[1]):
            pct = count / total
            lines.append(f"  {layer}: {count} ({pct:.0%})")
            if layer == "unknown" and pct > 0.5:
                anomalies.append(f"Over half of objects ({count}/{total}) have no layer assigned.")
            if count == 1:
                anomalies.append(f"Layer '{layer}' has only 1 object — possible orphan or misconfiguration.")

        if anomalies:
            lines.append("")
            lines.append("Anomalies detected:")
            for a in anomalies:
                lines.append(f"  - {a}")

        return [
            {
                "title": "Layer distribution overview",
                "content": "\n".join(lines),
                "category": "pattern",
                "confidence": self._CONFIDENCE_FACTUAL,
            }
        ]

    def _extract_object_type_inventory(self, result: ScanResult) -> list[dict]:
        """Inventory of object types discovered."""
        type_counts: Counter = Counter()
        for obj in result.objects:
            type_counts[obj.object_type.value] += 1

        total = len(result.objects)
        lines = [f"Object type inventory ({total} total objects):"]
        for otype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {otype}: {count}")

        # Flag unusual types (anything that isn't table/view/adso/transformation)
        common_types = {"table", "view", "adso", "transformation", "infoobject"}
        unusual = [t for t in type_counts if t not in common_types]
        if unusual:
            lines.append("")
            lines.append(f"Unusual object types found: {', '.join(unusual)}")

        return [
            {
                "title": "Object type inventory",
                "content": "\n".join(lines),
                "category": "inventory",
                "confidence": self._CONFIDENCE_FACTUAL,
            }
        ]

    def _extract_sql_patterns(self, result: ScanResult) -> list[dict]:
        """Detect SQL patterns and anti-patterns in view definitions / source code."""
        items: list[dict] = []

        # Collect all objects that have source_code
        objects_with_sql = [o for o in result.objects if o.source_code]
        if not objects_with_sql:
            return items

        total_sql = len(objects_with_sql)

        # Pattern checks — each returns (label, matching object names)
        checks = [
            ("SELECT *", re.compile(r"\bSELECT\s+\*", re.IGNORECASE)),
            ("UNION ALL", re.compile(r"\bUNION\s+ALL\b", re.IGNORECASE)),
            ("CASE expression", re.compile(r"\bCASE\b", re.IGNORECASE)),
            ("cross-space reference", re.compile(r"\bFROM\s+\w+\.\w+\.\w+", re.IGNORECASE)),
            ("subquery", re.compile(r"\(\s*SELECT\b", re.IGNORECASE)),
        ]

        for label, pattern in checks:
            matches = [o.technical_name or o.name for o in objects_with_sql if pattern.search(o.source_code)]
            if not matches:
                continue

            pct = len(matches) / total_sql
            is_antipattern = label == "SELECT *"
            category = "quirk" if is_antipattern else "pattern"
            note = " (anti-pattern: prefer explicit column lists)" if is_antipattern else ""

            items.append(
                {
                    "title": f"SQL pattern: {label}{' usage' if not is_antipattern else ' anti-pattern'}",
                    "content": (
                        f"{len(matches)} of {total_sql} objects with SQL use '{label}'{note}. "
                        f"({pct:.0%} prevalence). "
                        f"Affected objects: {', '.join(matches[:10])}" + (" and more..." if len(matches) > 10 else ".")
                    ),
                    "category": category,
                    "confidence": self._CONFIDENCE_PATTERN,
                }
            )

        return items

    def _extract_dependency_patterns(self, result: ScanResult) -> list[dict]:
        """Analyse dependency graph shape — hubs, leaves, orphans."""
        if not result.dependencies:
            if result.objects:
                return [
                    {
                        "title": "Dependency graph: no dependencies found",
                        "content": (
                            f"None of the {len(result.objects)} scanned objects have recorded "
                            "dependencies. This may indicate the scan did not capture dependency "
                            "information, or all objects are standalone."
                        ),
                        "category": "pattern",
                        "confidence": self._CONFIDENCE_FACTUAL,
                    }
                ]
            return []

        # Count how many times each object appears as a dependency target (fan-in)
        fan_in: Counter = Counter()
        fan_out: Counter = Counter()
        all_ids = {obj.object_id for obj in result.objects}

        for dep in result.dependencies:
            fan_out[dep.source_id] += 1
            fan_in[dep.target_id] += 1

        # Hub: referenced by many (top 10% by fan-in, minimum 3)
        hub_threshold = max(3, sorted(fan_in.values(), reverse=True)[len(fan_in) // 10] if fan_in else 3)
        hubs = [(oid, cnt) for oid, cnt in fan_in.most_common() if cnt >= hub_threshold]

        # Orphans: in object set but appear in neither side of any dependency
        dep_participants = set(fan_in.keys()) | set(fan_out.keys())
        orphans = [obj for obj in result.objects if obj.object_id not in dep_participants]

        # Leaves: objects with fan-out 0 (no outgoing deps) that are not orphans
        leaves = [obj for obj in result.objects if obj.object_id not in fan_out and obj.object_id in dep_participants]

        lines = [
            f"Dependency graph summary ({len(result.dependencies)} edges, {len(result.objects)} nodes):",
            "",
            f"  Hub objects (referenced by ≥{hub_threshold} others): {len(hubs)}",
        ]
        if hubs:
            # Resolve IDs to names where possible
            id_to_name = {obj.object_id: (obj.technical_name or obj.name) for obj in result.objects}
            hub_names = [f"{id_to_name.get(oid, oid)} ({cnt})" for oid, cnt in hubs[:5]]
            lines.append(f"    {', '.join(hub_names)}")

        lines += [
            f"  Leaf objects (no outgoing dependencies): {len(leaves)}",
            f"  Orphan objects (no dependencies at all): {len(orphans)}",
        ]

        if orphans:
            orphan_names = [obj.technical_name or obj.name for obj in orphans[:5]]
            lines.append(f"    Orphans: {', '.join(orphan_names)}" + (" ..." if len(orphans) > 5 else ""))

        return [
            {
                "title": "Dependency graph structure",
                "content": "\n".join(lines),
                "category": "pattern",
                "confidence": self._CONFIDENCE_FACTUAL,
            }
        ]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _find_existing(
        self,
        conn: asyncpg.Connection,
        ctx: ContextEnvelope,
        title: str,
        category: str,
    ) -> Optional[str]:
        """Return the UUID string of an existing knowledge item with the same
        title + category scoped to this tenant/customer/project, or None."""
        row = await conn.fetchrow(
            """
            SELECT id FROM knowledge_items
            WHERE tenant_id = $1
              AND customer_id = $2
              AND ($3::uuid IS NULL OR project_id = $3)
              AND title = $4
              AND category = $5
            LIMIT 1
            """,
            ctx.tenant_id,
            ctx.customer_id,
            ctx.project_id,
            title,
            category,
        )
        return str(row["id"]) if row else None

    async def _upsert_knowledge_item(
        self,
        ctx: ContextEnvelope,
        title: str,
        content: str,
        category: str,
        confidence: float,
    ) -> bool:
        """Upsert a knowledge item.

        Returns True if a new row was created, False if an existing row was updated.
        Embeddings are intentionally skipped (source="scan_auto"; no LLM budget).
        """
        conn = await _get_conn()
        try:
            existing_id = await self._find_existing(conn, ctx, title, category)

            if existing_id:
                await conn.execute(
                    """
                    UPDATE knowledge_items
                       SET content    = $1,
                           confidence = $2,
                           source     = 'scan_auto'
                     WHERE id = $3::uuid
                    """,
                    content,
                    confidence,
                    existing_id,
                )
                return False  # updated
            else:
                import uuid as _uuid  # noqa: PLC0415

                item_id = _uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO knowledge_items
                        (id, tenant_id, customer_id, project_id,
                         category, title, content,
                         embedding, source, confidence)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, 'scan_auto', $8)
                    """,
                    item_id,
                    ctx.tenant_id,
                    ctx.customer_id,
                    ctx.project_id,
                    category,
                    title,
                    content,
                    confidence,
                )
                return True  # created
        finally:
            await conn.close()
