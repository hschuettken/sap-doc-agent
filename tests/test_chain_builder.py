"""Tests for chain builder — graph walk to reconstruct data flow chains."""

from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType


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
