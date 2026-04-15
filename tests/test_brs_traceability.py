import pytest
from spec2sphere.agents.brs_traceability import (
    BRSTraceabilityAgent,
    Requirement,
)
from spec2sphere.scanner.models import ScannedObject, ScanResult, ObjectType


@pytest.fixture
def agent():
    return BRSTraceabilityAgent()


@pytest.fixture
def requirements():
    return [
        Requirement(
            req_id="BRS-001", title="Sales Data", description="Load sales actuals", keywords=["sales", "ADSO_SALES"]
        ),
        Requirement(req_id="BRS-002", title="Revenue Report", description="Revenue aggregation", keywords=["revenue"]),
    ]


@pytest.fixture
def scan_result():
    return ScanResult(
        source_system="BW4",
        objects=[
            ScannedObject(
                object_id="ADSO_SALES",
                object_type=ObjectType.ADSO,
                name="ADSO_SALES",
                description="Sales actuals data",
                source_system="BW4",
            ),
            ScannedObject(
                object_id="TRFN_REVENUE",
                object_type=ObjectType.TRANSFORMATION,
                name="TRFN_REVENUE",
                description="Aggregates revenue data",
                source_system="BW4",
            ),
            ScannedObject(
                object_id="ZCL_HELPER",
                object_type=ObjectType.CLASS,
                name="ZCL_HELPER",
                description="Utility class",
                source_system="BW4",
            ),
        ],
    )


def test_exact_match(agent, requirements, scan_result):
    report = agent.trace(requirements, scan_result)
    sales_links = [l for l in report.links if l.req_id == "BRS-001"]
    assert any(l.object_id == "ADSO_SALES" and l.match_type == "exact" for l in sales_links)


def test_keyword_match(agent, requirements, scan_result):
    report = agent.trace(requirements, scan_result)
    rev_links = [l for l in report.links if l.req_id == "BRS-002"]
    assert any(l.object_id == "TRFN_REVENUE" for l in rev_links)


def test_unlinked_requirements(agent, scan_result):
    reqs = [Requirement(req_id="BRS-999", title="Nonexistent", keywords=["zzz_nothing"])]
    report = agent.trace(reqs, scan_result)
    assert "BRS-999" in report.unlinked_requirements


def test_orphan_objects(agent, requirements, scan_result):
    report = agent.trace(requirements, scan_result)
    assert "ZCL_HELPER" in report.orphan_objects


def test_confidence_exact_higher(agent, requirements, scan_result):
    report = agent.trace(requirements, scan_result)
    exact = [l for l in report.links if l.match_type == "exact"]
    keyword = [l for l in report.links if l.match_type == "keyword"]
    if exact and keyword:
        assert exact[0].confidence > keyword[0].confidence


def test_load_requirements(agent, tmp_path):
    f = tmp_path / "reqs.yaml"
    f.write_text("""\
- req_id: BRS-001
  title: Test Req
  description: A test
  keywords: [test, sales]
""")
    reqs = agent.load_requirements(f)
    assert len(reqs) == 1
    assert reqs[0].req_id == "BRS-001"
