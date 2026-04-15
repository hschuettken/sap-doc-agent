"""Doc Sync Agent — pushes scanner output to documentation platform."""

from __future__ import annotations
from pathlib import Path
import yaml
from pydantic import BaseModel, Field
from spec2sphere.doc_platform.base import DocPlatformAdapter
from spec2sphere.scanner.models import ScanResult, ScannedObject
from spec2sphere.scanner.output import render_object_markdown


class SyncReport(BaseModel):
    pages_created: int = 0
    pages_updated: int = 0
    pages_skipped: int = 0
    errors: list[str] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return self.pages_created + self.pages_updated + self.pages_skipped


class DocSyncAgent:
    def __init__(self, doc_platform: DocPlatformAdapter, source_system_name: str = "SAP"):
        self._platform = doc_platform
        self._system_name = source_system_name

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
