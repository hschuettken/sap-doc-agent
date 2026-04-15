"""Tests for DSPScanner — Datasphere REST API scanner."""

from __future__ import annotations

import respx
import httpx

from spec2sphere.scanner.dsp_auth import DSPAuth
from spec2sphere.scanner.dsp_scanner import DSPScanner
from spec2sphere.scanner.models import ObjectType

BASE_URL = "https://dsp.example.com"
TOKEN_URL = "https://auth.example.com/oauth/token"
TOKEN_RESPONSE = httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})


def _make_scanner(spaces: list[str], namespace_filter=None) -> DSPScanner:
    auth = DSPAuth("cid", "csecret", TOKEN_URL)
    return DSPScanner(
        base_url=BASE_URL,
        auth=auth,
        spaces=spaces,
        namespace_filter=namespace_filter,
    )


@respx.mock
async def test_list_spaces_returns_space_list():
    """list_spaces returns the 'value' array from the spaces endpoint."""
    respx.post(TOKEN_URL).mock(return_value=TOKEN_RESPONSE)
    respx.get(f"{BASE_URL}/api/v1/dwc/catalog/spaces").mock(
        return_value=httpx.Response(200, json={"value": [{"name": "SPACE_A"}, {"name": "SPACE_B"}]})
    )
    scanner = _make_scanner(spaces=["SPACE_A"])
    result = await scanner.list_spaces()
    assert result == [{"name": "SPACE_A"}, {"name": "SPACE_B"}]


@respx.mock
async def test_get_space_objects_returns_objects():
    """get_space_objects returns the 'value' array from the assets endpoint."""
    respx.post(TOKEN_URL).mock(return_value=TOKEN_RESPONSE)
    respx.get(f"{BASE_URL}/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"technicalName": "MY_VIEW", "type": "VIEW", "description": "A view"},
                ]
            },
        )
    )
    scanner = _make_scanner(spaces=["SPACE_A"])
    result = await scanner.get_space_objects("SPACE_A")
    assert len(result) == 1
    assert result[0]["technicalName"] == "MY_VIEW"


@respx.mock
async def test_scan_produces_correct_object_type_mapping():
    """scan maps DSP type strings to correct ObjectType values."""
    respx.post(TOKEN_URL).mock(return_value=TOKEN_RESPONSE)
    respx.get(f"{BASE_URL}/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"technicalName": "V1", "type": "VIEW", "description": ""},
                    {"technicalName": "T1", "type": "LOCAL_TABLE", "description": ""},
                    {"technicalName": "RF1", "type": "REPLICATION_FLOW", "description": ""},
                ]
            },
        )
    )
    scanner = _make_scanner(spaces=["SPACE_A"])
    result = await scanner.scan()

    by_name = {o.name: o for o in result.objects}
    assert by_name["V1"].object_type == ObjectType.VIEW
    assert by_name["T1"].object_type == ObjectType.TABLE
    assert by_name["RF1"].object_type == ObjectType.DATA_SOURCE


@respx.mock
async def test_scan_applies_namespace_filter():
    """scan only includes objects whose names match the namespace_filter patterns."""
    respx.post(TOKEN_URL).mock(return_value=TOKEN_RESPONSE)
    respx.get(f"{BASE_URL}/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"technicalName": "01_RAW_SALES", "type": "LOCAL_TABLE", "description": ""},
                    {"technicalName": "02_HAR_SALES", "type": "VIEW", "description": ""},
                    {"technicalName": "INTERNAL_TEMP", "type": "LOCAL_TABLE", "description": ""},
                ]
            },
        )
    )
    scanner = _make_scanner(spaces=["SPACE_A"], namespace_filter=["01_*", "02_*"])
    result = await scanner.scan()

    names = {o.name for o in result.objects}
    assert "01_RAW_SALES" in names
    assert "02_HAR_SALES" in names
    assert "INTERNAL_TEMP" not in names


@respx.mock
async def test_scan_dsp_type_mapping_covers_view_table_replication():
    """DSP type mapping covers VIEW, LOCAL_TABLE, and REPLICATION_FLOW."""
    respx.post(TOKEN_URL).mock(return_value=TOKEN_RESPONSE)
    respx.get(f"{BASE_URL}/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"technicalName": "GV1", "type": "GRAPHICAL_VIEW", "description": ""},
                    {"technicalName": "RT1", "type": "REMOTE_TABLE", "description": ""},
                    {"technicalName": "DF1", "type": "DATA_FLOW", "description": ""},
                    {"technicalName": "AM1", "type": "ANALYTIC_MODEL", "description": ""},
                    {"technicalName": "TC1", "type": "TASK_CHAIN", "description": ""},
                    {"technicalName": "UNK1", "type": "UNKNOWN_TYPE", "description": ""},
                ]
            },
        )
    )
    scanner = _make_scanner(spaces=["SPACE_A"])
    result = await scanner.scan()

    by_name = {o.name: o for o in result.objects}
    assert by_name["GV1"].object_type == ObjectType.VIEW
    assert by_name["RT1"].object_type == ObjectType.TABLE
    assert by_name["DF1"].object_type == ObjectType.TRANSFORMATION
    assert by_name["AM1"].object_type == ObjectType.VIEW
    assert by_name["TC1"].object_type == ObjectType.PROCESS_CHAIN
    assert by_name["UNK1"].object_type == ObjectType.OTHER


@respx.mock
async def test_scan_sets_source_system_and_object_id():
    """scan sets source_system=DSP and object_id as space.name."""
    respx.post(TOKEN_URL).mock(return_value=TOKEN_RESPONSE)
    respx.get(f"{BASE_URL}/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(
            200,
            json={"value": [{"technicalName": "MY_OBJ", "type": "VIEW", "description": ""}]},
        )
    )
    scanner = _make_scanner(spaces=["MY_SPACE"])
    result = await scanner.scan()

    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.source_system == "DSP"
    assert obj.object_id == "MY_SPACE.MY_OBJ"
