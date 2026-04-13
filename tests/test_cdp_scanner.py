import pytest
from sap_doc_agent.scanner.cdp_client import CDPClient
from sap_doc_agent.scanner.cdp_scanner import (
    DSPCDPScanner,
    infer_layer,
    map_dsp_type,
)
from sap_doc_agent.scanner.models import ObjectType, DependencyType


# --- CDPClient tests ---


@pytest.mark.asyncio
async def test_cdp_client_init():
    client = CDPClient(cdp_url="http://test:9222")
    assert client.is_available


# --- Type mapping tests ---


def test_map_view_types():
    assert map_dsp_type("View (Fact)") == ObjectType.VIEW
    assert map_dsp_type("View (Relational Dataset)") == ObjectType.VIEW
    assert map_dsp_type("View (Text)") == ObjectType.VIEW
    assert map_dsp_type("View (Dimension)") == ObjectType.VIEW
    assert map_dsp_type("Analytic Model (Cube)") == ObjectType.VIEW


def test_map_table_types():
    assert map_dsp_type("Local Table (Relational Dataset)") == ObjectType.TABLE
    assert map_dsp_type("Local Table (Text)") == ObjectType.TABLE


def test_map_other_types():
    assert map_dsp_type("Data Flow") == ObjectType.TRANSFORMATION
    assert map_dsp_type("Task Chain") == ObjectType.PROCESS_CHAIN
    assert map_dsp_type("Unknown Thing") == ObjectType.OTHER


def test_infer_layer():
    assert infer_layer("01LT_SALES") == "raw"
    assert infer_layer("1LT_SALES") == "raw"
    assert infer_layer("02RV_SALES") == "harmonized"
    assert infer_layer("2TX_SALES") == "harmonized"
    assert infer_layer("03AM_SALES") == "mart"
    assert infer_layer("SOMETHING_ELSE") == ""


# --- DSPCDPScanner tests ---


@pytest.fixture
def scanner():
    return DSPCDPScanner(source_system="Horvath DSP", tenant_url="https://horvath.eu10.hcs.cloud.sap")


@pytest.fixture
def sample_repo_objects():
    return [
        {
            "business_name": "Sales Fact (RV)",
            "technical_name": "02RV_SALES",
            "dsp_type": "View (Relational Dataset)",
            "space": "MY_SPACE",
            "folder": "Fact Data",
            "status": "Deployed",
            "last_modified": "Apr 10, 2026",
        },
        {
            "business_name": "Sales Raw (LT)",
            "technical_name": "01LT_SALES",
            "dsp_type": "Local Table (Relational Dataset)",
            "space": "MY_SPACE",
            "folder": "Fact Data",
            "status": "Deployed",
            "last_modified": "Apr 9, 2026",
        },
        {
            "business_name": "Time Table",
            "technical_name": "SAP.TIME.M_TIME_DIMENSION",
            "dsp_type": "Local Table",
            "space": "MY_SPACE",
            "folder": "",
            "status": "Deployed",
            "last_modified": "",
        },
    ]


def test_process_repo_objects(scanner, sample_repo_objects):
    objects = scanner.process_repo_objects(sample_repo_objects)
    assert len(objects) == 2  # SAP.TIME skipped
    assert objects[0].name == "02RV_SALES"
    assert objects[0].object_type == ObjectType.VIEW
    assert objects[0].layer == "harmonized"
    assert objects[0].metadata["business_name"] == "Sales Fact (RV)"
    assert objects[1].layer == "raw"


def test_enrich_with_sql(scanner, sample_repo_objects):
    objects = scanner.process_repo_objects(sample_repo_objects)
    scanner.enrich_with_sql(objects[0], "SELECT * FROM 01LT_SALES")
    assert objects[0].source_code == "SELECT * FROM 01LT_SALES"
    assert objects[0].metadata["has_sql"] is True


def test_enrich_with_columns(scanner, sample_repo_objects):
    objects = scanner.process_repo_objects(sample_repo_objects)
    cols = [{"name": "AMOUNT", "type": "DECIMAL(17,2)", "description": "Sales amount"}]
    scanner.enrich_with_columns(objects[0], cols)
    assert objects[0].metadata["columns"] == cols


def test_enrich_with_lineage(scanner, sample_repo_objects):
    objects = scanner.process_repo_objects(sample_repo_objects)
    lineage = {"upstream": ["01LT_SALES"], "downstream": ["03AM_SALES_MODEL"]}
    deps = scanner.enrich_with_lineage(objects[0], lineage)
    assert len(deps) == 2
    assert deps[0].dependency_type == DependencyType.READS_FROM
    assert deps[0].target_id == "01LT_SALES"


def test_enrich_with_screenshot(scanner, sample_repo_objects):
    objects = scanner.process_repo_objects(sample_repo_objects)
    scanner.enrich_with_screenshot(objects[0], "screenshots/02RV_SALES.png")
    assert "screenshots/02RV_SALES.png" in objects[0].metadata["screenshots"]


def test_scan_from_extractions(scanner, sample_repo_objects):
    result = scanner.scan_from_extractions(
        repo_objects=sample_repo_objects,
        sql_by_id={"MY_SPACE.02RV_SALES": "SELECT a, b FROM 01LT_SALES"},
        columns_by_id={"MY_SPACE.02RV_SALES": [{"name": "a", "type": "VARCHAR"}]},
        lineage_by_id={"MY_SPACE.02RV_SALES": {"upstream": ["01LT_SALES"], "downstream": []}},
        screenshots_by_id={"MY_SPACE.02RV_SALES": ["shot1.png"]},
    )
    assert len(result.objects) == 2
    assert result.objects[0].source_code == "SELECT a, b FROM 01LT_SALES"
    assert len(result.objects[0].metadata["columns"]) == 1
    assert len(result.dependencies) == 1
    assert result.source_system == "Horvath DSP"


def test_build_result(scanner, sample_repo_objects):
    objects = scanner.process_repo_objects(sample_repo_objects)
    result = scanner.build_result(objects)
    assert result.source_system == "Horvath DSP"
    assert len(result.objects) == 2


def test_js_snippets():
    snippets = DSPCDPScanner.get_js_snippets()
    assert "repo_objects" in snippets
    assert "sql" in snippets
    assert "columns" in snippets
    assert "lineage" in snippets
    assert "querySelectorAll" in snippets["repo_objects"]
