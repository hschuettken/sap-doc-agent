"""Doc Sync Agent — pushes scanner output to documentation platform."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from spec2sphere.doc_platform.base import DocPlatformAdapter, Page
from spec2sphere.scanner.models import ScanResult, ScannedObject
from spec2sphere.scanner.output import render_object_markdown

logger = logging.getLogger(__name__)

_SYNC_STATE_FILE = ".sync_state.json"


class SyncReport(BaseModel):
    pages_created: int = 0
    pages_updated: int = 0
    pages_skipped: int = 0
    errors: list[str] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return self.pages_created + self.pages_updated + self.pages_skipped


@dataclass
class ConflictRecord:
    page_id: str
    local_path: str
    platform_updated: str  # ISO timestamp
    local_updated: str  # ISO timestamp
    resolution: str = "unresolved"  # platform_wins | local_wins | skipped


# ------------------------------------------------------------------
# Sync state helpers
# ------------------------------------------------------------------


def _load_sync_state(output_dir: Path) -> dict[str, str]:
    """Load {page_id: last_synced_at} from .sync_state.json."""
    state_file = output_dir / _SYNC_STATE_FILE
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            return {}
    return {}


def _save_sync_state(output_dir: Path, state: dict[str, str]) -> None:
    """Persist sync state to .sync_state.json."""
    state_file = output_dir / _SYNC_STATE_FILE
    state_file.write_text(json.dumps(state, indent=2))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime_iso(path: Path) -> str:
    """Return file mtime as ISO 8601 UTC string."""
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _page_local_path(output_dir: Path, page: Page) -> Path:
    """Derive the expected local markdown path for a platform page.

    Pages pulled from the platform land under output_dir/objects/platform/{title}.md.
    """
    safe_title = page.title.replace("/", "_").replace("\\", "_")
    return output_dir / "objects" / "platform" / f"{safe_title}.md"


class DocSyncAgent:
    def __init__(self, doc_platform: DocPlatformAdapter, source_system_name: str = "SAP"):
        self._platform = doc_platform
        self._system_name = source_system_name

    # ------------------------------------------------------------------
    # Existing one-way push methods — unchanged
    # ------------------------------------------------------------------

    async def sync_scan_result(self, result: ScanResult) -> SyncReport:
        report = SyncReport()
        # Create space for the source system
        space = await self._platform.create_space(self._system_name, f"Documentation for {self._system_name}")

        # Group objects by layer
        by_layer: dict[str, list[ScannedObject]] = {}
        for obj in result.objects:
            layer = obj.layer or "uncategorized"
            by_layer.setdefault(layer, []).append(obj)

        # Create chapters per layer, pages per object
        for layer, objects in sorted(by_layer.items()):
            chapter = await self._platform.create_page(
                space_id=space.id, title=layer.title(), content="", is_chapter=True
            )
            for obj in objects:
                try:
                    md = render_object_markdown(obj)
                    await self._platform.create_page(
                        space_id=space.id, title=obj.name, content=md, parent_id=chapter.id
                    )
                    report.pages_created += 1
                except Exception as e:
                    report.errors.append(f"{obj.object_id}: {e}")
        return report

    async def sync_from_output_dir(self, output_dir: Path) -> SyncReport:
        report = SyncReport()
        objects_dir = output_dir / "objects"
        if not objects_dir.exists():
            return report
        space = await self._platform.create_space(self._system_name, f"Documentation for {self._system_name}")

        for type_dir in sorted(objects_dir.iterdir()):
            if not type_dir.is_dir():
                continue
            chapter = await self._platform.create_page(
                space_id=space.id, title=type_dir.name.title(), content="", is_chapter=True
            )
            for md_file in sorted(type_dir.glob("*.md")):
                try:
                    content = md_file.read_text()
                    title = md_file.stem
                    # Try to extract title from frontmatter
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            fm = yaml.safe_load(parts[1])
                            title = fm.get("name", title)
                    await self._platform.create_page(
                        space_id=space.id, title=title, content=content, parent_id=chapter.id
                    )
                    report.pages_created += 1
                except Exception as e:
                    report.errors.append(f"{md_file.name}: {e}")
        return report

    # ------------------------------------------------------------------
    # Bidirectional sync — new methods
    # ------------------------------------------------------------------

    async def pull_from_platform(self, space_id: str, output_dir: Path) -> SyncReport:
        """Pull pages from doc platform back to local files.

        Pages are written to output_dir/objects/platform/{title}.md.
        Tracks pages_created (new local files), pages_updated (changed
        local files), and pages_skipped (identical content).
        """
        report = SyncReport()
        state = _load_sync_state(output_dir)
        now = _now_iso()

        try:
            pages = await self._platform.get_hierarchy(space_id)
        except Exception as e:
            report.errors.append(f"get_hierarchy failed: {e}")
            return report

        dest_dir = output_dir / "objects" / "platform"
        dest_dir.mkdir(parents=True, exist_ok=True)

        for page in pages:
            try:
                full_page = await self._platform.get_page(page.id)
                local_path = _page_local_path(output_dir, full_page)
                local_path.parent.mkdir(parents=True, exist_ok=True)

                content = full_page.content or ""
                if local_path.exists():
                    existing = local_path.read_text()
                    if existing == content:
                        report.pages_skipped += 1
                    else:
                        local_path.write_text(content)
                        report.pages_updated += 1
                else:
                    local_path.write_text(content)
                    report.pages_created += 1

                state[page.id] = now
            except Exception as e:
                report.errors.append(f"page {page.id}: {e}")

        _save_sync_state(output_dir, state)
        return report

    async def detect_conflicts(self, space_id: str, output_dir: Path) -> list[ConflictRecord]:
        """Compare timestamps between local files and platform pages.

        A conflict exists when both the local file and the platform page have
        been modified since the last recorded sync timestamp.
        """
        state = _load_sync_state(output_dir)
        conflicts: list[ConflictRecord] = []

        try:
            pages = await self._platform.get_hierarchy(space_id)
        except Exception as e:
            logger.warning("detect_conflicts: get_hierarchy failed: %s", e)
            return conflicts

        for page in pages:
            last_synced = state.get(page.id)
            if last_synced is None:
                # Never synced — no conflict baseline to compare against
                continue

            local_path = _page_local_path(output_dir, page)
            if not local_path.exists():
                continue

            try:
                platform_updated = await self._platform.get_page_updated_at(page.id)
            except Exception as e:
                logger.warning("detect_conflicts: get_page_updated_at(%s) failed: %s", page.id, e)
                continue

            local_updated = _mtime_iso(local_path)

            platform_changed = platform_updated is not None and platform_updated > last_synced
            local_changed = local_updated > last_synced

            if platform_changed and local_changed:
                logger.warning(
                    "Conflict on page %s (local=%s, platform=%s, last_synced=%s)",
                    page.id,
                    local_updated,
                    platform_updated,
                    last_synced,
                )
                conflicts.append(
                    ConflictRecord(
                        page_id=page.id,
                        local_path=str(local_path),
                        platform_updated=platform_updated,
                        local_updated=local_updated,
                    )
                )

        return conflicts

    async def sync_bidirectional(
        self,
        space_id: str,
        output_dir: Path,
        conflict_resolution: str = "platform_wins",
    ) -> SyncReport:
        """Full bidirectional sync with conflict resolution.

        Steps:
        1. Detect conflicts between local files and platform.
        2. Pull non-conflicting platform changes to local.
        3. Push local-only changes (no platform change) back up.
        4. Resolve conflicting pages per policy.

        conflict_resolution options:
            "platform_wins"  — overwrite local file with platform content (default)
            "local_wins"     — push local file content to platform
            "skip"           — leave both sides unchanged, record in report errors
        """
        report = SyncReport()
        state = _load_sync_state(output_dir)
        now = _now_iso()

        # --- Step 1: detect conflicts before pulling ---
        conflicts = await self.detect_conflicts(space_id, output_dir)
        conflict_page_ids = {c.page_id for c in conflicts}

        # --- Step 2 & 3: pull/push non-conflicting pages ---
        try:
            pages = await self._platform.get_hierarchy(space_id)
        except Exception as e:
            report.errors.append(f"get_hierarchy failed: {e}")
            return report

        (output_dir / "objects" / "platform").mkdir(parents=True, exist_ok=True)

        for page in pages:
            if page.id in conflict_page_ids:
                continue  # handled below
            try:
                full_page = await self._platform.get_page(page.id)
                local_path = _page_local_path(output_dir, full_page)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                platform_content = full_page.content or ""

                last_synced = state.get(page.id)
                if local_path.exists() and last_synced is not None:
                    local_updated = _mtime_iso(local_path)
                    if local_updated > last_synced:
                        # Local changed, platform not (or we'd be in conflict) — push local up
                        local_content = local_path.read_text()
                        await self._platform.update_page(page.id, local_content)
                        state[page.id] = now
                        report.pages_updated += 1
                        continue

                if local_path.exists():
                    existing = local_path.read_text()
                    if existing == platform_content:
                        report.pages_skipped += 1
                    else:
                        local_path.write_text(platform_content)
                        state[page.id] = now
                        report.pages_updated += 1
                else:
                    local_path.write_text(platform_content)
                    state[page.id] = now
                    report.pages_created += 1
            except Exception as e:
                report.errors.append(f"pull page {page.id}: {e}")

        # --- Step 4: resolve conflicts ---
        for conflict in conflicts:
            conflict.resolution = conflict_resolution
            local_path = Path(conflict.local_path)
            try:
                if conflict_resolution == "platform_wins":
                    full_page = await self._platform.get_page(conflict.page_id)
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_text(full_page.content or "")
                    state[conflict.page_id] = now
                    report.pages_updated += 1
                elif conflict_resolution == "local_wins":
                    if local_path.exists():
                        local_content = local_path.read_text()
                        await self._platform.update_page(conflict.page_id, local_content)
                        state[conflict.page_id] = now
                        report.pages_updated += 1
                else:  # "skip"
                    report.errors.append(
                        f"Conflict skipped for page {conflict.page_id} "
                        f"(platform={conflict.platform_updated}, local={conflict.local_updated})"
                    )
            except Exception as e:
                report.errors.append(f"conflict resolution for page {conflict.page_id}: {e}")

        _save_sync_state(output_dir, state)
        return report
