import pytest
from sap_doc_agent.agents.doc_qa import (
    DocQAAgent,
    QualityStandard,
    QualityRule,
    QAReport,
    QualityIssue,
    load_standard,
)
from sap_doc_agent.scanner.models import ScannedObject, ScanResult, ObjectType


@pytest.fixture
def basic_standard():
    return QualityStandard(
        name="Test Standard",
        rules=[
            QualityRule(
                id="desc_required",
                name="Description required",
                severity="critical",
                check_type="field_required",
                field="description",
                message="Missing description",
            ),
            QualityRule(
                id="desc_length",
                name="Description min length",
                severity="important",
                check_type="min_length",
                field="description",
                min_length=20,
                message="Description too short (min 20 chars)",
            ),
            QualityRule(
                id="owner_required",
                name="Owner required",
                severity="important",
                check_type="field_required",
                field="owner",
                message="Missing owner",
            ),
        ],
    )


@pytest.fixture
def naming_standard():
    return QualityStandard(
        name="Naming Standard",
        rules=[
            QualityRule(
                id="raw_prefix",
                name="Raw layer naming",
                severity="minor",
                check_type="naming_convention",
                pattern="01_|RAW_",
                message="Raw layer objects must start with 01_ or RAW_",
            ),
        ],
    )


def test_field_required_catches_missing(basic_standard):
    obj = ScannedObject(object_id="TEST", object_type=ObjectType.ADSO, name="TEST", description="", source_system="BW4")
    agent = DocQAAgent([basic_standard])
    issues = agent.check_object(obj)
    assert any(i.rule_id == "desc_required" for i in issues)


def test_min_length_catches_short(basic_standard):
    obj = ScannedObject(
        object_id="TEST", object_type=ObjectType.ADSO, name="TEST", description="Short", source_system="BW4"
    )
    agent = DocQAAgent([basic_standard])
    issues = agent.check_object(obj)
    assert any(i.rule_id == "desc_length" for i in issues)


def test_passes_when_valid(basic_standard):
    obj = ScannedObject(
        object_id="TEST",
        object_type=ObjectType.ADSO,
        name="TEST",
        description="This is a sufficiently long description for testing",
        owner="DEV1",
        source_system="BW4",
    )
    agent = DocQAAgent([basic_standard])
    issues = agent.check_object(obj)
    assert len(issues) == 0


def test_naming_convention(naming_standard):
    obj = ScannedObject(
        object_id="BAD_NAME", object_type=ObjectType.VIEW, name="BAD_NAME", source_system="DSP", layer="raw"
    )
    agent = DocQAAgent([naming_standard])
    issues = agent.check_object(obj)
    assert any(i.rule_id == "raw_prefix" for i in issues)


def test_naming_convention_passes(naming_standard):
    obj = ScannedObject(
        object_id="01_SALES", object_type=ObjectType.VIEW, name="01_SALES", source_system="DSP", layer="raw"
    )
    agent = DocQAAgent([naming_standard])
    assert len(agent.check_object(obj)) == 0


def test_check_all_report(basic_standard):
    result = ScanResult(
        source_system="BW4",
        objects=[
            ScannedObject(object_id="O1", object_type=ObjectType.ADSO, name="O1", description="", source_system="BW4"),
            ScannedObject(
                object_id="O2",
                object_type=ObjectType.ADSO,
                name="O2",
                description="A good long description here yes",
                owner="DEV1",
                source_system="BW4",
            ),
        ],
    )
    agent = DocQAAgent([basic_standard])
    report = agent.check_all(result)
    assert report.objects_checked == 2
    assert report.total_checks == 6  # 2 objects * 3 rules
    assert report.score < 100.0
    assert len(report.issues) > 0


def test_score_calculation():
    report = QAReport(standard_name="Test", objects_checked=1, total_checks=10, checks_passed=8, issues=[])
    assert report.score == 80.0


def test_by_severity():
    report = QAReport(
        standard_name="Test",
        objects_checked=1,
        total_checks=5,
        checks_passed=2,
        issues=[
            QualityIssue(object_id="A", rule_id="r1", severity="critical", message="x"),
            QualityIssue(object_id="A", rule_id="r2", severity="critical", message="y"),
            QualityIssue(object_id="A", rule_id="r3", severity="minor", message="z"),
        ],
    )
    assert report.by_severity == {"critical": 2, "minor": 1}


def test_load_standard(tmp_path):
    std_file = tmp_path / "test_standard.yaml"
    std_file.write_text("""\
name: File Standard
rules:
  - id: r1
    name: Test Rule
    severity: critical
    check_type: field_required
    field: description
    message: Need description
""")
    std = load_standard(std_file)
    assert std.name == "File Standard"
    assert len(std.rules) == 1
    assert std.rules[0].id == "r1"


def test_multiple_standards(basic_standard, naming_standard):
    obj = ScannedObject(
        object_id="BAD", object_type=ObjectType.VIEW, name="BAD", description="", source_system="DSP", layer="raw"
    )
    agent = DocQAAgent([basic_standard, naming_standard])
    issues = agent.check_object(obj)
    rule_ids = {i.rule_id for i in issues}
    assert "desc_required" in rule_ids
    assert "raw_prefix" in rule_ids
