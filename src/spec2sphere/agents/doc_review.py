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

from spec2sphere.llm.base import LLMProvider


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
    scope: dict = Field(default_factory=dict)

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

    def review_documentation_set(
        self,
        application_name: str,
        documents: list[dict],
        scope: str = "application",
    ) -> DocumentReview:
        """Review a SET of documents as one application's complete documentation.

        A complete application documentation should cover all application-level
        sections (dev guidelines, BRS, data flow, object docs, master data, runbook)
        across its documents. A single document can contain multiple sections.

        This merges all documents into one combined text and checks whether
        ALL required sections are covered — regardless of which document
        they appear in.

        Args:
            application_name: Name of the application being documented
            documents: List of dicts with 'title' and 'content'
            scope: 'application' (checks sections 2-7) or 'system' (checks section 1)
        """
        # Merge all documents into one combined text, preserving titles as headings
        combined_parts = []
        for doc in documents:
            combined_parts.append(f"# {doc['title']}\n\n{doc['content']}")
        combined_content = "\n\n---\n\n".join(combined_parts)

        # Determine which section types to check based on scope
        scope_def = getattr(self._standard, "scope", None)
        if scope_def and isinstance(scope_def, dict):
            if scope == "system":
                type_ids = scope_def.get("system_level", ["architecture_overview"])
            else:
                type_ids = scope_def.get("application_level", self._standard.get_type_ids())
        else:
            if scope == "system":
                type_ids = ["architecture_overview"]
            else:
                type_ids = [t for t in self._standard.get_type_ids() if t != "architecture_overview"]

        # Collect ALL required sections across all applicable types
        all_required_sections = []
        for type_id in type_ids:
            type_def = self._standard.get_type(type_id)
            if not type_def:
                continue
            for sec in type_def.get("required_sections", []):
                all_required_sections.append(
                    {
                        **sec,
                        "parent_type": type_id,
                        "parent_type_name": type_def.get("name", type_id),
                    }
                )

        # Evaluate all sections against the combined content
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
        covered_types: set[str] = set()

        for req in all_required_sections:
            sec_name = req["name"]
            min_length = req.get("min_content_length", 0)
            should_contain = req.get("should_contain", [])
            should_contain_visual = req.get("should_contain_visual", False)

            sec_max = section_present_pts + min_length_pts + keywords_pts
            if should_contain_visual:
                sec_max += visual_pts
            max_score += sec_max

            section_found, section_content = self._find_section(combined_content, sec_name, req["id"])

            sec = DocumentSection(
                section_id=f"{req['parent_type']}.{req['id']}",
                name=f"{req['parent_type_name']} > {sec_name}",
                found=section_found,
                content=section_content[:500],
                content_length=len(section_content),
            )

            if not section_found:
                sec.score = penalties.get("section_missing", -10)
                sec.issues.append(f"Missing: {sec_name} (expected in {req['parent_type_name']})")
                overall_issues.append(f"Missing: {sec_name}")
            else:
                covered_types.add(req["parent_type"])
                sec.score = section_present_pts
                if len(section_content) >= min_length:
                    sec.score += min_length_pts
                else:
                    sec.score += penalties.get("section_too_short", -3)
                    sec.issues.append(f"Too short ({len(section_content)} chars, need {min_length})")
                if not should_contain or any(kw.lower() in section_content.lower() for kw in should_contain):
                    sec.score += keywords_pts
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

        # Check which document types are completely missing
        missing_types = set(type_ids) - covered_types
        for mt in missing_types:
            type_def = self._standard.get_type(mt)
            if type_def:
                overall_issues.append(f"No coverage at all for: {type_def['name']}")

        percentage = max(0, min(100, round((total_score / max_score * 100) if max_score > 0 else 0, 1)))

        suggestions = []
        if missing_types:
            names = ", ".join(
                self._standard.get_type(t).get("name", t) for t in missing_types if self._standard.get_type(t)
            )
            suggestions.append(f"Documentation has no coverage for: {names}")
        missing_secs = [s for s in sections if not s.found]
        if missing_secs:
            suggestions.append(f"Add {len(missing_secs)} missing sections — see details above")
        short_secs = [s for s in sections if s.found and any("Too short" in i for i in s.issues)]
        if short_secs:
            suggestions.append(f"Expand {len(short_secs)} sections that are too brief")

        return DocumentReview(
            document_title=f"Documentation Set: {application_name}",
            document_type=f"set:{scope}",
            document_type_name=f"{'System' if scope == 'system' else 'Application'} Documentation Set",
            total_score=round(total_score, 1),
            max_score=round(max_score, 1),
            percentage=percentage,
            sections=sections,
            overall_issues=overall_issues,
            suggestions=suggestions,
        )

    def review_all(self, documents: list[dict]) -> ReviewReport:
        """Review multiple documents individually.

        Each document is a dict with 'title' and 'content', optionally 'type'.
        For holistic application-level review, use review_documentation_set() instead.
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

    async def parse_client_standard(self, title: str, content: str) -> StandardDefinition:
        """Parse a client's documentation standard from unstructured text.

        Takes the raw text of a client's documentation guidelines (extracted
        from PDF, Confluence, or Word) and converts it into a structured
        StandardDefinition that can be used for review and gap analysis.

        Works in two modes:
        - With LLM: uses the model to extract structured rules from the text
        - Without LLM: uses heuristic section/keyword extraction (less accurate)
        """
        if self._llm and self._llm.is_available():
            return await self._parse_standard_with_llm(title, content)
        return self._parse_standard_heuristic(title, content)

    async def _parse_standard_with_llm(self, title: str, content: str) -> StandardDefinition:
        """Use LLM to extract structured standard from unstructured text."""
        schema = {
            "type": "object",
            "properties": {
                "document_types": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "required_sections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "name": {"type": "string"},
                                        "min_content_length": {"type": "integer"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }

        system_prompt = (
            "You are an SAP documentation standards expert. Extract the documentation "
            "requirements from the following client guidelines into a structured format. "
            "Identify what document types they require (e.g., architecture docs, technical specs, "
            "runbooks) and what sections each type must contain. Map each to a standard ID. "
            "Use these IDs where applicable: architecture_overview, development_guidelines, "
            "business_requirements, data_flow, object_documentation, master_data, operational_runbook."
        )

        result = await self._llm.generate_json(
            f"Parse this documentation standard:\n\n{content[:8000]}",
            schema=schema,
            system=system_prompt,
            tier="doc_review",
        )

        if result and "document_types" in result:
            return StandardDefinition(
                name=f"Client Standard: {title}",
                version="parsed",
                description=f"Auto-parsed from: {title}",
                document_types=result["document_types"],
                scoring=self._standard.scoring,  # Inherit scoring from Horvath
            )

        # Fallback to heuristic if LLM fails
        return self._parse_standard_heuristic(title, content)

    def _parse_standard_heuristic(self, title: str, content: str) -> StandardDefinition:
        """Extract standard definition from text using heuristics.

        Looks for heading patterns and requirement keywords to build
        a rough standard definition. Less accurate than LLM but works
        without any external service.
        """
        content_lower = content.lower()
        document_types = []

        # Map of keywords to standard document types
        type_signals = {
            "architecture_overview": [
                "system landscape",
                "architecture",
                "overview",
                "high-level",
                "integration",
                "data flow map",
            ],
            "development_guidelines": [
                "naming convention",
                "coding standard",
                "development guideline",
                "transport",
                "code review",
                "best practice",
            ],
            "business_requirements": [
                "business requirement",
                "brs",
                "functional spec",
                "acceptance criteria",
                "business objective",
            ],
            "data_flow": [
                "data flow",
                "etl",
                "process chain",
                "extraction",
                "transformation",
                "loading",
                "source to target",
            ],
            "object_documentation": [
                "object documentation",
                "technical spec",
                "adso",
                "infoprovider",
                "table definition",
                "view definition",
            ],
            "master_data": [
                "master data",
                "hierarchy",
                "dimension",
                "characteristic",
                "attribute",
                "text table",
            ],
            "operational_runbook": [
                "runbook",
                "operation",
                "monitoring",
                "incident",
                "escalation",
                "recovery",
                "support procedure",
            ],
        }

        # Detect which types the client standard mentions
        for type_id, keywords in type_signals.items():
            matches = [kw for kw in keywords if kw in content_lower]
            if len(matches) >= 2:  # At least 2 keyword matches
                # Try to extract required sections from nearby headings
                sections = self._extract_sections_near_keywords(content, matches)
                type_name_map = {
                    "architecture_overview": "Architecture Overview",
                    "development_guidelines": "Development Guidelines",
                    "business_requirements": "Business Requirements",
                    "data_flow": "Data Flow Documentation",
                    "object_documentation": "Object Documentation",
                    "master_data": "Master Data Documentation",
                    "operational_runbook": "Operational Runbook",
                }
                document_types.append(
                    {
                        "id": type_id,
                        "name": type_name_map.get(type_id, type_id),
                        "required_sections": sections,
                    }
                )

        return StandardDefinition(
            name=f"Client Standard: {title}",
            version="heuristic",
            description=f"Auto-parsed (heuristic) from: {title}",
            document_types=document_types,
            scoring=self._standard.scoring,
        )

    def _extract_sections_near_keywords(self, content: str, keywords: list[str]) -> list[dict]:
        """Extract section headings near keyword matches as required sections."""
        sections = []
        seen_ids: set[str] = set()
        # Find all markdown headings
        headings = re.findall(r"^#{1,4}\s+(.+)", content, re.MULTILINE)
        for heading in headings:
            heading_lower = heading.lower().strip()
            # If heading relates to any keyword, treat it as a required section
            for kw in keywords:
                if kw in heading_lower or any(w in heading_lower for w in kw.split()):
                    sec_id = re.sub(r"[^a-z0-9]+", "_", heading_lower).strip("_")[:30]
                    if sec_id not in seen_ids:
                        seen_ids.add(sec_id)
                        sections.append(
                            {
                                "id": sec_id,
                                "name": heading.strip(),
                                "min_content_length": 50,
                            }
                        )
                    break
        return sections

    def review_against_both_standards(
        self,
        application_name: str,
        documents: list[dict],
        client_standard: StandardDefinition,
        scope: str = "application",
    ) -> dict:
        """Review documentation against BOTH Horvath and client standards.

        Returns a dict with:
        - horvath_review: DocumentReview against Horvath standard
        - client_review: DocumentReview against client standard
        - gap_analysis: where client standard is weaker than Horvath
        - combined_issues: all unique issues from both reviews
        """
        # Create a temp agent with client standard for review
        client_agent = DocReviewAgent(client_standard, llm=self._llm)

        horvath_review = self.review_documentation_set(application_name, documents, scope)
        client_review = client_agent.review_documentation_set(application_name, documents, scope)
        gap_analysis = self.compare_standards(client_standard)

        # Combine unique issues
        all_issues = set(horvath_review.overall_issues) | set(client_review.overall_issues)

        return {
            "horvath_review": horvath_review,
            "client_review": client_review,
            "gap_analysis": gap_analysis,
            "combined_issues": sorted(all_issues),
            "horvath_score": horvath_review.percentage,
            "client_score": client_review.percentage,
        }

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
