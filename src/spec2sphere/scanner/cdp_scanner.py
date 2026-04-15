"""CDP-based SAP Datasphere scanner.

Drives the DSP UI via Chrome DevTools Protocol to extract rich metadata
that the REST API doesn't provide: SQL definitions, column lists,
lineage graphs, and screenshots.

This scanner is designed to be called with pre-extracted JavaScript results.
The actual CDP/Playwright interaction happens at a higher level (CLI or
interactive session). This module converts raw extraction results into
the canonical ScannedObject/ScanResult model.

Design:
- extract_* methods define WHAT JavaScript to run in the DSP UI
- process_* methods convert raw JS results into ScannedObjects
- scan_from_extractions() merges everything into a ScanResult
"""

from __future__ import annotations

import logging
import re

from spec2sphere.scanner.models import (
    Dependency,
    DependencyType,
    ObjectType,
    ScanResult,
    ScannedObject,
)

logger = logging.getLogger(__name__)

# JavaScript snippets for extracting data from the DSP UI
JS_EXTRACT_REPO_OBJECTS = """
() => {
    const rows = document.querySelectorAll('tr[data-sap-ui]');
    const objects = [];
    for (const row of rows) {
        const cells = row.querySelectorAll('td');
        if (cells.length < 8) continue;
        const texts = Array.from(cells).map(c => c.textContent.trim());
        if (texts.some(t => t.includes('data-space-management'))) continue;
        objects.push({
            business_name: texts[1] || '',
            technical_name: texts[2] || '',
            dsp_type: texts[3] || '',
            space: texts[4] || '',
            folder: texts[5] || '',
            status: texts[6] || '',
            last_modified: texts[7] || '',
        });
    }
    return objects;
}
"""

JS_EXTRACT_SQL = """
() => {
    const editor = document.querySelector('.ace_editor');
    if (!editor) return null;
    const aceEditor = ace.edit(editor);
    return aceEditor ? aceEditor.getValue() : null;
}
"""

JS_EXTRACT_COLUMNS = """
() => {
    // Extract columns from the output panel or columns side panel
    const columnRows = document.querySelectorAll('[class*="column"] tr, [class*="output"] tr');
    const columns = [];
    for (const row of columnRows) {
        const cells = row.querySelectorAll('td, th');
        if (cells.length >= 2) {
            columns.push({
                name: cells[0]?.textContent?.trim() || '',
                type: cells[1]?.textContent?.trim() || '',
                description: cells[2]?.textContent?.trim() || '',
            });
        }
    }
    return columns;
}
"""

JS_EXTRACT_LINEAGE = """
() => {
    // Extract lineage from the impact/lineage analysis view
    const nodes = document.querySelectorAll('[class*="lineage"] [class*="node"], [class*="graph"] [class*="node"]');
    const result = { upstream: [], downstream: [] };
    for (const node of nodes) {
        const name = node.textContent?.trim();
        const isUpstream = node.closest('[class*="upstream"], [class*="source"]');
        if (isUpstream) {
            result.upstream.push(name);
        } else {
            result.downstream.push(name);
        }
    }
    return result;
}
"""

# DSP type string to ObjectType mapping
DSP_UI_TYPE_MAP: dict[str, ObjectType] = {
    "View (Fact)": ObjectType.VIEW,
    "View (Relational Dataset)": ObjectType.VIEW,
    "View (Text)": ObjectType.VIEW,
    "View (Dimension)": ObjectType.VIEW,
    "Analytic Model (Cube)": ObjectType.VIEW,
    "Analytic Model": ObjectType.VIEW,
    "Local Table (Relational Dataset)": ObjectType.TABLE,
    "Local Table (Text)": ObjectType.TABLE,
    "Local Table": ObjectType.TABLE,
    "Remote Table": ObjectType.TABLE,
    "Data Flow": ObjectType.TRANSFORMATION,
    "Transformation Flow": ObjectType.TRANSFORMATION,
    "Replication Flow": ObjectType.DATA_SOURCE,
    "Task Chain": ObjectType.PROCESS_CHAIN,
}


def infer_layer(technical_name: str) -> str:
    """Infer architecture layer from naming convention."""
    if re.match(r"^0?1", technical_name):
        return "raw"
    if re.match(r"^0?2", technical_name):
        return "harmonized"
    if re.match(r"^0?3", technical_name):
        return "mart"
    return ""


def map_dsp_type(dsp_type: str) -> ObjectType:
    """Map DSP UI type string to ObjectType."""
    return DSP_UI_TYPE_MAP.get(dsp_type, ObjectType.OTHER)


class DSPCDPScanner:
    """Converts CDP-extracted data into the canonical scanner model.

    This class doesn't drive the browser itself — it processes
    the results of JavaScript extractions run via CDP/Playwright.
    """

    def __init__(self, source_system: str = "DSP", tenant_url: str = ""):
        self._source_system = source_system
        self._tenant_url = tenant_url

    def process_repo_objects(self, raw_objects: list[dict]) -> list[ScannedObject]:
        """Convert raw Repository Explorer extraction to ScannedObjects."""
        objects = []
        for raw in raw_objects:
            tech_name = raw.get("technical_name", "")
            space = raw.get("space", "")
            if not tech_name:
                continue
            # Skip SAP standard objects
            if tech_name.startswith("SAP."):
                continue

            dsp_type = raw.get("dsp_type", "")
            obj = ScannedObject(
                object_id=f"{space}.{tech_name}" if space else tech_name,
                object_type=map_dsp_type(dsp_type),
                name=tech_name,
                description=raw.get("business_name", ""),
                package=space,
                source_system=self._source_system,
                technical_name=tech_name,
                layer=infer_layer(tech_name),
                metadata={
                    "business_name": raw.get("business_name", ""),
                    "dsp_type": dsp_type,
                    "space": space,
                    "folder": raw.get("folder", ""),
                    "status": raw.get("status", ""),
                    "last_modified": raw.get("last_modified", ""),
                },
            )
            objects.append(obj)
        return objects

    def enrich_with_sql(self, obj: ScannedObject, sql: str) -> None:
        """Add SQL definition to a scanned object."""
        if sql:
            obj.source_code = sql
            obj.metadata["has_sql"] = True

    def enrich_with_columns(self, obj: ScannedObject, columns: list[dict]) -> None:
        """Add column definitions to a scanned object."""
        if columns:
            obj.metadata["columns"] = columns

    def enrich_with_lineage(self, obj: ScannedObject, lineage: dict) -> list[Dependency]:
        """Add lineage information and return dependencies."""
        deps = []
        upstream = lineage.get("upstream", [])
        downstream = lineage.get("downstream", [])
        obj.metadata["lineage_upstream"] = upstream
        obj.metadata["lineage_downstream"] = downstream

        for up_name in upstream:
            deps.append(
                Dependency(
                    source_id=obj.object_id,
                    target_id=up_name,  # Will be resolved by orchestrator
                    dependency_type=DependencyType.READS_FROM,
                )
            )
        for down_name in downstream:
            deps.append(
                Dependency(
                    source_id=down_name,
                    target_id=obj.object_id,
                    dependency_type=DependencyType.READS_FROM,
                )
            )
        return deps

    def enrich_with_screenshot(self, obj: ScannedObject, screenshot_path: str) -> None:
        """Record a screenshot path for the object."""
        screenshots = obj.metadata.get("screenshots", [])
        screenshots.append(screenshot_path)
        obj.metadata["screenshots"] = screenshots

    def build_result(
        self,
        objects: list[ScannedObject],
        dependencies: list[Dependency] | None = None,
    ) -> ScanResult:
        """Build a ScanResult from processed objects."""
        return ScanResult(
            source_system=self._source_system,
            objects=objects,
            dependencies=dependencies or [],
        )

    def scan_from_extractions(
        self,
        repo_objects: list[dict],
        sql_by_id: dict[str, str] | None = None,
        columns_by_id: dict[str, list[dict]] | None = None,
        lineage_by_id: dict[str, dict] | None = None,
        screenshots_by_id: dict[str, list[str]] | None = None,
    ) -> ScanResult:
        """Build a complete ScanResult from all extraction data.

        This is the main entry point — takes raw extraction results
        and produces a fully enriched ScanResult.
        """
        objects = self.process_repo_objects(repo_objects)
        all_deps: list[Dependency] = []

        for obj in objects:
            if sql_by_id and obj.object_id in sql_by_id:
                self.enrich_with_sql(obj, sql_by_id[obj.object_id])
            if columns_by_id and obj.object_id in columns_by_id:
                self.enrich_with_columns(obj, columns_by_id[obj.object_id])
            if lineage_by_id and obj.object_id in lineage_by_id:
                deps = self.enrich_with_lineage(obj, lineage_by_id[obj.object_id])
                all_deps.extend(deps)
            if screenshots_by_id and obj.object_id in screenshots_by_id:
                for path in screenshots_by_id[obj.object_id]:
                    self.enrich_with_screenshot(obj, path)

        return self.build_result(objects, all_deps)

    @staticmethod
    def get_js_snippets() -> dict[str, str]:
        """Return all JavaScript extraction snippets for reference."""
        return {
            "repo_objects": JS_EXTRACT_REPO_OBJECTS,
            "sql": JS_EXTRACT_SQL,
            "columns": JS_EXTRACT_COLUMNS,
            "lineage": JS_EXTRACT_LINEAGE,
        }
