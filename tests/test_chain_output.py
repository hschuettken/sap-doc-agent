"""Tests for chain markdown rendering."""

from spec2sphere.scanner.models import (
    ChainStep,
    DataFlowChain,
    ObjectType,
)
from spec2sphere.scanner.output import render_chain_markdown


def test_render_chain_markdown_has_frontmatter():
    chain = DataFlowChain(
        chain_id="chain_001",
        name="Monthly Net Revenue",
        terminal_object_id="CMP_REV",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["DS_BILLING"],
        steps=[
            ChainStep(
                position=1,
                object_id="TRAN_001",
                object_type=ObjectType.TRANSFORMATION,
                name="Currency Conversion",
                step_summary="Converts USD to EUR via TCURR",
            ),
        ],
        all_object_ids=["DS_BILLING", "TRAN_001", "CMP_REV"],
        summary="Processes billing data into monthly EUR revenue figures.",
    )
    md = render_chain_markdown(chain)
    assert "chain_id: chain_001" in md
    assert "name: Monthly Net Revenue" in md
    assert "# Chain: Monthly Net Revenue" in md
    assert "Processes billing data" in md
    assert "Currency Conversion" in md


def test_render_chain_markdown_includes_steps():
    chain = DataFlowChain(
        chain_id="chain_002",
        name="Test Chain",
        terminal_object_id="T",
        terminal_object_type=ObjectType.ADSO,
        source_object_ids=["S"],
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Step One",
                step_summary="Filters test orders",
                inter_step_object_name="DSO_INTERIM",
                inter_step_fields=["F1", "F2"],
            ),
            ChainStep(
                position=2,
                object_id="TR2",
                object_type=ObjectType.TRANSFORMATION,
                name="Step Two",
                step_summary="Aggregates to monthly",
            ),
        ],
        all_object_ids=["S", "TR1", "TR2", "T"],
    )
    md = render_chain_markdown(chain)
    assert "### Step 1:" in md
    assert "### Step 2:" in md
    assert "DSO_INTERIM" in md
    assert "Filters test orders" in md


def test_render_chain_markdown_shared_deps():
    chain = DataFlowChain(
        chain_id="chain_003",
        name="With Deps",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[],
        all_object_ids=["S", "T"],
        shared_dependency_ids=["0CUSTOMER", "0MATERIAL"],
    )
    md = render_chain_markdown(chain)
    assert "0CUSTOMER" in md
    assert "0MATERIAL" in md
    assert "Shared Dependencies" in md


def test_render_chain_markdown_observations():
    chain = DataFlowChain(
        chain_id="chain_004",
        name="Obs Chain",
        terminal_object_id="T",
        terminal_object_type=ObjectType.ADSO,
        source_object_ids=["S"],
        steps=[],
        all_object_ids=["S", "T"],
        observations=["Hardcoded EUR target currency", "Year-partitioned ADSO pattern"],
    )
    md = render_chain_markdown(chain)
    assert "Observations" in md
    assert "Hardcoded EUR" in md


def test_render_chain_markdown_analyzed_at():
    from datetime import datetime, timezone

    ts = datetime(2026, 4, 14, 12, 30, 0, tzinfo=timezone.utc)
    chain = DataFlowChain(
        chain_id="chain_005",
        name="With Timestamp",
        terminal_object_id="T",
        terminal_object_type=ObjectType.ADSO,
        source_object_ids=["S"],
        steps=[],
        all_object_ids=["S", "T"],
        analyzed_at=ts,
    )
    md = render_chain_markdown(chain)
    assert "analyzed_at: 2026-04-14T12:30:00" in md


def test_render_chain_markdown_no_analyzed_at():
    chain = DataFlowChain(
        chain_id="chain_006",
        name="No Timestamp",
        terminal_object_id="T",
        terminal_object_type=ObjectType.ADSO,
        source_object_ids=["S"],
        steps=[],
        all_object_ids=["S", "T"],
    )
    md = render_chain_markdown(chain)
    assert "analyzed_at" not in md


def test_render_chain_markdown_rich_shared_deps():
    from spec2sphere.scanner.models import SharedDependency

    chain = DataFlowChain(
        chain_id="chain_007",
        name="Rich Deps",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[],
        all_object_ids=["S", "T"],
        shared_dependencies=[
            SharedDependency(object_id="IOBJ_CUST", name="0CUSTOMER", object_type="INFOOBJECT"),
            SharedDependency(object_id="IOBJ_MAT", name="0MATERIAL", object_type="INFOOBJECT"),
        ],
    )
    md = render_chain_markdown(chain)
    assert "Shared Dependencies" in md
    assert "0CUSTOMER (INFOOBJECT)" in md
    assert "0MATERIAL (INFOOBJECT)" in md
