"""Tests for chain builder — graph walk to reconstruct data flow chains."""

import json
from pathlib import Path

from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_bw_scan"


def load_fixture_graph():
    with open(FIXTURE_DIR / "graph.json") as f:
        return json.load(f)


def test_chain_step_creation():
    step = ChainStep(
        position=1,
        object_id="TRAN_001",
        object_type=ObjectType.TRANSFORMATION,
        name="Currency Conversion",
        source_code="* start routine\nDATA: lv_rate TYPE tcurr-ukurs.",
        inter_step_object_id="DSO_RAW",
        inter_step_object_name="ZADSO_BILLING_RAW",
        inter_step_fields=["KUNNR", "MATNR", "NETWR", "WAERS"],
    )
    assert step.position == 1
    assert step.inter_step_fields == ["KUNNR", "MATNR", "NETWR", "WAERS"]


def test_data_flow_chain_creation():
    chain = DataFlowChain(
        chain_id="chain_001",
        name="",
        terminal_object_id="ZQ_REV",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["2LIS_11_VAITM"],
        steps=[],
        all_object_ids=["2LIS_11_VAITM", "TRAN_001", "ZADSO_RAW", "ZQ_REV"],
        shared_dependency_ids=["0CUSTOMER", "0MATERIAL"],
    )
    assert chain.chain_id == "chain_001"
    assert len(chain.all_object_ids) == 4


def test_chain_step_count():
    chain = DataFlowChain(
        chain_id="c1",
        name="Test",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Step 1",
            ),
            ChainStep(
                position=2,
                object_id="TR2",
                object_type=ObjectType.TRANSFORMATION,
                name="Step 2",
            ),
        ],
        all_object_ids=["S", "TR1", "TR2", "T"],
    )
    assert chain.step_count == 2


# --- Tests using fixture graph ---


def test_build_chains_finds_three_chains():
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    assert len(chains) == 3


def test_revenue_chain_has_correct_structure():
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    assert rev_chain.source_object_ids == ["DS_BILLING"]
    assert rev_chain.step_count == 3  # 3 transformations
    assert "IOBJ_CUST" in rev_chain.shared_dependency_ids


def test_inventory_chain_is_simple():
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    inv_chain = next(c for c in chains if c.terminal_object_id == "DSO_INV")
    assert inv_chain.step_count == 1
    assert inv_chain.source_object_ids == ["DS_INVENTORY"]


def test_dead_chain_detected():
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    dead_chain = next(c for c in chains if c.terminal_object_id == "DSO_DEAD")
    assert dead_chain.step_count == 1


def test_chain_steps_ordered_by_position():
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    positions = [s.position for s in rev_chain.steps]
    assert positions == [1, 2, 3]


def test_inter_step_objects_populated():
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    # Step 1 writes to DSO_RAW
    assert rev_chain.steps[0].inter_step_object_id == "DSO_RAW"
    assert rev_chain.steps[0].inter_step_object_name == "ZADSO_BILLING_RAW"


def test_shared_dependencies_not_in_steps():
    """InfoObjects used by transformations are shared deps, not chain steps."""
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    step_ids = [s.object_id for s in rev_chain.steps]
    assert "IOBJ_CUST" not in step_ids


# --- Source code enrichment tests ---


def test_source_code_enriched_when_objects_dir_provided():
    """When objects_dir is given, transformation steps get ABAP source."""
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    objects_dir = FIXTURE_DIR / "objects"
    chains = build_chains_from_graph(graph, objects_dir=objects_dir)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    # TRAN_002 fixture has TCURR currency conversion ABAP
    step2 = next(s for s in rev_chain.steps if s.object_id == "TRAN_002")
    assert "tcurr" in step2.source_code.lower() or "TCURR" in step2.source_code


def test_source_code_empty_without_objects_dir():
    """Without objects_dir, source_code stays empty."""
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    for step in rev_chain.steps:
        assert step.source_code == ""


def test_all_transformation_steps_get_source():
    """Every transformation in the revenue chain should have source code."""
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    objects_dir = FIXTURE_DIR / "objects"
    chains = build_chains_from_graph(graph, objects_dir=objects_dir)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    for step in rev_chain.steps:
        assert step.source_code != "", f"Step {step.object_id} has no source code"


def test_shared_dependencies_have_rich_info():
    """shared_dependencies should contain name and type from graph nodes."""
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = load_fixture_graph()
    chains = build_chains_from_graph(graph)
    rev_chain = next(c for c in chains if c.terminal_object_id == "CMP_REV")
    assert len(rev_chain.shared_dependencies) == 1
    dep = rev_chain.shared_dependencies[0]
    assert dep.object_id == "IOBJ_CUST"
    assert dep.name == "0CUSTOMER"
    assert dep.object_type == "INFOOBJECT"


# --- Fan-out test ---


def test_fan_out_shared_adso_appears_in_multiple_chains():
    """When one ADSO feeds two terminals, it appears in both chains."""
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph

    graph = {
        "nodes": [
            {"id": "DS1", "type": "DATA_SOURCE", "name": "Source1", "metadata": {}},
            {"id": "TR1", "type": "TRANSFORMATION", "name": "Load1", "metadata": {}},
            {"id": "SHARED_DSO", "type": "ADSO", "name": "ZADSO_SHARED", "metadata": {"fields": ["F1"]}},
            {"id": "TR_A", "type": "TRANSFORMATION", "name": "ToA", "metadata": {}},
            {"id": "CMP_A", "type": "COMPOSITE", "name": "ZC_A", "metadata": {}},
            {"id": "TR_B", "type": "TRANSFORMATION", "name": "ToB", "metadata": {}},
            {"id": "CMP_B", "type": "COMPOSITE", "name": "ZC_B", "metadata": {}},
        ],
        "edges": [
            {"source": "DS1", "target": "TR1", "type": "READS_FROM"},
            {"source": "TR1", "target": "SHARED_DSO", "type": "WRITES_TO"},
            {"source": "SHARED_DSO", "target": "TR_A", "type": "READS_FROM"},
            {"source": "TR_A", "target": "CMP_A", "type": "WRITES_TO"},
            {"source": "SHARED_DSO", "target": "TR_B", "type": "READS_FROM"},
            {"source": "TR_B", "target": "CMP_B", "type": "WRITES_TO"},
        ],
    }
    chains = build_chains_from_graph(graph)
    assert len(chains) == 2

    chain_a = next(c for c in chains if c.terminal_object_id == "CMP_A")
    chain_b = next(c for c in chains if c.terminal_object_id == "CMP_B")

    # Both chains should include the shared ADSO
    assert "SHARED_DSO" in chain_a.all_object_ids
    assert "SHARED_DSO" in chain_b.all_object_ids

    # Both chains trace back to same source
    assert "DS1" in chain_a.source_object_ids
    assert "DS1" in chain_b.source_object_ids

    # Chain A has TR1 + TR_A, Chain B has TR1 + TR_B
    assert chain_a.step_count == 2
    assert chain_b.step_count == 2
    step_ids_a = [s.object_id for s in chain_a.steps]
    step_ids_b = [s.object_id for s in chain_b.steps]
    assert "TR1" in step_ids_a
    assert "TR_A" in step_ids_a
    assert "TR1" in step_ids_b
    assert "TR_B" in step_ids_b
