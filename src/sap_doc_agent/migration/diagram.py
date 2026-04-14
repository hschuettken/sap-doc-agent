"""Before/after migration diagrams in Mermaid syntax.

Generates a per-chain diagram showing:
  BW chain (left) → extracted intent (center) → DSP target (right)
"""

from __future__ import annotations

from sap_doc_agent.migration.models import ClassifiedChain, ViewSpec
from sap_doc_agent.scanner.models import DataFlowChain


def _sanitize(text: str) -> str:
    """Sanitize text for Mermaid node labels."""
    return text.replace('"', "'").replace("\n", " ")[:80]


def generate_chain_diagram(
    classified: ClassifiedChain,
    chain: DataFlowChain,
    target_views: list[ViewSpec],
) -> str:
    """Generate a Mermaid LR diagram for a single chain migration.

    Layout: BW source → BW steps → Intent → DSP target views
    """
    lines = ["graph LR"]

    # --- Subgraph: BW Source System ---
    lines.append('    subgraph BW["BW Source"]')

    # Source nodes
    for src in chain.source_object_ids:
        lines.append(f'        {src}["{_sanitize(src)}"]')

    # Steps: transformation → intermediate object
    for step in chain.steps:
        lines.append(f'        {step.object_id}[/"{_sanitize(step.name)}"/]')
        if step.inter_step_object_id:
            label = step.inter_step_object_name or step.inter_step_object_id
            lines.append(f'        {step.inter_step_object_id}["{_sanitize(label)}"]')

    # Terminal
    lines.append(f'        {chain.terminal_object_id}["{_sanitize(chain.terminal_object_id)}"]')
    lines.append("    end")

    # BW edges
    prev_id = chain.source_object_ids[0] if chain.source_object_ids else None
    for step in chain.steps:
        if prev_id:
            lines.append(f"    {prev_id} --> {step.object_id}")
        if step.inter_step_object_id:
            lines.append(f"    {step.object_id} --> {step.inter_step_object_id}")
            prev_id = step.inter_step_object_id
        else:
            prev_id = step.object_id

    if prev_id and prev_id != chain.terminal_object_id:
        lines.append(f"    {prev_id} --> {chain.terminal_object_id}")

    # --- Center: Business Intent ---
    intent = classified.intent_card
    purpose = _sanitize(intent.business_purpose) if intent.business_purpose else "Unknown"
    cls_label = classified.classification.value.upper()
    intent_id = f"INTENT_{chain.chain_id}"
    lines.append(f'    {intent_id}{{"Business Purpose:<br/>{purpose}<br/>[{cls_label}]"}}')
    lines.append(f"    {chain.terminal_object_id} ==> {intent_id}")

    # --- Subgraph: DSP Target ---
    if target_views:
        lines.append('    subgraph DSP["DSP Target"]')
        for view in target_views:
            layer_tag = view.layer[:3].upper() if view.layer else ""
            lines.append(
                f'        {view.technical_name}["{_sanitize(view.technical_name)}<br/>[{layer_tag}] {_sanitize(view.semantic_usage)}"]'
            )
        lines.append("    end")

        # Connect intent to first target view
        lines.append(f"    {intent_id} ==> {target_views[0].technical_name}")

        # Connect target views in order
        for i in range(len(target_views) - 1):
            lines.append(f"    {target_views[i].technical_name} --> {target_views[i + 1].technical_name}")
    else:
        # No target — show classification result
        no_target_id = f"NO_TARGET_{chain.chain_id}"
        lines.append(f'    {no_target_id}["{cls_label}: No DSP target needed"]')
        lines.append(f"    {intent_id} ==> {no_target_id}")

    # Styling
    lines.append("    style BW fill:#fce4ec,stroke:#c62828")
    if target_views:
        lines.append("    style DSP fill:#e8f5e9,stroke:#2e7d32")

    return "\n".join(lines)


def generate_project_diagrams(
    chains_data: list[tuple[ClassifiedChain, DataFlowChain, list[ViewSpec]]],
) -> dict[str, str]:
    """Generate diagrams for all chains in a project.

    Returns a dict of chain_id → Mermaid diagram string.
    """
    return {
        classified.chain_id: generate_chain_diagram(classified, chain, views)
        for classified, chain, views in chains_data
    }
