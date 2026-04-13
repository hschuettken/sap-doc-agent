import pytest
import httpx
import respx
from unittest.mock import MagicMock, patch
from sap_doc_agent.config import DocPlatformConfig, AuthConfig
from sap_doc_agent.doc_platform import create_doc_adapter
from sap_doc_agent.doc_platform.base import DocPlatformAdapter
from sap_doc_agent.doc_platform.bookstack import BookStackAdapter
from sap_doc_agent.doc_platform.outline import OutlineAdapter
from sap_doc_agent.doc_platform.confluence import ConfluenceAdapter


# --- BookStack tests ---


@pytest.fixture
def bookstack():
    return BookStackAdapter(base_url="http://test:8253", token_id="1", token_secret="abc")


def test_bookstack_is_adapter(bookstack):
    assert isinstance(bookstack, DocPlatformAdapter)


@pytest.mark.asyncio
@respx.mock
async def test_bookstack_create_book(bookstack):
    respx.post("http://test:8253/api/books").mock(return_value=httpx.Response(200, json={"id": 1, "name": "BW/4"}))
    space = await bookstack.create_space("BW/4")
    assert space.id == "1"


@pytest.mark.asyncio
@respx.mock
async def test_bookstack_create_chapter(bookstack):
    respx.post("http://test:8253/api/chapters").mock(
        return_value=httpx.Response(200, json={"id": 10, "name": "RAW", "book_id": 1})
    )
    page = await bookstack.create_page("1", "RAW", "", is_chapter=True)
    assert page.id == "10"


@pytest.mark.asyncio
@respx.mock
async def test_bookstack_create_page(bookstack):
    respx.post("http://test:8253/api/pages").mock(
        return_value=httpx.Response(200, json={"id": 100, "name": "ADSO_SALES", "chapter_id": 10})
    )
    page = await bookstack.create_page("1", "ADSO_SALES", "# Sales", parent_id="10")
    assert page.id == "100"


@pytest.mark.asyncio
@respx.mock
async def test_bookstack_get_page(bookstack):
    respx.get("http://test:8253/api/pages/100").mock(
        return_value=httpx.Response(
            200,
            json={"id": 100, "name": "ADSO_SALES", "markdown": "# ADSO", "tags": [{"name": "layer", "value": "raw"}]},
        )
    )
    page = await bookstack.get_page("100")
    assert page.title == "ADSO_SALES"
    assert page.labels["layer"] == "raw"


@pytest.mark.asyncio
@respx.mock
async def test_bookstack_search(bookstack):
    respx.get("http://test:8253/api/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": 100, "name": "ADSO_SALES", "type": "page", "preview": {"content": "Sales"}}],
                "total": 1,
            },
        )
    )
    results = await bookstack.search("ADSO")
    assert len(results) == 1


# --- Outline tests ---


@pytest.fixture
def outline():
    return OutlineAdapter(base_url="http://test:8250", api_key="test-key")


def test_outline_is_adapter(outline):
    assert isinstance(outline, DocPlatformAdapter)


@pytest.mark.asyncio
@respx.mock
async def test_outline_create_collection(outline):
    respx.post("http://test:8250/api/collections.create").mock(
        return_value=httpx.Response(200, json={"data": {"id": "col-1", "name": "BW/4"}})
    )
    space = await outline.create_space("BW/4")
    assert space.id == "col-1"


@pytest.mark.asyncio
@respx.mock
async def test_outline_create_doc(outline):
    respx.post("http://test:8250/api/documents.create").mock(
        return_value=httpx.Response(200, json={"data": {"id": "doc-1", "title": "ADSO", "text": "# ADSO"}})
    )
    page = await outline.create_page("col-1", "ADSO", "# ADSO")
    assert page.id == "doc-1"


@pytest.mark.asyncio
@respx.mock
async def test_outline_search(outline):
    respx.post("http://test:8250/api/documents.search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"document": {"id": "doc-1", "title": "ADSO", "text": "Sales"}}],
                "pagination": {"total": 1},
            },
        )
    )
    results = await outline.search("ADSO")
    assert len(results) == 1


# --- Confluence tests ---


@pytest.fixture
def mock_confluence():
    mock = MagicMock()
    mock.create_space.return_value = {"id": 123, "key": "SAP", "name": "SAP Docs"}
    mock.create_page.return_value = {"id": 456, "title": "ADSO_SALES"}
    mock.get_page_by_id.return_value = {
        "id": 456,
        "title": "ADSO_SALES",
        "body": {"storage": {"value": "<h1>ADSO</h1>"}},
        "metadata": {"labels": {"results": [{"name": "raw-layer"}]}},
    }
    mock.cql.return_value = {"results": [{"content": {"id": 789, "title": "ADSO_REVENUE"}}]}
    return mock


@pytest.fixture
def confluence(mock_confluence):
    with patch("sap_doc_agent.doc_platform.confluence.Confluence", return_value=mock_confluence):
        return ConfluenceAdapter(url="https://conf.test", token="tok")


def test_confluence_is_adapter(confluence):
    assert isinstance(confluence, DocPlatformAdapter)


@pytest.mark.asyncio
async def test_confluence_create_space(confluence, mock_confluence):
    await confluence.create_space("SAP Docs")
    mock_confluence.create_space.assert_called_once()


@pytest.mark.asyncio
async def test_confluence_create_page(confluence):
    page = await confluence.create_page("SAP", "ADSO_SALES", "<h1>ADSO</h1>")
    assert page.id == "456"


@pytest.mark.asyncio
async def test_confluence_search(confluence):
    results = await confluence.search("ADSO_REVENUE")
    assert len(results) == 1
    assert results[0].title == "ADSO_REVENUE"


# --- Factory tests ---


def test_factory_bookstack(monkeypatch):
    monkeypatch.setenv("BOOKSTACK_TOKEN", "1:secret")
    cfg = DocPlatformConfig(
        type="bookstack", url="http://localhost:8253", auth=AuthConfig(type="api_token", token_env="BOOKSTACK_TOKEN")
    )
    assert isinstance(create_doc_adapter(cfg), BookStackAdapter)


def test_factory_outline(monkeypatch):
    monkeypatch.setenv("OUTLINE_TOKEN", "ol_abc")
    cfg = DocPlatformConfig(
        type="outline", url="http://localhost:8250", auth=AuthConfig(type="api_token", token_env="OUTLINE_TOKEN")
    )
    assert isinstance(create_doc_adapter(cfg), OutlineAdapter)


def test_factory_confluence(monkeypatch):
    monkeypatch.setenv("CONF_TOKEN", "tok")
    cfg = DocPlatformConfig(
        type="confluence", url="https://conf.test", auth=AuthConfig(type="api_token", token_env="CONF_TOKEN")
    )
    with patch("sap_doc_agent.doc_platform.confluence.Confluence"):
        assert isinstance(create_doc_adapter(cfg), ConfluenceAdapter)


def test_factory_missing_env(monkeypatch):
    monkeypatch.delenv("BOOKSTACK_TOKEN", raising=False)
    cfg = DocPlatformConfig(
        type="bookstack", url="http://localhost", auth=AuthConfig(type="api_token", token_env="BOOKSTACK_TOKEN")
    )
    with pytest.raises(ValueError, match="environment variable"):
        create_doc_adapter(cfg)
