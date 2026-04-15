import pytest
import httpx
import respx
from spec2sphere.scanner.cdp_client import CDPClient


@pytest.fixture
def client():
    return CDPClient(cdp_url="http://test-chrome:9222")


@pytest.mark.asyncio
@respx.mock
async def test_list_targets(client):
    respx.get("http://test-chrome:9222/json/list").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "tab1", "url": "https://horvath.hcs.cloud.sap/dwaas-core/index.html", "type": "page"},
                {"id": "tab2", "url": "about:blank", "type": "page"},
            ],
        )
    )
    targets = await client.list_targets()
    assert len(targets) == 2


@pytest.mark.asyncio
@respx.mock
async def test_find_target(client):
    respx.get("http://test-chrome:9222/json/list").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "tab1", "url": "https://horvath.hcs.cloud.sap", "type": "page"},
                {"id": "tab2", "url": "about:blank", "type": "page"},
            ],
        )
    )
    target = await client.find_target("horvath")
    assert target is not None
    assert target["id"] == "tab1"


@pytest.mark.asyncio
@respx.mock
async def test_find_target_not_found(client):
    respx.get("http://test-chrome:9222/json/list").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "tab1", "url": "https://example.com", "type": "page"},
            ],
        )
    )
    target = await client.find_target("horvath")
    assert target is None


@pytest.mark.asyncio
@respx.mock
async def test_get_page_url(client):
    client._target_id = "tab1"
    respx.get("http://test-chrome:9222/json/list").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "tab1", "url": "https://horvath.hcs.cloud.sap/data-builder", "type": "page"},
            ],
        )
    )
    url = await client.get_page_url()
    assert "horvath" in url
