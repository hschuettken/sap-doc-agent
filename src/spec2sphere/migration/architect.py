"""DSP Architect: classified chains → target architecture design."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.migration.dsp_patterns import (
    DSP_SQL_RULES,
    LAYER_PREFIXES,
    suggest_persistence,
)
from spec2sphere.migration.models import (
    AnalyticModelSpec,
    ClassifiedChain,
    MigrationClassification,
    MigrationStep,
    PersistenceDecision,
    SpaceDesign,
    TargetArchitecture,
    ViewSpec,
)
from spec2sphere.scanner.models import DataFlowChain

_PROMPT_DIR = Path(__file__).parent / "prompts"

_ARCHITECT_SYSTEM = (
    "You are an SAP Datasphere architect. You design clean, DSP-native target "
    "architectures for BW migrations. Follow the 4-layer model, naming conventions, "
    "and SQL rules exactly. Respond with valid JSON only."
)

_DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "views": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "technical_name": {"type": "string"},
                    "space": {"type": "string"},
                    "layer": {"type": "string"},
                    "semantic_usage": {"type": "string"},
                    "description": {"type": "string"},
                    "source_chains": {"type": "array", "items": {"type": "string"}},
                    "source_objects": {"type": "array", "items": {"type": "string"}},
                    "sql_logic": {"type": "string"},
                    "collapse_rationale": {"type": "string"},
                    "collapsed_bw_steps": {"type": "array", "items": {"type": "string"}},
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "data_type": {"type": "string"},
                                "description": {"type": "string"},
                                "source_field": {"type": "string"},
                                "is_key": {"type": "boolean"},
                                "is_measure": {"type": "boolean"},
                                "aggregation": {"type": "string"},
                            },
                        },
                    },
                    "persistence": {"type": "boolean"},
                    "persistence_rationale": {"type": "string"},
                },
                "required": ["technical_name", "layer", "semantic_usage", "description"],
            },
        },
    },
    "required": ["views"],
}


def _load_template() -> Template:
    template_path = _PROMPT_DIR / "design_target.md"
    return Template(template_path.read_text())


def _build_design_prompt(classified: ClassifiedChain, chain: DataFlowChain) -> str:
    """Build the architect prompt for a single chain."""
    template = _load_template()

    steps_data = []
    for t in classified.intent_card.transformations:
        steps_data.append(
            {
                "step_number": t.step_number,
                "intent": t.intent,
                "implementation": t.implementation,
                "is_business_logic": t.is_business_logic,
                "simplification_note": t.simplification_note,
                "detected_patterns": t.detected_patterns,
                "dsp_equivalent": None,
            }
        )

    step_classifications = []
    for sc in classified.step_classifications:
        step_classifications.append(
            {
                "step_number": sc.step_number,
                "object_id": sc.object_id,
                "classification": sc.classification.value,
                "rationale": sc.rationale,
                "dsp_equivalent": sc.dsp_equivalent,
            }
        )

    return template.render(
        chain_id=classified.chain_id,
        business_purpose=classified.intent_card.business_purpose,
        data_domain=classified.intent_card.data_domain,
        grain=classified.intent_card.grain,
        classification=classified.classification.value,
        effort_category=classified.effort_category or "unknown",
        steps=steps_data,
        step_classifications=step_classifications,
        naming_prefixes=sorted(LAYER_PREFIXES.items()),
        sql_rules=DSP_SQL_RULES,
    )


async def design_chain_views(
    classified: ClassifiedChain,
    chain: DataFlowChain,
    llm: LLMProvider,
) -> list[ViewSpec]:
    """Design DSP target views for a single classified chain.

    Returns a list of ViewSpec objects — the architect's view design.
    Falls back to heuristic design if LLM fails.
    """
    prompt = _build_design_prompt(classified, chain)
    data = await generate_json_with_retry(
        llm, prompt, schema=_DESIGN_SCHEMA, system=_ARCHITECT_SYSTEM, tier="reasoning"
    )

    if data and "views" in data:
        return _parse_view_specs(data["views"], classified.chain_id)

    # Fallback: heuristic design based on classification
    return _heuristic_design(classified, chain)


async def design_target_architecture(
    project_name: str,
    classified_chains: list[tuple[ClassifiedChain, DataFlowChain]],
    llm: LLMProvider,
    default_space: str = "SAP_ADMIN",
) -> TargetArchitecture:
    """Design the complete DSP target architecture for all chains.

    Only designs views for MIGRATE and SIMPLIFY chains.
    DROP/CLARIFY chains are excluded from the target.
    """
    all_views: list[ViewSpec] = []

    for classified, chain in classified_chains:
        if classified.classification in (
            MigrationClassification.DROP,
            MigrationClassification.CLARIFY,
        ):
            continue

        views = await design_chain_views(classified, chain, llm)
        all_views.extend(views)

    # Build migration sequence (topological order by layer)
    sequence = _build_migration_sequence(all_views)

    # Build persistence plan
    persistence_plan = [
        PersistenceDecision(
            view_name=v.technical_name,
            persist=v.persistence,
            rationale=v.persistence_rationale or "",
        )
        for v in all_views
        if v.persistence
    ]

    # Build analytic models for fact views in mart layer
    analytic_models = []
    for v in all_views:
        if v.layer == "mart" and v.semantic_usage == "fact":
            analytic_models.append(
                AnalyticModelSpec(
                    technical_name=f"AM_{v.technical_name.lstrip('03_FV_')}",
                    source_fact_view=v.technical_name,
                    description=f"Analytic Model for {v.description}",
                )
            )

    # Default space design
    spaces = [
        SpaceDesign(
            name=default_space,
            purpose="Primary data space for migration target views",
            pattern="source_semantic_split",
        )
    ]

    return TargetArchitecture(
        project_name=project_name,
        spaces=spaces,
        views=all_views,
        replication_flows=[],
        analytic_models=analytic_models,
        persistence_plan=persistence_plan,
        migration_sequence=sequence,
    )


# --- Helpers ---


def _parse_view_specs(views_data: list[dict], chain_id: str) -> list[ViewSpec]:
    """Parse LLM view data into ViewSpec objects."""
    from spec2sphere.migration.models import ColumnSpec

    specs = []
    for v in views_data:
        columns = []
        for col_data in v.get("columns", []):
            columns.append(
                ColumnSpec(
                    name=col_data.get("name", ""),
                    data_type=col_data.get("data_type", ""),
                    description=col_data.get("description", ""),
                    source_field=col_data.get("source_field", ""),
                    is_key=col_data.get("is_key", False),
                    is_measure=col_data.get("is_measure", False),
                    aggregation=col_data.get("aggregation", ""),
                )
            )
        specs.append(
            ViewSpec(
                technical_name=v.get("technical_name", ""),
                space=v.get("space", "SAP_ADMIN"),
                layer=v.get("layer", "harmonization"),
                semantic_usage=v.get("semantic_usage", "relational_dataset"),
                description=v.get("description", ""),
                source_chains=v.get("source_chains", [chain_id]),
                source_objects=v.get("source_objects", []),
                columns=columns,
                sql_logic=v.get("sql_logic", ""),
                collapse_rationale=v.get("collapse_rationale", ""),
                collapsed_bw_steps=v.get("collapsed_bw_steps", []),
                persistence=v.get("persistence", False),
                persistence_rationale=v.get("persistence_rationale"),
                estimated_rows=v.get("estimated_rows"),
            )
        )
    return specs


def _heuristic_design(
    classified: ClassifiedChain,
    chain: DataFlowChain,
) -> list[ViewSpec]:
    """Fallback: generate a minimal view design from classification data."""
    intent = classified.intent_card
    domain_abbr = intent.data_domain[:3].upper() if intent.data_domain else "GEN"

    # Create a single harmonization view that collapses all steps
    step_ids = [s.object_id for s in chain.steps]
    view_name_base = chain.name.replace(" ", "_").upper()[:30] if chain.name else chain.chain_id.upper()

    views = [
        ViewSpec(
            technical_name=f"02_RV_{view_name_base}",
            space="SAP_ADMIN",
            layer="harmonization",
            semantic_usage="relational_dataset",
            description=intent.business_purpose or f"Harmonization view for {chain.chain_id}",
            source_chains=[classified.chain_id],
            collapse_rationale=f"Collapses {len(step_ids)} BW steps into single DSP view (heuristic fallback)",
            collapsed_bw_steps=step_ids,
            persistence=False,
        ),
    ]

    # If the chain has measures/aggregation, add a mart fact view
    if intent.key_measures:
        views.append(
            ViewSpec(
                technical_name=f"03_FV_{view_name_base}",
                space="SAP_ADMIN",
                layer="mart",
                semantic_usage="fact",
                description=f"Fact view: {intent.grain}" if intent.grain else "Fact view",
                source_chains=[classified.chain_id],
                source_objects=[views[0].technical_name],
                persistence=suggest_persistence(consumer_count=len(intent.consumers)),
            )
        )

    return views


_LAYER_ORDER = {"staging": 0, "harmonization": 1, "mart": 2, "consumption": 3}


def _build_migration_sequence(views: list[ViewSpec]) -> list[MigrationStep]:
    """Build an ordered migration sequence using topological sort by dependencies.

    Falls back to layer ordering when dependencies don't fully constrain the order.
    """
    view_names = {v.technical_name for v in views}
    view_by_name = {v.technical_name: v for v in views}

    # Topological sort: Kahn's algorithm
    # Count in-degree (how many dependencies each view has within our set)
    in_degree: dict[str, int] = {v.technical_name: 0 for v in views}
    dependents: dict[str, list[str]] = {v.technical_name: [] for v in views}

    for v in views:
        for dep in v.source_objects:
            if dep in view_names:
                in_degree[v.technical_name] += 1
                dependents[dep].append(v.technical_name)

    # Start with views that have no in-set dependencies, sorted by layer for stability
    queue = sorted(
        [name for name, deg in in_degree.items() if deg == 0],
        key=lambda n: _LAYER_ORDER.get(view_by_name[n].layer, 99),
    )
    ordered: list[str] = []

    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for dep_name in sorted(dependents[current]):
            in_degree[dep_name] -= 1
            if in_degree[dep_name] == 0:
                queue.append(dep_name)
        # Keep queue sorted by layer for stable ordering
        queue.sort(key=lambda n: _LAYER_ORDER.get(view_by_name[n].layer, 99))

    # Add any remaining views (cycle or unresolved) at the end
    for v in views:
        if v.technical_name not in ordered:
            ordered.append(v.technical_name)

    sequence = []
    for i, name in enumerate(ordered):
        v = view_by_name[name]
        sequence.append(
            MigrationStep(
                order=i + 1,
                view_name=name,
                depends_on=[d for d in v.source_objects if d in view_names],
                effort="trivial" if v.layer == "staging" else "moderate",
                notes=v.collapse_rationale or v.description,
            )
        )

    return sequence
