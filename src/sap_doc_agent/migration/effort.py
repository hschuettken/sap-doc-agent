"""Effort estimation for migration chains.

Scores chains as trivial/moderate/complex based on step count and ABAP line count.
Thresholds are configurable via EffortThresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sap_doc_agent.migration.models import ClassifiedChain, MigrationClassification
from sap_doc_agent.scanner.models import DataFlowChain


class EffortCategory(str, Enum):
    TRIVIAL = "trivial"
    MODERATE = "moderate"
    COMPLEX = "complex"


@dataclass
class EffortThresholds:
    """Configurable thresholds for effort scoring."""

    trivial_max_steps: int = 2
    complex_min_steps: int = 6
    complex_min_abap_lines: int = 200


@dataclass
class EffortEstimate:
    """Result of effort estimation for a single chain."""

    chain_id: str
    category: EffortCategory
    step_count: int
    abap_line_count: int
    rationale: str


_DEFAULT_THRESHOLDS = EffortThresholds()


def _count_abap_lines(chain: DataFlowChain) -> int:
    return sum(len(step.source_code.splitlines()) for step in chain.steps if step.source_code)


def estimate_chain_effort(
    classified: ClassifiedChain,
    chain: DataFlowChain,
    thresholds: EffortThresholds | None = None,
) -> EffortEstimate:
    """Estimate migration effort for a single classified chain."""
    t = thresholds or _DEFAULT_THRESHOLDS
    step_count = len(chain.steps)
    abap_lines = _count_abap_lines(chain)

    # DROP and REPLACE chains are trivial — no migration work needed
    if classified.classification in (MigrationClassification.DROP, MigrationClassification.REPLACE):
        return EffortEstimate(
            chain_id=classified.chain_id,
            category=EffortCategory.TRIVIAL,
            step_count=step_count,
            abap_line_count=abap_lines,
            rationale=f"Classification is {classified.classification.value} — no migration implementation needed",
        )

    # Complex: many steps OR many ABAP lines
    if step_count >= t.complex_min_steps or abap_lines >= t.complex_min_abap_lines:
        reasons = []
        if step_count >= t.complex_min_steps:
            reasons.append(f"{step_count} steps (threshold: {t.complex_min_steps})")
        if abap_lines >= t.complex_min_abap_lines:
            reasons.append(f"{abap_lines} ABAP lines (threshold: {t.complex_min_abap_lines})")
        return EffortEstimate(
            chain_id=classified.chain_id,
            category=EffortCategory.COMPLEX,
            step_count=step_count,
            abap_line_count=abap_lines,
            rationale=f"Complex: {', '.join(reasons)}",
        )

    # Trivial: few steps and little code
    if step_count <= t.trivial_max_steps:
        return EffortEstimate(
            chain_id=classified.chain_id,
            category=EffortCategory.TRIVIAL,
            step_count=step_count,
            abap_line_count=abap_lines,
            rationale=f"Trivial: {step_count} step(s), {abap_lines} ABAP lines",
        )

    # Everything else is moderate
    return EffortEstimate(
        chain_id=classified.chain_id,
        category=EffortCategory.MODERATE,
        step_count=step_count,
        abap_line_count=abap_lines,
        rationale=f"Moderate: {step_count} steps, {abap_lines} ABAP lines",
    )


def estimate_project_effort(
    chains: list[tuple[ClassifiedChain, DataFlowChain]],
    thresholds: EffortThresholds | None = None,
) -> list[EffortEstimate]:
    """Estimate effort for all chains in a project."""
    return [estimate_chain_effort(classified, chain, thresholds) for classified, chain in chains]
