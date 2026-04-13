"""
Output writer for scan results.

Renders scanned objects as markdown and generates dependency graph.
"""

from __future__ import annotations

import json
from pathlib import Path

from sap_doc_agent.scanner.models import ScanResult, ScannedObject


def render_object_markdown(obj: ScannedObject) -> str:
    """
    Render a scanned object as markdown with YAML frontmatter.

    Includes:
    - YAML frontmatter with metadata
    - Heading with object name
    - Description paragraph
    - Details section with type, package, owner, layer, source_system
    - Source code section (if source_code is non-empty)
    """
    lines = []

    # YAML frontmatter
    lines.append("---")
    fm_data = {
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
    if obj.content_hash:
        fm_data["content_hash"] = obj.content_hash
    if obj.metadata:
        fm_data["metadata"] = obj.metadata
    for key, value in fm_data.items():
        lines.append(f"{key}: {value!r}")
    lines.append("---")
    lines.append("")

    # Heading
    lines.append(f"# {obj.name}")
    lines.append("")

    # Description
    if obj.description:
        lines.append(obj.description)
        lines.append("")

    # Details section
    lines.append("## Details")
    lines.append("")
    details = [
        f"- **Type**: {obj.object_type.value}",
        f"- **Package**: {obj.package}",
        f"- **Owner**: {obj.owner}",
        f"- **Layer**: {obj.layer}",
        f"- **Source System**: {obj.source_system}",
    ]
    lines.extend(details)
    lines.append("")

    # Source code section (only if non-empty)
    if obj.source_code:
        lines.append("## Source Code")
        lines.append("")
        lines.append("```abap")
        lines.append(obj.source_code)
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def write_scan_output(result: ScanResult, output_dir: Path) -> None:
    """
    Write scan results to disk.

    Creates:
    - output_dir/objects/<type>/<id>.md for each object
    - output_dir/graph.json with dependency graph

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

        # Create type subdirectory
        type_dir = objects_dir / obj.object_type.value
        type_dir.mkdir(parents=True, exist_ok=True)

        # Write markdown file
        md_file = type_dir / f"{obj.object_id}.md"
        md_content = render_object_markdown(obj)
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
