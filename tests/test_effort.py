"""Tests for migration effort estimation."""

from sap_doc_agent.migration.effort import (
    EffortCategory,
    EffortThresholds,
    estimate_chain_effort,
    estimate_project_effort,
)
from sap_doc_agent.migration.models import ClassifiedChain, IntentCard, MigrationClassification
from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType


def _make_chain(step_count: int, abap_lines: int = 0) -> DataFlowChain:
    steps = []
    for i in range(step_count):
        code = "\n".join(f"line {j}" for j in range(abap_lines // max(step_count, 1)))
        steps.append(
            ChainStep(
                position=i + 1,
                object_id=f"TR_{i}",
                object_type=ObjectType.TRANSFORMATION,
                name=f"Step {i}",
                source_code=code,
            )
        )
    return DataFlowChain(
        chain_id="test_chain",
        name="Test",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=steps,
        all_object_ids=["S", "T"],
    )


def _make_classified(
    chain: DataFlowChain, classification: MigrationClassification = MigrationClassification.MIGRATE
) -> ClassifiedChain:
    return ClassifiedChain(
        chain_id=chain.chain_id,
        intent_card=IntentCard(chain_id=chain.chain_id, business_purpose="Test"),
        classification=classification,
    )


def test_trivial_effort():
    chain = _make_chain(step_count=1, abap_lines=10)
    classified = _make_classified(chain)
    result = estimate_chain_effort(classified, chain)
    assert result.category == EffortCategory.TRIVIAL
    assert result.step_count == 1
    assert result.abap_line_count == 10


def test_moderate_effort():
    chain = _make_chain(step_count=4, abap_lines=80)
    classified = _make_classified(chain)
    result = estimate_chain_effort(classified, chain)
    assert result.category == EffortCategory.MODERATE


def test_complex_effort_many_steps():
    chain = _make_chain(step_count=8, abap_lines=50)
    classified = _make_classified(chain)
    result = estimate_chain_effort(classified, chain)
    assert result.category == EffortCategory.COMPLEX


def test_complex_effort_many_abap_lines():
    chain = _make_chain(step_count=2, abap_lines=300)
    classified = _make_classified(chain)
    result = estimate_chain_effort(classified, chain)
    assert result.category == EffortCategory.COMPLEX


def test_drop_chains_are_trivial():
    chain = _make_chain(step_count=10, abap_lines=500)
    classified = _make_classified(chain, MigrationClassification.DROP)
    result = estimate_chain_effort(classified, chain)
    assert result.category == EffortCategory.TRIVIAL


def test_custom_thresholds():
    thresholds = EffortThresholds(trivial_max_steps=1, complex_min_steps=3, complex_min_abap_lines=50)
    chain = _make_chain(step_count=2, abap_lines=10)
    classified = _make_classified(chain)
    result = estimate_chain_effort(classified, chain, thresholds)
    assert result.category == EffortCategory.MODERATE


def test_estimate_project_effort():
    chains = []
    for i, (steps, lines, cls) in enumerate(
        [
            (1, 10, MigrationClassification.MIGRATE),
            (4, 80, MigrationClassification.SIMPLIFY),
            (8, 300, MigrationClassification.MIGRATE),
            (3, 50, MigrationClassification.DROP),
        ]
    ):
        chain = _make_chain(steps, lines)
        chain.chain_id = f"chain_{i}"  # type: ignore[misc]
        classified = _make_classified(chain, cls)
        chains.append((classified, chain))

    results = estimate_project_effort(chains)
    assert len(results) == 4
    categories = [r.category for r in results]
    assert EffortCategory.TRIVIAL in categories
    assert EffortCategory.COMPLEX in categories


def test_effort_estimate_has_rationale():
    chain = _make_chain(step_count=3, abap_lines=50)
    classified = _make_classified(chain)
    result = estimate_chain_effort(classified, chain)
    assert result.rationale != ""
    assert "step" in result.rationale.lower() or "abap" in result.rationale.lower()
