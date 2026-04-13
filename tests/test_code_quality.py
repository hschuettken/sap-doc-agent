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
        name="RAW_CLEAN_TRANSFORMATION",
        source_system="BW4",
        layer="raw",
        description="Clean transformation with no issues",
        source_code="SELECT field1 field2 FROM ztable INTO TABLE lt_data WHERE bukrs = lv_bukrs.",
    )
    issues = agent.check_object(obj)
    assert len(issues) == 0


def test_no_source_code_skipped(agent):
    obj = ScannedObject(
        object_id="T1",
        object_type=ObjectType.ADSO,
        name="RAW_SALES",
        source_system="BW4",
        layer="raw",
        description="Sales data source object",
        source_code="",
    )
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


# ------------------------------------------------------------------
# HANA SQL checks
# ------------------------------------------------------------------


def test_sql_select_star_detected(agent):
    obj = ScannedObject(
        object_id="V1",
        object_type=ObjectType.VIEW,
        name="V1",
        source_system="DSP",
        source_code='CREATE VIEW MY_VIEW AS SELECT * FROM "SPACE"."SOURCE_TABLE"',
    )
    issues = agent.check_object(obj)
    assert any(i.rule == "sql_select_star" for i in issues)


def test_sql_hardcoded_date_detected(agent):
    obj = ScannedObject(
        object_id="V2",
        object_type=ObjectType.VIEW,
        name="V2",
        source_system="DSP",
        source_code="CREATE VIEW MY_VIEW AS SELECT col1 FROM t WHERE col1 > '20230101'",
    )
    issues = agent.check_object(obj)
    assert any(i.rule == "sql_hardcoded_dates" for i in issues)


def test_sql_union_missing_alias(agent):
    obj = ScannedObject(
        object_id="V3",
        object_type=ObjectType.VIEW,
        name="V3",
        source_system="DSP",
        source_code=(
            "CREATE VIEW MY_VIEW AS\nSELECT col1, col2 FROM table_a\nUNION ALL\nSELECT col1, col2 FROM table_b"
        ),
    )
    issues = agent.check_object(obj)
    assert any(i.rule == "sql_union_missing_alias" for i in issues)


def test_sql_union_with_aliases_passes(agent):
    obj = ScannedObject(
        object_id="V4",
        object_type=ObjectType.VIEW,
        name="V4",
        source_system="DSP",
        source_code=(
            "CREATE VIEW MY_VIEW AS\n"
            "SELECT col1 AS c1, col2 AS c2 FROM table_a\n"
            "UNION ALL\n"
            "SELECT col1 AS c1, col2 AS c2 FROM table_b"
        ),
    )
    issues = agent.check_object(obj)
    assert not any(i.rule == "sql_union_missing_alias" for i in issues)


# ------------------------------------------------------------------
# Data model quality checks
# ------------------------------------------------------------------


def test_layer_missing_flagged(agent):
    obj = ScannedObject(
        object_id="DM1",
        object_type=ObjectType.ADSO,
        name="SOME_OBJECT",
        source_system="BW4",
        layer="",
        description="A well described object here",
    )
    issues = agent.check_object(obj)
    assert any(i.rule == "layer_assignment" for i in issues)


def test_naming_prefix_mismatch(agent):
    obj = ScannedObject(
        object_id="DM2",
        object_type=ObjectType.ADSO,
        name="WRONG_NAME",
        source_system="BW4",
        layer="raw",
        description="A well described raw object here",
    )
    issues = agent.check_object(obj)
    assert any(i.rule == "naming_prefix" for i in issues)


def test_naming_prefix_correct_passes(agent):
    obj = ScannedObject(
        object_id="DM3",
        object_type=ObjectType.ADSO,
        name="RAW_SALES_DATA",
        source_system="BW4",
        layer="raw",
        description="Raw sales data from source system",
    )
    issues = agent.check_object(obj)
    assert not any(i.rule == "naming_prefix" for i in issues)


def test_description_too_brief(agent):
    obj = ScannedObject(
        object_id="DM4",
        object_type=ObjectType.ADSO,
        name="RAW_DATA",
        source_system="BW4",
        layer="raw",
        description="x",
    )
    issues = agent.check_object(obj)
    assert any(i.rule == "description_quality" for i in issues)


def test_dsp_view_passes_clean(agent):
    """A well-formed Datasphere SQL view should pass all SQL checks."""
    obj = ScannedObject(
        object_id="V5",
        object_type=ObjectType.VIEW,
        name="03_MART_REVENUE",
        source_system="DSP",
        layer="mart",
        description="Revenue mart view joining harmonized data for reporting",
        source_code=(
            "CREATE VIEW V5 AS\nSELECT t.col1 AS revenue, t.col2 AS region FROM harmonized_table t\nWHERE t.active = 1"
        ),
    )
    issues = agent.check_object(obj)
    sql_issues = [i for i in issues if i.rule.startswith("sql_")]
    assert len(sql_issues) == 0
