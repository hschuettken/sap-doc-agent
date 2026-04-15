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


# --- Phase C: Target Architecture models ---


class ColumnSpec(BaseModel):
    """Column definition in a target DSP view."""

    name: str
    data_type: str = ""
    description: str = ""
    source_field: str = ""  # BW source field for traceability
    is_key: bool = False
    is_measure: bool = False
    aggregation: str = ""  # SUM, COUNT, AVG, etc.


class ViewSpec(BaseModel):
    """Specification for a target DSP SQL view."""

    technical_name: str  # e.g., "02_RV_BILLING_CLEAN"
    space: str = ""
    layer: str = ""  # staging, harmonization, mart, consumption
    semantic_usage: str = ""  # relational_dataset, fact, dimension, text, hierarchy
    description: str = ""
    source_chains: list[str] = Field(default_factory=list)  # BW chains this replaces
    source_objects: list[str] = Field(default_factory=list)  # upstream DSP views/tables
    columns: list[ColumnSpec] = Field(default_factory=list)
    sql_logic: str = ""  # SQL sketch (logic, not final code)
    collapse_rationale: str = ""  # why BW steps were collapsed into this view
    collapsed_bw_steps: list[str] = Field(default_factory=list)  # BW step IDs this replaces
    persistence: bool = False
    persistence_rationale: Optional[str] = None
    estimated_rows: Optional[int] = None


class ReplicationFlowSpec(BaseModel):
    """Specification for a DSP replication flow."""

    technical_name: str
    source_table: str  # ECC/S4 table
    target_table: str  # 01_LT_ local table
    space: str = ""
    delta_enabled: bool = True
    schedule: str = ""  # e.g., "daily 02:00"


class AnalyticModelSpec(BaseModel):
    """Specification for a DSP Analytic Model (consumption layer)."""

    technical_name: str
    source_fact_view: str
    dimension_associations: list[str] = Field(default_factory=list)
    description: str = ""
    replaces_bex_query: Optional[str] = None


class PersistenceDecision(BaseModel):
    """Decision about whether to persist a view."""

    view_name: str
    persist: bool
    rationale: str


class MigrationStep(BaseModel):
    """One step in the ordered migration sequence."""

    order: int
    view_name: str
    depends_on: list[str] = Field(default_factory=list)
    effort: str = ""  # trivial, moderate, complex
    notes: str = ""


class SpaceDesign(BaseModel):
    """Design for a DSP space."""

    name: str
    purpose: str = ""
    pattern: str = ""  # single_tenant, source_semantic_split, multi_tier
    shares_from: list[str] = Field(default_factory=list)
    shares_to: list[str] = Field(default_factory=list)
    estimated_disk_gb: Optional[float] = None


class TargetArchitecture(BaseModel):
    """Complete DSP target architecture for a migration project."""

    project_name: str
    spaces: list[SpaceDesign] = Field(default_factory=list)
    views: list[ViewSpec] = Field(default_factory=list)
    replication_flows: list[ReplicationFlowSpec] = Field(default_factory=list)
    analytic_models: list[AnalyticModelSpec] = Field(default_factory=list)
    persistence_plan: list[PersistenceDecision] = Field(default_factory=list)
    migration_sequence: list[MigrationStep] = Field(default_factory=list)
