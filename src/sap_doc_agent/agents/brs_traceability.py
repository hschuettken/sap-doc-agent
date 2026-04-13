"""BRS Traceability Agent — maps requirements to SAP object implementations."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from sap_doc_agent.scanner.models import ScanResult


class Requirement(BaseModel):
    req_id: str
    title: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)


class TraceLink(BaseModel):
    req_id: str
    object_id: str
    match_type: str  # "exact" or "keyword"
    confidence: float  # 0.0 – 1.0


class TraceReport(BaseModel):
    requirements: list[Requirement]
    links: list[TraceLink]
    unlinked_requirements: list[str]
    orphan_objects: list[str]


class BRSTraceabilityAgent:
    """Traces business requirements to SAP implementation objects."""

    def load_requirements(self, path: Path) -> list[Requirement]:
        """Load requirements from a YAML file (list of requirement dicts)."""
        with open(path) as f:
            raw = yaml.safe_load(f)
        return [Requirement.model_validate(item) for item in raw]

    def trace(self, requirements: list[Requirement], result: ScanResult) -> TraceReport:
        """
        Trace requirements to objects in the ScanResult.

        Matching strategy:
        - exact: a keyword matches the object_id exactly (confidence=1.0)
        - keyword: a keyword appears in the object name or description (confidence=0.7)
        """
        links: list[TraceLink] = []
        linked_req_ids: set[str] = set()
        linked_object_ids: set[str] = set()

        for req in requirements:
            for kw in req.keywords:
                kw_lower = kw.lower()
                for obj in result.objects:
                    # Exact match: keyword equals object_id (case-insensitive)
                    if kw_lower == obj.object_id.lower():
                        links.append(
                            TraceLink(
                                req_id=req.req_id,
                                object_id=obj.object_id,
                                match_type="exact",
                                confidence=1.0,
                            )
                        )
                        linked_req_ids.add(req.req_id)
                        linked_object_ids.add(obj.object_id)
                    # Keyword match: keyword appears in name or description
                    elif kw_lower in obj.name.lower() or kw_lower in obj.description.lower():
                        links.append(
                            TraceLink(
                                req_id=req.req_id,
                                object_id=obj.object_id,
                                match_type="keyword",
                                confidence=0.7,
                            )
                        )
                        linked_req_ids.add(req.req_id)
                        linked_object_ids.add(obj.object_id)

        unlinked_requirements = [req.req_id for req in requirements if req.req_id not in linked_req_ids]
        all_object_ids = {obj.object_id for obj in result.objects}
        orphan_objects = sorted(all_object_ids - linked_object_ids)

        return TraceReport(
            requirements=requirements,
            links=links,
            unlinked_requirements=unlinked_requirements,
            orphan_objects=orphan_objects,
        )
