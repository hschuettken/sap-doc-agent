"""Tests for Migration Accelerator Pydantic models."""

from spec2sphere.migration.models import (
    BRSDelta,
    BRSReference,
    ClassifiedChain,
    IntentCard,
    MigrationClassification,
    ReviewDecision,
    StepClassification,
    TransformationIntent,
)


def test_migration_classification_enum_values():
    assert MigrationClassification.MIGRATE == "migrate"
    assert MigrationClassification.SIMPLIFY == "simplify"
    assert MigrationClassification.REPLACE == "replace"
    assert MigrationClassification.DROP == "drop"
    assert MigrationClassification.CLARIFY == "clarify"


def test_transformation_intent_minimal():
    ti = TransformationIntent(step_number=1, intent="Convert currency to EUR")
    assert ti.step_number == 1
    assert ti.is_business_logic is True
    assert ti.simplification_note is None


def test_transformation_intent_full():
    ti = TransformationIntent(
        step_number=2,
        intent="Convert currency to EUR",
        implementation="ABAP start routine reads TCURR, hardcoded target EUR",
        is_business_logic=True,
        simplification_note="Use CASE WHEN or currency dimension in DSP",
        detected_patterns=["tcurr_conversion"],
    )
    assert ti.detected_patterns == ["tcurr_conversion"]


def test_brs_reference():
    ref = BRSReference(
        brs_document="BRS_Revenue_2020.docx",
        requirement_id="REQ-042",
        requirement_text="Monthly revenue by customer in EUR",
        match_confidence=0.85,
        delta_notes="BRS didn't mention currency conversion",
    )
    assert ref.match_confidence == 0.85


def test_intent_card_minimal():
    card = IntentCard(chain_id="chain_001")
    assert card.chain_id == "chain_001"
    assert card.business_purpose == ""
    assert card.confidence == 0.0
    assert card.needs_human_review is False
    assert card.transformations == []
    assert card.brs_references == []


def test_intent_card_full():
    card = IntentCard(
        chain_id="chain_001",
        business_purpose="Monthly net revenue reporting by customer",
        data_domain="Sales & Distribution",
        source_systems=["ECC SD"],
        key_entities=["Customer", "Material"],
        key_measures=["Net Revenue (EUR)"],
        grain="Customer × Material × Month",
        consumers=["BEx Query ZQ_REV"],
        transformations=[
            TransformationIntent(step_number=1, intent="Filter test orders"),
            TransformationIntent(step_number=2, intent="Convert to EUR"),
        ],
        brs_references=[
            BRSReference(brs_document="BRS_Rev.docx", requirement_id="REQ-001"),
        ],
        confidence=0.85,
        needs_human_review=False,
        review_notes=["Verify customer hierarchy source"],
    )
    assert len(card.transformations) == 2
    assert len(card.brs_references) == 1
    assert card.grain == "Customer × Material × Month"


def test_intent_card_low_confidence_flags_review():
    card = IntentCard(chain_id="c1", confidence=0.5, needs_human_review=True)
    assert card.needs_human_review is True


def test_step_classification():
    sc = StepClassification(
        step_number=1,
        object_id="TRAN_001",
        classification=MigrationClassification.SIMPLIFY,
        rationale="Currency conversion via TCURR can be SQL CASE WHEN",
        detected_patterns=["tcurr_conversion"],
        dsp_equivalent="CASE WHEN in SQL view",
    )
    assert sc.classification == MigrationClassification.SIMPLIFY


def test_classified_chain_minimal():
    card = IntentCard(chain_id="c1", business_purpose="Revenue")
    cc = ClassifiedChain(
        chain_id="c1",
        intent_card=card,
        classification=MigrationClassification.MIGRATE,
    )
    assert cc.classification == MigrationClassification.MIGRATE
    assert cc.effort_category is None
    assert cc.step_classifications == []


def test_classified_chain_drop_with_evidence():
    card = IntentCard(chain_id="c_dead")
    cc = ClassifiedChain(
        chain_id="c_dead",
        intent_card=card,
        classification=MigrationClassification.DROP,
        rationale="No execution in 18 months, zero query usage",
        last_execution="2024-01-15",
        query_usage_count=0,
        needs_human_review=True,
    )
    assert cc.last_execution == "2024-01-15"
    assert cc.needs_human_review is True


def test_classified_chain_with_effort():
    card = IntentCard(chain_id="c1")
    cc = ClassifiedChain(
        chain_id="c1",
        intent_card=card,
        classification=MigrationClassification.SIMPLIFY,
        effort_category="moderate",
        effort_rationale="3 steps, simple ABAP but currency logic",
    )
    assert cc.effort_category == "moderate"


def test_brs_delta():
    delta = BRSDelta(
        chain_id="c1",
        brs_document="BRS_Rev.docx",
        brs_says="Monthly revenue for DE only",
        bw_does="Revenue for DE, AT, and CH",
        delta="Scope expanded to include AT and CH beyond original spec",
        delta_type="scope_creep",
        confidence=0.8,
    )
    assert delta.delta_type == "scope_creep"


def test_review_decision():
    rd = ReviewDecision(
        decision="approve",
        notes="Classification looks correct",
        reviewer="consultant@horvath.com",
    )
    assert rd.decision == "approve"


def test_intent_card_json_round_trip():
    card = IntentCard(
        chain_id="c1",
        business_purpose="Test",
        transformations=[TransformationIntent(step_number=1, intent="Filter")],
        confidence=0.9,
    )
    json_str = card.model_dump_json()
    restored = IntentCard.model_validate_json(json_str)
    assert restored.chain_id == "c1"
    assert len(restored.transformations) == 1


def test_classified_chain_json_round_trip():
    card = IntentCard(chain_id="c1")
    cc = ClassifiedChain(
        chain_id="c1",
        intent_card=card,
        classification=MigrationClassification.MIGRATE,
        step_classifications=[
            StepClassification(
                step_number=1,
                object_id="TR1",
                classification=MigrationClassification.SIMPLIFY,
            )
        ],
    )
    json_str = cc.model_dump_json()
    restored = ClassifiedChain.model_validate_json(json_str)
    assert restored.step_classifications[0].classification == MigrationClassification.SIMPLIFY
