"""Pydantic models for the Migration Accelerator."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MigrationClassification(str, Enum):
    """How a chain should be handled during migration."""

    MIGRATE = "migrate"
    SIMPLIFY = "simplify"
    REPLACE = "replace"
    DROP = "drop"
    CLARIFY = "clarify"


class TransformationIntent(BaseModel):
    """Semantic interpretation of a single transformation step."""

    step_number: int
    intent: str
    implementation: str = ""
    is_business_logic: bool = True
    simplification_note: Optional[str] = None
    detected_patterns: list[str] = Field(default_factory=list)


class BRSReference(BaseModel):
    """Link between a chain and an original Business Requirement Spec."""

    brs_document: str
    requirement_id: str = ""
    requirement_text: str = ""
    match_confidence: float = 0.0
    delta_notes: Optional[str] = None


class IntentCard(BaseModel):
    """Semantic interpretation of a complete data flow chain."""

    chain_id: str
    business_purpose: str = ""
    data_domain: str = ""
    source_systems: list[str] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)
    key_measures: list[str] = Field(default_factory=list)
    grain: str = ""
    consumers: list[str] = Field(default_factory=list)
    transformations: list[TransformationIntent] = Field(default_factory=list)
    brs_references: list[BRSReference] = Field(default_factory=list)
    brs_delta: Optional[str] = None
    confidence: float = 0.0
    needs_human_review: bool = False
    review_notes: list[str] = Field(default_factory=list)


class StepClassification(BaseModel):
    """Classification of a single transformation step."""

    step_number: int
    object_id: str
    classification: MigrationClassification
    rationale: str = ""
    detected_patterns: list[str] = Field(default_factory=list)
    dsp_equivalent: Optional[str] = None


class ClassifiedChain(BaseModel):
    """A chain with migration classification applied."""

    chain_id: str
    intent_card: IntentCard
    classification: MigrationClassification
    rationale: str = ""
    step_classifications: list[StepClassification] = Field(default_factory=list)
    dsp_equivalent_pattern: Optional[str] = None
    last_execution: Optional[str] = None
    query_usage_count: Optional[int] = None
    effort_category: Optional[str] = None
    effort_rationale: Optional[str] = None
    confidence: float = 0.0
    needs_human_review: bool = False


class BRSDelta(BaseModel):
    """Delta between BRS specification and actual BW implementation."""

    chain_id: str
    brs_document: str
    brs_says: str = ""
    bw_does: str = ""
    delta: str = ""
    delta_type: str = ""  # cr_addition, scope_creep, partial_implementation, workaround
    confidence: float = 0.0


class ReviewDecision(BaseModel):
    """Human review decision for an intent card or classification."""

    decision: str  # approve, reject, clarify
    notes: str = ""
    reviewer: str = ""
