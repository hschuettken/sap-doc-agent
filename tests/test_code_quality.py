import pytest
from sap_doc_agent.agents.code_quality import CodeQualityAgent
from sap_doc_agent.scanner.models import ScannedObject, ScanResult, ObjectType


@pytest.fixture
def agent():
    return CodeQualityAgent()


def test_select_star_detected(agent):
    obj = ScannedObject(
        object_id="T1",
        object_type=ObjectType.TRANSFORMATION,
        name="T1",
        source_system="BW4",
        source_code="SELECT * FROM ztable INTO TABLE lt_data.",
    )
    issues = agent.check_object(obj)
    assert any("SELECT *" in i.message for i in issues)


def test_hardcoded_client_detected(agent):
    obj = ScannedObject(
        object_id="T1",
        object_type=ObjectType.TRANSFORMATION,
        name="T1",
        source_system="BW4",
        source_code="WHERE mandt = '800'.",
    )
    issues = agent.check_object(obj)
    assert any("client" in i.message.lower() or "hardcoded" in i.message.lower() for i in issues)


def test_magic_date_detected(agent):
    obj = ScannedObject(
        object_id="T1",
        object_type=ObjectType.TRANSFORMATION,
        name="T1",
        source_system="BW4",
        source_code="IF date > '20251231'.",
    )
    issues = agent.check_object(obj)
    assert any(
        "date" in i.message.lower() or "magic" in i.message.lower() or "hardcoded" in i.message.lower() for i in issues
    )


def test_clean_code_passes(agent):
    obj = ScannedObject(
        object_id="T1",
        object_type=ObjectType.TRANSFORMATION,
        name="T1",
        source_system="BW4",
        source_code="SELECT field1 field2 FROM ztable INTO TABLE lt_data WHERE bukrs = lv_bukrs.",
    )
    issues = agent.check_object(obj)
    assert len(issues) == 0


def test_no_source_code_skipped(agent):
    obj = ScannedObject(object_id="T1", object_type=ObjectType.ADSO, name="T1", source_system="BW4", source_code="")
    assert len(agent.check_object(obj)) == 0


def test_check_all_aggregates(agent):
    result = ScanResult(
        source_system="BW4",
        objects=[
            ScannedObject(
                object_id="T1",
                object_type=ObjectType.TRANSFORMATION,
                name="T1",
                source_system="BW4",
                source_code="SELECT * FROM ztable.",
            ),
            ScannedObject(
                object_id="T2",
                object_type=ObjectType.TRANSFORMATION,
                name="T2",
                source_system="BW4",
                source_code="SELECT field1 FROM ztable WHERE x = y.",
            ),
        ],
    )
    issues = agent.check_all(result)
    assert len(issues) >= 1  # At least the SELECT * from T1
