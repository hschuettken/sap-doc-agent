"""Migration Assessment Report generator.

Produces a self-contained HTML report aggregating all migration phase outputs.
Mermaid diagrams are rendered client-side via CDN script tag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Template

from sap_doc_agent.migration.effort import EffortEstimate
from sap_doc_agent.migration.models import (
    ClassifiedChain,
    MigrationClassification,
    TargetArchitecture,
    ViewSpec,
)
from sap_doc_agent.scanner.models import DataFlowChain

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "migration_report.html"


@dataclass
class ReportData:
    """All data needed to generate the migration assessment report."""

    project_name: str
    chains: list[tuple[ClassifiedChain, DataFlowChain]]
    architecture: TargetArchitecture | None = None
    efforts: list[EffortEstimate] = field(default_factory=list)
    diagrams: dict[str, str] = field(default_factory=dict)
    brs_reconciliation: list[dict] | None = None
    generated_sql: dict[str, str] = field(default_factory=dict)


def _classification_counts(chains: list[tuple[ClassifiedChain, DataFlowChain]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for classified, _ in chains:
        key = classified.classification.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _effort_summary(efforts: list[EffortEstimate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in efforts:
        counts[e.category.value] = counts.get(e.category.value, 0) + 1
    return counts


def _object_type_counts(chains: list[tuple[ClassifiedChain, DataFlowChain]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, chain in chains:
        for step in chain.steps:
            key = step.object_type.value
            counts[key] = counts.get(key, 0) + 1
    return counts


def _drop_chains(chains: list[tuple[ClassifiedChain, DataFlowChain]]) -> list[tuple[ClassifiedChain, DataFlowChain]]:
    return [
        (c, ch)
        for c, ch in chains
        if c.classification in (MigrationClassification.DROP, MigrationClassification.CLARIFY)
    ]


def generate_report_html(data: ReportData) -> str:
    """Generate the migration assessment report as self-contained HTML."""
    template = Template(_TEMPLATE_PATH.read_text())

    classification_counts = _classification_counts(data.chains)
    effort_counts = _effort_summary(data.efforts)
    object_types = _object_type_counts(data.chains)
    drop_chains = _drop_chains(data.chains)
    effort_by_chain = {e.chain_id: e for e in data.efforts}

    views = data.architecture.views if data.architecture else []
    views_by_layer: dict[str, list[ViewSpec]] = {}
    for v in views:
        views_by_layer.setdefault(v.layer, []).append(v)

    return template.render(
        project_name=data.project_name,
        chains=data.chains,
        chain_count=len(data.chains),
        classification_counts=classification_counts,
        effort_counts=effort_counts,
        effort_by_chain=effort_by_chain,
        object_types=object_types,
        drop_chains=drop_chains,
        architecture=data.architecture,
        views=views,
        views_by_layer=views_by_layer,
        diagrams=data.diagrams,
        brs_reconciliation=data.brs_reconciliation,
        generated_sql=data.generated_sql,
    )
