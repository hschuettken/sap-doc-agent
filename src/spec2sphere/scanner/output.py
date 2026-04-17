"""
Output writer for scan results.

Renders scanned objects as markdown and generates dependency graph.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from spec2sphere.scanner.models import (
    Dependency,
    DependencyType,
    ScanResult,
    ScannedObject,
)


# Human-readable labels for dependency types
_DEP_TYPE_LABELS: dict[str, str] = {
    DependencyType.READS_FROM.value: "Reads From",
    DependencyType.WRITES_TO.value: "Writes To",
    DependencyType.CALLS.value: "Calls",
    DependencyType.REFERENCES.value: "References",
    DependencyType.CONTAINS.value: "Contains",
    DependencyType.DEPENDS_ON.value: "Depends On",
}

# Human-readable labels for object types
_OBJ_TYPE_LABELS: dict[str, str] = {
    "adso": "Advanced DSO",
    "composite": "Composite Provider",
    "transformation": "Transformation",
    "class": "ABAP Class",
    "fm": "Function Module",
    "table": "Database Table",
    "data_element": "Data Element",
    "domain": "Domain",
    "infoobject": "InfoObject",
    "process_chain": "Process Chain",
    "data_source": "Data Source",
    "view": "View (Relational Dataset)",
    "report": "Report",
    "other": "Other",
}


def _format_date(dt: datetime | None) -> str:
    """Format a datetime as human-readable date string."""
    if dt is None:
        return "—"
    return dt.strftime("%b %-d, %Y")


def render_object_markdown(
    obj: ScannedObject,
    dependencies: list[Dependency] | None = None,
) -> str:
    """
    Render a scanned object as rich markdown with YAML frontmatter.

    Includes:
    - YAML frontmatter with metadata
    - H1 heading (business name if available, else technical name)
    - Summary line with type, space, layer, status, owner
    - Description section
    - Columns section (from metadata.columns)
    - SQL/Source definition section (from source_code)
    - Dependencies section (reads from / read by)
    - Screenshots section (from metadata.screenshots)
    - Metadata section with remaining fields
    """
    if dependencies is None:
        dependencies = []

    lines: list[str] = []

    # --- YAML frontmatter ---
    lines.append("---")
    fm_data: dict = {
        "object_id": obj.object_id,
        "object_type": obj.object_type.value,
        "name": obj.name,
        "source_system": obj.source_system,
        "package": obj.package,
        "owner": obj.owner,
        "layer": obj.layer,
        "technical_name": obj.technical_name,
        "scanned_at": obj.scanned_at.isoformat(),
    }
    # Add optional frontmatter fields from metadata
    meta = obj.metadata or {}
    if meta.get("business_name"):
        fm_data["business_name"] = meta["business_name"]
    if meta.get("space"):
        fm_data["space"] = meta["space"]
    if meta.get("folder"):
        fm_data["folder"] = meta["folder"]
    if meta.get("status"):
        fm_data["status"] = meta["status"]
    if obj.content_hash:
        fm_data["content_hash"] = obj.content_hash
    if meta:
        fm_data["metadata"] = meta

    for key, value in fm_data.items():
        lines.append(f"{key}: {value!r}")
    lines.append("---")
    lines.append("")

    # --- H1 heading ---
    business_name = meta.get("business_name") or ""
    display_name = business_name if business_name else obj.name
    lines.append(f"# {display_name}")
    lines.append("")

    # --- Technical name + summary line ---
    tech = obj.technical_name or obj.name
    obj_type_label = _OBJ_TYPE_LABELS.get(obj.object_type.value, obj.object_type.value.title())
    space = meta.get("space") or obj.package or ""
    layer = obj.layer.title() if obj.layer else "—"
    status = meta.get("status") or "—"
    owner = obj.owner or "—"

    lines.append(f"**Technical Name:** `{tech}`")
    lines.append(
        f"**Type:** {obj_type_label}"
        + (f" | **Space:** {space}" if space else "")
        + (f" | **Layer:** {layer}" if obj.layer else "")
    )
    lines.append(f"**Status:** {status} | **Owner:** {owner}")
    lines.append("")

    # --- Description ---
    lines.append("## Description")
    lines.append("")
    if obj.description:
        lines.append(obj.description)
    else:
        folder = meta.get("folder") or ""
        desc_parts = [f"{display_name}"]
        if obj_type_label:
            desc_parts.append(f"— {obj_type_label}")
        if folder:
            desc_parts.append(f"in the {folder} folder")
        desc_parts.append(".")
        lines.append(" ".join(desc_parts))
    lines.append("")

    # --- Details section (kept for backward compatibility) ---
    lines.append("## Details")
    lines.append("")
    lines.append(f"- **Type**: {obj.object_type.value}")
    lines.append(f"- **Package**: {obj.package}")
    lines.append(f"- **Owner**: {obj.owner}")
    lines.append(f"- **Layer**: {obj.layer}")
    lines.append(f"- **Source System**: {obj.source_system}")
    lines.append("")

    # --- Columns section ---
    lines.append("## Columns")
    lines.append("")
    columns = meta.get("columns")
    if columns:
        lines.append("| Column | Type | Description |")
        lines.append("|--------|------|-------------|")
        for col in columns:
            col_name = col.get("name", "")
            col_type = col.get("type", "")
            col_desc = col.get("description", "")
            lines.append(f"| {col_name} | {col_type} | {col_desc} |")
    else:
        lines.append("*(Column data populated by deep scan)*")
    lines.append("")

    # --- SQL / Source Code section ---
    if obj.source_code:
        lines.append("## SQL Definition")
        lines.append("")
        lines.append("```sql")
        lines.append(obj.source_code)
        lines.append("```")
        lines.append("")
    else:
        lines.append("## SQL Definition")
        lines.append("")
        lines.append("*(SQL definition populated by deep scan)*")
        lines.append("")

    # --- Source Code section (ABAP) for non-view/table types ---
    source_type = obj.object_type.value
    if source_type in ("class", "fm", "transformation", "report", "process_chain") and obj.source_code:
        lines.append("## Source Code")
        lines.append("")
        lines.append("```abap")
        lines.append(obj.source_code)
        lines.append("```")
        lines.append("")

    # --- Dependencies section ---
    lines.append("## Dependencies")
    lines.append("")

    if dependencies:
        # Group by dependency type from the perspective of this object
        reads_from = [d for d in dependencies if d.source_id == obj.object_id]
        read_by = [d for d in dependencies if d.target_id == obj.object_id]

        if reads_from:
            # Group reads_from by dep type
            by_type: dict[str, list[Dependency]] = defaultdict(list)
            for dep in reads_from:
                by_type[dep.dependency_type.value].append(dep)

            for dep_type, deps in by_type.items():
                label = _DEP_TYPE_LABELS.get(dep_type, dep_type.replace("_", " ").title())
                lines.append(f"### {label}")
                for dep in deps:
                    target_id = dep.target_id
                    dep_meta = dep.metadata or {}
                    target_type = dep_meta.get("target_type", "")
                    target_name = dep_meta.get("target_name", target_id)
                    # Build relative link path: ../type/id.md
                    if target_type:
                        link = f"../{target_type}/{target_id}.md"
                    else:
                        link = f"../{target_id}.md"
                    type_label = _OBJ_TYPE_LABELS.get(target_type, target_type.title()) if target_type else ""
                    suffix = f" — {type_label}" if type_label else ""
                    lines.append(f"- [`{target_name}`]({link}){suffix}")
                lines.append("")

        if read_by:
            lines.append("### Read By")
            for dep in read_by:
                source_id = dep.source_id
                dep_meta = dep.metadata or {}
                source_type_val = dep_meta.get("source_type", "")
                source_name = dep_meta.get("source_name", source_id)
                if source_type_val:
                    link = f"../{source_type_val}/{source_id}.md"
                else:
                    link = f"../{source_id}.md"
                type_label = _OBJ_TYPE_LABELS.get(source_type_val, source_type_val.title()) if source_type_val else ""
                suffix = f" — {type_label}" if type_label else ""
                lines.append(f"- [`{source_name}`]({link}){suffix}")
            lines.append("")

        if not reads_from and not read_by:
            lines.append("*(No dependencies recorded)*")
            lines.append("")
    else:
        lines.append("*(No dependencies recorded)*")
        lines.append("")

    # --- Screenshots section ---
    lines.append("## Screenshots")
    lines.append("")
    screenshots = meta.get("screenshots")
    if screenshots:
        for filename in screenshots:
            lines.append(f"![{filename}]({filename})")
        lines.append("")
    else:
        lines.append("*(Screenshots populated by deep scan)*")
        lines.append("")

    # --- Metadata section ---
    lines.append("## Metadata")
    lines.append("")
    # Render known metadata fields as bullets, skip columns/screenshots/business_name (shown elsewhere)
    _skip_keys = {"columns", "screenshots", "business_name", "space", "status"}
    folder = meta.get("folder")
    last_modified = meta.get("last_modified")

    if folder:
        lines.append(f"- **Folder:** {folder}")
    if last_modified:
        # Try to parse and reformat
        try:
            dt = datetime.fromisoformat(str(last_modified))
            lines.append(f"- **Last Modified:** {_format_date(dt)}")
        except (ValueError, TypeError):
            lines.append(f"- **Last Modified:** {last_modified}")

    # Remaining metadata keys not already shown
    _shown_keys = _skip_keys | {"folder", "last_modified"}
    extra = {k: v for k, v in meta.items() if k not in _shown_keys}
    for key, value in extra.items():
        label = key.replace("_", " ").title()
        lines.append(f"- **{label}:** {value}")

    if not folder and not last_modified and not extra:
        lines.append("*(No additional metadata)*")

    lines.append("")

    return "\n".join(lines)


def write_scan_output(result: ScanResult, output_dir: Path) -> None:
    """
    Write scan results to disk.

    Creates:
    - output_dir/objects/<type>/<id>.md for each object
    - output_dir/graph.json with dependency graph
    - output_dir/README.md with summary table and stats

    Each object's hash is computed before writing.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    objects_dir = output_dir / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)

    # Write individual object markdown files
    for obj in result.objects:
        # Compute hash before writing
        obj.compute_hash()

        # Filter dependencies for this object
        obj_deps = [
            dep for dep in result.dependencies if dep.source_id == obj.object_id or dep.target_id == obj.object_id
        ]

        # Create type subdirectory
        type_dir = objects_dir / obj.object_type.value
        type_dir.mkdir(parents=True, exist_ok=True)

        # Write markdown file
        md_file = type_dir / f"{obj.object_id}.md"
        md_content = render_object_markdown(obj, dependencies=obj_deps)
        md_file.write_text(md_content)

    # Write dependency graph
    graph_data = {
        "source_system": result.source_system,
        "scanned_at": result.scanned_at.isoformat(),
        "nodes": [
            {
                "id": obj.object_id,
                "name": obj.name,
                "type": obj.object_type.value,
                "source_system": obj.source_system,
                "layer": obj.layer,
                "package": obj.package,
            }
            for obj in result.objects
        ],
        "edges": [
            {
                "source": dep.source_id,
                "target": dep.target_id,
                "type": dep.dependency_type.value,
            }
            for dep in result.dependencies
        ],
    }
    graph_file = output_dir / "graph.json"
    graph_file.write_text(json.dumps(graph_data, indent=2))

    # Write README.md summary
    readme_content = _render_readme(result)
    (output_dir / "README.md").write_text(readme_content)

    # Best-effort NOTIFY so dsp-ai's schema_semantic feeder picks up the new graph.
    # Import lazily so the scanner has no hard dependency on dsp_ai at import time.
    try:
        _emit_scan_completed(str(result.source_system), str(graph_file))
    except Exception:  # pragma: no cover — NOTIFY is fire-and-forget
        pass


def _emit_scan_completed(customer: str, graph_path: str) -> None:
    """Fire ``NOTIFY scan_completed`` with the graph.json path.

    Handles both sync (standalone CLI) and async (FastAPI/Celery) contexts
    without blocking the scanner.
    """
    import asyncio

    from spec2sphere.dsp_ai.events import emit  # noqa: E402 — deferred

    payload = {"customer": customer, "graph_path": graph_path}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(emit("scan_completed", payload))
    else:
        loop.create_task(emit("scan_completed", payload))


def _render_readme(result: ScanResult) -> str:
    """Render a README.md summary for the scan output directory."""
    lines: list[str] = []

    lines.append("# SAP Scan Output")
    lines.append("")
    lines.append(f"**Source System:** {result.source_system}  ")
    lines.append(f"**Scanned At:** {result.scanned_at.strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(f"**Total Objects:** {len(result.objects)}  ")
    lines.append(f"**Total Dependencies:** {len(result.dependencies)}  ")
    lines.append("")

    # Type breakdown
    type_counts: dict[str, int] = defaultdict(int)
    for obj in result.objects:
        type_counts[obj.object_type.value] += 1

    if type_counts:
        lines.append("## Object Types")
        lines.append("")
        lines.append("| Type | Count |")
        lines.append("|------|-------|")
        for obj_type, count in sorted(type_counts.items()):
            label = _OBJ_TYPE_LABELS.get(obj_type, obj_type.title())
            lines.append(f"| {label} | {count} |")
        lines.append("")

    # Layer breakdown
    layer_counts: dict[str, int] = defaultdict(int)
    for obj in result.objects:
        layer = obj.layer or "unknown"
        layer_counts[layer] += 1

    if layer_counts:
        lines.append("## Layer Breakdown")
        lines.append("")
        lines.append("| Layer | Count |")
        lines.append("|-------|-------|")
        for layer, count in sorted(layer_counts.items()):
            lines.append(f"| {layer} | {count} |")
        lines.append("")

    # Dependency graph summary
    if result.dependencies:
        dep_type_counts: dict[str, int] = defaultdict(int)
        for dep in result.dependencies:
            dep_type_counts[dep.dependency_type.value] += 1

        lines.append("## Dependency Graph")
        lines.append("")
        lines.append(f"Total edges: **{len(result.dependencies)}**")
        lines.append("")
        lines.append("| Dependency Type | Count |")
        lines.append("|----------------|-------|")
        for dep_type, count in sorted(dep_type_counts.items()):
            label = _DEP_TYPE_LABELS.get(dep_type, dep_type.replace("_", " ").title())
            lines.append(f"| {label} | {count} |")
        lines.append("")

    # All objects table
    if result.objects:
        lines.append("## All Objects")
        lines.append("")
        lines.append("| Object | Type | Layer | Space/Package |")
        lines.append("|--------|------|-------|---------------|")
        for obj in sorted(result.objects, key=lambda o: (o.object_type.value, o.name)):
            meta = obj.metadata or {}
            business_name = meta.get("business_name") or obj.name
            space = meta.get("space") or obj.package or "—"
            layer = obj.layer or "—"
            type_label = _OBJ_TYPE_LABELS.get(obj.object_type.value, obj.object_type.value.title())
            link = f"objects/{obj.object_type.value}/{obj.object_id}.md"
            lines.append(f"| [{business_name}]({link}) | {type_label} | {layer} | {space} |")
        lines.append("")

    return "\n".join(lines)


async def persist_scan_to_db(result: ScanResult, scan_id: str) -> None:
    """Persist scan results to PostgreSQL."""
    from spec2sphere.db import save_scan_result

    objects = [
        {
            "object_id": obj.object_id,
            "object_type": obj.object_type.value,
            "name": obj.name,
            "description": obj.description,
            "package": obj.package,
            "owner": obj.owner,
            "source_system": obj.source_system,
            "technical_name": obj.technical_name,
            "layer": obj.layer,
            "source_code": obj.source_code,
            "metadata": obj.metadata,
            "content_hash": obj.content_hash,
            "scanned_at": obj.scanned_at.isoformat(),
        }
        for obj in result.objects
    ]
    deps = [
        {
            "source_id": dep.source_id,
            "target_id": dep.target_id,
            "dependency_type": dep.dependency_type.value,
            "metadata": dep.metadata,
        }
        for dep in result.dependencies
    ]
    await save_scan_result(scan_id, objects, deps)


def render_chain_markdown(chain: "DataFlowChain") -> str:
    """Render a DataFlowChain as markdown with YAML frontmatter."""

    lines = [
        "---",
        f"chain_id: {chain.chain_id}",
        f"name: {chain.name}",
        f"terminal_object: {chain.terminal_object_id} ({chain.terminal_object_type.value})",
        f"source_objects: {chain.source_object_ids}",
        f"steps: {chain.step_count}",
        f"objects_involved: {len(chain.all_object_ids)}",
        f"confidence: {chain.confidence}",
    ]
    if chain.analyzed_at:
        lines.append(f"analyzed_at: {chain.analyzed_at.isoformat()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Chain: {chain.name or chain.chain_id}")
    lines.append("")

    if chain.summary:
        lines.extend(["## Overview", "", chain.summary, ""])

    if chain.steps:
        lines.append("## Step Details")
        lines.append("")
        for step in chain.steps:
            lines.append(f"### Step {step.position}: {step.name}")
            lines.append(f"**Object:** {step.object_id} ({step.object_type.value})")
            if step.step_summary:
                lines.append(f"**Summary:** {step.step_summary}")
            if step.inter_step_object_name:
                fields_str = ", ".join(step.inter_step_fields) if step.inter_step_fields else "—"
                lines.append(f"**Writes to:** {step.inter_step_object_name} (fields: {fields_str})")
            if step.source_code:
                lines.extend(["", "```abap", step.source_code, "```"])
            lines.append("")

    if chain.shared_dependencies:
        dep_lines = []
        for dep in chain.shared_dependencies:
            label = dep.name or dep.object_id
            type_label = f" ({dep.object_type})" if dep.object_type else ""
            dep_lines.append(f"- {label}{type_label}")
        lines.extend(["## Shared Dependencies", "", *dep_lines, ""])
    elif chain.shared_dependency_ids:
        lines.extend(
            [
                "## Shared Dependencies",
                "",
                *[f"- {dep_id}" for dep_id in chain.shared_dependency_ids],
                "",
            ]
        )

    if chain.observations:
        lines.extend(
            [
                "## Observations",
                "",
                *[f"- {obs}" for obs in chain.observations],
                "",
            ]
        )

    return "\n".join(lines)
