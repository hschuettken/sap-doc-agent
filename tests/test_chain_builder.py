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
