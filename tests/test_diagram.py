"""Tests for before/after migration diagrams (Mermaid syntax)."""

from sap_doc_agent.migration.diagram import generate_chain_diagram, generate_project_diagrams
from sap_doc_agent.migration.models import (
    ClassifiedChain,
    IntentCard,
    MigrationClassification,
    TransformationIntent,
    ViewSpec,
)
from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType


def _make_chain() -> DataFlowChain:
    return DataFlowChain(
        chain_id="chain_001",
        name="Sales Revenue",
        terminal_object_id="CMP_REV",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["DS_BILLING"],
        steps=[
            ChainStep(
                position=1,
                object_id="TRAN_001",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_BILLING_RAW",
                inter_step_object_id="DSO_RAW",
                inter_step_object_name="ZADSO_BILLING_RAW",
            ),
            ChainStep(
                position=2,
                object_id="TRAN_002",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_REVENUE_CLEAN",
                inter_step_object_id="DSO_CLEAN",
                inter_step_object_name="ZADSO_REVENUE_CLEAN",
            ),
            ChainStep(
                position=3,
                object_id="TRAN_003",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_REVENUE_AGG",
                inter_step_object_id="DSO_AGG",
                inter_step_object_name="ZADSO_REVENUE_AGG",
            ),
        ],
        all_object_ids=["DS_BILLING", "TRAN_001", "DSO_RAW", "TRAN_002", "DSO_CLEAN", "TRAN_003", "DSO_AGG", "CMP_REV"],
    )


def _make_classified(chain: DataFlowChain) -> ClassifiedChain:
    return ClassifiedChain(
        chain_id=chain.chain_id,
        intent_card=IntentCard(
            chain_id=chain.chain_id,
            business_purpose="Monthly net revenue by customer and material",
            data_domain="Sales",
            transformations=[
                TransformationIntent(step_number=1, intent="Load billing data"),
                TransformationIntent(step_number=2, intent="Currency conversion to EUR"),
                TransformationIntent(step_number=3, intent="Monthly aggregation by customer"),
            ],
        ),
        classification=MigrationClassification.MIGRATE,
    )


def _make_views() -> list[ViewSpec]:
    return [
        ViewSpec(
            technical_name="02_RV_BILLING_CLEAN",
            layer="harmonization",
            semantic_usage="relational_dataset",
            description="Billing data cleaned and currency-converted",
            collapsed_bw_steps=["TRAN_001", "TRAN_002"],
        ),
        ViewSpec(
            technical_name="03_FV_REVENUE_MONTHLY",
            layer="mart",
            semantic_usage="fact",
            description="Monthly revenue fact view",
            collapsed_bw_steps=["TRAN_003"],
        ),
    ]


def test_diagram_contains_mermaid_header():
    chain = _make_chain()
    classified = _make_classified(chain)
    views = _make_views()
    mermaid = generate_chain_diagram(classified, chain, views)
    assert mermaid.startswith("graph LR")


def test_diagram_contains_bw_source():
    chain = _make_chain()
    classified = _make_classified(chain)
    views = _make_views()
    mermaid = generate_chain_diagram(classified, chain, views)
    assert "DS_BILLING" in mermaid


def test_diagram_contains_bw_steps():
    chain = _make_chain()
    classified = _make_classified(chain)
    views = _make_views()
    mermaid = generate_chain_diagram(classified, chain, views)
    assert "TRAN_001" in mermaid
    assert "TRAN_002" in mermaid
    assert "DSO_RAW" in mermaid


def test_diagram_contains_intent():
    chain = _make_chain()
    classified = _make_classified(chain)
    views = _make_views()
    mermaid = generate_chain_diagram(classified, chain, views)
    assert "business_purpose" in mermaid.lower() or "Monthly net revenue" in mermaid


def test_diagram_contains_dsp_target():
    chain = _make_chain()
    classified = _make_classified(chain)
    views = _make_views()
    mermaid = generate_chain_diagram(classified, chain, views)
    assert "02_RV_BILLING_CLEAN" in mermaid
    assert "03_FV_REVENUE_MONTHLY" in mermaid


def test_diagram_drop_chain_no_target():
    chain = _make_chain()
    classified = ClassifiedChain(
        chain_id=chain.chain_id,
        intent_card=IntentCard(chain_id=chain.chain_id, business_purpose="Dead chain"),
        classification=MigrationClassification.DROP,
    )
    mermaid = generate_chain_diagram(classified, chain, [])
    assert "DROP" in mermaid
    # Should still show BW side
    assert "DS_BILLING" in mermaid


def test_diagram_empty_chain():
    chain = DataFlowChain(
        chain_id="empty",
        name="Empty",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[],
        all_object_ids=["S", "T"],
    )
    classified = ClassifiedChain(
        chain_id="empty",
        intent_card=IntentCard(chain_id="empty", business_purpose="Nothing"),
        classification=MigrationClassification.CLARIFY,
    )
    mermaid = generate_chain_diagram(classified, chain, [])
    assert "graph LR" in mermaid


def test_generate_project_diagrams():
    chain = _make_chain()
    classified = _make_classified(chain)
    views = _make_views()
    diagrams = generate_project_diagrams([(classified, chain, views)])
    assert len(diagrams) == 1
    assert "chain_001" in diagrams
    assert "graph LR" in diagrams["chain_001"]
