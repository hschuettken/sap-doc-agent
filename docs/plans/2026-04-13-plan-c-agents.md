# Plan C: Agents — Doc Sync, QA, Code Quality, BRS, Reports

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the six Python agents that sync documentation, validate quality, audit code, trace requirements, and generate reports with sitemaps for M365 Copilot.

**Architecture:** Each agent is a standalone async class that takes the shared components (LLMProvider, DocPlatformAdapter, GitBackend) from AppConfig. Agents operate on ScanResults and the doc platform. Rule-based checks work without LLM; LLM-enhanced checks are conditional on `llm.is_available()`.

**Tech Stack:** Python 3.12, pydantic, httpx, jinja2 (reports), pyyaml (standards), pytest

---

## File Structure

```
src/sap_doc_agent/
├── agents/
│   ├── __init__.py
│   ├── doc_sync.py          # Git ↔ Doc Platform sync
│   ├── doc_qa.py             # Documentation quality checks
│   ├── code_quality.py       # ABAP + DSP code audit
│   ├── brs_traceability.py   # Requirements ↔ implementation mapping
│   └── report_generator.py   # Reports + sitemap.xml
│
tests/
├── test_doc_sync.py
├── test_doc_qa.py
├── test_code_quality.py
├── test_brs_traceability.py
└── test_report_generator.py
```

---

### Task 1: Doc Sync Agent

**Files:**
- Create: `src/sap_doc_agent/agents/__init__.py`
- Create: `src/sap_doc_agent/agents/doc_sync.py`
- Create: `tests/test_doc_sync.py`

The Doc Sync agent pushes scanner output from Git/local to the documentation platform, mapping the folder structure to the platform's hierarchy.

**`doc_sync.py`:**
- Class `DocSyncAgent(doc_platform: DocPlatformAdapter, source_system_name: str)`
- `async sync_scan_result(result: ScanResult) -> SyncReport`:
  - Creates a space/book for the source system (or finds existing)
  - Groups objects by layer → creates chapter/parent per layer
  - Creates/updates a page per object using `render_object_markdown()`
  - Returns a `SyncReport` with counts (created, updated, skipped, errors)
- `async sync_from_output_dir(output_dir: Path) -> SyncReport`:
  - Reads markdown files from `output_dir/objects/` tree
  - Parses YAML frontmatter to extract metadata
  - Syncs each to the doc platform
- `SyncReport(BaseModel)`: pages_created (int), pages_updated (int), pages_skipped (int), errors (list[str])

**`tests/test_doc_sync.py`:**
- Test sync creates space for source system
- Test sync creates pages for objects
- Test sync groups by layer (creates chapters)
- Test SyncReport tracks counts
- Test sync_from_output_dir reads markdown files
- Use mock DocPlatformAdapter (or respx-mocked BookStack)

---

### Task 2: Doc QA Agent

**Files:**
- Create: `src/sap_doc_agent/agents/doc_qa.py`
- Create: `tests/test_doc_qa.py`

The Doc QA agent validates documentation against quality standards.

**`doc_qa.py`:**
- `QualityStandard(BaseModel)`:
  - `name` (str)
  - `rules` (list[QualityRule])
- `QualityRule(BaseModel)`:
  - `id` (str), `name` (str), `severity` (literal "critical"/"important"/"minor")
  - `check_type` (literal "field_required"/"min_length"/"pattern"/"naming_convention"/"custom")
  - `field` (Optional[str]) — which frontmatter field to check
  - `min_length` (Optional[int])
  - `pattern` (Optional[str]) — regex
  - `message` (str) — human-readable violation message
- `QualityIssue(BaseModel)`:
  - `object_id` (str), `rule_id` (str), `severity` (str), `message` (str), `field` (Optional[str])
- `QAReport(BaseModel)`:
  - `standard_name` (str), `objects_checked` (int), `issues` (list[QualityIssue])
  - `score` (float) — percentage of checks passed
  - `by_severity` property → dict counting critical/important/minor
- `DocQAAgent(standards: list[QualityStandard], llm: Optional[LLMProvider] = None)`
- `check_object(obj: ScannedObject) -> list[QualityIssue]`:
  - Runs all rules against the object
  - field_required: checks if field is non-empty
  - min_length: checks field length
  - pattern: regex match on field value
  - naming_convention: checks object name matches expected prefix for its layer
- `check_all(result: ScanResult) -> QAReport`:
  - Runs check_object on all objects, aggregates into QAReport
- `load_standard(path: Path) -> QualityStandard`:
  - Loads a YAML standard definition file

**`tests/test_doc_qa.py`:**
- Test field_required catches missing description
- Test min_length catches short descriptions
- Test naming_convention catches wrong prefix
- Test check_all produces QAReport with correct score
- Test score calculation (passed / total)
- Test load_standard from YAML
- Test multiple standards combined

---

### Task 3: Code Quality Agent

**Files:**
- Create: `src/sap_doc_agent/agents/code_quality.py`
- Create: `tests/test_code_quality.py`

Rule-based ABAP and DSP code quality checks.

**`code_quality.py`:**
- `CodeIssue(BaseModel)`:
  - `object_id` (str), `rule` (str), `severity` (str), `message` (str), `line` (Optional[int])
- `CodeQualityAgent()`
- `check_object(obj: ScannedObject) -> list[CodeIssue]`:
  - Only runs if obj.source_code is non-empty
  - Rules (each a private method):
    - `_check_select_star`: regex for `SELECT *` (not `SELECT * INTO`)
    - `_check_hardcoded_client`: regex for `SY-MANDT` or `= '000'`/`= '100'` etc
    - `_check_missing_where`: regex for `SELECT ... FROM ... ` without `WHERE`
    - `_check_magic_numbers`: finds hardcoded dates (8-digit numbers starting with 20)
    - `_check_empty_catch`: finds empty CATCH blocks
    - `_check_nested_select`: finds SELECT inside LOOP
- `check_all(result: ScanResult) -> list[CodeIssue]`:
  - Runs check_object on all objects with source code

**`tests/test_code_quality.py`:**
- Test SELECT * detected
- Test hardcoded client detected
- Test missing WHERE detected
- Test clean code passes all checks
- Test check_all aggregates across objects
- Test objects without source_code are skipped

---

### Task 4: BRS Traceability Agent

**Files:**
- Create: `src/sap_doc_agent/agents/brs_traceability.py`
- Create: `tests/test_brs_traceability.py`

Maps business requirements to scanned implementations.

**`brs_traceability.py`:**
- `Requirement(BaseModel)`:
  - `req_id` (str), `title` (str), `description` (str), `keywords` (list[str] = [])
- `TraceLink(BaseModel)`:
  - `req_id` (str), `object_id` (str), `match_type` (literal "exact"/"keyword"/"manual")
  - `confidence` (float, 0.0-1.0)
- `TraceReport(BaseModel)`:
  - `requirements` (list[Requirement])
  - `links` (list[TraceLink])
  - `unlinked_requirements` (list[str]) — req_ids with no matching object
  - `orphan_objects` (list[str]) — object_ids with no requirement
- `BRSTraceabilityAgent()`
- `load_requirements(path: Path) -> list[Requirement]`:
  - Loads from YAML file: list of {req_id, title, description, keywords}
- `trace(requirements: list[Requirement], result: ScanResult) -> TraceReport`:
  - For each requirement, search objects by:
    1. Exact match: req keywords appear in object_id or name
    2. Keyword match: req keywords appear in object description or source_code
  - For each object, check if any requirement references it
  - Build unlinked_requirements and orphan_objects lists
- `trace_from_file(req_path: Path, result: ScanResult) -> TraceReport`

**`tests/test_brs_traceability.py`:**
- Test exact match (keyword in object name)
- Test keyword match (keyword in description)
- Test unlinked requirements detected
- Test orphan objects detected
- Test load_requirements from YAML
- Test confidence scoring (exact > keyword)

---

### Task 5: Report Generator + Sitemap

**Files:**
- Create: `src/sap_doc_agent/agents/report_generator.py`
- Create: `tests/test_report_generator.py`

Generates quality reports and sitemap.xml for M365 Copilot.

**`report_generator.py`:**
- `ReportGenerator(doc_platform_url: str)`
- `generate_summary(qa_report: QAReport, code_issues: list[CodeIssue], trace_report: TraceReport) -> str`:
  - Returns markdown summary with:
    - Overall quality score
    - Issue counts by severity
    - Top 10 issues
    - Unlinked requirements count
    - Orphan objects count
- `generate_html_report(qa_report, code_issues, trace_report) -> str`:
  - Returns a self-contained HTML page with the same content, styled for presentation
  - Simple inline CSS, no external dependencies
- `generate_sitemap(pages: list[dict]) -> str`:
  - Returns sitemap.xml content
  - Each page entry has: loc (URL), lastmod (ISO date), priority (0.5-1.0)
  - Pages with type "space" get priority 1.0, chapters 0.8, pages 0.5
- `write_reports(output_dir: Path, ...)`:
  - Writes summary.md, report.html, sitemap.xml to output_dir/reports/

**`tests/test_report_generator.py`:**
- Test summary includes score and issue counts
- Test HTML report is valid (has html/head/body tags)
- Test sitemap is valid XML with urlset and url elements
- Test sitemap priorities differ by page type
- Test write_reports creates all files

---

### Task 6: Standards content + push

**Files:**
- Create: `standards/horvath/doc_standard.yaml`
- Create: `standards/horvath/code_standard.yaml`

Write the initial Horvath best-practice standards as YAML files that the QA agents load.

**`doc_standard.yaml`** — rules for documentation quality:
- description_required: every object must have a description (field_required)
- description_min_length: description must be >= 20 chars (min_length)
- owner_required: every object must have an owner (field_required)
- package_required: BW objects must have a package (field_required)
- naming_raw_layer: objects in raw layer must start with 01_ or RAW_ (naming_convention)
- naming_harmonized_layer: harmonized layer → 02_ or HARM_ prefix
- naming_mart_layer: mart layer → 03_ or MART_ prefix

**`code_standard.yaml`** — this is loaded by code quality agent for reference, but the actual rules are hardcoded (they're regex-based). This file documents what's checked:
- no_select_star
- no_hardcoded_client
- require_where_clause
- no_magic_numbers
- no_empty_catch
- no_nested_select

Then push everything to Gitea.

---
