# SAP Documentation Agent — Design Specification

**Date:** 2026-04-13
**Author:** Henning Schuettken + Claude
**Status:** Approved
**Target:** Portable product, developed in Horvath environment, deployable at client sites

---

## 1. Problem Statement

SAP BW/4HANA and Datasphere systems accumulate hundreds of objects — ADSOs, transformations, classes, views, data flows — with documentation scattered across Confluence pages, tribal knowledge, and developer memories. There is no automated way to:

- Discover what exists and how it connects
- Verify documentation meets quality standards
- Trace business requirements to actual implementations
- Audit code quality against best practices
- Keep documentation current as the system evolves

## 2. Product Vision

An automated documentation and quality assurance platform for SAP BW/4HANA and Datasphere environments. Three layers of value:

1. **Automated Documentation Extraction** — ABAP and MCP scanners crawl the system, discover objects and dependencies, push structured documentation to Git and a documentation platform
2. **Documentation & Code Quality Assurance** — agents validate documentation against configurable standards (client-specific and Horvath best-practice), audit ABAP code quality, and verify BRS traceability
3. **Self-Improving Knowledge** — agents don't just flag issues, they fix documentation directly. Every scan run enriches the knowledge base with new quirks, patterns, and conventions

The frontend is **M365 Copilot** — consultants and developers ask natural-language questions, grounded in the living documentation. No CLI tools, no app installs, no training required.

## 3. Architecture

```
+--------------------------------------------------+
|  FRONTEND: M365 Copilot                          |
|  - Custom knowledge URLs -> doc server sitemap   |
|  - Enterprise Graph Connector (optional)         |
+------------------+-------------------------------+
                   | reads HTML via sitemap
+------------------v-------------------------------+
|  DOC PLATFORM: BookStack / Outline / Confluence  |
|  - Source of truth for all documentation         |
|  - BRS specs, scanned objects, dependency graphs |
|  - Human-editable, API-driven sync from Git      |
|  - Agents READ and WRITE here                    |
|  - Adapter interface: one per platform           |
+------------------+-------------------------------+
                   | sync via REST API
+------------------v-------------------------------+
|  AGENT LAYER: Python services                    |
|  - Scanner Orchestrator                          |
|  - Doc Sync (Git <-> Doc Platform, bidirectional)|
|  - Doc QA (validate + fix against standards)     |
|  - Code Quality Audit (ABAP + DSP checks)        |
|  - BRS Traceability (requirements <-> impl)      |
|  - Report Generator + Sitemap                    |
+------------------+-------------------------------+
                   | reads/writes
+------------------v-------------------------------+
|  GIT LAYER: GitHub / Gitea / GitLab / Azure DO   |
|  - Intermediate structured storage               |
|  - One .md per object + YAML frontmatter         |
|  - graph.json (full dependency graph)            |
|  - standards/ (Horvath + client doc standards)   |
|  - brs/ (Business Requirement Specs)             |
|  - knowledge/ (learned quirks per tenant)        |
+---------+-------------------+--------------------+
          |                   |
+---------v--------+  +-------v--------------------+
|  SAP BW/4HANA    |  |  SAP Datasphere            |
|  ABAP scanner    |  |  MCP scanner (API-based)    |
|  3 transport     |  |  + CDP/Playwright fallback  |
|  backends        |  |  (UI automation)            |
+------------------+  +----------------------------+
```

### Key design principles

- **Portable**: No dependency on any specific infrastructure. Ships as a self-contained package.
- **Configurable**: Every aspect controlled via `config.yaml` — SAP systems, doc platform, Git backend, LLM mode, standards, scan scope.
- **Environment-agnostic**: Runs at Horvath for dev/demo, deploys identically at client sites.
- **Incremental**: Each scan only processes changed objects (hash-based change detection).
- **Deduplicated**: Each object scanned once, linked from every reference point.

## 4. SAP BW/4HANA Scanner (ABAP)

### Program 1: Z_DOC_AGENT_SETUP

Idempotent setup program. Creates configuration and result tables, sets up connectivity. Re-run to update config without losing scan history.

**Tables created:**

| Table | Purpose |
|-------|---------|
| `ZDOC_AGENT_CFG` | Transport backend, Git URL, auth, scan scope, object type filters |
| `ZDOC_AGENT_SCAN` | Object key, type, metadata, last scan timestamp, content hash |
| `ZDOC_AGENT_DEPS` | Source object -> target object, relationship type |

**Additional setup:**
- RFC/HTTP destination for GitHub/Gitea API (if using direct API backend)
- abapGit repo registration (if using abapGit backend)
- Application server file path configuration (if using file drop backend)

### Program 2: Z_DOC_AGENT_SCAN

**Input:** Top-level provider(s) from selection screen or config table.

**Crawl algorithm:**

1. Start with configured top-level provider(s)
2. For each object in the crawl queue:
   - Check `ZDOC_AGENT_SCAN` — already scanned with same content hash? Skip, record dependency link only
   - Extract metadata: description, technical info, owner, package, change timestamps
   - Extract source code: transformation generated ABAP, class methods, FM source
   - Query SAP dependency tables for all referenced objects
   - Store results in `ZDOC_AGENT_SCAN` + `ZDOC_AGENT_DEPS`
   - Add referenced Z*/Y* objects to crawl queue
3. Namespace filter: skip SAP standard objects (configurable, default Z*/Y* only)
4. Generate structured output: one file per object + graph.json
5. Push via configured transport backend

**Object types and SAP source tables:**

| Object Type | Description | SAP Tables |
|---|---|---|
| ADSO | Advanced DataStore Objects | RSOADSO, RSOADSOT |
| CompositeProvider | Composite/query providers | RSDCUBE, RSDCUBET |
| Transformation | Transformation definitions | RSTRAN, RSTRANSTEPROUT |
| Transformation ABAP | Generated ABAP code | RSAABAP, generated includes |
| InfoObject | Master data objects | RSDIOBJ, RSDIOBJT |
| Process Chain | Scheduling/orchestration | RSPCCHAIN, RSPCCHAINATTR |
| Data Source | Extractor definitions | RSDS, RSDST |
| Class | ABAP OO classes | SEOCOMPO, SEOMETAREL |
| Function Module | Function modules | TFDIR, FUNCT |
| Table | Dictionary tables | DD02L, DD03L |
| Data Element | Dictionary data elements | DD04L, DD04T |
| Domain | Dictionary domains | DD01L, DD01T |
| Package | Package assignments | TADIR |
| Where-Used | Cross-references | CROSS, WBCROSSGT |

Note: Exact table names need verification on the demo BW system. BW/4HANA may have different tables than classic BW.

**Three transport backends:**

1. **abapGit** — Scanner writes objects as abapGit-compatible format. abapGit handles Git push. Requires abapGit installed on the BW system.
2. **Direct API** — `CL_HTTP_CLIENT` calls GitHub/Gitea/GitLab REST API. Creates/updates files via commits. Self-contained, no additional tools needed.
3. **File Drop** — Writes to AL11 application server path. A Linux-side cron job or agent picks up files and commits to Git. Simplest ABAP side, requires shared filesystem access.

All three are implemented; client picks based on their infrastructure and security policies.

## 5. SAP Datasphere Scanner

### Primary: MCP Server (API-based)

Based on [sap-datasphere-mcp](https://github.com/MarioDeFelipe/sap-datasphere-mcp) — a production-ready MCP server with 47 tools for SAP Datasphere.

**Key tools used:**

| Purpose | MCP Tool |
|---|---|
| List spaces | `list_spaces` |
| Browse assets per space | `get_space_assets`, `list_catalog_assets` |
| Schema + columns | `get_table_schema`, `get_asset_details` |
| Object definitions (SQL) | `get_object_definition` |
| Search objects | `search_catalog`, `search_repository` |
| Dependency/lineage | `search_repository` (lineage param), `find_assets_by_column` |
| Deployed status | `get_deployed_objects` |
| Data validation | `execute_query`, `smart_query` |

**Authentication:** OAuth 2.0 client credentials flow. Configured per tenant via env vars (`DATASPHERE_CLIENT_ID`, `DATASPHERE_CLIENT_SECRET`, `DATASPHERE_TOKEN_URL`).

### Supplementary: CDP/Playwright (UI automation)

For metadata the API cannot reach — data flow visual definitions, transformation logic details, UI-only metadata, screenshots for documentation.

Uses the battle-tested patterns from our sap_dev knowledge base:
- `CDP_PLAYBOOK.md` — verified UI5 IDs, deployment workflows, recovery techniques
- `UI_MAPPING.md` — 150+ CSS selectors for DSP UI elements
- Playwright for navigation (handles beforeunload dialogs), sap-cdp for one-shot evals
- Never `cdp_navigate` on unsaved tabs

### Knowledge learning loop

The DSP scanner doesn't just extract — it **learns**. Every scan session:
- New UI quirks discovered → written to `knowledge/tenants/<tenant>/quirks.md`
- New selector patterns found → updated in tenant-specific UI mapping
- Client-specific naming conventions → added to `knowledge/tenants/<tenant>/conventions.md`
- CDP recovery techniques → documented in per-tenant playbook

Shared patterns get promoted to `knowledge/shared/` (the Horvath best-practice base). The sap_dev knowledge we already have seeds `knowledge/shared/`:
- `dsp_quirks.md` (from KNOWLEDGE.md — HANA SQL quirks, Ace editor, cross-space access)
- `hana_sql.md` (LIMIT in UNION ALL, VARCHAR dates, SELECT * cross-space)
- `cdp_playbook.md` (from CDP_PLAYBOOK.md)
- `ui_mapping.md` (from UI_MAPPING.md)
- `best_practices.md` (from DATASPHERE_BEST_PRACTICES.md — 4-layer architecture, naming, persistence)

### Combined scan flow

1. MCP: `list_spaces` → enumerate all spaces
2. MCP: `get_space_assets` per space → full object inventory
3. MCP: `get_object_definition` per object → SQL definitions, config
4. MCP: `search_repository` with lineage → dependency links
5. MCP: `find_assets_by_column` → cross-object column lineage
6. CDP (optional): capture data flow visuals, transformation details not in API
7. Filter: skip SAP standard objects (configurable)
8. Generate: structured markdown + update graph.json
9. Write learned quirks/patterns to `knowledge/tenants/<tenant>/`
10. Push to Git layer

No ABAP install needed for DSP — purely API-driven. Much easier to deploy than BW/4.

## 6. Agent Layer

Six Python agents sharing a common config framework and LLM provider interface. All agents operate on the doc platform as their source of truth, with Git as the intermediate/working layer.

### Agent 1: Scanner Orchestrator

- Triggers BW/4 ABAP scan (monitors Git for new output) and DSP MCP scan
- Merges results from both sources into a unified object graph
- Deduplicates: objects referenced by both BW and DSP are linked, not duplicated
- Outputs `objects/<type>/<name>.md` (YAML frontmatter + structured content) and `graph.json`
- Manages the knowledge learning loop: writes new quirks, selectors, conventions back to `knowledge/`

### Agent 2: Doc Sync

- Bidirectional sync between Git and Doc Platform
- Git → Doc Platform mapping:
  - Space/Book per SAP system (e.g., "Horvath BW/4", "Client X DSP")
  - Chapter per architecture layer (RAW, HARMONIZED, MART, CONSUMPTION)
  - Page per object
  - Dependency graph rendered as linked pages + visual diagram
- Doc Platform → Git for human edits
- Conflict resolution: human edits in doc platform always win; scanner changes that conflict with human edits are flagged for review

### Agent 3: Doc QA

Validates documentation against loaded standards and optionally fixes issues.

**Rule-based checks (no LLM needed):**
- Mandatory fields present (description, owner, business purpose, dependencies, change history)
- Naming conventions followed (layer prefixes, namespace rules)
- Cross-references resolve (no broken links in dependency graph)
- Change history maintained (modification dates, authors)
- All scanned objects have corresponding documentation pages
- Structure matches expected template

**LLM-enhanced checks (mode 2 or 3 only):**
- Description quality assessment ("ADSO for sales" flagged as too vague)
- Consistency across related objects
- Language/terminology alignment with BRS documents
- Automatic doc improvement: rewrites and enriches documentation to meet standards

**Standards comparison:**
- Loads client standard from `standards/client/<name>/`
- Loads Horvath best-practice from `standards/horvath/`
- Gap report: where client standard is weaker or missing coverage vs. Horvath recommendation

### Agent 4: Code Quality Audit

**Rule-based ABAP checks:**
- `SELECT *` usage
- Missing WHERE clauses on large tables
- Hardcoded values (magic numbers, dates, client IDs)
- Unused variables
- Performance anti-patterns (nested SELECTs, missing buffering hints)
- Naming convention violations
- Error handling gaps (missing TRY/CATCH, unchecked SY-SUBRC)

**DSP-specific checks:**
- 4-layer architecture compliance (RAW -> HARMONIZED -> MART -> CONSUMPTION)
- View naming convention validation (01_LT_, 02_RV_, 03_FV_ prefixes)
- Cross-space access patterns
- Persistence strategy review
- HANA SQL anti-patterns (from learned knowledge base)

**LLM-enhanced (optional):**
- Logic complexity assessment
- Refactoring suggestions
- Semantic validation: "does this code actually do what the description says?"

### Agent 5: BRS Traceability

- Reads Business Requirement Specs from `brs/` folder or doc platform
- Parses requirements (configurable format: numbered lists, tables, structured YAML)
- Maps requirements to scanned objects:
  - **Rule-based**: keyword matching, object name references, explicit trace IDs in frontmatter
  - **LLM-enhanced**: semantic matching ("revenue allocation" finds the pricing transformation)
- Bidirectional gap report:
  - Requirements with no implementing objects
  - Objects with no tracing requirement (orphans)
  - Partial implementations flagged
- Links trace results into doc platform pages as cross-references

### Agent 6: Report Generator

- Aggregates output from all other agents
- Generates:
  - **Executive summary** — overall quality score, top issues, trend over time
  - **Detailed compliance matrix** — per-object, per-check results
  - **Gap analysis** — client standard vs. Horvath best-practice
  - **Dependency visualization** — interactive diagrams from graph.json
  - **Improvement suggestions** — prioritized list of what to fix first
- Output formats: HTML (for doc platform), PDF (for client presentations), Markdown (for Git)
- **Sitemap generator** — produces sitemap.xml for M365 Copilot to crawl

### Shared framework

```python
class AgentConfig:
    llm_mode: Literal["none", "copilot_passthrough", "direct"]
    llm_provider: Optional[LLMProvider]       # OpenAI, Claude, Ollama, Azure OpenAI
    doc_platform: DocPlatformAdapter          # BookStack, Outline, Confluence
    git_backend: GitBackend                   # GitHub, Gitea, GitLab, Azure DevOps
    standards: list[QualityStandard]          # Horvath + client standards
    tenant_knowledge: Path                    # Per-tenant learned knowledge
```

### LLM operating modes

| Mode | Description | Use case |
|---|---|---|
| `none` | Rule-based only. LLM steps skipped. Flags issues but doesn't fix. | Client with no LLM budget or strict governance |
| `copilot_passthrough` | Generates structured prompts for user to run through M365 Copilot | Enterprise: M365 Copilot is the only approved LLM |
| `direct` | Agents call LLM API directly (Azure OpenAI, Claude, Ollama, etc.) | Full automation: agents fix docs, generate descriptions, do semantic matching |

## 7. Doc Platform Adapters

Abstract interface with three implementations:

### Common interface

```python
class DocPlatformAdapter(ABC):
    def create_space(name, description) -> SpaceID
    def create_page(space, title, content, parent=None) -> PageID
    def update_page(page_id, content) -> None
    def get_page(page_id) -> Page
    def search(query) -> list[Page]
    def get_hierarchy(space) -> Tree
    def attach_file(page_id, file) -> None
    def add_label(page_id, label) -> None
```

### BookStack adapter
- REST API at configured URL
- Books = SAP systems, Chapters = architecture layers, Pages = objects
- API token auth

### Outline adapter
- REST API, markdown-native
- Collections = SAP systems, Documents = objects
- API token or OIDC auth

### Confluence adapter
- REST API via `atlassian-python-api`
- Supports both Cloud (`/cloud/confluence/rest/v2/`) and Server/Data Center (`/rest/api/`)
- Spaces = SAP systems, Pages with parent hierarchy = layers + objects
- API token or basic auth

## 8. M365 Copilot Integration

### For demo (Declarative Agent)
- Configure custom knowledge URLs (up to 4) pointing at doc platform
- Doc platform serves HTML with proper semantic structure
- Report Generator creates `sitemap.xml` listing all documentation pages
- Copilot crawls via sitemap, indexes all sub-pages

### For enterprise (Graph Connector)
- Enterprise Websites connector crawls doc platform (50+ sites)
- Auto-indexes into Microsoft Graph
- Content available across all M365 Copilot experiences
- Supports incremental crawling on subsequent runs

### Optimization for Copilot consumption
- Clean HTML with semantic headings (h1-h4)
- Structured metadata in page headers
- Cross-links between related objects
- Dependency graphs as both visual diagrams and text lists
- BRS traceability tables embedded in relevant pages

## 9. Git Repository Structure

```
sap-doc-agent/
|-- setup/
|   |-- abap/
|   |   |-- Z_DOC_AGENT_SETUP.abap
|   |   |-- Z_DOC_AGENT_SCAN.abap
|   |   +-- transport/
|   |-- linux/
|   |   |-- install.sh
|   |   +-- docker-compose.yml
|   +-- config/
|       |-- config.example.yaml
|       +-- wizard.py
|
|-- agents/
|   |-- core/
|   |   |-- config.py
|   |   |-- llm_provider.py
|   |   |-- doc_adapter.py
|   |   +-- git_backend.py
|   |-- scanner_orchestrator.py
|   |-- doc_sync.py
|   |-- doc_qa.py
|   |-- code_quality.py
|   |-- brs_traceability.py
|   +-- report_generator.py
|
|-- standards/
|   |-- horvath/
|   |   |-- doc_standard.yaml
|   |   |-- code_standard.yaml
|   |   +-- architecture_standard.yaml
|   +-- client/
|       +-- .gitkeep
|
|-- knowledge/
|   |-- shared/
|   |   |-- dsp_quirks.md
|   |   |-- hana_sql.md
|   |   |-- cdp_playbook.md
|   |   |-- ui_mapping.md
|   |   +-- best_practices.md
|   +-- tenants/
|       +-- .gitkeep
|
|-- brs/
|   +-- .gitkeep
|
|-- output/
|   |-- objects/
|   +-- graph.json
|
|-- reports/
|
|-- docs/
|   |-- getting-started.md
|   |-- admin-guide.md
|   +-- horvath-best-practice.md
|
+-- config.yaml
```

## 10. Quality Standards

### Horvath Best-Practice Standard (developed as part of this project)

Three standard definition files shipped with the product:

**doc_standard.yaml** — Documentation quality rules:
- Every object must have: description (min 50 chars), business purpose, technical owner, change history
- Cross-references: every dependency must link to a documented object
- Naming: must follow layer-prefix conventions
- Freshness: documentation updated within 90 days of last object change
- Completeness: all scanned objects have corresponding documentation

**code_standard.yaml** — ABAP code quality rules:
- No SELECT * on production tables
- WHERE clauses required on tables > 10K rows
- No hardcoded dates, client IDs, or magic numbers
- Proper error handling (SY-SUBRC checks, TRY/CATCH)
- Naming conventions for variables, methods, classes
- Performance: no nested SELECT in LOOPs

**architecture_standard.yaml** — Design quality rules:
- 4-layer compliance (RAW -> HARMONIZED -> MART -> CONSUMPTION)
- No circular dependencies
- No dead objects (unreferenced from any active chain)
- Reuse patterns: shared objects properly factored
- DSP naming conventions (layer prefixes)

### Client standards

Loaded from `standards/client/<name>/` — same YAML schema as Horvath standards. Client can override severity levels, add custom rules, or disable rules that don't apply.

### Gap analysis

Doc QA Agent compares client standard vs. Horvath best-practice and generates a gap report: where the client's standard is less strict, missing coverage, or contradicts best practice. This is a consulting deliverable.

## 11. Demo Plan

### Demo environment (Horvath)

| Component | Location |
|---|---|
| BW/4HANA | Horvath demo system (1-2 data models + ABAP scanner) |
| Datasphere | Horvath DSP tenant (existing content, MCP scanner) |
| Git | Personal GitHub repo (separate `sap-doc-agent` repo) |
| Doc Platform | BookStack at homelab :8253 (dev) or public-facing instance |
| M365 Copilot | Horvath M365 Copilot with custom knowledge URLs |
| LLM | Homelab LLM Router (:8070, OpenAI-compatible API, qwen2.5 models). Production LLM TBD — needs Horvath IT approval for Azure OpenAI or similar. |
| Agent Layer | Dev box or any Linux host |

### Demo script

**Act 1 — "The Problem"** (2 min)
- Show a typical SAP system: undocumented objects, tribal knowledge, no traceability
- "How do you know your BW system actually implements what was specified?"

**Act 2 — "The Scanner"** (5 min)
- Run Z_DOC_AGENT_SCAN live on demo BW — watch it crawl providers and discover dependencies
- Show DSP MCP scan running in parallel
- Objects appear in Git: structured markdown, dependency graph

**Act 3 — "The Documentation"** (5 min)
- Doc Sync pushes to BookStack/Confluence
- Navigate generated docs: hierarchical, cross-linked, dependency diagrams
- Show BRS document and traceability matrix

**Act 4 — "The Quality Gate"** (5 min)
- Run Doc QA — flag incomplete docs, naming violations, missing descriptions
- Run Code Quality audit — show ABAP anti-patterns
- Show gap analysis: client standard vs. Horvath best-practice
- Show Fix mode: agent improves a doc entry live

**Act 5 — "Ask Your System"** (3 min)
- Open M365 Copilot
- "What transformations feed the sales ADSO?"
- "Which objects don't meet our documentation standard?"
- "Is requirement BRS-042 fully implemented?"
- Copilot answers grounded in the documentation

## 12. Implementation Phases

### Phase 1 — Foundation
1. Git repo structure + config framework (`config.yaml`, `AgentConfig`)
2. ABAP setup program (`Z_DOC_AGENT_SETUP`)
3. ABAP scanner (`Z_DOC_AGENT_SCAN`) — direct API transport first
4. DSP MCP scanner integration (extend/wrap sap-datasphere-mcp)
5. Doc platform adapters (BookStack first, Confluence second)

### Phase 2 — Agents
6. Scanner Orchestrator (merge BW + DSP output, deduplicate)
7. Doc Sync agent (Git -> Doc Platform, bidirectional)
8. Doc QA agent (rule-based checks)
9. Code Quality audit (rule-based ABAP + DSP checks)
10. BRS Traceability agent

### Phase 3 — Intelligence & Polish
11. LLM provider integration (direct mode)
12. Copilot passthrough mode
13. Report Generator + sitemap for M365 Copilot
14. Horvath best-practice standard content (the actual rules)
15. Knowledge learning loop
16. Setup wizard + Linux install script

### Phase 4 — Demo
17. Install ABAP on demo BW system
18. Configure DSP OAuth on Horvath tenant
19. Run full pipeline: scan -> sync -> QA
20. Configure M365 Copilot custom knowledge URLs
21. Rehearse and refine demo script

## 13. Technology Stack

| Component | Technology |
|---|---|
| ABAP scanner | ABAP (SE38/ADT), BW/4HANA standard tables |
| DSP scanner | Python + sap-datasphere-mcp (MCP) + Playwright/CDP (UI fallback) |
| Agent layer | Python 3.12+, async, configurable |
| Doc adapters | Python — BookStack REST, Outline REST, atlassian-python-api (Confluence) |
| Git adapters | Python — PyGithub, gitea-python, python-gitlab |
| LLM providers | OpenAI-compatible API (LLM Router for demo, Azure OpenAI / Claude / Ollama for production) |
| Config | YAML (config.yaml + standards/*.yaml) |
| Reports | Jinja2 templates -> HTML/PDF/Markdown |
| Containerization | Docker + docker-compose (optional) |
| M365 integration | Sitemap.xml + static HTML serving |
