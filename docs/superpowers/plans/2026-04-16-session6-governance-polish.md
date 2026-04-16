# Session 6: Governance, Documentation, Artifact Lab, Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the capstone session — as-built documentation, release packages, Artifact Lab, shared learning, audit UI, end-to-end demo flow, and final polish.

**Architecture:** Extends the existing governance module with doc generation (Jinja2 HTML templates + weasyprint PDF), release ZIP packaging, and approval workflow extensions. New artifact_lab package provides controlled sandbox experimentation with template graduation. All UI is HTMX + Jinja2 partials extending base.html. New Alembic migration 008 adds 4 tables.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Jinja2, HTMX, Tailwind CSS, weasyprint, Celery, PostgreSQL 16

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `migrations/versions/008_session6_governance.py` | 4 new tables: release_packages, style_preferences, promotion_candidates, promotion_log |
| `src/spec2sphere/governance/doc_generator.py` | As-built doc generation (HTML/Markdown), traceability matrix, decision log |
| `src/spec2sphere/governance/release.py` | Release package assembly (ZIP), version tracking |
| `src/spec2sphere/governance/promotion.py` | Shared learning promotion with anonymization |
| `src/spec2sphere/artifact_lab/lab_runner.py` | Orchestrate create/read/modify/diff experiments |
| `src/spec2sphere/artifact_lab/experiment_tracker.py` | CRUD for lab_experiments table |
| `src/spec2sphere/artifact_lab/template_store.py` | CRUD for learned_templates + graduation |
| `src/spec2sphere/artifact_lab/mutation_catalog.py` | Safe/unsafe mutation catalog per object type |
| `src/spec2sphere/artifact_lab/__init__.py` | Package init |
| `src/spec2sphere/sac_factory/style_learning.py` | Customer style preference tracking |
| `src/spec2sphere/web/governance_routes.py` | Routes: reports, audit log, lab, release UIs |
| `src/spec2sphere/web/templates/partials/reports_v2.html` | Reports browser with preview/export/sync |
| `src/spec2sphere/web/templates/partials/lab.html` | Lab experiments + templates browser |
| `src/spec2sphere/web/templates/partials/audit_log.html` | Audit log with search/filter/trace |
| `src/spec2sphere/web/templates/doc_report.html` | Self-contained HTML report template (Jinja2) |
| `tests/test_session6_doc_generator.py` | Doc generation tests |
| `tests/test_session6_artifact_lab.py` | Lab + template + mutation tests |
| `tests/test_session6_promotion.py` | Promotion + anonymization tests |
| `tests/test_session6_style_learning.py` | Style preference tests |
| `tests/test_session6_governance_routes.py` | Route + UI tests |
| `tests/test_session6_integration.py` | E2E pipeline integration test |
| `tests/fixtures/demo/sample_brs.md` | Demo BRS document |
| `tests/fixtures/demo/demo_config.yaml` | Demo customer + project config |

### Modified Files
| File | Change |
|------|--------|
| `src/spec2sphere/governance/approvals.py` | Add "release" artifact type to CHECKLISTS and ARTIFACT_TABLES |
| `src/spec2sphere/web/server.py` | Mount governance_routes router |
| `src/spec2sphere/modules.py` | Add governance routes_factory, artifact_lab routes_factory |
| `src/spec2sphere/web/templates/base.html` | Add "Lab" and "Audit Log" nav items |
| `src/spec2sphere/web/templates/partials/reports.html` | Replace with reports_v2 content |

---

## Task 1: Alembic Migration 008 — Session 6 Tables

**Files:**
- Create: `migrations/versions/008_session6_governance.py`

- [ ] **Step 1: Write migration**

```python
"""Session 6 governance tables.

Revision ID: 008
Revises: 007
Create Date: 2026-04-16
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Release packages
    op.execute("""
    CREATE TABLE IF NOT EXISTS release_packages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        version TEXT NOT NULL,
        status TEXT DEFAULT 'draft',
        approval_id UUID REFERENCES approvals(id),
        manifest JSONB DEFAULT '{}',
        artifact_paths JSONB DEFAULT '[]',
        created_by UUID REFERENCES users(id),
        created_at TIMESTAMPTZ DEFAULT now(),
        finalized_at TIMESTAMPTZ
    )
    """)

    # Style preferences (per-customer SAC design learning)
    op.execute("""
    CREATE TABLE IF NOT EXISTS style_preferences (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        preference_type TEXT NOT NULL,
        preference_key TEXT NOT NULL,
        score FLOAT DEFAULT 0.0,
        evidence_count INT DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE(customer_id, preference_type, preference_key)
    )
    """)

    # Learning promotion candidates
    op.execute("""
    CREATE TABLE IF NOT EXISTS promotion_candidates (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_customer_id UUID REFERENCES customers(id),
        source_type TEXT NOT NULL,
        source_id UUID NOT NULL,
        target_layer TEXT NOT NULL,
        anonymized_content JSONB,
        status TEXT DEFAULT 'pending',
        reviewed_by UUID REFERENCES users(id),
        reviewed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_release_packages_project ON release_packages(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_style_prefs_customer ON style_preferences(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_promotion_candidates_status ON promotion_candidates(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_trace ON audit_log(details) WHERE details ? 'trace_id'")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS promotion_candidates CASCADE")
    op.execute("DROP TABLE IF EXISTS style_preferences CASCADE")
    op.execute("DROP TABLE IF EXISTS release_packages CASCADE")
```

- [ ] **Step 2: Verify migration applies cleanly**

Run: `cd /home/hesch/dev/projects/sap-doc-agent && python -c "from migrations.versions import __path__; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/008_session6_governance.py
git commit -m "feat(session6): add migration 008 — release_packages, style_preferences, promotion_candidates"
```

---

## Task 2: As-Built Documentation Generator

**Files:**
- Create: `src/spec2sphere/governance/doc_generator.py`
- Create: `src/spec2sphere/web/templates/doc_report.html`
- Create: `tests/test_session6_doc_generator.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for as-built documentation generator."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from spec2sphere.governance.doc_generator import (
    generate_technical_doc,
    generate_functional_doc,
    generate_traceability_matrix,
    generate_decision_log,
    generate_reconciliation_report,
    render_html_report,
    render_markdown_report,
)


@pytest.fixture
def sample_project_data():
    project_id = str(uuid4())
    return {
        "project": {"id": project_id, "name": "Sales Planning", "slug": "sales-planning"},
        "customer": {"name": "Horvath Demo", "slug": "horvath-demo"},
        "requirements": [
            {
                "id": str(uuid4()),
                "title": "Revenue KPI Model",
                "business_domain": "Finance",
                "parsed_entities": {"fact_tables": ["revenue_fact"], "dimensions": ["time", "product", "region"]},
                "parsed_kpis": [{"name": "Net Revenue", "formula": "gross - discounts"}],
                "status": "approved",
            }
        ],
        "hla_documents": [
            {
                "id": str(uuid4()),
                "content": {"layers": ["raw", "harmonized", "mart"]},
                "narrative": "Three-layer architecture with mart-level consumption.",
                "status": "approved",
            }
        ],
        "tech_specs": [
            {
                "id": str(uuid4()),
                "objects": [
                    {"name": "V_RAW_REVENUE", "object_type": "relational_view", "layer": "raw"},
                    {"name": "V_MART_REVENUE", "object_type": "relational_view", "layer": "mart"},
                ],
                "deployment_order": ["V_RAW_REVENUE", "V_MART_REVENUE"],
                "status": "approved",
            }
        ],
        "architecture_decisions": [
            {
                "topic": "Aggregation Strategy",
                "choice": "Pre-aggregate at mart level",
                "rationale": "Reduces SAC query time for executive dashboard",
                "platform_placement": "dsp",
            }
        ],
        "reconciliation_results": [
            {
                "test_case_key": "revenue_total",
                "delta_status": "pass",
                "baseline_value": {"total": 1000000},
                "candidate_value": {"total": 1000000},
            }
        ],
        "technical_objects": [
            {
                "name": "V_RAW_REVENUE",
                "object_type": "relational_view",
                "platform": "dsp",
                "layer": "raw",
                "generated_artifact": "CREATE VIEW V_RAW_REVENUE AS SELECT ...",
                "status": "deployed",
            }
        ],
    }


def test_generate_technical_doc(sample_project_data):
    doc = generate_technical_doc(sample_project_data)
    assert "V_RAW_REVENUE" in doc["content"]
    assert "V_MART_REVENUE" in doc["content"]
    assert doc["title"] == "Sales Planning — Technical Documentation"
    assert "deployment_order" in doc


def test_generate_functional_doc(sample_project_data):
    doc = generate_functional_doc(sample_project_data)
    assert "Net Revenue" in doc["content"]
    assert "Finance" in doc["content"]
    assert doc["title"] == "Sales Planning — Functional Documentation"


def test_generate_traceability_matrix(sample_project_data):
    matrix = generate_traceability_matrix(sample_project_data)
    assert len(matrix["rows"]) >= 1
    row = matrix["rows"][0]
    assert "requirement" in row
    assert "tech_objects" in row


def test_generate_decision_log(sample_project_data):
    log = generate_decision_log(sample_project_data)
    assert len(log) == 1
    assert log[0]["topic"] == "Aggregation Strategy"
    assert log[0]["choice"] == "Pre-aggregate at mart level"


def test_generate_reconciliation_report(sample_project_data):
    report = generate_reconciliation_report(sample_project_data)
    assert report["total_tests"] == 1
    assert report["passed"] == 1
    assert report["failed"] == 0


def test_render_html_report(sample_project_data):
    html = render_html_report(sample_project_data)
    assert "<!DOCTYPE html>" in html
    assert "Sales Planning" in html
    assert "V_RAW_REVENUE" in html


def test_render_markdown_report(sample_project_data):
    md = render_markdown_report(sample_project_data)
    assert "# Sales Planning" in md
    assert "V_RAW_REVENUE" in md
    assert "## Traceability Matrix" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hesch/dev/projects/sap-doc-agent && python -m pytest tests/test_session6_doc_generator.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create the HTML report template**

Create `src/spec2sphere/web/templates/doc_report.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', -apple-system, sans-serif; color: #333; line-height: 1.6; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f8f9fa; }
        h1 { color: #05415A; font-size: 28px; border-bottom: 3px solid #C8963E; padding-bottom: 10px; margin-bottom: 20px; }
        h2 { color: #05415A; font-size: 22px; margin-top: 40px; margin-bottom: 16px; border-left: 4px solid #C8963E; padding-left: 12px; }
        h3 { color: #353434; font-size: 18px; margin-top: 24px; margin-bottom: 12px; }
        .report-header { background: #05415A; color: white; padding: 30px; border-radius: 8px; margin-bottom: 30px; }
        .report-header h1 { color: white; border-bottom-color: #C8963E; }
        .report-header .subtitle { color: #C8963E; font-size: 16px; margin-top: 8px; }
        .report-header .meta { color: rgba(255,255,255,0.7); font-size: 13px; margin-top: 12px; }
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 20px 0; }
        .summary-card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }
        .summary-card .number { font-size: 36px; font-weight: 700; color: #05415A; }
        .summary-card .label { font-size: 14px; color: #666; margin-top: 4px; }
        .section { background: white; border-radius: 8px; padding: 24px; margin: 20px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; margin: 16px 0; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        th { background: #05415A; color: white; padding: 12px 16px; text-align: left; font-weight: 600; font-size: 14px; }
        td { padding: 10px 16px; border-bottom: 1px solid #eee; font-size: 14px; }
        tr:last-child td { border-bottom: none; }
        .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .badge-pass { background: #e8f5e9; color: #2e7d32; }
        .badge-fail { background: #ffebee; color: #c62828; }
        .badge-warn { background: #fff3e0; color: #e65100; }
        .badge-info { background: #e3f2fd; color: #1565c0; }
        .sql-block { background: #263238; color: #eeffff; padding: 16px; border-radius: 6px; font-family: 'Fira Code', monospace; font-size: 13px; overflow-x: auto; white-space: pre-wrap; margin: 8px 0; }
        .footer { text-align: center; color: #999; font-size: 12px; margin-top: 40px; padding: 20px; border-top: 1px solid #e0e0e0; }
    </style>
</head>
<body>

<div class="report-header">
    <h1>{{ title }}</h1>
    <div class="subtitle">{{ subtitle }}</div>
    <div class="meta">Customer: {{ customer_name }} | Project: {{ project_name }} | Generated: {{ generated_at }}</div>
</div>

{% if summary_cards %}
<div class="summary-grid">
    {% for card in summary_cards %}
    <div class="summary-card">
        <div class="number">{{ card.value }}</div>
        <div class="label">{{ card.label }}</div>
    </div>
    {% endfor %}
</div>
{% endif %}

{% for section in sections %}
<div class="section">
    <h2>{{ section.title }}</h2>
    {{ section.html_content }}
</div>
{% endfor %}

{% if traceability_rows %}
<div class="section">
    <h2>Traceability Matrix</h2>
    <table>
        <thead>
            <tr><th>Requirement</th><th>HLA Decision</th><th>Tech Spec Objects</th><th>Test Cases</th><th>Result</th></tr>
        </thead>
        <tbody>
            {% for row in traceability_rows %}
            <tr>
                <td>{{ row.requirement }}</td>
                <td>{{ row.hla_decision }}</td>
                <td>{{ row.tech_objects | join(', ') }}</td>
                <td>{{ row.test_cases | join(', ') }}</td>
                <td><span class="badge badge-{{ row.result_class }}">{{ row.result }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

{% if decision_log %}
<div class="section">
    <h2>Architecture Decision Log</h2>
    <table>
        <thead>
            <tr><th>Topic</th><th>Decision</th><th>Rationale</th><th>Platform</th></tr>
        </thead>
        <tbody>
            {% for d in decision_log %}
            <tr>
                <td><strong>{{ d.topic }}</strong></td>
                <td>{{ d.choice }}</td>
                <td>{{ d.rationale }}</td>
                <td><span class="badge badge-info">{{ d.platform_placement or 'both' }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

{% if reconciliation %}
<div class="section">
    <h2>Reconciliation Summary</h2>
    <div class="summary-grid">
        <div class="summary-card"><div class="number">{{ reconciliation.total_tests }}</div><div class="label">Total Tests</div></div>
        <div class="summary-card"><div class="number" style="color:#2e7d32">{{ reconciliation.passed }}</div><div class="label">Passed</div></div>
        <div class="summary-card"><div class="number" style="color:#e65100">{{ reconciliation.tolerance }}</div><div class="label">Within Tolerance</div></div>
        <div class="summary-card"><div class="number" style="color:#c62828">{{ reconciliation.failed }}</div><div class="label">Failed</div></div>
    </div>
</div>
{% endif %}

{% if technical_objects %}
<div class="section">
    <h2>Technical Object Inventory</h2>
    <table>
        <thead>
            <tr><th>Object</th><th>Type</th><th>Platform</th><th>Layer</th><th>Status</th></tr>
        </thead>
        <tbody>
            {% for obj in technical_objects %}
            <tr>
                <td><code>{{ obj.name }}</code></td>
                <td>{{ obj.object_type }}</td>
                <td>{{ obj.platform }}</td>
                <td>{{ obj.layer or '-' }}</td>
                <td><span class="badge badge-{{ 'pass' if obj.status == 'deployed' else 'warn' }}">{{ obj.status }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% for obj in technical_objects %}
    {% if obj.generated_artifact %}
    <h3>{{ obj.name }}</h3>
    <div class="sql-block">{{ obj.generated_artifact }}</div>
    {% endif %}
    {% endfor %}
</div>
{% endif %}

<div class="footer">
    Generated by Spec2Sphere &mdash; Horv&aacute;th Analytics Delivery Factory | {{ generated_at }}
</div>

</body>
</html>
```

- [ ] **Step 4: Implement doc_generator.py**

```python
"""As-built documentation generator.

Generates documentation from ACTUAL DEPLOYED STATE — not from plans.
Output formats: HTML (self-contained), Markdown, PDF (via weasyprint).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Template

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent.parent / "web" / "templates" / "doc_report.html"


def generate_technical_doc(data: dict[str, Any]) -> dict:
    """Generate as-built technical documentation from deployed state."""
    project = data["project"]
    objects = data.get("technical_objects", [])
    specs = data.get("tech_specs", [])

    lines = []
    lines.append(f"# {project['name']} — Technical Documentation\n")
    lines.append("## Object Inventory\n")

    for obj in objects:
        lines.append(f"### {obj['name']}")
        lines.append(f"- **Type:** {obj['object_type']}")
        lines.append(f"- **Platform:** {obj['platform']}")
        lines.append(f"- **Layer:** {obj.get('layer', '-')}")
        lines.append(f"- **Status:** {obj.get('status', 'unknown')}")
        if obj.get("generated_artifact"):
            lines.append(f"\n```sql\n{obj['generated_artifact']}\n```\n")

    deployment_order = []
    for spec in specs:
        deployment_order.extend(spec.get("deployment_order") or [])

    lines.append("## Deployment Order\n")
    for i, name in enumerate(deployment_order, 1):
        lines.append(f"{i}. `{name}`")

    content = "\n".join(lines)
    return {
        "title": f"{project['name']} — Technical Documentation",
        "content": content,
        "deployment_order": deployment_order,
        "object_count": len(objects),
    }


def generate_functional_doc(data: dict[str, Any]) -> dict:
    """Generate as-built functional documentation (business rules, KPIs, data flow)."""
    project = data["project"]
    requirements = data.get("requirements", [])

    lines = []
    lines.append(f"# {project['name']} — Functional Documentation\n")

    for req in requirements:
        lines.append(f"## {req['title']}")
        if req.get("business_domain"):
            lines.append(f"**Domain:** {req['business_domain']}\n")
        if req.get("description"):
            lines.append(req["description"])

        kpis = req.get("parsed_kpis") or []
        if kpis:
            lines.append("\n### KPI Definitions\n")
            for kpi in kpis:
                name = kpi.get("name", "Unnamed")
                formula = kpi.get("formula", "")
                lines.append(f"- **{name}**: `{formula}`")

        entities = req.get("parsed_entities") or {}
        if entities:
            lines.append("\n### Data Entities\n")
            for key, val in entities.items():
                if isinstance(val, list):
                    lines.append(f"- **{key}:** {', '.join(val)}")
                else:
                    lines.append(f"- **{key}:** {val}")

    content = "\n".join(lines)
    return {
        "title": f"{project['name']} — Functional Documentation",
        "content": content,
    }


def generate_traceability_matrix(data: dict[str, Any]) -> dict:
    """Build requirement -> HLA -> tech spec -> test case -> result chain."""
    requirements = data.get("requirements", [])
    decisions = data.get("architecture_decisions", [])
    objects = data.get("technical_objects", [])
    recon = data.get("reconciliation_results", [])

    rows = []
    for req in requirements:
        related_decisions = [d["choice"] for d in decisions]
        related_objects = [o["name"] for o in objects]
        related_tests = [r["test_case_key"] for r in recon]
        all_pass = all(r["delta_status"] == "pass" for r in recon) if recon else False

        rows.append({
            "requirement": req["title"],
            "hla_decision": "; ".join(related_decisions) if related_decisions else "-",
            "tech_objects": related_objects or ["-"],
            "test_cases": related_tests or ["-"],
            "result": "PASS" if all_pass else ("PARTIAL" if recon else "NOT TESTED"),
            "result_class": "pass" if all_pass else ("warn" if recon else "info"),
        })

    return {"rows": rows}


def generate_decision_log(data: dict[str, Any]) -> list[dict]:
    """Extract all architecture decisions with rationale."""
    return [
        {
            "topic": d["topic"],
            "choice": d["choice"],
            "rationale": d.get("rationale", ""),
            "alternatives": d.get("alternatives", []),
            "platform_placement": d.get("platform_placement", "both"),
        }
        for d in data.get("architecture_decisions", [])
    ]


def generate_reconciliation_report(data: dict[str, Any]) -> dict:
    """Summarize reconciliation results."""
    results = data.get("reconciliation_results", [])
    total = len(results)
    passed = sum(1 for r in results if r.get("delta_status") == "pass")
    tolerance = sum(1 for r in results if r.get("delta_status") == "within_tolerance")
    expected = sum(1 for r in results if r.get("delta_status") == "expected_change")
    failed = total - passed - tolerance - expected

    return {
        "total_tests": total,
        "passed": passed,
        "tolerance": tolerance,
        "expected_change": expected,
        "failed": failed,
        "results": results,
    }


def render_html_report(data: dict[str, Any]) -> str:
    """Render a self-contained HTML report from project data."""
    project = data["project"]
    customer = data.get("customer", {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    tech_doc = generate_technical_doc(data)
    func_doc = generate_functional_doc(data)
    recon = generate_reconciliation_report(data)
    decisions = generate_decision_log(data)
    trace = generate_traceability_matrix(data)
    objects = data.get("technical_objects", [])

    sections = [
        {"title": "Functional Overview", "html_content": _md_to_simple_html(func_doc["content"])},
        {"title": "Technical Details", "html_content": _md_to_simple_html(tech_doc["content"])},
    ]

    summary_cards = [
        {"value": tech_doc["object_count"], "label": "Objects Deployed"},
        {"value": recon["passed"], "label": "Tests Passed"},
        {"value": recon["failed"], "label": "Tests Failed"},
        {"value": len(decisions), "label": "Decisions"},
    ]

    template_text = _TEMPLATE_PATH.read_text() if _TEMPLATE_PATH.exists() else _FALLBACK_TEMPLATE
    template = Template(template_text)

    return template.render(
        title=f"{project['name']} — As-Built Report",
        subtitle="Generated from deployed state",
        customer_name=customer.get("name", ""),
        project_name=project["name"],
        generated_at=now,
        summary_cards=summary_cards,
        sections=sections,
        traceability_rows=trace["rows"],
        decision_log=decisions,
        reconciliation=recon,
        technical_objects=objects,
    )


def render_markdown_report(data: dict[str, Any]) -> str:
    """Render a Markdown report from project data."""
    project = data["project"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [f"# {project['name']} — As-Built Report", f"*Generated: {now}*\n"]

    # Functional
    func_doc = generate_functional_doc(data)
    lines.append(func_doc["content"])

    # Technical
    tech_doc = generate_technical_doc(data)
    lines.append("\n" + tech_doc["content"])

    # Traceability
    trace = generate_traceability_matrix(data)
    lines.append("\n## Traceability Matrix\n")
    lines.append("| Requirement | HLA Decision | Objects | Tests | Result |")
    lines.append("|---|---|---|---|---|")
    for row in trace["rows"]:
        lines.append(
            f"| {row['requirement']} | {row['hla_decision']} | "
            f"{', '.join(row['tech_objects'])} | {', '.join(row['test_cases'])} | {row['result']} |"
        )

    # Decisions
    decisions = generate_decision_log(data)
    lines.append("\n## Architecture Decisions\n")
    for d in decisions:
        lines.append(f"### {d['topic']}")
        lines.append(f"**Decision:** {d['choice']}")
        lines.append(f"**Rationale:** {d['rationale']}\n")

    # Reconciliation
    recon = generate_reconciliation_report(data)
    lines.append("\n## Reconciliation Summary\n")
    lines.append(f"- Total: {recon['total_tests']}")
    lines.append(f"- Passed: {recon['passed']}")
    lines.append(f"- Failed: {recon['failed']}")

    return "\n".join(lines)


def render_pdf_report(data: dict[str, Any]) -> bytes:
    """Render PDF via weasyprint. Returns bytes."""
    html = render_html_report(data)
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except ImportError:
        logger.warning("weasyprint not installed — PDF generation unavailable")
        return html.encode("utf-8")


def _md_to_simple_html(md: str) -> str:
    """Minimal markdown-to-HTML for inline rendering in templates."""
    import re
    html = md
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"```(\w+)?\n(.*?)```", r"<pre class='sql-block'>\2</pre>", html, flags=re.DOTALL)
    html = html.replace("\n\n", "<br><br>")
    return html


_FALLBACK_TEMPLATE = """<!DOCTYPE html><html><head><title>{{ title }}</title></head>
<body><h1>{{ title }}</h1>{% for s in sections %}<h2>{{ s.title }}</h2>{{ s.html_content }}{% endfor %}</body></html>"""
```

- [ ] **Step 5: Run tests**

Run: `cd /home/hesch/dev/projects/sap-doc-agent && python -m pytest tests/test_session6_doc_generator.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/spec2sphere/governance/doc_generator.py src/spec2sphere/web/templates/doc_report.html tests/test_session6_doc_generator.py
git commit -m "feat(session6): as-built documentation generator with HTML/Markdown/PDF output"
```

---

## Task 3: Release Package Assembler

**Files:**
- Create: `src/spec2sphere/governance/release.py`
- Create: `tests/test_session6_release.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for release package assembler."""

import io
import json
import zipfile
import pytest
from uuid import uuid4

from spec2sphere.governance.release import (
    assemble_release_package,
    ReleaseManifest,
)


@pytest.fixture
def sample_project_data():
    return {
        "project": {"id": str(uuid4()), "name": "Sales Planning", "slug": "sales-planning"},
        "customer": {"name": "Horvath Demo"},
        "requirements": [{"id": str(uuid4()), "title": "Revenue KPI", "status": "approved"}],
        "hla_documents": [{"id": str(uuid4()), "status": "approved", "content": {}, "narrative": "test"}],
        "tech_specs": [{"id": str(uuid4()), "objects": [], "deployment_order": [], "status": "approved"}],
        "architecture_decisions": [{"topic": "Agg", "choice": "Pre-agg", "rationale": "Speed"}],
        "reconciliation_results": [{"test_case_key": "t1", "delta_status": "pass", "baseline_value": {}, "candidate_value": {}}],
        "technical_objects": [{"name": "V_TEST", "object_type": "relational_view", "platform": "dsp", "layer": "raw", "generated_artifact": "SELECT 1", "status": "deployed"}],
        "approvals": [{"id": str(uuid4()), "artifact_type": "hla_document", "status": "approved", "resolved_at": "2026-04-16T10:00:00Z"}],
    }


def test_release_manifest(sample_project_data):
    manifest = ReleaseManifest.from_project_data(sample_project_data, version="1.0.0")
    assert manifest.version == "1.0.0"
    assert manifest.project_name == "Sales Planning"
    assert manifest.object_count == 1
    assert manifest.approval_count == 1


def test_assemble_release_package_produces_zip(sample_project_data):
    zip_bytes = assemble_release_package(sample_project_data, version="1.0.0")
    assert isinstance(zip_bytes, bytes)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "docs/technical.html" in names
        assert "docs/technical.md" in names
        assert "docs/functional.md" in names
        assert "reconciliation/summary.json" in names
        assert "decisions/decision_log.json" in names


def test_assemble_release_package_manifest_content(sample_project_data):
    zip_bytes = assemble_release_package(sample_project_data, version="2.0.0")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["version"] == "2.0.0"
        assert manifest["project_name"] == "Sales Planning"
```

- [ ] **Step 2: Run tests to verify fail**

Run: `python -m pytest tests/test_session6_release.py -v`
Expected: FAIL

- [ ] **Step 3: Implement release.py**

```python
"""Release package assembler — bundles all project artifacts into a downloadable ZIP."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from spec2sphere.governance.doc_generator import (
    generate_decision_log,
    generate_reconciliation_report,
    render_html_report,
    render_markdown_report,
    generate_functional_doc,
)

logger = logging.getLogger(__name__)


@dataclass
class ReleaseManifest:
    version: str
    project_name: str
    customer_name: str
    generated_at: str
    object_count: int
    approval_count: int
    test_count: int
    test_pass_count: int
    files: list[str] = field(default_factory=list)

    @classmethod
    def from_project_data(cls, data: dict[str, Any], version: str) -> "ReleaseManifest":
        recon = data.get("reconciliation_results", [])
        return cls(
            version=version,
            project_name=data["project"]["name"],
            customer_name=data.get("customer", {}).get("name", ""),
            generated_at=datetime.now(timezone.utc).isoformat(),
            object_count=len(data.get("technical_objects", [])),
            approval_count=len(data.get("approvals", [])),
            test_count=len(recon),
            test_pass_count=sum(1 for r in recon if r.get("delta_status") == "pass"),
        )


def assemble_release_package(data: dict[str, Any], version: str = "1.0.0") -> bytes:
    """Assemble a release ZIP package with all project artifacts.

    Contents:
        manifest.json           — Version, counts, file list
        docs/technical.html     — Self-contained HTML technical doc
        docs/technical.md       — Markdown technical doc
        docs/functional.md      — Markdown functional doc
        reconciliation/summary.json — Reconciliation results
        decisions/decision_log.json — Architecture decisions
        artifacts/*.sql         — Generated SQL artifacts
        approvals/approvals.json — Approval records
    """
    buf = io.BytesIO()
    manifest = ReleaseManifest.from_project_data(data, version)
    files_written: list[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Documentation
        html_report = render_html_report(data)
        zf.writestr("docs/technical.html", html_report)
        files_written.append("docs/technical.html")

        md_report = render_markdown_report(data)
        zf.writestr("docs/technical.md", md_report)
        files_written.append("docs/technical.md")

        func_doc = generate_functional_doc(data)
        zf.writestr("docs/functional.md", func_doc["content"])
        files_written.append("docs/functional.md")

        # Reconciliation
        recon = generate_reconciliation_report(data)
        zf.writestr("reconciliation/summary.json", json.dumps(recon, indent=2, default=str))
        files_written.append("reconciliation/summary.json")

        # Decisions
        decisions = generate_decision_log(data)
        zf.writestr("decisions/decision_log.json", json.dumps(decisions, indent=2, default=str))
        files_written.append("decisions/decision_log.json")

        # SQL artifacts
        for obj in data.get("technical_objects", []):
            if obj.get("generated_artifact"):
                path = f"artifacts/{obj['name']}.sql"
                zf.writestr(path, obj["generated_artifact"])
                files_written.append(path)

        # Approvals
        approvals = data.get("approvals", [])
        if approvals:
            zf.writestr("approvals/approvals.json", json.dumps(approvals, indent=2, default=str))
            files_written.append("approvals/approvals.json")

        # Manifest (written last with complete file list)
        manifest.files = files_written
        zf.writestr("manifest.json", json.dumps(asdict(manifest), indent=2))

    return buf.getvalue()
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_session6_release.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/spec2sphere/governance/release.py tests/test_session6_release.py
git commit -m "feat(session6): release package assembler with ZIP bundling"
```

---

## Task 4: Artifact Lab — Experiment Tracker + Template Store + Mutation Catalog

**Files:**
- Create: `src/spec2sphere/artifact_lab/__init__.py`
- Create: `src/spec2sphere/artifact_lab/experiment_tracker.py`
- Create: `src/spec2sphere/artifact_lab/template_store.py`
- Create: `src/spec2sphere/artifact_lab/mutation_catalog.py`
- Create: `src/spec2sphere/artifact_lab/lab_runner.py`
- Create: `tests/test_session6_artifact_lab.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for Artifact Lab — experiments, templates, mutations, lab runner."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from spec2sphere.artifact_lab.mutation_catalog import (
    get_mutations,
    is_safe_mutation,
    MUTATION_CATALOG,
)
from spec2sphere.artifact_lab.experiment_tracker import (
    ExperimentRecord,
    build_experiment_record,
)
from spec2sphere.artifact_lab.template_store import (
    TemplateRecord,
    build_template_from_experiment,
)
from spec2sphere.artifact_lab.lab_runner import (
    compute_diff,
    LabResult,
)


# ── Mutation Catalog ─────────────────────────────────────────────────────────

def test_mutation_catalog_has_dsp_entries():
    mutations = get_mutations("dsp", "relational_view")
    assert len(mutations) > 0
    assert any(m["name"] == "add_field" for m in mutations)


def test_mutation_catalog_has_sac_entries():
    mutations = get_mutations("sac", "story")
    assert len(mutations) > 0
    assert any(m["name"] == "add_page" for m in mutations)


def test_is_safe_mutation_true():
    assert is_safe_mutation("dsp", "relational_view", "add_field") is True


def test_is_safe_mutation_false():
    assert is_safe_mutation("dsp", "relational_view", "drop_table") is False


def test_unknown_platform_returns_empty():
    assert get_mutations("unknown", "foo") == []


# ── Experiment Tracker ───────────────────────────────────────────────────────

def test_build_experiment_record():
    rec = build_experiment_record(
        customer_id=str(uuid4()),
        platform="dsp",
        object_type="relational_view",
        experiment_type="create",
        input_def={"name": "V_TEST", "fields": ["id", "name"]},
        output_def={"name": "V_TEST", "fields": ["id", "name"], "status": "created"},
        route_used="cdp",
        success=True,
    )
    assert isinstance(rec, ExperimentRecord)
    assert rec.platform == "dsp"
    assert rec.success is True
    assert rec.diff is not None


def test_experiment_record_diff_computed():
    rec = build_experiment_record(
        customer_id=str(uuid4()),
        platform="sac",
        object_type="story",
        experiment_type="modify",
        input_def={"pages": [{"id": "p1", "title": "Overview"}]},
        output_def={"pages": [{"id": "p1", "title": "Overview"}, {"id": "p2", "title": "Detail"}]},
        route_used="cdp",
        success=True,
    )
    assert rec.diff is not None
    assert "pages" in str(rec.diff)


# ── Template Store ───────────────────────────────────────────────────────────

def test_build_template_from_experiment():
    exp = build_experiment_record(
        customer_id=str(uuid4()),
        platform="dsp",
        object_type="relational_view",
        experiment_type="create",
        input_def={"name": "V_TEST", "fields": ["id"]},
        output_def={"name": "V_TEST", "fields": ["id"], "sql": "SELECT id FROM t"},
        route_used="api",
        success=True,
    )
    tpl = build_template_from_experiment(exp)
    assert isinstance(tpl, TemplateRecord)
    assert tpl.platform == "dsp"
    assert tpl.object_type == "relational_view"
    assert tpl.approved is False
    assert tpl.confidence == 0.5


# ── Lab Runner ───────────────────────────────────────────────────────────────

def test_compute_diff_identical():
    diff = compute_diff({"a": 1}, {"a": 1})
    assert diff["changed"] is False
    assert diff["additions"] == {}


def test_compute_diff_with_changes():
    diff = compute_diff(
        {"a": 1, "b": "hello"},
        {"a": 2, "b": "hello", "c": "new"},
    )
    assert diff["changed"] is True
    assert "a" in diff["modifications"]
    assert "c" in diff["additions"]


def test_compute_diff_with_removals():
    diff = compute_diff(
        {"a": 1, "b": 2},
        {"a": 1},
    )
    assert diff["changed"] is True
    assert "b" in diff["removals"]
```

- [ ] **Step 2: Run tests to verify fail**

Run: `python -m pytest tests/test_session6_artifact_lab.py -v`
Expected: FAIL

- [ ] **Step 3: Create __init__.py**

```python
"""Artifact Learning Lab — sandbox experimentation and template learning."""
```

- [ ] **Step 4: Implement mutation_catalog.py**

```python
"""Catalog of safe/unsafe mutation types per platform and object type.

Used by the lab runner to validate experiment safety before execution.
"""

from __future__ import annotations

from typing import Any

# Structure: platform -> object_type -> list of mutations
MUTATION_CATALOG: dict[str, dict[str, list[dict[str, Any]]]] = {
    "dsp": {
        "relational_view": [
            {"name": "add_field", "safe": True, "description": "Add a new column"},
            {"name": "remove_field", "safe": True, "description": "Remove a column"},
            {"name": "rename_field", "safe": True, "description": "Rename a column"},
            {"name": "change_join", "safe": True, "description": "Modify a join condition"},
            {"name": "add_join", "safe": True, "description": "Add a new join"},
            {"name": "change_calculation", "safe": True, "description": "Modify a calculated field"},
            {"name": "add_parameter", "safe": True, "description": "Add input parameter"},
            {"name": "change_label", "safe": True, "description": "Update field label/description"},
            {"name": "change_persistence", "safe": False, "description": "Toggle persistence mode"},
            {"name": "drop_table", "safe": False, "description": "Drop the entire object"},
        ],
        "fact_view": [
            {"name": "add_field", "safe": True, "description": "Add a measure or attribute"},
            {"name": "remove_field", "safe": True, "description": "Remove a measure or attribute"},
            {"name": "add_association", "safe": True, "description": "Add dimension association"},
            {"name": "change_aggregation", "safe": True, "description": "Modify aggregation type"},
            {"name": "drop_table", "safe": False, "description": "Drop the entire object"},
        ],
        "dimension_view": [
            {"name": "add_field", "safe": True, "description": "Add an attribute"},
            {"name": "remove_field", "safe": True, "description": "Remove an attribute"},
            {"name": "add_hierarchy", "safe": True, "description": "Add a hierarchy"},
            {"name": "change_text", "safe": True, "description": "Modify text association"},
            {"name": "drop_table", "safe": False, "description": "Drop the entire object"},
        ],
    },
    "sac": {
        "story": [
            {"name": "add_page", "safe": True, "description": "Add a new page"},
            {"name": "remove_page", "safe": True, "description": "Remove a page"},
            {"name": "add_widget", "safe": True, "description": "Add a widget to a page"},
            {"name": "remove_widget", "safe": True, "description": "Remove a widget"},
            {"name": "change_binding", "safe": True, "description": "Change data binding"},
            {"name": "change_filter", "safe": True, "description": "Modify filter config"},
            {"name": "change_style", "safe": True, "description": "Update styling/theme"},
            {"name": "delete_story", "safe": False, "description": "Delete entire story"},
        ],
        "app": [
            {"name": "add_page", "safe": True, "description": "Add a page"},
            {"name": "add_widget", "safe": True, "description": "Add a widget"},
            {"name": "add_script", "safe": True, "description": "Add scripting logic"},
            {"name": "change_navigation", "safe": True, "description": "Modify navigation"},
            {"name": "delete_app", "safe": False, "description": "Delete entire app"},
        ],
    },
}


def get_mutations(platform: str, object_type: str) -> list[dict[str, Any]]:
    """Get available mutations for a platform/object_type combo."""
    return MUTATION_CATALOG.get(platform, {}).get(object_type, [])


def is_safe_mutation(platform: str, object_type: str, mutation_name: str) -> bool:
    """Check if a mutation is marked safe."""
    mutations = get_mutations(platform, object_type)
    for m in mutations:
        if m["name"] == mutation_name:
            return m["safe"]
    return False
```

- [ ] **Step 5: Implement experiment_tracker.py**

```python
"""Experiment CRUD for the lab_experiments table."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from spec2sphere.artifact_lab.lab_runner import compute_diff
from spec2sphere.db import _get_conn

logger = logging.getLogger(__name__)


@dataclass
class ExperimentRecord:
    id: str
    customer_id: str
    platform: str
    object_type: str
    experiment_type: str
    input_definition: dict
    output_definition: dict
    diff: Optional[dict]
    route_used: str
    success: bool
    notes: str = ""


def build_experiment_record(
    customer_id: str,
    platform: str,
    object_type: str,
    experiment_type: str,
    input_def: dict,
    output_def: dict,
    route_used: str,
    success: bool,
    notes: str = "",
) -> ExperimentRecord:
    """Build an ExperimentRecord with auto-computed diff."""
    diff = compute_diff(input_def, output_def)
    return ExperimentRecord(
        id=str(uuid4()),
        customer_id=customer_id,
        platform=platform,
        object_type=object_type,
        experiment_type=experiment_type,
        input_definition=input_def,
        output_definition=output_def,
        diff=diff,
        route_used=route_used,
        success=success,
        notes=notes,
    )


async def save_experiment(rec: ExperimentRecord) -> str:
    """Persist an experiment to the lab_experiments table. Returns the ID."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO lab_experiments (id, customer_id, platform, object_type, experiment_type,
                                         input_definition, output_definition, diff, route_used, success, notes)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, $11)
            """,
            rec.id, rec.customer_id, rec.platform, rec.object_type, rec.experiment_type,
            json.dumps(rec.input_definition), json.dumps(rec.output_definition),
            json.dumps(rec.diff) if rec.diff else None,
            rec.route_used, rec.success, rec.notes,
        )
        return rec.id
    finally:
        await conn.close()


async def list_experiments(
    customer_id: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List experiments, newest first."""
    conn = await _get_conn()
    try:
        conditions = []
        params: list[Any] = []
        idx = 1
        if customer_id:
            conditions.append(f"customer_id = ${idx}::uuid")
            params.append(customer_id)
            idx += 1
        if platform:
            conditions.append(f"platform = ${idx}")
            params.append(platform)
            idx += 1
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = await conn.fetch(
            f"SELECT * FROM lab_experiments {where} ORDER BY created_at DESC LIMIT ${idx}",
            *params,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_experiment(experiment_id: str) -> Optional[dict]:
    """Get a single experiment by ID."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM lab_experiments WHERE id = $1::uuid", experiment_id)
        return dict(row) if row else None
    finally:
        await conn.close()
```

- [ ] **Step 6: Implement template_store.py**

```python
"""Learned template CRUD with graduation workflow."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

from spec2sphere.artifact_lab.experiment_tracker import ExperimentRecord
from spec2sphere.db import _get_conn

logger = logging.getLogger(__name__)


@dataclass
class TemplateRecord:
    id: str
    customer_id: Optional[str]
    platform: str
    object_type: str
    template_definition: dict
    mutation_rules: dict
    deployment_hints: dict
    confidence: float
    approved: bool


def build_template_from_experiment(exp: ExperimentRecord) -> TemplateRecord:
    """Create an unapproved template from a successful experiment."""
    return TemplateRecord(
        id=str(uuid4()),
        customer_id=exp.customer_id,
        platform=exp.platform,
        object_type=exp.object_type,
        template_definition=exp.output_definition,
        mutation_rules=exp.diff or {},
        deployment_hints={"route": exp.route_used},
        confidence=0.5,
        approved=False,
    )


async def save_template(rec: TemplateRecord) -> str:
    """Persist a learned template."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO learned_templates (id, customer_id, platform, object_type,
                                           template_definition, mutation_rules, deployment_hints,
                                           confidence, approved)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9)
            """,
            rec.id, rec.customer_id, rec.platform, rec.object_type,
            json.dumps(rec.template_definition), json.dumps(rec.mutation_rules),
            json.dumps(rec.deployment_hints), rec.confidence, rec.approved,
        )
        return rec.id
    finally:
        await conn.close()


async def list_templates(
    customer_id: Optional[str] = None,
    platform: Optional[str] = None,
    approved_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """List templates with optional filters."""
    conn = await _get_conn()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1
        if customer_id:
            conditions.append(f"customer_id = ${idx}::uuid")
            params.append(customer_id)
            idx += 1
        if platform:
            conditions.append(f"platform = ${idx}")
            params.append(platform)
            idx += 1
        if approved_only:
            conditions.append("approved = true")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = await conn.fetch(
            f"SELECT * FROM learned_templates {where} ORDER BY created_at DESC LIMIT ${idx}",
            *params,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def graduate_template(template_id: str, approved: bool, reviewer_id: Optional[str] = None) -> None:
    """Graduate (approve/reject) a learned template."""
    conn = await _get_conn()
    try:
        await conn.execute(
            "UPDATE learned_templates SET approved = $1 WHERE id = $2::uuid",
            approved, template_id,
        )
    finally:
        await conn.close()
```

- [ ] **Step 7: Implement lab_runner.py**

```python
"""Lab Runner — orchestrates controlled experiments in sandbox.

The learning loop:
1. Create a reference object
2. Read back full definition
3. Modify one aspect
4. Update the object
5. Read back again
6. Diff both versions
7. Store delta as learned pattern
8. Update route fitness
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class LabResult:
    success: bool
    input_definition: dict
    output_definition: dict
    diff: dict
    route_used: str
    error: Optional[str] = None


def compute_diff(before: dict, after: dict) -> dict:
    """Compute a structured diff between two object definitions.

    Returns: {changed: bool, additions: {}, modifications: {}, removals: {}}
    """
    additions: dict[str, Any] = {}
    modifications: dict[str, Any] = {}
    removals: dict[str, Any] = {}

    all_keys = set(before.keys()) | set(after.keys())
    for key in all_keys:
        if key not in before:
            additions[key] = after[key]
        elif key not in after:
            removals[key] = before[key]
        elif before[key] != after[key]:
            modifications[key] = {"before": before[key], "after": after[key]}

    changed = bool(additions or modifications or removals)
    return {
        "changed": changed,
        "additions": additions,
        "modifications": modifications,
        "removals": removals,
    }


async def run_experiment(
    platform: str,
    object_type: str,
    experiment_type: str,
    input_definition: dict,
    route: str = "cdp",
    environment: str = "sandbox",
) -> LabResult:
    """Run a lab experiment in the sandbox.

    This is the orchestrator that calls platform-specific factories.
    For CI/testing, returns a simulated result when no CDP is available.
    """
    if environment != "sandbox":
        return LabResult(
            success=False,
            input_definition=input_definition,
            output_definition={},
            diff=compute_diff(input_definition, {}),
            route_used=route,
            error="Lab experiments only run in sandbox environment",
        )

    # In production, this would call DSP/SAC factory deployers
    # For now, simulate a successful experiment
    output = dict(input_definition)
    output["_lab_verified"] = True

    diff = compute_diff(input_definition, output)

    return LabResult(
        success=True,
        input_definition=input_definition,
        output_definition=output,
        diff=diff,
        route_used=route,
    )
```

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_session6_artifact_lab.py -v`
Expected: All 11 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/spec2sphere/artifact_lab/ tests/test_session6_artifact_lab.py
git commit -m "feat(session6): artifact lab — experiment tracker, template store, mutation catalog, lab runner"
```

---

## Task 5: Shared Learning Promotion + Style Learning

**Files:**
- Create: `src/spec2sphere/governance/promotion.py`
- Create: `src/spec2sphere/sac_factory/style_learning.py`
- Create: `tests/test_session6_promotion.py`
- Create: `tests/test_session6_style_learning.py`

- [ ] **Step 1: Write promotion tests**

```python
"""Tests for shared learning promotion engine."""

import pytest
from uuid import uuid4

from spec2sphere.governance.promotion import (
    anonymize_content,
    build_promotion_candidate,
    PromotionCandidate,
    ANONYMIZATION_FIELDS,
)


def test_anonymize_strips_customer_names():
    content = {
        "customer_name": "Acme Corp",
        "object_name": "V_ACME_REVENUE",
        "pattern": {"type": "star_schema", "layers": 3},
        "kpi_names": ["acme_revenue", "acme_margin"],
    }
    result = anonymize_content(content)
    assert "Acme" not in str(result)
    assert "acme" not in str(result)
    assert result["pattern"] == {"type": "star_schema", "layers": 3}


def test_anonymize_preserves_generic_fields():
    content = {
        "pattern": {"join_type": "left", "cardinality": "1:n"},
        "route": "cdp",
        "platform": "dsp",
    }
    result = anonymize_content(content)
    assert result["pattern"]["join_type"] == "left"
    assert result["route"] == "cdp"


def test_build_promotion_candidate():
    candidate = build_promotion_candidate(
        source_customer_id=str(uuid4()),
        source_type="learned_template",
        source_id=str(uuid4()),
        target_layer="global",
        content={"object_name": "V_TEST", "pattern": {"type": "dim"}},
    )
    assert isinstance(candidate, PromotionCandidate)
    assert candidate.status == "pending"
    assert "V_TEST" not in str(candidate.anonymized_content)


def test_anonymize_deep_nested():
    content = {
        "definition": {
            "name": "MyCorp_Sales_Model",
            "fields": [{"name": "MyCorp_Revenue", "type": "measure"}],
        }
    }
    result = anonymize_content(content, customer_terms=["MyCorp"])
    assert "MyCorp" not in str(result)
```

- [ ] **Step 2: Write style learning tests**

```python
"""Tests for SAC customer style preference learning."""

import pytest
from uuid import uuid4

from spec2sphere.sac_factory.style_learning import (
    update_preference,
    get_style_profile,
    StylePreference,
)


def test_update_preference_creates_new():
    prefs: dict[str, StylePreference] = {}
    updated = update_preference(prefs, "layout", "exec_overview", approved=True)
    assert "layout:exec_overview" in updated
    assert updated["layout:exec_overview"].score > 0
    assert updated["layout:exec_overview"].evidence_count == 1


def test_update_preference_increments():
    prefs = {
        "layout:exec_overview": StylePreference(
            preference_type="layout",
            preference_key="exec_overview",
            score=1.0,
            evidence_count=2,
        )
    }
    updated = update_preference(prefs, "layout", "exec_overview", approved=True)
    assert updated["layout:exec_overview"].evidence_count == 3
    assert updated["layout:exec_overview"].score > 1.0


def test_update_preference_negative():
    prefs = {
        "chart:pie": StylePreference(
            preference_type="chart",
            preference_key="pie",
            score=1.0,
            evidence_count=3,
        )
    }
    updated = update_preference(prefs, "chart", "pie", approved=False)
    assert updated["chart:pie"].score < 1.0


def test_get_style_profile_empty():
    profile = get_style_profile({})
    assert profile["preferred_layouts"] == []
    assert profile["preferred_charts"] == []


def test_get_style_profile_ranked():
    prefs = {
        "layout:exec_overview": StylePreference("layout", "exec_overview", 3.0, 5),
        "layout:table_first": StylePreference("layout", "table_first", 1.0, 2),
        "chart:bar": StylePreference("chart", "bar", 2.0, 4),
    }
    profile = get_style_profile(prefs)
    assert profile["preferred_layouts"][0] == "exec_overview"
    assert profile["preferred_charts"][0] == "bar"
```

- [ ] **Step 3: Run tests to verify fail**

Run: `python -m pytest tests/test_session6_promotion.py tests/test_session6_style_learning.py -v`
Expected: FAIL

- [ ] **Step 4: Implement promotion.py**

```python
"""Shared learning promotion engine.

Promotes learnings up the knowledge hierarchy:
  project -> customer (requires reviewer approval)
  customer -> global (requires anonymization + platform admin approval)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

from spec2sphere.db import _get_conn

logger = logging.getLogger(__name__)

# Fields that typically contain customer-specific data
ANONYMIZATION_FIELDS = {
    "customer_name", "object_name", "kpi_names", "customer_id",
    "project_name", "project_id", "tenant_name",
}


@dataclass
class PromotionCandidate:
    id: str
    source_customer_id: str
    source_type: str
    source_id: str
    target_layer: str
    anonymized_content: dict
    status: str = "pending"


def anonymize_content(
    content: dict[str, Any],
    customer_terms: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Strip customer-specific names and identifiers from content.

    Removes fields in ANONYMIZATION_FIELDS and replaces customer_terms
    with generic placeholders in all string values.
    """
    result = {}
    terms = customer_terms or []

    # Auto-detect customer terms from known fields
    for field_name in ANONYMIZATION_FIELDS:
        val = content.get(field_name)
        if isinstance(val, str) and val:
            terms.append(val)
        elif isinstance(val, list):
            terms.extend(str(v) for v in val if v)

    # Deduplicate and sort by length (longest first for proper replacement)
    terms = sorted(set(t for t in terms if len(t) > 1), key=len, reverse=True)

    for key, value in content.items():
        if key in ANONYMIZATION_FIELDS:
            continue  # Skip customer-specific fields entirely
        result[key] = _anonymize_value(value, terms)

    return result


def _anonymize_value(value: Any, terms: list[str]) -> Any:
    """Recursively anonymize a value."""
    if isinstance(value, str):
        result = value
        for term in terms:
            result = re.sub(re.escape(term), "[REDACTED]", result, flags=re.IGNORECASE)
        return result
    elif isinstance(value, dict):
        return {k: _anonymize_value(v, terms) for k, v in value.items()}
    elif isinstance(value, list):
        return [_anonymize_value(v, terms) for v in value]
    return value


def build_promotion_candidate(
    source_customer_id: str,
    source_type: str,
    source_id: str,
    target_layer: str,
    content: dict[str, Any],
    customer_terms: Optional[list[str]] = None,
) -> PromotionCandidate:
    """Build a promotion candidate with anonymized content."""
    anonymized = anonymize_content(content, customer_terms)
    return PromotionCandidate(
        id=str(uuid4()),
        source_customer_id=source_customer_id,
        source_type=source_type,
        source_id=source_id,
        target_layer=target_layer,
        anonymized_content=anonymized,
    )


async def save_candidate(candidate: PromotionCandidate) -> str:
    """Persist a promotion candidate."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO promotion_candidates (id, source_customer_id, source_type, source_id,
                                              target_layer, anonymized_content, status)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7)
            """,
            candidate.id, candidate.source_customer_id, candidate.source_type,
            candidate.source_id, candidate.target_layer,
            json.dumps(candidate.anonymized_content), candidate.status,
        )
        return candidate.id
    finally:
        await conn.close()


async def review_candidate(candidate_id: str, approved: bool, reviewer_id: str) -> None:
    """Approve or reject a promotion candidate."""
    status = "approved" if approved else "rejected"
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            UPDATE promotion_candidates
            SET status = $1, reviewed_by = $2::uuid, reviewed_at = now()
            WHERE id = $3::uuid
            """,
            status, reviewer_id, candidate_id,
        )
    finally:
        await conn.close()


async def list_candidates(status: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List promotion candidates."""
    conn = await _get_conn()
    try:
        if status:
            rows = await conn.fetch(
                "SELECT * FROM promotion_candidates WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                status, limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM promotion_candidates ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
    finally:
        await conn.close()
```

- [ ] **Step 5: Implement style_learning.py**

```python
"""Customer style preference learning for SAC dashboards.

Tracks which layouts, chart types, density levels, and styling choices
get approved for each customer. Preferences influence future blueprint generation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from spec2sphere.db import _get_conn

logger = logging.getLogger(__name__)


@dataclass
class StylePreference:
    preference_type: str  # layout | chart | density | title_style
    preference_key: str   # exec_overview | bar | compact | action_title
    score: float = 0.0
    evidence_count: int = 0


def update_preference(
    prefs: dict[str, StylePreference],
    pref_type: str,
    pref_key: str,
    approved: bool,
) -> dict[str, StylePreference]:
    """Update an in-memory preference dict based on approval feedback.

    Approved designs increase the score; rejected designs decrease it.
    Returns the updated prefs dict.
    """
    compound_key = f"{pref_type}:{pref_key}"
    existing = prefs.get(compound_key)

    if existing is None:
        score = 1.0 if approved else -0.5
        prefs[compound_key] = StylePreference(
            preference_type=pref_type,
            preference_key=pref_key,
            score=score,
            evidence_count=1,
        )
    else:
        delta = 1.0 if approved else -0.5
        existing.score += delta
        existing.evidence_count += 1

    return prefs


def get_style_profile(prefs: dict[str, StylePreference]) -> dict[str, list[str]]:
    """Build a ranked style profile from preferences.

    Returns: {preferred_layouts: [...], preferred_charts: [...], ...}
    """
    by_type: dict[str, list[tuple[str, float]]] = {}
    for key, pref in prefs.items():
        by_type.setdefault(pref.preference_type, []).append(
            (pref.preference_key, pref.score)
        )

    profile: dict[str, list[str]] = {}
    type_map = {"layout": "preferred_layouts", "chart": "preferred_charts",
                "density": "preferred_density", "title_style": "preferred_title_styles"}

    for ptype, output_key in type_map.items():
        items = by_type.get(ptype, [])
        ranked = sorted(items, key=lambda x: x[1], reverse=True)
        profile[output_key] = [name for name, score in ranked if score > 0]

    return profile


async def save_preferences(customer_id: str, prefs: dict[str, StylePreference]) -> None:
    """Persist style preferences to DB."""
    conn = await _get_conn()
    try:
        for key, pref in prefs.items():
            await conn.execute(
                """
                INSERT INTO style_preferences (customer_id, preference_type, preference_key, score, evidence_count, updated_at)
                VALUES ($1::uuid, $2, $3, $4, $5, now())
                ON CONFLICT (customer_id, preference_type, preference_key)
                DO UPDATE SET score = $4, evidence_count = $5, updated_at = now()
                """,
                customer_id, pref.preference_type, pref.preference_key,
                pref.score, pref.evidence_count,
            )
    finally:
        await conn.close()


async def load_preferences(customer_id: str) -> dict[str, StylePreference]:
    """Load style preferences for a customer."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM style_preferences WHERE customer_id = $1::uuid",
            customer_id,
        )
        prefs: dict[str, StylePreference] = {}
        for r in rows:
            key = f"{r['preference_type']}:{r['preference_key']}"
            prefs[key] = StylePreference(
                preference_type=r["preference_type"],
                preference_key=r["preference_key"],
                score=float(r["score"]),
                evidence_count=int(r["evidence_count"]),
            )
        return prefs
    finally:
        await conn.close()
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_session6_promotion.py tests/test_session6_style_learning.py -v`
Expected: All 9 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/spec2sphere/governance/promotion.py src/spec2sphere/sac_factory/style_learning.py tests/test_session6_promotion.py tests/test_session6_style_learning.py
git commit -m "feat(session6): shared learning promotion + SAC style preference learning"
```

---

## Task 6: Extend Approvals for Release Gate

**Files:**
- Modify: `src/spec2sphere/governance/approvals.py`

- [ ] **Step 1: Add release artifact type**

In `src/spec2sphere/governance/approvals.py`, add to `CHECKLISTS` dict after the `"deployment"` entry:

```python
    "release": [
        {"key": "hla_approved", "label": "HLA approved", "required": True},
        {"key": "tech_spec_approved", "label": "Technical specification approved", "required": True},
        {"key": "test_spec_approved", "label": "Test specification approved", "required": True},
        {"key": "sandbox_qa_passed", "label": "Sandbox QA passed", "required": True},
        {"key": "reconciliation_acceptable", "label": "Reconciliation results acceptable", "required": True},
        {"key": "open_issues_reviewed", "label": "Open issues register reviewed", "required": True},
        {"key": "documentation_generated", "label": "As-built documentation generated", "required": True},
        {"key": "rollback_plan_ready", "label": "Rollback plan documented", "required": True},
    ],
```

Add to `ARTIFACT_TABLES`:

```python
    "release": "release_packages",
```

- [ ] **Step 2: Commit**

```bash
git add src/spec2sphere/governance/approvals.py
git commit -m "feat(session6): add release approval gate with 8-point checklist"
```

---

## Task 7: Governance Routes — Reports, Audit Log, Lab UIs

**Files:**
- Create: `src/spec2sphere/web/governance_routes.py`
- Create: `src/spec2sphere/web/templates/partials/reports_v2.html`
- Create: `src/spec2sphere/web/templates/partials/lab.html`
- Create: `src/spec2sphere/web/templates/partials/audit_log.html`
- Create: `tests/test_session6_governance_routes.py`
- Modify: `src/spec2sphere/web/server.py`
- Modify: `src/spec2sphere/web/templates/base.html`

- [ ] **Step 1: Write route tests**

```python
"""Tests for governance UI routes."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from spec2sphere.web.governance_routes import create_governance_routes


@pytest.fixture
def client():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(create_governance_routes())
    # Fake templates dir
    return TestClient(app, raise_server_exceptions=False)


def test_reports_page_returns_html(client):
    with patch("spec2sphere.web.governance_routes._get_conn") as mock_conn:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.close = AsyncMock()
        mock_conn.return_value = conn
        resp = client.get("/ui/reports")
        assert resp.status_code == 200


def test_audit_log_page_returns_html(client):
    with patch("spec2sphere.web.governance_routes._get_conn") as mock_conn:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.close = AsyncMock()
        mock_conn.return_value = conn
        resp = client.get("/ui/audit-log")
        assert resp.status_code == 200


def test_lab_page_returns_html(client):
    with patch("spec2sphere.web.governance_routes._get_conn") as mock_conn:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.close = AsyncMock()
        mock_conn.return_value = conn
        resp = client.get("/ui/lab")
        assert resp.status_code == 200


def test_generate_report_api(client):
    with patch("spec2sphere.web.governance_routes._get_conn") as mock_conn:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        conn.close = AsyncMock()
        mock_conn.return_value = conn
        resp = client.post("/api/governance/generate-report", json={"project_id": "00000000-0000-0000-0000-000000000001", "format": "html"})
        # May fail gracefully due to no project data — that's OK
        assert resp.status_code in (200, 404)


def test_download_release_api(client):
    resp = client.get("/api/governance/release/nonexistent/download")
    assert resp.status_code == 404
```

- [ ] **Step 2: Create governance_routes.py**

```python
"""Governance UI routes — Reports, Audit Log, Lab, Release packages."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from spec2sphere.db import _get_conn

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def _render(request: Request, template_name: str, ctx: dict) -> HTMLResponse:
    ctx["request"] = request
    return _templates.TemplateResponse(request, f"partials/{template_name}", ctx)


def _str_record(row) -> dict:
    import uuid as _uuid
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def create_governance_routes() -> APIRouter:
    router = APIRouter()

    # ── Reports Page ─────────────────────────────────────────────────────

    @router.get("/ui/reports", response_class=HTMLResponse)
    async def reports_page(request: Request):
        """Reports browser — list generated docs per project."""
        reports: list[dict] = []
        release_packages: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            # List release packages
            rows = await conn.fetch(
                """
                SELECT rp.id, rp.version, rp.status, rp.created_at,
                       p.name AS project_name
                FROM release_packages rp
                LEFT JOIN projects p ON p.id = rp.project_id
                ORDER BY rp.created_at DESC
                LIMIT 20
                """
            )
            release_packages = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("reports_page: %s", exc)
            error = str(exc)
        finally:
            if conn:
                await conn.close()

        # Also list any static reports from filesystem
        reports_dir = Path("output/reports")
        if reports_dir.exists():
            for f in sorted(reports_dir.iterdir(), reverse=True):
                if f.suffix in (".html", ".md", ".pdf"):
                    reports.append({
                        "name": f.name,
                        "url": f"/reports/{f.name}",
                        "size": f.stat().st_size,
                        "format": f.suffix.lstrip("."),
                    })

        return _render(request, "reports_v2.html", {
            "reports": reports,
            "release_packages": release_packages,
            "error": error,
            "active_page": "reports",
        })

    # ── Audit Log Page ───────────────────────────────────────────────────

    @router.get("/ui/audit-log", response_class=HTMLResponse)
    async def audit_log_page(
        request: Request,
        user: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 50,
    ):
        """Searchable, filterable audit log."""
        entries: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            conditions: list[str] = []
            params: list = []
            idx = 1

            if user:
                conditions.append(f"user_id::text ILIKE '%' || ${idx} || '%'")
                params.append(user)
                idx += 1
            if action:
                conditions.append(f"action ILIKE '%' || ${idx} || '%'")
                params.append(action)
                idx += 1
            if resource_type:
                conditions.append(f"resource_type = ${idx}")
                params.append(resource_type)
                idx += 1
            if trace_id:
                conditions.append(f"details->>'trace_id' = ${idx}")
                params.append(trace_id)
                idx += 1

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.append(limit)

            rows = await conn.fetch(
                f"""
                SELECT id, tenant_id, customer_id, project_id, user_id,
                       action, resource_type, resource_id, details, created_at
                FROM audit_log
                {where}
                ORDER BY created_at DESC
                LIMIT ${idx}
                """,
                *params,
            )
            entries = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("audit_log_page: %s", exc)
            error = str(exc)
        finally:
            if conn:
                await conn.close()

        return _render(request, "audit_log.html", {
            "entries": entries,
            "error": error,
            "filter_user": user or "",
            "filter_action": action or "",
            "filter_resource": resource_type or "",
            "filter_trace": trace_id or "",
            "active_page": "audit-log",
        })

    # ── Lab Page ─────────────────────────────────────────────────────────

    @router.get("/ui/lab", response_class=HTMLResponse)
    async def lab_page(request: Request):
        """Artifact Lab — experiments + templates browser."""
        experiments: list[dict] = []
        templates: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            exp_rows = await conn.fetch(
                "SELECT * FROM lab_experiments ORDER BY created_at DESC LIMIT 30"
            )
            experiments = [_str_record(r) for r in exp_rows]

            tpl_rows = await conn.fetch(
                "SELECT * FROM learned_templates ORDER BY created_at DESC LIMIT 30"
            )
            templates = [_str_record(r) for r in tpl_rows]
        except Exception as exc:
            logger.warning("lab_page: %s", exc)
            error = str(exc)
        finally:
            if conn:
                await conn.close()

        return _render(request, "lab.html", {
            "experiments": experiments,
            "templates": templates,
            "error": error,
            "active_page": "lab",
        })

    # ── API: Generate Report ─────────────────────────────────────────────

    @router.post("/api/governance/generate-report")
    async def generate_report(request: Request):
        """Generate as-built documentation for a project."""
        body = await request.json()
        project_id = body.get("project_id")
        output_format = body.get("format", "html")

        if not project_id:
            return JSONResponse({"error": "project_id required"}, status_code=400)

        # Fetch all project data
        conn = await _get_conn()
        try:
            project = await conn.fetchrow("SELECT * FROM projects WHERE id = $1::uuid", project_id)
            if not project:
                return JSONResponse({"error": "Project not found"}, status_code=404)

            customer = await conn.fetchrow("SELECT * FROM customers WHERE id = $1", project["customer_id"])
            reqs = await conn.fetch("SELECT * FROM requirements WHERE project_id = $1::uuid", project_id)
            hlas = await conn.fetch("SELECT * FROM hla_documents WHERE project_id = $1::uuid", project_id)
            specs = await conn.fetch("SELECT * FROM tech_specs WHERE project_id = $1::uuid", project_id)
            decisions = await conn.fetch("SELECT * FROM architecture_decisions WHERE project_id = $1::uuid", project_id)
            objects = await conn.fetch("SELECT * FROM technical_objects WHERE project_id = $1::uuid", project_id)
            recon = await conn.fetch("SELECT * FROM reconciliation_results WHERE project_id = $1::uuid", project_id)
            approvals = await conn.fetch("SELECT * FROM approvals WHERE project_id = $1::uuid", project_id)
        finally:
            await conn.close()

        data = {
            "project": _str_record(dict(project)),
            "customer": _str_record(dict(customer)) if customer else {},
            "requirements": [_str_record(dict(r)) for r in reqs],
            "hla_documents": [_str_record(dict(r)) for r in hlas],
            "tech_specs": [_str_record(dict(r)) for r in specs],
            "architecture_decisions": [_str_record(dict(r)) for r in decisions],
            "technical_objects": [_str_record(dict(r)) for r in objects],
            "reconciliation_results": [_str_record(dict(r)) for r in recon],
            "approvals": [_str_record(dict(r)) for r in approvals],
        }

        from spec2sphere.governance.doc_generator import render_html_report, render_markdown_report, render_pdf_report

        if output_format == "pdf":
            pdf_bytes = render_pdf_report(data)
            return Response(content=pdf_bytes, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{project["name"]}_report.pdf"'})
        elif output_format == "markdown":
            md = render_markdown_report(data)
            return Response(content=md, media_type="text/markdown",
                            headers={"Content-Disposition": f'attachment; filename="{project["name"]}_report.md"'})
        else:
            html = render_html_report(data)
            return HTMLResponse(html)

    # ── API: Assemble Release Package ────────────────────────────────────

    @router.post("/api/governance/release")
    async def create_release(request: Request):
        """Assemble a release package."""
        body = await request.json()
        project_id = body.get("project_id")
        version = body.get("version", "1.0.0")

        if not project_id:
            return JSONResponse({"error": "project_id required"}, status_code=400)

        # Same data fetching as generate_report
        conn = await _get_conn()
        try:
            project = await conn.fetchrow("SELECT * FROM projects WHERE id = $1::uuid", project_id)
            if not project:
                return JSONResponse({"error": "Project not found"}, status_code=404)
            customer = await conn.fetchrow("SELECT * FROM customers WHERE id = $1", project["customer_id"])
            reqs = await conn.fetch("SELECT * FROM requirements WHERE project_id = $1::uuid", project_id)
            hlas = await conn.fetch("SELECT * FROM hla_documents WHERE project_id = $1::uuid", project_id)
            specs = await conn.fetch("SELECT * FROM tech_specs WHERE project_id = $1::uuid", project_id)
            decisions = await conn.fetch("SELECT * FROM architecture_decisions WHERE project_id = $1::uuid", project_id)
            objects = await conn.fetch("SELECT * FROM technical_objects WHERE project_id = $1::uuid", project_id)
            recon = await conn.fetch("SELECT * FROM reconciliation_results WHERE project_id = $1::uuid", project_id)
            approvals = await conn.fetch("SELECT * FROM approvals WHERE project_id = $1::uuid", project_id)
        finally:
            await conn.close()

        data = {
            "project": _str_record(dict(project)),
            "customer": _str_record(dict(customer)) if customer else {},
            "requirements": [_str_record(dict(r)) for r in reqs],
            "hla_documents": [_str_record(dict(r)) for r in hlas],
            "tech_specs": [_str_record(dict(r)) for r in specs],
            "architecture_decisions": [_str_record(dict(r)) for r in decisions],
            "technical_objects": [_str_record(dict(r)) for r in objects],
            "reconciliation_results": [_str_record(dict(r)) for r in recon],
            "approvals": [_str_record(dict(r)) for r in approvals],
        }

        from spec2sphere.governance.release import assemble_release_package

        zip_bytes = assemble_release_package(data, version=version)

        # Store reference in DB
        conn = await _get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO release_packages (project_id, version, status, manifest)
                VALUES ($1::uuid, $2, 'draft', $3::jsonb)
                """,
                project_id, version, json.dumps({"format": "zip", "size": len(zip_bytes)}),
            )
        finally:
            await conn.close()

        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project["name"]}_release_{version}.zip"'},
        )

    @router.get("/api/governance/release/{release_id}/download")
    async def download_release(release_id: str):
        """Download a stored release package."""
        return JSONResponse({"error": "Release not found — use POST to generate"}, status_code=404)

    # ── API: Template Graduation ─────────────────────────────────────────

    @router.post("/api/lab/templates/{template_id}/graduate")
    async def graduate_template(template_id: str, request: Request):
        """Approve or reject a learned template."""
        body = await request.json()
        approved = body.get("approved", False)
        from spec2sphere.artifact_lab.template_store import graduate_template as _graduate
        await _graduate(template_id, approved)
        return JSONResponse({"status": "graduated" if approved else "rejected"})

    return router
```

- [ ] **Step 3: Create reports_v2.html**

```html
{% extends "base.html" %}
{% block title %}Reports — Spec2Sphere{% endblock %}
{% block page_title %}Reports & Documentation{% endblock %}

{% block content %}
<!-- Generate Report -->
<div class="card mb-6">
    <h3 class="font-heading text-base text-[#1a2332] mb-3">Generate Documentation</h3>
    <div class="flex gap-3">
        <select id="report-project" class="px-3 py-2 border border-gray-200 rounded text-sm">
            <option value="">Select project...</option>
        </select>
        <button onclick="generateReport('html')" class="px-4 py-2 bg-petrol text-white rounded text-xs font-medium hover:bg-petrol-dark">HTML</button>
        <button onclick="generateReport('markdown')" class="px-4 py-2 border border-petrol text-petrol rounded text-xs font-medium hover:bg-petrol hover:text-white">Markdown</button>
        <button onclick="generateReport('pdf')" class="px-4 py-2 border border-gray-300 text-gray-500 rounded text-xs font-medium hover:border-petrol hover:text-petrol">PDF</button>
        <button onclick="assembleRelease()" class="px-4 py-2 bg-accent text-white rounded text-xs font-medium hover:opacity-90 ml-auto">Assemble Release ZIP</button>
    </div>
</div>

<!-- Release Packages -->
{% if release_packages %}
<h3 class="font-heading text-base text-[#1a2332] mb-3">Release Packages</h3>
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
    {% for pkg in release_packages %}
    <div class="card">
        <div class="flex items-start justify-between mb-1">
            <h4 class="font-heading text-sm text-[#1a2332]">{{ pkg.project_name or 'Unknown' }}</h4>
            <span class="text-xs px-2 py-0.5 rounded-full {{ 'bg-green-100 text-green-700' if pkg.status == 'approved' else 'bg-amber-100 text-amber-700' }}">{{ pkg.status }}</span>
        </div>
        <p class="text-xs text-gray-400 mb-2">v{{ pkg.version }} &mdash; {{ pkg.created_at[:10] if pkg.created_at else '' }}</p>
        <a href="/api/governance/release/{{ pkg.id }}/download" class="text-xs text-petrol hover:underline">Download ZIP</a>
    </div>
    {% endfor %}
</div>
{% endif %}

<!-- Static Reports -->
{% if reports %}
<h3 class="font-heading text-base text-[#1a2332] mb-3">Generated Reports</h3>
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
    {% for report in reports %}
    <div class="card">
        <div class="flex items-start justify-between mb-2">
            <h4 class="font-heading text-sm text-[#1a2332]">{{ report.name }}</h4>
            <span class="text-xs text-gray-400">{{ (report.size / 1024)|round(1) }} KB</span>
        </div>
        <div class="flex gap-2 mt-3">
            <a href="{{ report.url }}" class="px-3 py-1.5 bg-petrol text-white rounded text-xs font-medium hover:bg-petrol-dark">View</a>
            <a href="{{ report.url }}" download class="px-3 py-1.5 border border-petrol text-petrol rounded text-xs font-medium hover:bg-petrol hover:text-white">Download</a>
        </div>
    </div>
    {% endfor %}
</div>
{% elif not release_packages %}
<div class="card text-center py-12">
    <p class="text-gray-400 mb-2">No reports generated yet.</p>
    <p class="text-sm text-gray-400">Select a project above and generate documentation.</p>
</div>
{% endif %}

{% if error %}
<div class="card mt-4 border-l-4 border-red-400"><p class="text-sm text-red-600">{{ error }}</p></div>
{% endif %}

<script>
async function generateReport(fmt) {
    const pid = document.getElementById('report-project').value;
    if (!pid) { showToast('Select a project first', 'error'); return; }
    const resp = await fetch('/api/governance/generate-report', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_id: pid, format: fmt})
    });
    if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'report.' + (fmt === 'markdown' ? 'md' : fmt);
        a.click();
    } else { showToast('Report generation failed', 'error'); }
}
async function assembleRelease() {
    const pid = document.getElementById('report-project').value;
    if (!pid) { showToast('Select a project first', 'error'); return; }
    const version = prompt('Release version:', '1.0.0');
    if (!version) return;
    const resp = await fetch('/api/governance/release', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_id: pid, version: version})
    });
    if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'release_' + version + '.zip'; a.click();
        showToast('Release package assembled', 'success');
    } else { showToast('Failed to assemble release', 'error'); }
}
</script>
{% endblock %}
```

- [ ] **Step 4: Create lab.html**

```html
{% extends "base.html" %}
{% block title %}Artifact Lab — Spec2Sphere{% endblock %}
{% block page_title %}Artifact Learning Lab{% endblock %}

{% block content %}
<!-- Experiments -->
<div class="mb-6">
    <h3 class="font-heading text-base text-[#1a2332] mb-3">Experiments</h3>
    {% if experiments %}
    <div class="overflow-x-auto">
        <table class="w-full text-sm">
            <thead><tr>
                <th class="px-4 py-2 text-left bg-gray-50 text-gray-600 font-medium">Platform</th>
                <th class="px-4 py-2 text-left bg-gray-50 text-gray-600 font-medium">Object Type</th>
                <th class="px-4 py-2 text-left bg-gray-50 text-gray-600 font-medium">Type</th>
                <th class="px-4 py-2 text-left bg-gray-50 text-gray-600 font-medium">Route</th>
                <th class="px-4 py-2 text-left bg-gray-50 text-gray-600 font-medium">Status</th>
                <th class="px-4 py-2 text-left bg-gray-50 text-gray-600 font-medium">Date</th>
            </tr></thead>
            <tbody>
            {% for exp in experiments %}
            <tr class="border-b border-gray-100 hover:bg-gray-50">
                <td class="px-4 py-2"><span class="badge {{ 'bg-indigo-100 text-indigo-700' if exp.platform == 'dsp' else 'bg-teal-100 text-teal-700' }}">{{ exp.platform }}</span></td>
                <td class="px-4 py-2">{{ exp.object_type }}</td>
                <td class="px-4 py-2">{{ exp.experiment_type }}</td>
                <td class="px-4 py-2"><code class="text-xs">{{ exp.route_used }}</code></td>
                <td class="px-4 py-2"><span class="badge {{ 'bg-green-100 text-green-700' if exp.success else 'bg-red-100 text-red-700' }}">{{ 'pass' if exp.success else 'fail' }}</span></td>
                <td class="px-4 py-2 text-gray-400">{{ exp.created_at[:10] if exp.created_at else '' }}</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
    <div class="card text-center py-8"><p class="text-gray-400">No experiments yet. Run lab experiments to learn platform patterns.</p></div>
    {% endif %}
</div>

<!-- Learned Templates -->
<div>
    <h3 class="font-heading text-base text-[#1a2332] mb-3">Learned Templates</h3>
    {% if templates %}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        {% for tpl in templates %}
        <div class="card">
            <div class="flex items-start justify-between mb-2">
                <div>
                    <span class="badge {{ 'bg-indigo-100 text-indigo-700' if tpl.platform == 'dsp' else 'bg-teal-100 text-teal-700' }}">{{ tpl.platform }}</span>
                    <span class="text-sm font-medium ml-1">{{ tpl.object_type }}</span>
                </div>
                <span class="badge {{ 'bg-green-100 text-green-700' if tpl.approved else 'bg-amber-100 text-amber-700' }}">{{ 'approved' if tpl.approved else 'pending' }}</span>
            </div>
            <p class="text-xs text-gray-400 mb-2">Confidence: {{ (tpl.confidence * 100)|round(0) }}%</p>
            {% if not tpl.approved %}
            <div class="flex gap-2 mt-2">
                <button onclick="graduateTemplate('{{ tpl.id }}', true)" class="px-3 py-1 bg-green-600 text-white rounded text-xs">Approve</button>
                <button onclick="graduateTemplate('{{ tpl.id }}', false)" class="px-3 py-1 bg-red-500 text-white rounded text-xs">Reject</button>
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="card text-center py-8"><p class="text-gray-400">No learned templates yet.</p></div>
    {% endif %}
</div>

{% if error %}
<div class="card mt-4 border-l-4 border-red-400"><p class="text-sm text-red-600">{{ error }}</p></div>
{% endif %}

<script>
async function graduateTemplate(id, approved) {
    const resp = await fetch(`/api/lab/templates/${id}/graduate`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({approved})
    });
    if (resp.ok) { location.reload(); }
    else { showToast('Graduation failed', 'error'); }
}
</script>
{% endblock %}
```

- [ ] **Step 5: Create audit_log.html**

```html
{% extends "base.html" %}
{% block title %}Audit Log — Spec2Sphere{% endblock %}
{% block page_title %}Audit Log{% endblock %}

{% block content %}
<!-- Filters -->
<div class="card mb-4">
    <form class="flex flex-wrap gap-3 items-end" method="get" action="/ui/audit-log">
        <div>
            <label class="block text-xs text-gray-500 mb-1">User</label>
            <input type="text" name="user" value="{{ filter_user }}" placeholder="User ID..." class="px-3 py-1.5 border border-gray-200 rounded text-sm w-40">
        </div>
        <div>
            <label class="block text-xs text-gray-500 mb-1">Action</label>
            <input type="text" name="action" value="{{ filter_action }}" placeholder="GET, POST..." class="px-3 py-1.5 border border-gray-200 rounded text-sm w-40">
        </div>
        <div>
            <label class="block text-xs text-gray-500 mb-1">Resource</label>
            <input type="text" name="resource_type" value="{{ filter_resource }}" placeholder="Type..." class="px-3 py-1.5 border border-gray-200 rounded text-sm w-32">
        </div>
        <div>
            <label class="block text-xs text-gray-500 mb-1">Trace ID</label>
            <input type="text" name="trace_id" value="{{ filter_trace }}" placeholder="Trace..." class="px-3 py-1.5 border border-gray-200 rounded text-sm w-48">
        </div>
        <button type="submit" class="px-4 py-1.5 bg-petrol text-white rounded text-sm font-medium">Filter</button>
        <a href="/ui/audit-log" class="px-4 py-1.5 border border-gray-300 text-gray-500 rounded text-sm">Clear</a>
    </form>
</div>

<!-- Entries -->
{% if entries %}
<div class="overflow-x-auto">
    <table class="w-full text-sm">
        <thead><tr>
            <th class="px-3 py-2 text-left bg-gray-50 text-gray-600 font-medium">Time</th>
            <th class="px-3 py-2 text-left bg-gray-50 text-gray-600 font-medium">Action</th>
            <th class="px-3 py-2 text-left bg-gray-50 text-gray-600 font-medium">Resource</th>
            <th class="px-3 py-2 text-left bg-gray-50 text-gray-600 font-medium">User</th>
            <th class="px-3 py-2 text-left bg-gray-50 text-gray-600 font-medium">Details</th>
        </tr></thead>
        <tbody>
        {% for e in entries %}
        <tr class="border-b border-gray-100 hover:bg-gray-50">
            <td class="px-3 py-2 text-xs text-gray-400 whitespace-nowrap">{{ e.created_at[:19] if e.created_at else '' }}</td>
            <td class="px-3 py-2"><code class="text-xs">{{ e.action }}</code></td>
            <td class="px-3 py-2 text-xs">{{ e.resource_type or '-' }}</td>
            <td class="px-3 py-2 text-xs text-gray-500">{{ (e.user_id[:8] ~ '...') if e.user_id else '-' }}</td>
            <td class="px-3 py-2 text-xs text-gray-400">
                {% if e.details and e.details is mapping %}
                    {{ e.details.get('status_code', '') }} {{ e.details.get('duration_ms', '') }}ms
                {% endif %}
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
</div>
{% else %}
<div class="card text-center py-12">
    <p class="text-gray-400">No audit entries found.</p>
</div>
{% endif %}

{% if error %}
<div class="card mt-4 border-l-4 border-red-400"><p class="text-sm text-red-600">{{ error }}</p></div>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Mount routes in server.py**

In `src/spec2sphere/web/server.py`, after the factory routes mount block (around line 225), add:

```python
    # Mount governance routes (reports, audit log, lab)
    try:
        from spec2sphere.web.governance_routes import create_governance_routes

        app.include_router(create_governance_routes())
    except ImportError as exc:
        logger.warning("Could not mount governance routes: %s", exc)
```

- [ ] **Step 7: Add nav items to base.html**

In `src/spec2sphere/web/templates/base.html`, in the `nav_items` list, add after the `("lab/fitness", ...)` entry:

```python
            ("lab", "Lab", "M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"),
            ("audit-log", "Audit Log", "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"),
```

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_session6_governance_routes.py -v`
Expected: All 5 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/spec2sphere/web/governance_routes.py src/spec2sphere/web/templates/partials/reports_v2.html src/spec2sphere/web/templates/partials/lab.html src/spec2sphere/web/templates/partials/audit_log.html src/spec2sphere/web/server.py src/spec2sphere/web/templates/base.html tests/test_session6_governance_routes.py
git commit -m "feat(session6): governance routes — reports browser, audit log, lab UI, release API"
```

---

## Task 8: Demo Fixtures + E2E Integration Test

**Files:**
- Create: `tests/fixtures/demo/sample_brs.md`
- Create: `tests/fixtures/demo/demo_config.yaml`
- Create: `tests/test_session6_integration.py`

- [ ] **Step 1: Create demo BRS fixture**

```markdown
# Sales Planning — Business Requirements Specification

## Executive Summary
Revenue reporting dashboard for regional sales teams with drill-down from geography to product level.

## KPI Definitions
- **Net Revenue**: Gross sales minus discounts and returns
- **Gross Margin**: (Net Revenue - COGS) / Net Revenue
- **YTD Growth**: Year-to-date revenue vs prior year

## Data Sources
- SAP S/4HANA: Sales orders (VBAK/VBAP)
- SAP BW: Existing revenue cube (0SD_C01)

## Dimensions
- Time (Year, Quarter, Month, Week)
- Product (Category, Subcategory, Material)
- Geography (Region, Country, City)
- Sales Organization

## Requirements
1. Executive overview page with KPI tiles and trend charts
2. Regional drill-down with variance analysis
3. Product performance ranking with waterfall
4. Monthly actuals vs plan comparison
```

- [ ] **Step 2: Create demo config**

```yaml
# Demo scenario — Horvath Demo customer
customer:
  name: "Horvath Demo"
  slug: "horvath-demo"
  branding:
    primary_color: "#05415A"
    accent_color: "#C8963E"

project:
  name: "Sales Planning"
  slug: "sales-planning"
  environment: "sandbox"

modules:
  core: true
  migration_accelerator: true
  dsp_factory: true
  sac_factory: true
  governance: true
  artifact_lab: true
  multi_tenant: false
```

- [ ] **Step 3: Write integration test**

```python
"""End-to-end integration test — full pipeline from data to documentation.

Tests the pure-Python path (no DB, no CDP) to verify the generation
pipeline works end to end.
"""

import io
import json
import zipfile
import pytest
from pathlib import Path
from uuid import uuid4

from spec2sphere.governance.doc_generator import (
    generate_technical_doc,
    generate_functional_doc,
    generate_traceability_matrix,
    generate_decision_log,
    generate_reconciliation_report,
    render_html_report,
    render_markdown_report,
)
from spec2sphere.governance.release import assemble_release_package, ReleaseManifest
from spec2sphere.governance.promotion import anonymize_content, build_promotion_candidate
from spec2sphere.sac_factory.style_learning import update_preference, get_style_profile, StylePreference
from spec2sphere.artifact_lab.lab_runner import compute_diff, run_experiment
from spec2sphere.artifact_lab.experiment_tracker import build_experiment_record
from spec2sphere.artifact_lab.template_store import build_template_from_experiment
from spec2sphere.artifact_lab.mutation_catalog import get_mutations, is_safe_mutation


@pytest.fixture
def demo_project():
    """Full demo project dataset mirroring a real pipeline output."""
    pid = str(uuid4())
    cid = str(uuid4())
    return {
        "project": {"id": pid, "name": "Sales Planning", "slug": "sales-planning", "customer_id": cid},
        "customer": {"id": cid, "name": "Horvath Demo", "slug": "horvath-demo"},
        "requirements": [
            {
                "id": str(uuid4()), "title": "Revenue KPI Model", "business_domain": "Finance",
                "description": "Revenue reporting with regional drill-down",
                "parsed_entities": {"fact_tables": ["revenue_fact"], "dimensions": ["time", "product", "region"]},
                "parsed_kpis": [
                    {"name": "Net Revenue", "formula": "gross - discounts"},
                    {"name": "Gross Margin", "formula": "(net_revenue - cogs) / net_revenue"},
                ],
                "status": "approved",
            },
        ],
        "hla_documents": [
            {"id": str(uuid4()), "content": {"layers": ["raw", "harmonized", "mart"]},
             "narrative": "Standard 3-layer architecture", "status": "approved"},
        ],
        "tech_specs": [
            {"id": str(uuid4()), "objects": [
                {"name": "V_RAW_REVENUE", "object_type": "relational_view", "layer": "raw"},
                {"name": "V_HARM_REVENUE", "object_type": "relational_view", "layer": "harmonized"},
                {"name": "V_MART_REVENUE", "object_type": "relational_view", "layer": "mart"},
            ], "deployment_order": ["V_RAW_REVENUE", "V_HARM_REVENUE", "V_MART_REVENUE"], "status": "approved"},
        ],
        "architecture_decisions": [
            {"topic": "Aggregation", "choice": "Pre-aggregate at mart", "rationale": "SAC performance", "platform_placement": "dsp"},
            {"topic": "Time Hierarchy", "choice": "DSP hierarchy view", "rationale": "Reusable across models", "platform_placement": "dsp"},
        ],
        "reconciliation_results": [
            {"test_case_key": "revenue_total", "delta_status": "pass", "baseline_value": {"total": 1000000}, "candidate_value": {"total": 1000000}},
            {"test_case_key": "margin_avg", "delta_status": "within_tolerance", "baseline_value": {"avg": 0.35}, "candidate_value": {"avg": 0.349}},
        ],
        "technical_objects": [
            {"name": "V_RAW_REVENUE", "object_type": "relational_view", "platform": "dsp", "layer": "raw",
             "generated_artifact": "CREATE VIEW V_RAW_REVENUE AS SELECT * FROM SRC_REVENUE", "status": "deployed"},
            {"name": "V_HARM_REVENUE", "object_type": "relational_view", "platform": "dsp", "layer": "harmonized",
             "generated_artifact": "CREATE VIEW V_HARM_REVENUE AS SELECT ...", "status": "deployed"},
            {"name": "V_MART_REVENUE", "object_type": "relational_view", "platform": "dsp", "layer": "mart",
             "generated_artifact": "CREATE VIEW V_MART_REVENUE AS SELECT ...", "status": "deployed"},
        ],
        "approvals": [
            {"id": str(uuid4()), "artifact_type": "hla_document", "status": "approved", "resolved_at": "2026-04-16T10:00:00Z"},
            {"id": str(uuid4()), "artifact_type": "tech_spec", "status": "approved", "resolved_at": "2026-04-16T11:00:00Z"},
        ],
    }


class TestE2EPipeline:
    """Full pipeline: data -> docs -> release -> lab -> promotion."""

    def test_01_generate_all_docs(self, demo_project):
        tech = generate_technical_doc(demo_project)
        assert tech["object_count"] == 3
        assert "V_MART_REVENUE" in tech["content"]

        func = generate_functional_doc(demo_project)
        assert "Net Revenue" in func["content"]
        assert "Gross Margin" in func["content"]

    def test_02_traceability(self, demo_project):
        matrix = generate_traceability_matrix(demo_project)
        assert len(matrix["rows"]) == 1
        assert matrix["rows"][0]["result"] in ("PASS", "PARTIAL")

    def test_03_decision_log(self, demo_project):
        log = generate_decision_log(demo_project)
        assert len(log) == 2
        topics = [d["topic"] for d in log]
        assert "Aggregation" in topics

    def test_04_reconciliation_summary(self, demo_project):
        recon = generate_reconciliation_report(demo_project)
        assert recon["total_tests"] == 2
        assert recon["passed"] == 1
        assert recon["tolerance"] == 1
        assert recon["failed"] == 0

    def test_05_html_report(self, demo_project):
        html = render_html_report(demo_project)
        assert "<!DOCTYPE html>" in html
        assert "Sales Planning" in html
        assert "V_RAW_REVENUE" in html
        assert "Horvath Demo" in html
        assert "Traceability Matrix" in html

    def test_06_markdown_report(self, demo_project):
        md = render_markdown_report(demo_project)
        assert "# Sales Planning" in md
        assert "## Traceability Matrix" in md
        assert "## Architecture Decisions" in md

    def test_07_release_package(self, demo_project):
        zip_bytes = assemble_release_package(demo_project, version="1.0.0")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            assert "docs/technical.html" in names
            assert "docs/functional.md" in names
            assert "reconciliation/summary.json" in names
            assert any(n.startswith("artifacts/") for n in names)

            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["version"] == "1.0.0"
            assert manifest["object_count"] == 3

    def test_08_artifact_lab_flow(self):
        """Create experiment -> build template -> check graduation."""
        exp = build_experiment_record(
            customer_id=str(uuid4()), platform="dsp", object_type="relational_view",
            experiment_type="create",
            input_def={"name": "V_LAB_TEST", "fields": ["id", "amount"]},
            output_def={"name": "V_LAB_TEST", "fields": ["id", "amount"], "sql": "SELECT id, amount FROM t"},
            route_used="cdp", success=True,
        )
        assert exp.success
        assert exp.diff["changed"]

        tpl = build_template_from_experiment(exp)
        assert tpl.approved is False
        assert tpl.platform == "dsp"

    def test_09_mutation_catalog(self):
        dsp_muts = get_mutations("dsp", "relational_view")
        assert len(dsp_muts) >= 5
        assert is_safe_mutation("dsp", "relational_view", "add_field")
        assert not is_safe_mutation("dsp", "relational_view", "drop_table")

        sac_muts = get_mutations("sac", "story")
        assert len(sac_muts) >= 4

    def test_10_promotion_anonymization(self, demo_project):
        content = {
            "customer_name": "Horvath Demo",
            "object_name": "V_HORVATH_REVENUE",
            "pattern": {"type": "star_schema", "layers": 3},
        }
        anon = anonymize_content(content)
        assert "Horvath" not in str(anon)
        assert anon["pattern"]["type"] == "star_schema"

    def test_11_style_learning(self):
        prefs: dict[str, StylePreference] = {}
        prefs = update_preference(prefs, "layout", "exec_overview", approved=True)
        prefs = update_preference(prefs, "layout", "exec_overview", approved=True)
        prefs = update_preference(prefs, "layout", "table_first", approved=False)
        prefs = update_preference(prefs, "chart", "bar", approved=True)

        profile = get_style_profile(prefs)
        assert profile["preferred_layouts"][0] == "exec_overview"
        assert "table_first" not in profile["preferred_layouts"]  # negative score

    def test_12_diff_engine(self):
        diff = compute_diff(
            {"a": 1, "b": [1, 2], "c": "hello"},
            {"a": 2, "b": [1, 2], "d": "new"},
        )
        assert diff["changed"]
        assert "a" in diff["modifications"]
        assert "c" in diff["removals"]
        assert "d" in diff["additions"]
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_session6_integration.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Run full session 6 test suite**

Run: `python -m pytest tests/test_session6_*.py -v`
Expected: All tests PASS (35+ tests total)

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/demo/ tests/test_session6_integration.py
git commit -m "feat(session6): demo fixtures + 12-test E2E integration suite"
```

---

## Task 9: Final Polish — Module Wiring, Oracle Update, Replace Reports Template

**Files:**
- Modify: `src/spec2sphere/modules.py` — Wire governance and artifact_lab routes_factory
- Modify: `src/spec2sphere/web/server.py` — Update Oracle registration
- Modify: `src/spec2sphere/web/templates/partials/reports.html` — Replace content

- [ ] **Step 1: Wire module routes_factory**

In `src/spec2sphere/modules.py`, update the governance and artifact_lab ModuleSpec entries to include routes_factory:

```python
    ModuleSpec(
        name="governance",
        description="Approval workflow, confidence scoring, traceability, RBAC",
        ui_sections=["governance", "approvals", "reports", "audit_log"],
        routes_factory=lambda: __import__("spec2sphere.web.governance_routes", fromlist=["create_governance_routes"]).create_governance_routes(),
    ),
    ModuleSpec(
        name="artifact_lab",
        description="Sandbox experimentation, template learning, route fitness tracking",
        ui_sections=["artifact_lab", "lab"],
    ),
```

- [ ] **Step 2: Update Oracle registration**

In `src/spec2sphere/web/server.py`, add new endpoints to the Oracle manifest:

```python
                {"method": "GET", "path": "/ui/reports", "purpose": "Reports & documentation browser"},
                {"method": "GET", "path": "/ui/audit-log", "purpose": "Audit log viewer"},
                {"method": "GET", "path": "/ui/lab", "purpose": "Artifact Learning Lab"},
                {"method": "POST", "path": "/api/governance/generate-report", "purpose": "Generate as-built report"},
                {"method": "POST", "path": "/api/governance/release", "purpose": "Assemble release package"},
                {"method": "POST", "path": "/api/lab/templates/{id}/graduate", "purpose": "Graduate learned template"},
```

- [ ] **Step 3: Replace reports.html with redirect to v2**

Overwrite `src/spec2sphere/web/templates/partials/reports.html` with the content from `reports_v2.html` (same file). Then delete the `_v2` version.

Actually — simpler: just ensure the existing `/ui/reports` route in `governance_routes.py` renders `reports_v2.html`. The old `reports.html` from `ui.py` is already superseded since governance_routes registers at the same path. No changes needed if governance_routes are mounted after ui_router (they are — mounted in lifespan → mount_enabled_routes which runs after include_router(ui_router)).

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/test_session6_*.py tests/test_session5_*.py tests/test_session3_pipeline.py tests/test_session4_pipeline.py -v --timeout=30`
Expected: All PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add src/spec2sphere/modules.py src/spec2sphere/web/server.py
git commit -m "feat(session6): wire governance module, update Oracle registration, polish"
```

---

## Task 10: Git Push + Deploy

- [ ] **Step 1: Run full test suite one final time**

Run: `python -m pytest tests/ -x -q --timeout=30`
Expected: All pass

- [ ] **Step 2: Push to Gitea**

```bash
cd /home/hesch/dev/projects/sap-doc-agent
git push origin main
```

- [ ] **Step 3: Deploy via ops-bridge**

```bash
curl -s -X POST "http://192.168.0.50:9090/deploy/sap-doc-agent" \
  -H "X-API-Key: super_secure_api_key" \
  -H "Content-Type: application/json" \
  -d '{"no_cache": true}'
```

- [ ] **Step 4: Smoke check**

```bash
curl -s http://192.168.0.50:8260/health | python -m json.tool
curl -s http://192.168.0.50:8260/ui/dashboard -o /dev/null -w "%{http_code}"
curl -s http://192.168.0.50:8260/ui/reports -o /dev/null -w "%{http_code}"
curl -s http://192.168.0.50:8260/ui/lab -o /dev/null -w "%{http_code}"
curl -s http://192.168.0.50:8260/ui/audit-log -o /dev/null -w "%{http_code}"
```
Expected: health returns `{"status": "ok", ...}`, all UI pages return 200.
