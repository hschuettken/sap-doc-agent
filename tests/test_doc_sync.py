import pytest
from spec2sphere.agents.doc_sync import DocSyncAgent, SyncReport
from spec2sphere.doc_platform.base import DocPlatformAdapter, Page, Space
from spec2sphere.scanner.models import ScannedObject, ScanResult, ObjectType


class MockDocPlatform(DocPlatformAdapter):
    def __init__(self):
        self.spaces = []
        self.pages = []
        self._id_counter = 0

    def _next_id(self):
        self._id_counter += 1
        return str(self._id_counter)

    async def create_space(self, name, description=""):
        s = Space(id=self._next_id(), name=name)
        self.spaces.append(s)
        return s

    async def create_page(self, space_id, title, content, parent_id=None, is_chapter=False):
        p = Page(id=self._next_id(), title=title, content=content, parent_id=parent_id)
        self.pages.append(p)
        return p

    async def update_page(self, page_id, content, title=None):
        pass

    async def get_page(self, page_id):
        return Page(id=page_id, title="", content="")

    async def search(self, query):
        return []

    async def delete_page(self, page_id):
        pass


@pytest.fixture
def platform():
    return MockDocPlatform()


@pytest.fixture
def sample_result():
    return ScanResult(
        source_system="BW4",
        objects=[
            ScannedObject(
                object_id="ADSO_SALES",
                object_type=ObjectType.ADSO,
                name="ADSO_SALES",
                description="Sales",
                source_system="BW4",
                layer="raw",
            ),
            ScannedObject(
                object_id="V_MART",
                object_type=ObjectType.VIEW,
                name="V_MART",
                description="Mart view",
                source_system="BW4",
                layer="mart",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_sync_creates_space(platform, sample_result):
    agent = DocSyncAgent(platform, "Horvath BW/4")
    await agent.sync_scan_result(sample_result)
    assert len(platform.spaces) == 1
    assert platform.spaces[0].name == "Horvath BW/4"


@pytest.mark.asyncio
async def test_sync_creates_pages(platform, sample_result):
    agent = DocSyncAgent(platform, "BW4")
    report = await agent.sync_scan_result(sample_result)
    assert report.pages_created == 2
    assert report.total == 2


@pytest.mark.asyncio
async def test_sync_groups_by_layer(platform, sample_result):
    agent = DocSyncAgent(platform, "BW4")
    await agent.sync_scan_result(sample_result)
    chapter_titles = [p.title for p in platform.pages if p.parent_id is None or p.content == ""]
    # Should have chapters for "Raw" and "Mart"
    assert any("Raw" in t for t in chapter_titles)
    assert any("Mart" in t for t in chapter_titles)


@pytest.mark.asyncio
async def test_sync_report_tracks_errors(platform):
    result = ScanResult(source_system="BW4", objects=[])
    agent = DocSyncAgent(platform, "BW4")
    report = await agent.sync_scan_result(result)
    assert report.pages_created == 0
    assert len(report.errors) == 0


@pytest.mark.asyncio
async def test_sync_from_output_dir(platform, tmp_path):
    # Create a fake output dir
    obj_dir = tmp_path / "objects" / "adso"
    obj_dir.mkdir(parents=True)
    (obj_dir / "ADSO_TEST.md").write_text("---\nname: ADSO_TEST\n---\n# ADSO_TEST\n")
    agent = DocSyncAgent(platform, "BW4")
    report = await agent.sync_from_output_dir(tmp_path)
    assert report.pages_created == 1


def test_sync_report_model():
    r = SyncReport(pages_created=3, pages_updated=1, pages_skipped=2)
    assert r.total == 6
