"""Content hub: aggregates all Spec2Sphere knowledge for external consumption.

Provides a structured view of knowledge files, standards, SAP objects,
migration guides, architecture docs, quality gates, and a glossary.
All content is read lazily on request — no preloading.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Project root: two levels up from src/spec2sphere/copilot/
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

_KNOWLEDGE_DIR = _PROJECT_ROOT / "knowledge" / "shared"
_STANDARDS_DIR = _PROJECT_ROOT / "standards" / "horvath"

# ------------------------------------------------------------------ helpers --


def _md_to_html(text: str) -> str:
    """Convert markdown to HTML. Uses the `markdown` library if available,
    falls back to a simple regex-based converter."""
    try:
        import markdown as _md  # type: ignore

        return _md.markdown(text, extensions=["fenced_code", "tables"])
    except ImportError:
        pass

    # Simple regex fallback
    html = text
    # Remove YAML frontmatter
    if html.startswith("---"):
        parts = html.split("---", 2)
        if len(parts) >= 3:
            html = parts[2].lstrip("\n")

    # Code blocks (must come before inline code)
    html = re.sub(r"```[\w]*\n(.*?)```", r"<pre><code>\1</code></pre>", html, flags=re.DOTALL)
    # Headings
    html = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    # Bold / inline code
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    # List items
    html = re.sub(r"^[-*] (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

    # Tables (simple: | col | col |)
    def _table_row(m: re.Match) -> str:
        cells = [c.strip() for c in m.group(1).split("|") if c.strip()]
        tag = "th" if m.group(2) else "td"
        return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"

    # Paragraphs
    html = html.replace("\n\n", "</p><p>")
    return f"<p>{html}</p>"


def _yaml_to_readable_html(data: dict | list, depth: int = 0) -> str:  # noqa: PLR0912
    """Recursively convert a YAML dict/list to readable HTML."""
    if isinstance(data, dict):
        if depth == 0:
            parts = []
            for k, v in data.items():
                title = str(k).replace("_", " ").title()
                if isinstance(v, (dict, list)):
                    inner = _yaml_to_readable_html(v, depth + 1)
                    parts.append(f"<h3>{title}</h3>{inner}")
                else:
                    parts.append(f"<p><strong>{title}:</strong> {v}</p>")
            return "\n".join(parts)
        else:
            rows = ""
            for k, v in data.items():
                label = str(k).replace("_", " ").title()
                if isinstance(v, (dict, list)):
                    cell = _yaml_to_readable_html(v, depth + 1)
                else:
                    cell = str(v)
                rows += f"<tr><td><strong>{label}</strong></td><td>{cell}</td></tr>"
            return f"<table><tbody>{rows}</tbody></table>"
    elif isinstance(data, list):
        items = "".join(
            f"<li>{_yaml_to_readable_html(item, depth + 1) if isinstance(item, (dict, list)) else item}</li>"
            for item in data
        )
        return f"<ul>{items}</ul>"
    else:
        return str(data)


def _file_mtime(path: Path) -> str:
    """Return ISO 8601 mtime string for a file, or now if file missing."""
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _excerpt(html: str, max_chars: int = 200) -> str:
    """Strip HTML tags and return a plain-text excerpt."""
    plain = re.sub(r"<[^>]+>", "", html)
    plain = " ".join(plain.split())
    return plain[:max_chars] + ("…" if len(plain) > max_chars else "")


# ----------------------------------------------------------------- sections --

_SECTION_META: dict[str, dict] = {
    "knowledge": {
        "title": "Knowledge Base",
        "description": "SAP BW/4HANA and Datasphere best practices, HANA SQL patterns, DSP quirks, UI mappings.",
        "icon": "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
    },
    "standards": {
        "title": "Horvath Standards",
        "description": "Quality gates, documentation standards, code standards, and modeling guidelines from Horvath Analytics.",
        "icon": "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
    },
    "architecture": {
        "title": "Architecture Guide",
        "description": "4-layer architecture, naming conventions, persistence strategy, and design patterns.",
        "icon": "M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10",
    },
    "migration": {
        "title": "Migration Guides",
        "description": "Step-by-step guides for migrating SAP objects and data models to Datasphere.",
        "icon": "M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4",
    },
    "quality": {
        "title": "Quality Framework",
        "description": "Quality gates, audit criteria, and how to interpret quality reports.",
        "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4",
    },
    "glossary": {
        "title": "Glossary",
        "description": "Key terms: SAP Datasphere, SAC, BW/4HANA, HANA SQL, and Horvath delivery concepts.",
        "icon": "M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129",
    },
}


# ---------------------------------------------------------------- ContentHub --


class ContentHub:
    """Aggregates Spec2Sphere content for external consumption.

    All methods are synchronous (no DB calls) — content comes from the
    filesystem (knowledge/ and standards/ directories).

    Session B adds async helpers that read from the Corporate Brain
    (Neo4j) — see ``list_topics``, ``objects_for_topic``, ``lookup_object``.
    These degrade to filesystem or empty results when Brain is unavailable.
    """

    # --------------------------------------------------------------- brain --

    async def list_topics(self) -> list[dict]:
        """Return Corporate Brain :Topic nodes — best-effort."""
        try:
            from spec2sphere.dsp_ai.brain.client import run as brain_run

            rows = await brain_run("MATCH (t:Topic) RETURN t.name AS name, t.vector AS vector")
            return [dict(r) for r in rows]
        except Exception:
            logger.debug("list_topics: brain unreachable, returning empty", exc_info=True)
            return []

    async def objects_for_topic(self, topic: str) -> list[dict]:
        """Return DspObjects correlated with a Topic — best-effort."""
        try:
            from spec2sphere.dsp_ai.brain.client import run as brain_run

            rows = await brain_run(
                "MATCH (o:DspObject)-[:CORRELATED_WITH|INTERESTED_IN]-(t:Topic {name:$t}) "
                "RETURN DISTINCT o.id AS id, o.name AS name, o.kind AS kind",
                t=topic,
            )
            return [dict(r) for r in rows]
        except Exception:
            logger.debug("objects_for_topic: brain unreachable", exc_info=True)
            return []

    async def lookup_object(self, object_id: str) -> Optional[dict]:
        """Resolve a DSP object by ID — prefers Brain, falls back to graph.json file.

        Returns ``{id, name, kind, columns}`` or None. Consumer (e.g. the
        Copilot MCP ``get_object`` tool) can then read the matching
        consultant-facing ``.md`` via its own filesystem walk.
        """
        try:
            from spec2sphere.dsp_ai.brain.client import run as brain_run

            rows = await brain_run(
                "MATCH (o:DspObject {id:$id}) "
                "OPTIONAL MATCH (o)-[:HAS_COLUMN]->(c:Column) "
                "RETURN o.id AS id, o.name AS name, o.kind AS kind, "
                "collect(DISTINCT c.id) AS column_ids LIMIT 1",
                id=object_id,
            )
            if rows:
                return dict(rows[0])
        except Exception:
            logger.debug("lookup_object: brain unreachable", exc_info=True)

        # Fallback: scan legacy graph.json through the dual-read helper
        try:
            from spec2sphere.scanner.graph_repo import list_objects

            all_objs = await list_objects()
            for o in all_objs:
                if o.get("id") == object_id:
                    return o
        except Exception:
            logger.debug("lookup_object: graph_repo fallback failed", exc_info=True)
        return None

    # ---------------------------------------------------------------- index --

    def get_index(self) -> dict:
        """Return top-level section listing with page counts."""
        sections = []
        for section_id, meta in _SECTION_META.items():
            pages = self._list_pages(section_id)
            sections.append(
                {
                    "id": section_id,
                    "title": meta["title"],
                    "description": meta["description"],
                    "icon": meta["icon"],
                    "page_count": len(pages),
                    "url": f"/copilot/{section_id}",
                }
            )
        return {
            "title": "Spec2Sphere Knowledge Hub",
            "description": (
                "Authoritative reference for SAP Datasphere and SAC delivery. "
                "Covers best practices, quality standards, architecture patterns, "
                "migration guides, and the Horvath Analytics delivery methodology."
            ),
            "sections": sections,
        }

    # -------------------------------------------------------------- section --

    def get_section(self, section_id: str) -> dict | None:
        """Return a section with its list of pages."""
        if section_id not in _SECTION_META:
            return None
        meta = _SECTION_META[section_id]
        pages = self._list_pages(section_id)
        return {
            "id": section_id,
            "title": meta["title"],
            "description": meta["description"],
            "pages": pages,
            "breadcrumbs": [
                {"label": "Hub", "url": "/copilot"},
                {"label": meta["title"], "url": f"/copilot/{section_id}"},
            ],
        }

    # --------------------------------------------------------------- pages --

    def get_page(self, section_id: str, page_id: str) -> dict | None:
        """Return a specific page with rendered content."""
        if section_id not in _SECTION_META:
            return None

        content_md, content_html, title, updated_at = self._load_page(section_id, page_id)
        if content_md is None:
            return None

        related = [p for p in self._list_pages(section_id) if p["id"] != page_id][:4]
        meta = _SECTION_META[section_id]
        return {
            "id": page_id,
            "section_id": section_id,
            "title": title,
            "content_md": content_md,
            "content_html": content_html,
            "updated_at": updated_at,
            "breadcrumbs": [
                {"label": "Hub", "url": "/copilot"},
                {"label": meta["title"], "url": f"/copilot/{section_id}"},
                {"label": title, "url": f"/copilot/{section_id}/{page_id}"},
            ],
            "related": related,
        }

    # --------------------------------------------------------------- search --

    def search(self, query: str, section: Optional[str] = None) -> list[dict]:
        """Full-text search across all (or one) section's content."""
        q = query.lower().strip()
        if not q:
            return []

        results: list[dict] = []
        target_sections = [section] if section and section in _SECTION_META else list(_SECTION_META.keys())

        for sec_id in target_sections:
            for page_info in self._list_pages(sec_id):
                pid = page_info["id"]
                md, html, title, updated_at = self._load_page(sec_id, pid)
                if md is None:
                    continue
                search_text = (title + " " + md).lower()
                if q in search_text:
                    idx = search_text.find(q)
                    snippet = md[max(0, idx - 80) : idx + 200].strip()
                    results.append(
                        {
                            "section_id": sec_id,
                            "section_title": _SECTION_META[sec_id]["title"],
                            "page_id": pid,
                            "title": title,
                            "snippet": snippet,
                            "url": f"/copilot/{sec_id}/{pid}",
                            "updated_at": updated_at,
                        }
                    )

        return results

    # ------------------------------------------------------- internal helpers -

    def _list_pages(self, section_id: str) -> list[dict]:
        """Return page stubs for a section."""
        pages: list[dict] = []
        for loader in self._page_loaders(section_id):
            pid, title, excerpt, updated_at = loader()
            pages.append(
                {
                    "id": pid,
                    "title": title,
                    "excerpt": excerpt,
                    "updated_at": updated_at,
                    "url": f"/copilot/{section_id}/{pid}",
                }
            )
        return pages

    def _page_loaders(self, section_id: str):
        """Return a list of callables, each returning (id, title, excerpt, updated_at)."""
        if section_id == "knowledge":
            return self._knowledge_page_loaders()
        elif section_id == "standards":
            return self._standards_page_loaders()
        elif section_id == "architecture":
            return self._architecture_page_loaders()
        elif section_id == "migration":
            return self._migration_page_loaders()
        elif section_id == "quality":
            return self._quality_page_loaders()
        elif section_id == "glossary":
            return self._glossary_page_loaders()
        return []

    def _load_page(self, section_id: str, page_id: str) -> tuple[str | None, str, str, str]:
        """Return (markdown, html, title, updated_at) for section/page or (None, '', '', '')."""
        loaders = {
            "knowledge": self._load_knowledge_page,
            "standards": self._load_standards_page,
            "architecture": self._load_architecture_page,
            "migration": self._load_migration_page,
            "quality": self._load_quality_page,
            "glossary": self._load_glossary_page,
        }
        loader = loaders.get(section_id)
        if loader is None:
            return None, "", "", ""
        return loader(page_id)

    # ------------------------------------------------- knowledge section -----

    def _knowledge_page_loaders(self):
        loaders = []
        if not _KNOWLEDGE_DIR.exists():
            return loaders
        for md_file in sorted(_KNOWLEDGE_DIR.glob("*.md")):
            path = md_file

            def _make(p: Path):
                def _loader():
                    pid = p.stem
                    try:
                        text = p.read_text(encoding="utf-8")
                        title = self._title_from_md(text) or pid.replace("_", " ").title()
                        html = _md_to_html(text)
                        excerpt = _excerpt(html)
                        return pid, title, excerpt, _file_mtime(p)
                    except OSError:
                        return pid, pid.replace("_", " ").title(), "", _file_mtime(p)

                return _loader

            loaders.append(_make(path))
        return loaders

    def _load_knowledge_page(self, page_id: str) -> tuple[str | None, str, str, str]:
        path = _KNOWLEDGE_DIR / f"{page_id}.md"
        if not path.exists():
            return None, "", "", ""
        try:
            text = path.read_text(encoding="utf-8")
            title = self._title_from_md(text) or page_id.replace("_", " ").title()
            return text, _md_to_html(text), title, _file_mtime(path)
        except OSError:
            return None, "", "", ""

    # ------------------------------------------------- standards section -----

    def _standards_page_loaders(self):
        loaders = []
        if not _STANDARDS_DIR.exists():
            return loaders
        for f in sorted(_STANDARDS_DIR.iterdir()):
            if f.suffix not in {".yaml", ".yml", ".md"}:
                continue
            path = f

            def _make(p: Path):
                def _loader():
                    pid = p.stem
                    title = pid.replace("_", " ").title()
                    try:
                        md, html = self._render_standard(p)
                        return pid, title, _excerpt(html), _file_mtime(p)
                    except Exception:
                        return pid, title, "", _file_mtime(p)

                return _loader

            loaders.append(_make(path))
        return loaders

    def _load_standards_page(self, page_id: str) -> tuple[str | None, str, str, str]:
        for suffix in [".yaml", ".yml", ".md"]:
            path = _STANDARDS_DIR / f"{page_id}{suffix}"
            if path.exists():
                try:
                    md, html = self._render_standard(path)
                    title = page_id.replace("_", " ").title()
                    return md, html, title, _file_mtime(path)
                except Exception as exc:
                    logger.warning("Failed to render standard %s: %s", page_id, exc)
                    return None, "", "", ""
        return None, "", "", ""

    def _render_standard(self, path: Path) -> tuple[str, str]:
        """Render a standard file to (markdown-ish text, html)."""
        if path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            return text, _md_to_html(text)
        # YAML
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        html = _yaml_to_readable_html(data)
        # Build a simple markdown representation
        md_lines = [f"# {path.stem.replace('_', ' ').title()}\n"]
        md_lines.append(f"*Source: `{path.name}`*\n\n")
        md_lines.append("This standard is maintained in YAML format. Key sections:\n\n")
        for k in data:
            md_lines.append(f"- **{str(k).replace('_', ' ').title()}**\n")
        return "".join(md_lines), html

    # ----------------------------------------------- architecture section ---

    def _architecture_page_loaders(self):
        return [
            lambda: (
                "overview",
                "Architecture Overview",
                "4-layer architecture: raw, harmonized, analytical, consumption.",
                "",
            ),
            lambda: ("naming-conventions", "Naming Conventions", "Object naming rules for DSP and SAC.", ""),
            lambda: (
                "persistence-strategy",
                "Persistence Strategy",
                "Local table, remote table, and replication strategies.",
                "",
            ),
            lambda: ("design-patterns", "Design Patterns", "Common patterns for data flows and transformations.", ""),
        ]

    def _load_architecture_page(self, page_id: str) -> tuple[str | None, str, str, str]:
        pages = {
            "overview": self._arch_overview,
            "naming-conventions": self._arch_naming,
            "persistence-strategy": self._arch_persistence,
            "design-patterns": self._arch_design_patterns,
        }
        fn = pages.get(page_id)
        if fn is None:
            return None, "", "", ""
        md = fn()
        return md, _md_to_html(md), page_id.replace("-", " ").title(), ""

    def _arch_overview(self) -> str:
        return """# Architecture Overview

## 4-Layer Data Architecture

Spec2Sphere follows a strict 4-layer architecture for SAP Datasphere:

### Layer 1 — Raw (R_)
- Source-aligned structures
- No transformations, no business logic
- Prefix: `R_`

### Layer 2 — Harmonized (H_)
- Cleansed, deduplicated, standardized data
- Surrogate keys generated here
- Prefix: `H_`

### Layer 3 — Analytical (A_)
- Business model layer
- Fact and dimension tables
- Prefix: `A_`

### Layer 4 — Consumption (C_)
- Analytical datasets for SAC
- Optimized for reporting performance
- Prefix: `C_`

## Key Principles

- Every object belongs to exactly one layer
- No skip-layer references (R_ cannot directly feed C_)
- All layer transitions are explicit and documented
"""

    def _arch_naming(self) -> str:
        return """# Naming Conventions

## General Rules

- Maximum 40 characters for technical names
- Use snake_case for all technical names
- Use prefix to indicate layer and type

## DSP Object Prefixes

| Prefix | Layer | Type |
|--------|-------|------|
| `R_` | Raw | Any |
| `H_` | Harmonized | Any |
| `A_` | Analytical | Any |
| `C_` | Consumption | Any |
| `F_` | Any | Flow / transformation |
| `V_` | Any | View |

## Examples

- `R_SALES_ORDER` — Raw sales order table
- `H_SALES_ORDER` — Harmonized sales order
- `A_SALES_FACT` — Analytical sales fact table
- `C_SALES_REVENUE` — Consumption view for SAC

## SAC Conventions

- Stories: `[Client]_[Domain]_[Topic]_Story`
- Models: `[Client]_[Domain]_[Topic]_Model`
- Dimensions: `DIM_[EntityName]`
"""

    def _arch_persistence(self) -> str:
        return """# Persistence Strategy

## Object Types

### Local Tables
- Use for harmonized and analytical layers
- Best for frequently queried data
- Supports partitioning and indices

### Remote Tables
- Use for raw layer when data volume is large
- No storage cost in DSP
- Performance depends on source system connectivity

### Replication Flows
- Use to copy remote data into local tables
- Scheduled or real-time via change data capture
- Required for cross-system joins

## Decision Matrix

| Scenario | Recommended Approach |
|----------|---------------------|
| High query frequency | Local table |
| Large volume, infrequent queries | Remote table |
| Need for offline analytics | Replication to local |
| Near-real-time updates | CDC replication flow |
| Cross-system join | Both sides local |
"""

    def _arch_design_patterns(self) -> str:
        return """# Design Patterns

## Star Schema Pattern
The standard analytical model pattern:
- One central fact table (`A_*_FACT`)
- Multiple dimension tables (`A_DIM_*`)
- Surrogate keys as join keys
- Business keys preserved as attributes

## Slowly Changing Dimensions (SCD)
- Type 1: Overwrite (default for reference data)
- Type 2: History rows with valid_from / valid_to
- Type 3: Current + previous columns (rarely used)

## Data Flow Composition
```
Source → R_TABLE → [Replication Flow] → H_TABLE → A_TABLE → C_VIEW
```

## Error Handling
- All flows must have error output targets
- Failed records go to `ERR_[SourceTable]`
- Error tables include: source_key, error_code, error_message, load_timestamp

## Incremental Loading
- Use `LOAD_DATE` technical column in all tables
- Delta loads via change tracking or high-watermark
- Full loads only for small reference data
"""

    # ------------------------------------------------ migration section ------

    def _migration_page_loaders(self):
        return [
            lambda: (
                "bw-to-datasphere",
                "BW to Datasphere Migration",
                "Migrating BW InfoProviders to Datasphere objects.",
                "",
            ),
            lambda: (
                "object-classification",
                "Object Classification",
                "How to classify legacy objects for migration.",
                "",
            ),
            lambda: ("validation-checklist", "Validation Checklist", "Post-migration validation steps.", ""),
        ]

    def _load_migration_page(self, page_id: str) -> tuple[str | None, str, str, str]:
        pages = {
            "bw-to-datasphere": self._migration_bw_dsp,
            "object-classification": self._migration_classification,
            "validation-checklist": self._migration_validation,
        }
        fn = pages.get(page_id)
        if fn is None:
            return None, "", "", ""
        md = fn()
        return md, _md_to_html(md), page_id.replace("-", " ").title(), ""

    def _migration_bw_dsp(self) -> str:
        return """# BW to Datasphere Migration Guide

## Overview
Migrating from SAP BW/4HANA to SAP Datasphere requires mapping legacy BW objects
to their Datasphere equivalents.

## Object Mapping

| BW Object | Datasphere Equivalent |
|-----------|----------------------|
| DataStore Object (DSO) | Local Table + Data Flow |
| InfoCube | Analytical Dataset |
| InfoObject | Dimension / Master Data Table |
| Transformation | Data Flow |
| Process Chain | Task Chain |
| Query | Analytical Dataset (SAC Story) |

## Migration Steps

1. **Classify objects** — Use the object classification guide
2. **Assess dependencies** — Map upstream and downstream objects
3. **Design target model** — Follow 4-layer architecture
4. **Generate DSP objects** — Use Spec2Sphere factory
5. **Validate data** — Run reconciliation checks
6. **Deploy to production** — Follow Horvath deployment standard

## Common Pitfalls

- InfoObject attributes need to be denormalized in Datasphere
- BW aggregation levels map to Analytical Datasets with pre-aggregation
- Process Chains with parallel steps need careful Task Chain design
"""

    def _migration_classification(self) -> str:
        return """# Object Classification for Migration

## Classification Dimensions

Each legacy BW object is classified on three axes:

### Complexity
- **Low**: Direct structural mapping, no business logic
- **Medium**: Some transformation or aggregation logic
- **High**: Complex business logic, multiple sources, or custom code

### Effort (days)
- Low: 0.5 – 1 day
- Medium: 2 – 5 days
- High: 5 – 15 days

### Priority
- **P1**: Core objects required for go-live
- **P2**: Important but not blocking
- **P3**: Nice to have, can be deferred

## Classification Rules

```
IF type IN (DSO, InfoCube) AND row_count < 1M → Low complexity
IF type = InfoObject AND attributes < 10 → Low complexity
IF custom_code = True → High complexity
IF source_count > 3 → High complexity
```
"""

    def _migration_validation(self) -> str:
        return """# Post-Migration Validation Checklist

## Data Completeness
- [ ] Row counts match source (±0.1% tolerance)
- [ ] No null values in key fields
- [ ] Date ranges complete (no gaps)
- [ ] All expected partitions present

## Data Accuracy
- [ ] Aggregated totals match source
- [ ] Spot-check 10 random records per object
- [ ] Year-end totals verified
- [ ] Currency conversion consistent

## Performance
- [ ] Query response < 5s for standard reports
- [ ] Data load within agreed SLA window
- [ ] No table scans on large fact tables

## Functional
- [ ] SAC stories render correctly
- [ ] All filters functional
- [ ] Drill-down paths work
- [ ] Calculated measures correct
"""

    # -------------------------------------------------- quality section ------

    def _quality_page_loaders(self):
        # Try to read from standards directory for quality gates
        loaders = []
        quality_path = _STANDARDS_DIR / "quality_gates_standard.yaml"
        if quality_path.exists():
            loaders.append(
                lambda: ("quality-gates", "Quality Gates", "Automated quality gate checks.", _file_mtime(quality_path))
            )
        loaders.extend(
            [
                lambda: ("scoring", "Scoring Model", "How quality scores are calculated.", ""),
                lambda: ("audit-guide", "Audit Guide", "How to interpret audit results.", ""),
            ]
        )
        return loaders

    def _load_quality_page(self, page_id: str) -> tuple[str | None, str, str, str]:
        if page_id == "quality-gates":
            path = _STANDARDS_DIR / "quality_gates_standard.yaml"
            if path.exists():
                md, html = self._render_standard(path)
                return md, html, "Quality Gates", _file_mtime(path)
        if page_id == "scoring":
            md = self._quality_scoring()
            return md, _md_to_html(md), "Scoring Model", ""
        if page_id == "audit-guide":
            md = self._quality_audit_guide()
            return md, _md_to_html(md), "Audit Guide", ""
        return None, "", "", ""

    def _quality_scoring(self) -> str:
        return """# Documentation Quality Scoring

## Score Components

Quality scores are calculated as a weighted sum of section scores:

| Section | Weight | Description |
|---------|--------|-------------|
| Executive Summary | 15% | Purpose, scope, stakeholders |
| Architecture | 25% | Layer design, object map |
| Data Model | 20% | Tables, relationships, keys |
| Data Flows | 20% | Transformations, lineage |
| Technical Specs | 10% | SQL, filters, calculations |
| Testing | 10% | Test cases, acceptance criteria |

## Scoring Levels

- **95–100**: Excellent — ready for production
- **80–94**: Good — minor improvements recommended
- **60–79**: Acceptable — specific gaps need addressing
- **40–59**: Needs work — significant sections missing
- **< 40**: Insufficient — major rework required

## Automated Checks

- Section presence (is the section there at all?)
- Content depth (minimum word count per section)
- Required fields (stakeholders named, dates present)
- Cross-references (objects referenced exist in scan)
"""

    def _quality_audit_guide(self) -> str:
        return """# Interpreting Audit Results

## Audit Report Structure

Each audit run produces:
1. **Overall score** (0–100)
2. **Section scores** — per-section breakdown
3. **Issues list** — specific gaps with severity
4. **Suggestions** — actionable improvements

## Issue Severity

| Severity | Meaning | Action Required |
|----------|---------|----------------|
| Critical | Core section missing | Must fix before approval |
| High | Important content absent | Fix in current sprint |
| Medium | Could be improved | Address in next revision |
| Low | Minor improvement | Nice to have |

## Common Issues

- **Missing executive summary**: Add purpose and scope paragraph
- **No stakeholder list**: Name responsible business and IT contacts
- **Undocumented SQL**: Add inline comments to all SQL transformations
- **Missing test cases**: Add at least 3 acceptance criteria per object

## Gap Analysis (Horvath vs Client Standard)

When comparing against both standards, the gap analysis shows:
- Fields present in Horvath but missing in client standard
- Fields present in client standard but not in Horvath
- Fields present in both with conflicting requirements
"""

    # ------------------------------------------------- glossary section ------

    def _glossary_page_loaders(self):
        terms = self._build_glossary()
        # Group into alphabetical pages
        groups: dict[str, list] = {}
        for term in terms:
            letter = term["term"][0].upper()
            groups.setdefault(letter, []).append(term)

        loaders = []
        for letter in sorted(groups.keys()):
            grp = groups[letter]

            def _make(l: str, g: list):
                excerpt = ", ".join(t["term"] for t in g[:3])
                return lambda: (f"terms-{l.lower()}", f"Terms: {l}", excerpt, "")

            loaders.append(_make(letter, grp))
        return loaders

    def _load_glossary_page(self, page_id: str) -> tuple[str | None, str, str, str]:
        if not page_id.startswith("terms-"):
            return None, "", "", ""
        letter = page_id.replace("terms-", "").upper()
        terms = [t for t in self._build_glossary() if t["term"].upper().startswith(letter)]
        if not terms:
            return None, "", "", ""
        lines = [f"# Glossary: {letter}\n\n"]
        for t in sorted(terms, key=lambda x: x["term"]):
            lines.append(f"## {t['term']}\n\n{t['definition']}\n\n")
        md = "".join(lines)
        return md, _md_to_html(md), f"Glossary: {letter}", ""

    def _build_glossary(self) -> list[dict]:
        return [
            {
                "term": "Analytical Dataset",
                "definition": "A DSP object type used for analytical processing, typically feeding SAC. Combines fact and dimension data with pre-aggregations.",
            },
            {
                "term": "CDC",
                "definition": "Change Data Capture. A technique for detecting and propagating incremental data changes from source systems.",
            },
            {
                "term": "Consumption Layer",
                "definition": "The top layer (C_) of the 4-layer architecture, optimized for SAC reporting. Views and analytical datasets expose data to end users.",
            },
            {
                "term": "Data Flow",
                "definition": "A DSP object that defines a transformation pipeline from source to target, replacing BW Transformations.",
            },
            {
                "term": "DataStore Object (DSO)",
                "definition": "Legacy BW object for persistent data storage. Migrates to Local Table + Data Flow in Datasphere.",
            },
            {
                "term": "Datasphere (DSP)",
                "definition": "SAP Datasphere — the next-generation data integration and management platform, successor to SAP BW/4HANA.",
            },
            {
                "term": "Dimension",
                "definition": "A DSP master data entity representing a business dimension (customer, product, time). Corresponds to BW InfoObjects.",
            },
            {
                "term": "Entity-Relationship Model (E/R Model)",
                "definition": "A DSP modeling view that combines facts and dimensions into a star schema for analytical consumption.",
            },
            {
                "term": "Fact Table",
                "definition": "A central table in a star schema containing measurable business events (transactions, measurements).",
            },
            {
                "term": "Harmonized Layer",
                "definition": "Layer 2 (H_) of the 4-layer architecture. Contains cleansed, deduplicated data with business keys and surrogate keys.",
            },
            {
                "term": "Horvath",
                "definition": "Horvath Analytics — the consulting firm whose delivery methodology, standards, and quality gates are implemented in Spec2Sphere.",
            },
            {
                "term": "InfoCube",
                "definition": "Legacy BW star-schema object. Migrates to a combination of Dimension tables and Analytical Dataset in Datasphere.",
            },
            {
                "term": "InfoObject",
                "definition": "Legacy BW master data and characteristic/key figure definition. Migrates to Dimension or measure definition.",
            },
            {
                "term": "Local Table",
                "definition": "A DSP table stored physically in Datasphere (HANA). Best for frequently queried data in harmonized and analytical layers.",
            },
            {
                "term": "Quality Gate",
                "definition": "An automated check point that documentation or objects must pass before proceeding to the next delivery phase.",
            },
            {
                "term": "Raw Layer",
                "definition": "Layer 1 (R_) of the 4-layer architecture. Source-aligned structures with no transformation. Data lands here first.",
            },
            {
                "term": "Replication Flow",
                "definition": "A DSP object that copies data from a remote source into a local table, optionally with CDC for incremental updates.",
            },
            {
                "term": "Remote Table",
                "definition": "A DSP virtual table that queries data directly from a connected source system without storing a local copy.",
            },
            {
                "term": "SAC",
                "definition": "SAP Analytics Cloud — the cloud BI and planning platform. Consumes data from Datasphere Analytical Datasets.",
            },
            {
                "term": "SAP BW/4HANA",
                "definition": "The on-premise SAP data warehouse platform, predecessor to Datasphere. Many Spec2Sphere clients migrate from BW/4HANA.",
            },
            {
                "term": "Spec2Sphere",
                "definition": "The Horvath Analytics delivery accelerator — AI-governed toolchain for SAP Datasphere + SAC delivery, documentation, and quality assurance.",
            },
            {
                "term": "Star Schema",
                "definition": "A dimensional modeling pattern with a central fact table surrounded by dimension tables. The standard analytical model in Datasphere.",
            },
            {
                "term": "Surrogate Key",
                "definition": "A system-generated key (integer or UUID) used as the join key in star schemas, replacing business keys for join performance.",
            },
            {
                "term": "Task Chain",
                "definition": "A DSP object that orchestrates the sequential or parallel execution of Data Flows and Replication Flows, replacing BW Process Chains.",
            },
            {
                "term": "Technical Object",
                "definition": "Any DSP object created by Spec2Sphere: tables, views, data flows, replication flows, dimensions, analytical datasets.",
            },
        ]

    # ---------------------------------------------------- shared helpers ------

    @staticmethod
    def _title_from_md(text: str) -> str:
        """Extract the first H1 heading from markdown text."""
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""
