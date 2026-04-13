"""Document Review Agent — evaluates documentation against standards.

This is the core product: clients hand us their SAP documentation
(Confluence pages, PDFs, uploaded files) and we evaluate it against
Horvath best-practice and their own standards.

The agent:
1. Ingests documents from multiple sources (text, file, URL)
2. Classifies each document by type (BRS, data flow, object doc, etc.)
3. Evaluates against the applicable standard
4. Generates a detailed review report with scores and suggestions
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
import yaml

from sap_doc_agent.llm.base import LLMProvider


class DocumentSection(BaseModel):
    """A section found (or expected) in a document."""

    section_id: str
    name: str
    found: bool = False
    content: str = ""
    content_length: int = 0
    keywords_found: list[str] = Field(default_factory=list)
    has_visual: bool = False
    score: float = 0.0
    issues: list[str] = Field(default_factory=list)


class DocumentReview(BaseModel):
    """Review result for a single document."""

    document_title: str
    document_type: str
    document_type_name: str = ""
    total_score: float = 0.0
    max_score: float = 0.0
    percentage: float = 0.0
    sections: list[DocumentSection] = Field(default_factory=list)
    overall_issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    classification_confidence: float = 1.0


class ReviewReport(BaseModel):
    """Aggregated report across multiple documents."""

    standard_name: str
    standard_version: str = ""
    documents_reviewed: int = 0
    reviews: list[DocumentReview] = Field(default_factory=list)
    average_score: float = 0.0
    worst_documents: list[str] = Field(default_factory=list)
    most_common_issues: list[str] = Field(default_factory=list)
    gap_analysis: list[str] = Field(default_factory=list)

    def compute_summary(self) -> None:
        """Compute aggregate stats from individual reviews."""
        if not self.reviews:
            return
        self.documents_reviewed = len(self.reviews)
        scores = [r.percentage for r in self.reviews]
        self.average_score = round(sum(scores) / len(scores), 1)
        # Worst documents (below 50%)
        self.worst_documents = [
            f"{r.document_title} ({r.percentage}%)"
            for r in sorted(self.reviews, key=lambda r: r.percentage)
            if r.percentage < 50
        ]
        # Most common issues
        all_issues: dict[str, int] = {}
        for r in self.reviews:
            for issue in r.overall_issues:
                all_issues[issue] = all_issues.get(issue, 0) + 1
        self.most_common_issues = [
            f"{issue} ({count}x)" for issue, count in sorted(all_issues.items(), key=lambda x: -x[1])[:10]
        ]


class StandardDefinition(BaseModel):
    """Parsed documentation standard definition."""

    name: str
    version: str = ""
    description: str = ""
    document_types: list[dict] = Field(default_factory=list)
    scoring: dict = Field(default_factory=dict)

    def get_type(self, type_id: str) -> Optional[dict]:
        for dt in self.document_types:
            if dt["id"] == type_id:
                return dt
        return None

    def get_type_ids(self) -> list[str]:
        return [dt["id"] for dt in self.document_types]


def load_documentation_standard(path: Path) -> StandardDefinition:
    """Load a documentation standard from YAML."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return StandardDefinition.model_validate(raw)


class DocReviewAgent:
    """Reviews documents against a documentation standard."""

    def __init__(
        self,
        standard: StandardDefinition,
        llm: Optional[LLMProvider] = None,
    ):
        self._standard = standard
        self._llm = llm

    def classify_document(self, title: str, content: str) -> tuple[str, float]:
        """Classify a document into one of the standard's document types.

        Returns (type_id, confidence) based on keyword matching.
        """
        scores: dict[str, float] = {}
        title_lower = title.lower()
        content_lower = content.lower()[:3000]  # First 3000 chars for efficiency

        # Keyword patterns for each document type
        type_keywords = {
            "architecture_overview": [
                "architecture",
                "landscape",
                "overview",
                "system landscape",
                "data flow map",
                "layer",
                "integration",
                "high-level",
            ],
            "development_guidelines": [
                "guideline",
                "naming convention",
                "coding standard",
                "development",
                "best practice",
                "transport",
                "code review",
            ],
            "business_requirements": [
                "requirement",
                "brs",
                "business requirement",
                "acceptance criteria",
                "business objective",
                "scope",
                "stakeholder",
            ],
            "data_flow": [
                "data flow",
                "process chain",
                "transformation",
                "etl",
                "source to target",
                "extraction",
                "loading",
            ],
            "object_documentation": [
                "adso",
                "infoprovider",
                "view",
                "table",
                "infocube",
                "composite",
                "datasource",
                "technical name",
            ],
            "master_data": [
                "master data",
                "hierarchy",
                "attribute",
                "dimension",
                "infoobject",
                "characteristic",
                "text table",
            ],
            "operational_runbook": [
                "runbook",
                "operation",
                "monitoring",
                "daily check",
                "incident",
                "escalation",
                "recovery",
                "support",
            ],
        }

        for type_id, keywords in type_keywords.items():
            score = 0.0
            for kw in keywords:
                if kw in title_lower:
                    score += 3.0  # Title match worth more
                if kw in content_lower:
                    score += 1.0
            scores[type_id] = score

        if not scores or max(scores.values()) == 0:
            return "object_documentation", 0.3  # Default fallback

        best_type = max(scores, key=scores.get)
        # Normalize confidence to 0-1
        max_score = max(scores.values())
        total_score = sum(scores.values())
        confidence = min(max_score / max(total_score * 0.5, 1), 1.0)
        return best_type, round(confidence, 2)

    def review_document(
        self,
        title: str,
        content: str,
        doc_type: Optional[str] = None,
    ) -> DocumentReview:
        """Review a single document against the standard.

        If doc_type is not provided, it will be auto-classified.
        """
        if doc_type:
            confidence = 1.0
        else:
            doc_type, confidence = self.classify_document(title, content)

        type_def = self._standard.get_type(doc_type)
        if not type_def:
            return DocumentReview(
                document_title=title,
                document_type=doc_type,
                overall_issues=["Unknown document type"],
            )

        scoring = self._standard.scoring
        section_present_pts = scoring.get("section_present", 5)
        min_length_pts = scoring.get("section_min_length_met", 3)
        keywords_pts = scoring.get("section_contains_keywords", 2)
        visual_pts = scoring.get("section_has_visual", 3)
        penalties = scoring.get("penalties", {})

        sections: list[DocumentSection] = []
        total_score = 0.0
        max_score = 0.0
        overall_issues: list[str] = []
        content_lower = content.lower()

        for req_section in type_def.get("required_sections", []):
            sec_id = req_section["id"]
            sec_name = req_section["name"]
            min_length = req_section.get("min_content_length", 0)
            should_contain = req_section.get("should_contain", [])
            should_contain_visual = req_section.get("should_contain_visual", False)

            # Calculate max possible score for this section
            sec_max = section_present_pts + min_length_pts + keywords_pts
            if should_contain_visual:
                sec_max += visual_pts
            max_score += sec_max

            # Check if section exists in content (by heading or keywords)
            section_found, section_content = self._find_section(content, sec_name, sec_id)

            sec = DocumentSection(
                section_id=sec_id,
                name=sec_name,
                found=section_found,
                content=section_content[:500],
                content_length=len(section_content),
            )

            if not section_found:
                sec.score = penalties.get("section_missing", -10)
                sec.issues.append(f"Missing required section: {sec_name}")
                overall_issues.append(f"Missing: {sec_name}")
            else:
                sec.score = section_present_pts

                # Check minimum length
                if len(section_content) >= min_length:
                    sec.score += min_length_pts
                else:
                    sec.score += penalties.get("section_too_short", -3)
                    sec.issues.append(f"Too short ({len(section_content)} chars, need {min_length})")

                # Check keywords
                found_kw = [kw for kw in should_contain if kw.lower() in section_content.lower()]
                sec.keywords_found = found_kw
                if found_kw or not should_contain:
                    sec.score += keywords_pts

                # Check visuals
                if should_contain_visual:
                    has_visual = bool(
                        re.search(
                            r"!\[.*\]\(.*\)|<img|diagram|figure|screenshot|\.png|\.jpg|flowchart|mermaid|```",
                            section_content,
                            re.IGNORECASE,
                        )
                    )
                    sec.has_visual = has_visual
                    if has_visual:
                        sec.score += visual_pts
                    else:
                        sec.score += penalties.get("no_visuals_where_expected", -5)
                        sec.issues.append("Expected visual/diagram not found")

            total_score += sec.score
            sections.append(sec)

        # Compute percentage (clamped to 0-100)
        percentage = max(0, min(100, round((total_score / max_score * 100) if max_score > 0 else 0, 1)))

        # Generate suggestions
        suggestions = self._generate_suggestions(sections, type_def)

        return DocumentReview(
            document_title=title,
            document_type=doc_type,
            document_type_name=type_def.get("name", doc_type),
            total_score=round(total_score, 1),
            max_score=round(max_score, 1),
            percentage=percentage,
            sections=sections,
            overall_issues=overall_issues,
            suggestions=suggestions,
            classification_confidence=confidence,
        )

    def review_all(self, documents: list[dict]) -> ReviewReport:
        """Review multiple documents.

        Each document is a dict with 'title' and 'content', optionally 'type'.
        """
        reviews = []
        for doc in documents:
            review = self.review_document(
                title=doc["title"],
                content=doc["content"],
                doc_type=doc.get("type"),
            )
            reviews.append(review)

        report = ReviewReport(
            standard_name=self._standard.name,
            standard_version=self._standard.version,
            reviews=reviews,
        )
        report.compute_summary()
        return report

    def compare_standards(
        self,
        client_standard: StandardDefinition,
    ) -> list[str]:
        """Compare a client standard against Horvath best-practice.

        Returns list of gaps where the client standard is weaker.
        """
        gaps = []
        horvath_type_ids = set(self._standard.get_type_ids())
        client_type_ids = set(client_standard.get_type_ids())

        # Missing document types
        for missing in horvath_type_ids - client_type_ids:
            type_def = self._standard.get_type(missing)
            gaps.append(f"Client standard missing document type: {type_def['name']}")

        # Compare sections within shared types
        for type_id in horvath_type_ids & client_type_ids:
            h_type = self._standard.get_type(type_id)
            c_type = client_standard.get_type(type_id)
            h_sections = {s["id"] for s in h_type.get("required_sections", [])}
            c_sections = {s["id"] for s in c_type.get("required_sections", [])}
            for missing_sec in h_sections - c_sections:
                h_sec = next(s for s in h_type["required_sections"] if s["id"] == missing_sec)
                gaps.append(f"{h_type['name']}: client standard missing section '{h_sec['name']}'")

        return gaps

    def _find_section(self, content: str, section_name: str, section_id: str) -> tuple[bool, str]:
        """Find a section in document content by heading match.

        Returns (found, section_content).
        """
        escaped = re.escape(section_name)
        # Use MULTILINE so ^ matches line starts; DOTALL so . matches newlines in capture
        # Pattern: markdown heading (1-4 #) followed by section name, captures until next heading
        patterns = [
            rf"^#{{1,4}}\s*{escaped}[^\n]*\n(.*?)(?=^#{{1,4}}\s|\Z)",
            rf"^\*\*{escaped}\*\*[^\n]*\n(.*?)(?=^\*\*|\n^#{{1,4}}\s|\Z)",
            rf"^{escaped}\n[-=]+\n(.*?)(?=^\S+\n[-=]+|\Z)",
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            if match:
                return True, match.group(1).strip()

        # Fallback: check if key phrases from section_name appear in content
        name_words = section_name.lower().split()
        if len(name_words) >= 2:
            # At least 2 significant words from the section name appear together
            key_words = [w for w in name_words if len(w) > 3]
            if key_words and all(w in content.lower() for w in key_words[:2]):
                # Found keywords but not as a proper section
                return True, ""  # Found but can't extract content cleanly

        return False, ""

    def _generate_suggestions(self, sections: list[DocumentSection], type_def: dict) -> list[str]:
        """Generate improvement suggestions based on review findings."""
        suggestions = []
        missing = [s for s in sections if not s.found]
        short = [s for s in sections if s.found and s.issues and any("Too short" in i for i in s.issues)]
        no_visual = [s for s in sections if s.found and any("visual" in i.lower() for i in s.issues)]

        if missing:
            names = ", ".join(s.name for s in missing)
            suggestions.append(f"Add these missing sections: {names}")

        if short:
            for s in short:
                suggestions.append(f"Expand '{s.name}' — add more detail about {s.name.lower()}")

        if no_visual:
            for s in no_visual:
                suggestions.append(f"Add a diagram or screenshot to '{s.name}'")

        if not missing and not short and not no_visual:
            suggestions.append("Document meets all structural requirements. Consider a content quality review.")

        return suggestions
