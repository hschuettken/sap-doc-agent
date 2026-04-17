import json
import time
from datetime import datetime, timezone
from typing import Optional

import pytest

from spec2sphere.agents.doc_sync import ConflictRecord, DocSyncAgent, SyncReport, _SYNC_STATE_FILE
from spec2sphere.doc_platform.base import DocPlatformAdapter, Page, Space
from spec2sphere.scanner.models import ObjectType, ScanResult, ScannedObject


class MockDocPlatform(DocPlatformAdapter):
    def __init__(self):
        self.spaces = []
        self.pages = []
        self._id_counter = 0
        # Optional overrides for bidirectional tests
        self._hierarchy: list[Page] = []
        self._page_updated_at: dict[str, Optional[str]] = {}
        self._page_contents: dict[str, str] = {}
        self._updated_pages: dict[str, str] = {}  # page_id -> new content

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
        self._page_contents[p.id] = content
        return p

    async def update_page(self, page_id, content, title=None):
        self._updated_pages[page_id] = content

    async def get_page(self, page_id):
        content = self._page_contents.get(page_id, f"content of {page_id}")
        # find title from hierarchy
        title = next((p.title for p in self._hierarchy if p.id == page_id), "")
        return Page(id=page_id, title=title, content=content)

    async def search(self, query):
        return []

    async def delete_page(self, page_id):
        pass

    async def get_hierarchy(self, space_id: str) -> list[Page]:
        return list(self._hierarchy)

    async def get_page_updated_at(self, page_id: str) -> Optional[str]:
        return self._page_updated_at.get(page_id)


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


# ------------------------------------------------------------------
# Existing tests — unchanged
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# New bidirectional sync tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_from_platform_creates_local_files(platform, tmp_path):
    """pull_from_platform writes new pages as local markdown files."""
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_contents["p1"] = "# MyPage\nSome content"

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.pull_from_platform("space1", tmp_path)

    assert report.pages_created == 1
    assert report.pages_updated == 0
    assert report.errors == []

    written = tmp_path / "objects" / "platform" / "MyPage.md"
    assert written.exists()
    assert written.read_text() == "# MyPage\nSome content"


@pytest.mark.asyncio
async def test_pull_from_platform_updates_changed_files(platform, tmp_path):
    """pull_from_platform updates existing local files that differ from platform."""
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_contents["p1"] = "# MyPage\nNew content"

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    (dest / "MyPage.md").write_text("# MyPage\nOld content")

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.pull_from_platform("space1", tmp_path)

    assert report.pages_updated == 1
    assert report.pages_created == 0
    assert (dest / "MyPage.md").read_text() == "# MyPage\nNew content"


@pytest.mark.asyncio
async def test_pull_from_platform_skips_identical_files(platform, tmp_path):
    """pull_from_platform skips pages where local content matches platform."""
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_contents["p1"] = "# MyPage\nSame content"

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    (dest / "MyPage.md").write_text("# MyPage\nSame content")

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.pull_from_platform("space1", tmp_path)

    assert report.pages_skipped == 1
    assert report.pages_created == 0
    assert report.pages_updated == 0


@pytest.mark.asyncio
async def test_pull_from_platform_writes_sync_state(platform, tmp_path):
    """pull_from_platform persists .sync_state.json after completion."""
    platform._hierarchy = [Page(id="p1", title="Page1"), Page(id="p2", title="Page2")]
    platform._page_contents["p1"] = "content 1"
    platform._page_contents["p2"] = "content 2"

    agent = DocSyncAgent(platform, "BW4")
    await agent.pull_from_platform("space1", tmp_path)

    state_file = tmp_path / _SYNC_STATE_FILE
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert "p1" in state
    assert "p2" in state


@pytest.mark.asyncio
async def test_pull_from_platform_handles_hierarchy_error(platform, tmp_path):
    """pull_from_platform returns error in report if get_hierarchy fails."""

    async def bad_hierarchy(space_id):
        raise RuntimeError("network error")

    platform.get_hierarchy = bad_hierarchy  # type: ignore[method-assign]

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.pull_from_platform("space1", tmp_path)

    assert report.pages_created == 0
    assert any("get_hierarchy" in e for e in report.errors)


@pytest.mark.asyncio
async def test_detect_conflicts_no_prior_sync(platform, tmp_path):
    """detect_conflicts returns nothing when no sync state exists yet."""
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_updated_at["p1"] = "2026-01-02T12:00:00+00:00"

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    (dest / "MyPage.md").write_text("content")

    agent = DocSyncAgent(platform, "BW4")
    conflicts = await agent.detect_conflicts("space1", tmp_path)
    assert conflicts == []


@pytest.mark.asyncio
async def test_detect_conflicts_identifies_both_changed(platform, tmp_path):
    """detect_conflicts returns a ConflictRecord when both sides changed after last sync."""
    last_synced = "2026-01-01T10:00:00+00:00"
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    # Platform updated after last sync
    platform._page_updated_at["p1"] = "2026-01-02T12:00:00+00:00"

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    local_file = dest / "MyPage.md"
    local_file.write_text("local edits")

    # Write a sync state that predates the local file mtime
    state = {"p1": last_synced}
    (tmp_path / _SYNC_STATE_FILE).write_text(json.dumps(state))

    # Bump file mtime past last_synced using a future timestamp
    future_ts = time.time() + 3600  # ensure local_updated > last_synced
    import os

    os.utime(local_file, (future_ts, future_ts))

    agent = DocSyncAgent(platform, "BW4")
    conflicts = await agent.detect_conflicts("space1", tmp_path)

    assert len(conflicts) == 1
    assert conflicts[0].page_id == "p1"
    assert conflicts[0].resolution == "unresolved"


@pytest.mark.asyncio
async def test_detect_conflicts_no_conflict_when_only_platform_changed(platform, tmp_path):
    """detect_conflicts does not flag when only the platform changed."""
    # local file mtime is 2h ago; last_synced is 1h ago; platform changed after that
    past_ts = time.time() - 7200  # local file mtime: 2 hours ago
    synced_ts = time.time() - 3600  # last synced: 1 hour ago
    future_ts = time.time() + 3600  # platform updated: 1 hour from now

    last_synced = datetime.fromtimestamp(synced_ts, tz=timezone.utc).isoformat()
    platform_updated = datetime.fromtimestamp(future_ts, tz=timezone.utc).isoformat()

    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_updated_at["p1"] = platform_updated

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    local_file = dest / "MyPage.md"
    local_file.write_text("original")

    # local file has mtime before last_synced
    import os

    os.utime(local_file, (past_ts, past_ts))

    state = {"p1": last_synced}
    (tmp_path / _SYNC_STATE_FILE).write_text(json.dumps(state))

    agent = DocSyncAgent(platform, "BW4")
    conflicts = await agent.detect_conflicts("space1", tmp_path)

    assert conflicts == []


@pytest.mark.asyncio
async def test_sync_bidirectional_platform_wins(platform, tmp_path):
    """sync_bidirectional with platform_wins overwrites local conflicting file."""
    last_synced = "2026-01-01T10:00:00+00:00"
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_updated_at["p1"] = "2026-01-02T12:00:00+00:00"
    platform._page_contents["p1"] = "platform version"

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    local_file = dest / "MyPage.md"
    local_file.write_text("local version")

    state = {"p1": last_synced}
    (tmp_path / _SYNC_STATE_FILE).write_text(json.dumps(state))

    import os

    os.utime(local_file, (time.time() + 3600, time.time() + 3600))

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.sync_bidirectional("space1", tmp_path, conflict_resolution="platform_wins")

    assert report.pages_updated >= 1
    assert local_file.read_text() == "platform version"


@pytest.mark.asyncio
async def test_sync_bidirectional_local_wins(platform, tmp_path):
    """sync_bidirectional with local_wins pushes local content to platform."""
    last_synced = "2026-01-01T10:00:00+00:00"
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_updated_at["p1"] = "2026-01-02T12:00:00+00:00"
    platform._page_contents["p1"] = "platform version"

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    local_file = dest / "MyPage.md"
    local_file.write_text("local version")

    state = {"p1": last_synced}
    (tmp_path / _SYNC_STATE_FILE).write_text(json.dumps(state))

    import os

    os.utime(local_file, (time.time() + 3600, time.time() + 3600))

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.sync_bidirectional("space1", tmp_path, conflict_resolution="local_wins")

    assert report.pages_updated >= 1
    assert platform._updated_pages.get("p1") == "local version"


@pytest.mark.asyncio
async def test_sync_bidirectional_skip_records_error(platform, tmp_path):
    """sync_bidirectional with skip records the conflict in report errors."""
    last_synced = "2026-01-01T10:00:00+00:00"
    platform._hierarchy = [Page(id="p1", title="MyPage")]
    platform._page_updated_at["p1"] = "2026-01-02T12:00:00+00:00"
    platform._page_contents["p1"] = "platform version"

    dest = tmp_path / "objects" / "platform"
    dest.mkdir(parents=True)
    local_file = dest / "MyPage.md"
    local_file.write_text("local version")

    state = {"p1": last_synced}
    (tmp_path / _SYNC_STATE_FILE).write_text(json.dumps(state))

    import os

    os.utime(local_file, (time.time() + 3600, time.time() + 3600))

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.sync_bidirectional("space1", tmp_path, conflict_resolution="skip")

    assert any("skipped" in e.lower() or "p1" in e for e in report.errors)


@pytest.mark.asyncio
async def test_sync_bidirectional_no_conflict_new_pages(platform, tmp_path):
    """sync_bidirectional creates local files for pages not seen before."""
    platform._hierarchy = [Page(id="p1", title="NewPage")]
    platform._page_contents["p1"] = "brand new content"

    agent = DocSyncAgent(platform, "BW4")
    report = await agent.sync_bidirectional("space1", tmp_path)

    assert report.pages_created == 1
    local_file = tmp_path / "objects" / "platform" / "NewPage.md"
    assert local_file.exists()
    assert local_file.read_text() == "brand new content"


def test_conflict_record_defaults():
    c = ConflictRecord(
        page_id="p1",
        local_path="/tmp/page.md",
        platform_updated="2026-01-02T00:00:00+00:00",
        local_updated="2026-01-02T01:00:00+00:00",
    )
    assert c.resolution == "unresolved"
