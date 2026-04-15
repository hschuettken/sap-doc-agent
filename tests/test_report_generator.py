import pytest
from spec2sphere.agents.report_generator import ReportGenerator
from spec2sphere.agents.doc_qa import QAReport, QualityIssue
from spec2sphere.agents.code_quality import CodeIssue
from spec2sphere.agents.brs_traceability import TraceReport, Requirement


@pytest.fixture
def generator():
    return ReportGenerator(doc_platform_url="http://localhost:8253")


@pytest.fixture
def qa_report():
    return QAReport(
        standard_name="Test",
        objects_checked=10,
        total_checks=30,
        checks_passed=25,
        issues=[
            QualityIssue(object_id="A", rule_id="r1", severity="critical", message="Missing desc"),
            QualityIssue(object_id="B", rule_id="r2", severity="minor", message="Short desc"),
        ],
    )


@pytest.fixture
def code_issues():
    return [
        CodeIssue(object_id="T1", rule="select_star", severity="important", message="SELECT * found"),
    ]


@pytest.fixture
def trace_report():
    return TraceReport(
        requirements=[Requirement(req_id="BRS-001", title="Sales")],
        links=[],
        unlinked_requirements=["BRS-001"],
        orphan_objects=["ZCL_HELPER"],
    )


def test_summary_includes_score(generator, qa_report, code_issues, trace_report):
    md = generator.generate_summary(qa_report, code_issues, trace_report)
    assert "83.3" in md  # 25/30 * 100
    assert "critical" in md.lower()


def test_html_is_valid(generator, qa_report, code_issues, trace_report):
    html = generator.generate_html_report(qa_report, code_issues, trace_report)
    assert "<html" in html
    assert "<body" in html
    assert "</html>" in html


def test_sitemap_valid_xml(generator):
    pages = [
        {"url": "http://localhost:8253/books/1", "lastmod": "2026-04-13", "page_type": "space"},
        {"url": "http://localhost:8253/pages/10", "lastmod": "2026-04-13", "page_type": "page"},
    ]
    xml = generator.generate_sitemap(pages)
    assert "<?xml" in xml
    assert "<urlset" in xml
    assert "<url>" in xml
    assert "<priority>1.0</priority>" in xml  # space
    assert "<priority>0.5</priority>" in xml  # page


def test_sitemap_priorities(generator):
    pages = [
        {"url": "http://x/a", "lastmod": "2026-01-01", "page_type": "chapter"},
    ]
    xml = generator.generate_sitemap(pages)
    assert "<priority>0.8</priority>" in xml


def test_write_reports(generator, qa_report, code_issues, trace_report, tmp_path):
    generator.write_reports(tmp_path, qa_report, code_issues, trace_report)
    assert (tmp_path / "reports" / "summary.md").exists()
    assert (tmp_path / "reports" / "report.html").exists()


def test_write_reports_with_sitemap(generator, qa_report, code_issues, trace_report, tmp_path):
    pages = [{"url": "http://x/1", "lastmod": "2026-01-01", "page_type": "space"}]
    generator.write_reports(tmp_path, qa_report, code_issues, trace_report, pages=pages)
    assert (tmp_path / "reports" / "sitemap.xml").exists()
