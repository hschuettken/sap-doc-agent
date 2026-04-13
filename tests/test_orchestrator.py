"""Tests for ScannerOrchestrator — merge and deduplicate."""

from __future__ import annotations

import json
from pathlib import Path


from sap_doc_agent.scanner.models import (
    Dependency,
    DependencyType,
    ObjectType,
    ScanResult,
    ScannedObject,
)
from sap_doc_agent.scanner.orchestrator import ScannerOrchestrator
from sap_doc_agent.scanner.output import write_scan_output


def _make_obj(object_id: str, name: str, description: str = "") -> ScannedObject:
    return ScannedObject(
        object_id=object_id,
        object_type=ObjectType.VIEW,
        name=name,
        description=description,
        source_system="DSP",
    )


def _make_dep(source_id: str, target_id: str) -> Dependency:
    return Dependency(
        source_id=source_id,
        target_id=target_id,
        dependency_type=DependencyType.READS_FROM,
    )


def test_merge_single_source_preserves_objects_and_deps():
    """Merging a single ScanResult preserves all objects and dependencies."""
    obj = _make_obj("S.A", "A")
    dep = _make_dep("S.A", "S.B")
    source = ScanResult(source_system="DSP", objects=[obj], dependencies=[dep])

    orch = ScannerOrchestrator()
    merged = orch.merge([source])

    assert len(merged.objects) == 1
    assert len(merged.dependencies) == 1
    assert merged.source_system == "merged"


def test_merge_two_sources_concatenates_all():
    """Merging two ScanResults concatenates objects and dependencies."""
    obj_a = _make_obj("S1.A", "ObjA")
    obj_b = _make_obj("S2.B", "ObjB")
    dep_a = _make_dep("S1.A", "S1.C")
    dep_b = _make_dep("S2.B", "S2.D")

    src1 = ScanResult(source_system="SRC1", objects=[obj_a], dependencies=[dep_a])
    src2 = ScanResult(source_system="SRC2", objects=[obj_b], dependencies=[dep_b])

    orch = ScannerOrchestrator()
    merged = orch.merge([src1, src2])

    assert len(merged.objects) == 2
    assert len(merged.dependencies) == 2
    obj_ids = {o.object_id for o in merged.objects}
    assert "S1.A" in obj_ids
    assert "S2.B" in obj_ids


def test_deduplicate_removes_duplicate_by_name_keeps_richer_description():
    """Deduplicate keeps the object with the longer description."""
    obj_short = _make_obj("S1.VIEW_A", "MY_VIEW", description="Short")
    obj_long = _make_obj("S2.VIEW_A", "MY_VIEW", description="A much longer description here")

    result = ScanResult(
        source_system="merged",
        objects=[obj_short, obj_long],
        dependencies=[],
    )
    orch = ScannerOrchestrator()
    deduped = orch.deduplicate(result)

    assert len(deduped.objects) == 1
    assert deduped.objects[0].description == "A much longer description here"


def test_deduplicate_remaps_dependency_ids():
    """Deduplicate remaps loser IDs in dependencies to the winner ID."""
    winner = _make_obj("S1.VIEW_A", "MY_VIEW", description="Winner with longer description")
    loser = _make_obj("S2.VIEW_A", "MY_VIEW", description="Loser")
    other = _make_obj("S1.TABLE_B", "MY_TABLE")

    # Dependency uses the loser's ID
    dep = _make_dep("S2.VIEW_A", "S1.TABLE_B")

    result = ScanResult(
        source_system="merged",
        objects=[winner, loser, other],
        dependencies=[dep],
    )
    orch = ScannerOrchestrator()
    deduped = orch.deduplicate(result)

    # The dependency source should be remapped to the winner's ID
    assert len(deduped.dependencies) == 1
    assert deduped.dependencies[0].source_id == "S1.VIEW_A"
    assert deduped.dependencies[0].target_id == "S1.TABLE_B"


def test_deduplicate_removes_duplicate_edges():
    """Deduplicate removes edges with the same (source, target, type)."""
    obj_a = _make_obj("S.A", "ObjA")
    obj_b = _make_obj("S.B", "ObjB")

    dep1 = _make_dep("S.A", "S.B")
    dep2 = _make_dep("S.A", "S.B")  # duplicate

    result = ScanResult(
        source_system="merged",
        objects=[obj_a, obj_b],
        dependencies=[dep1, dep2],
    )
    orch = ScannerOrchestrator()
    deduped = orch.deduplicate(result)

    assert len(deduped.dependencies) == 1


def test_full_pipeline_merge_deduplicate_write(tmp_path: Path):
    """Full pipeline: merge → deduplicate → write_scan_output produces correct files."""
    obj1 = _make_obj("S1.VIEW_X", "VIEW_X", description="Short desc")
    obj2 = _make_obj("S2.VIEW_X", "VIEW_X", description="Longer description wins here")
    obj3 = _make_obj("S1.TABLE_Y", "TABLE_Y")

    dep = Dependency(
        source_id="S2.VIEW_X",
        target_id="S1.TABLE_Y",
        dependency_type=DependencyType.READS_FROM,
    )

    src1 = ScanResult(source_system="SRC1", objects=[obj1], dependencies=[])
    src2 = ScanResult(source_system="SRC2", objects=[obj2, obj3], dependencies=[dep])

    orch = ScannerOrchestrator()
    merged = orch.merge([src1, src2])
    deduped = orch.deduplicate(merged)

    assert len(deduped.objects) == 2

    write_scan_output(deduped, tmp_path)

    # graph.json should exist
    graph_file = tmp_path / "graph.json"
    assert graph_file.exists()

    graph = json.loads(graph_file.read_text())
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "S1.VIEW_X" in node_ids or "S2.VIEW_X" in node_ids
    assert "S1.TABLE_Y" in node_ids

    # Dependency remapped: source S2.VIEW_X → winner (S1.VIEW_X or S2.VIEW_X)
    assert len(graph["edges"]) == 1

    # Two object markdown files plus README.md in output root
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 3  # 2 object files + README.md
