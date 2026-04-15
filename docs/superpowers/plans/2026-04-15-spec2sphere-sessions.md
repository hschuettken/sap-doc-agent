# Spec2Sphere — Dev Session Prompts

**Design spec:** `docs/superpowers/specs/2026-04-15-spec2sphere-design.md`
**Sessions:** 6 (larger sessions as requested)
**Each session:** autonomous, self-contained, produces working code with tests

---

## Session 1: Platform Foundation

```
You are building the foundation of Spec2Sphere — a modular, multi-tenant SAP analytics delivery accelerator. This session transforms the existing SAP Doc Agent (v1.1.0) into the Spec2Sphere platform shell.

DESIGN SPEC: Read docs/superpowers/specs/2026-04-15-spec2sphere-design.md — Sections 3, 4, 5, 9, 11

EXISTING CODEBASE: This is an existing Python project at src/sap_doc_agent/ with FastAPI + HTMX + Jinja2 web UI, 7 LLM providers, Celery workers, migration accelerator, scanners, and agents. 254 passing tests. Docker Compose with web/worker/scheduler/postgres/redis.

WHAT TO BUILD (in this order):

1. RENAME: sap_doc_agent -> spec2sphere
   - Rename src/sap_doc_agent/ to src/spec2sphere/
   - Update all imports across the entire codebase
   - Update pyproject.toml (package name, entry points — add spec2sphere alias, keep sap-doc-agent for backwards compat)
   - Update docker-compose.yml service references
   - Update all test imports
   - Run existing tests to verify nothing breaks

2. ALEMBIC SETUP + MULTI-TENANT SCHEMA
   - Initialize Alembic (async PostgreSQL)
   - Create initial migration with the full schema from spec Section 5.2: tenants, customers, projects, users, user_customer_access, knowledge_items (with vector column), landscape_objects, requirements, architecture_decisions, hla_documents, tech_specs, technical_objects, sac_blueprints, test_specs, reconciliation_results, visual_qa_results, lab_experiments, learned_templates, route_fitness, approvals, audit_log, design_tokens, layout_archetypes
   - Use pgvector extension (CREATE EXTENSION IF NOT EXISTS vector)
   - All tables have proper indexes (tenant_id, customer_id, project_id, created_at)
   - entrypoint.sh runs alembic upgrade head on startup

3. CONTEXT ENVELOPE MIDDLEWARE
   - Create spec2sphere/tenant/context.py with ContextEnvelope dataclass (fields from spec Section 5.3)
   - Create FastAPI dependency get_context() that resolves tenant/customer/project from session + URL path
   - Create ScopedQuery helper that adds WHERE tenant_id/customer_id/project_id clauses
   - Single-tenant fallback: when multi_tenant=false in config, auto-create a default tenant and skip workspace switching
   - All existing API endpoints should work in single-tenant mode without changes

4. POLICY STACK ENGINE
   - Create spec2sphere/tenant/policy.py
   - 5-layer resolution: platform base -> Horvath defaults -> accelerator rules -> customer overrides -> project exceptions
   - Each layer is a JSON document stored in the DB (customers.policy_overrides, projects.config)
   - Resolved stack cached in Redis (key: policy:{customer_id}:{project_id}, TTL 5min)
   - Policy resolution function: merge layers, later overrides earlier, log conflicts

5. MODULE SYSTEM
   - Create spec2sphere/modules.py — reads config.yaml modules section
   - Each module registers its FastAPI routes and Celery tasks only when enabled
   - Disabled modules: routes not mounted, tasks not imported, UI sections hidden
   - Module registry: name -> {routes, tasks, ui_sections, enabled}
   - Wire this into app.py lifespan

6. USER MODEL + RBAC
   - Users table with email/password_hash/display_name/role
   - Roles: admin, architect, consultant, developer, reviewer, viewer
   - User-customer access table for per-customer permissions
   - Replace existing single-password auth with user login (keep single-password as fallback for single-tenant mode)
   - Role-based route guards: require_role("architect") FastAPI dependency
   - Session stores user_id + active customer_id + active project_id

7. WORKSPACE SWITCHER UI
   - Top-bar component showing: active customer, active project, active environment
   - Dropdown to switch customer/project
   - On switch: clear session scoped state, redirect to dashboard
   - Visual badges: environment (sandbox/test/prod), tenant mode
   - Tenant/customer/project CRUD pages (admin only)

8. CONTAINERIZED CHROME
   - Create docker/chrome/Dockerfile: Ubuntu + Chrome + Xvfb + x11vnc
   - Chrome launched with: --remote-debugging-port=9222 --no-sandbox --disable-gpu --window-size=1920,1080
   - Xvfb :99 with 1920x1080x24
   - VNC server on port 5900 (password: spec2sphere)
   - Create spec2sphere/browser/pool.py: BrowserPool class
     - get_session(tenant_id, environment) -> CDP connection
     - Session isolation: separate browser contexts per tenant
     - Health check: verify CDP endpoint responsive
     - Graceful shutdown
   - Add chrome service to docker-compose.yml (port 5900 for VNC, 9222 for CDP)
   - Config option: browser.mode = "container" | "remote" (Win11 fallback)

9. AUDIT LOG MIDDLEWARE
   - FastAPI middleware that logs every request to audit_log table
   - Fields: tenant_id, customer_id, project_id, user_id, action, resource_type, resource_id, details
   - Non-blocking (fire-and-forget insert via Celery or asyncio.create_task)

10. TESTS
    - All existing tests pass with new package name
    - Context envelope: creation, scoping, single-tenant fallback
    - Policy stack: layer resolution, override logic, caching
    - RBAC: role guards, user-customer access
    - Browser pool: session creation, tenant isolation
    - Module system: enable/disable routes
    - Scoped queries: tenant filtering, no cross-tenant leakage

IMPORTANT:
- Do NOT break any existing functionality. The migration accelerator, scanners, agents, LLM providers, and web UI must all continue working.
- The rename is the most delicate part. Do it first, run tests, then proceed.
- Use asyncpg for all new DB operations. The existing code already uses asyncpg.
- HTMX patterns: use hx-get/hx-post for dynamic content, hx-swap for partial updates, hx-trigger for events.

COMPLETION:
- All tests pass
- docker compose up starts all 7 containers
- Web UI loads with workspace switcher
- Single-tenant mode works out of the box (no configuration needed)
- VNC connection to chrome container works
- Create a git commit, push to Gitea, deploy via ops-bridge
```

---

## Session 2: Intelligence Core + Knowledge Engine

```
You are building the Intelligence Core for Spec2Sphere — the knowledge engine that powers all downstream pipeline stages.

DESIGN SPEC: Read docs/superpowers/specs/2026-04-15-spec2sphere-design.md — Sections 6.2, 8, and the Intelligence Core parts of Section 10

PREREQUISITE: Session 1 is complete. The codebase is at src/spec2sphere/, multi-tenant schema exists, context envelope middleware works, containerized Chrome is running.

WHAT TO BUILD:

1. KNOWLEDGE ENGINE (spec2sphere/core/knowledge/)
   - knowledge_service.py: CRUD for knowledge_items with pgvector embeddings
   - Embedding generation: use the existing LLM provider abstraction. Add an embed() method to the LLM base class. For providers that support embeddings (OpenAI, Ollama/nomic-embed), generate embeddings. For others, fall back to a simple TF-IDF or skip.
   - Scoped semantic search: search_knowledge(query, ctx: ContextEnvelope, top_k=10)
     - Searches project -> customer -> global layers in priority order
     - Tags each result with source layer
     - Deduplicates and re-ranks
   - Bulk ingestion: ingest_documents(files, ctx) -> parse + chunk + embed + store

2. STANDARDS INTAKE PIPELINE (spec2sphere/core/standards/)
   - intake.py: accepts PDF, Word, Markdown, plain text
   - Uses existing pdfplumber + python-docx infrastructure
   - LLM extraction: parse prose guidelines into structured rules (category, rule_text, severity, examples)
   - Rule categories: naming | layering | anti_pattern | template | quality | governance
   - Store extracted rules as knowledge_items with embeddings
   - Re-extraction: can re-run on updated documents, deduplicates

3. DESIGN SYSTEM (spec2sphere/core/design_system/)
   - tokens.py: CRUD for design_tokens (color roles, typography, spacing, density, emphasis)
   - archetypes.py: CRUD for layout_archetypes (9 types from spec Section 8.2) + widget_archetypes
   - Seed Horvath defaults: pre-populate design_tokens and layout_archetypes with Horvath brand (petrol #05415A, gold #C8963E, Georgia headings, Inter body)
   - Customer override layer: customer-specific tokens override Horvath defaults
   - resolve_design_profile(ctx) -> merged token set for current customer
   - Design quality scorer: score_dashboard(blueprint_or_inventory_item) -> DesignScore (0-100, breakdown per category)
   - Scoring criteria from spec Section 8.4: archetype compliance 30%, layout/readability 25%, chart choice 15%, title quality 10%, filter usability 10%, navigation clarity 10%

4. DSP TENANT SCANNER ENHANCEMENT (spec2sphere/core/scanner/)
   - Enhance existing scanner to store results in landscape_objects table (not just files)
   - Scoped by customer_id + project_id via context envelope
   - Full inventory: views, tables, analytic models, dimensions, remote tables, task chains, data flows
   - Dependency extraction: object-to-object references stored in dependencies JSONB
   - Incremental scan: hash-based change detection (existing), skip unchanged objects

5. SAC TENANT SCANNER (spec2sphere/core/scanner/sac_scanner.py)
   - New scanner for SAP Analytics Cloud
   - Uses browser pool (containerized Chrome or Win11 fallback)
   - Inventory: stories, optimized stories, analytic applications, models, folders, data actions
   - For each artifact: extract metadata, page structure, widget list, model bindings
   - SAC Content API integration where available (story list, model metadata)
   - CDP fallback for metadata not available via API
   - Store results in landscape_objects (platform='sac')
   - Dependency mapping: story -> model -> DSP view chain

6. CROSS-PLATFORM DEPENDENCY GRAPH
   - graph_builder.py: build unified dependency graph across DSP + SAC + BW objects
   - Store as adjacency list in landscape_objects.dependencies
   - Graph query helpers: upstream(object_id), downstream(object_id), impact_analysis(object_id)
   - Integration with vis.js for visualization (existing graph page)

7. DOCUMENTATION AUDIT ENGINE (spec2sphere/core/audit/)
   - Compare existing object documentation against loaded standards
   - Produce scorecard per object: documented fields, naming compliance, description quality, missing cross-references
   - Aggregate scorecard per customer/project
   - Identify gaps and generate recommendations

8. KNOWLEDGE BROWSER UI (Jinja2 + HTMX)
   - /ui/knowledge page: search bar with semantic search, browse by category, filter by knowledge layer (global/customer/project)
   - Upload documents for standards intake (drag-and-drop file upload)
   - View extracted rules with source reference
   - Edit/delete knowledge items
   - Design token browser: view current resolved design profile

9. LANDSCAPE EXPLORER UI
   - /ui/landscape page: combined DSP + SAC object inventory
   - Filter by platform, object type, layer, scan status
   - Object detail panel: metadata, documentation, dependencies, design score (SAC)
   - Dependency graph visualization (vis.js)
   - Scan trigger button (kicks off Celery scan task)
   - Migration wave grouping view (criticality/complexity/debt heatmap)

10. TESTS
    - Knowledge scoping: verify no cross-tenant retrieval leakage
    - Standards extraction: test PDF/Word/Markdown parsing + LLM extraction
    - Design system: token resolution with customer overrides
    - Design scoring: test against known good/bad examples
    - Scanner: DSP and SAC inventory storage and incremental scan
    - Dependency graph: upstream/downstream traversal
    - Documentation audit: scorecard generation

COMPLETION:
- Upload a guidelines PDF -> see extracted rules in knowledge browser
- Run DSP scan -> see objects in landscape explorer with dependency graph
- Run SAC scan -> see stories/apps alongside DSP objects
- Design quality scores shown for SAC content
- Documentation audit produces per-object scorecards
- All scoped by current workspace (customer/project)
- Create a git commit, push to Gitea, deploy via ops-bridge
```

---

## Session 3: Pipeline — Requirement to Architecture

```
You are building the Pipeline module for Spec2Sphere — from business requirements to approved architecture.

DESIGN SPEC: Read docs/superpowers/specs/2026-04-15-spec2sphere-design.md — Sections 6.3, 6.4, 6.5 (first half)

PREREQUISITE: Sessions 1-2 complete. Multi-tenant platform with knowledge engine, landscape scanning, and design system.

WHAT TO BUILD:

1. REQUIREMENT INTAKE ENGINE (spec2sphere/pipeline/intake.py)
   - Accept BRS in multiple formats: PDF, Word, Markdown, plain text, structured YAML
   - Also accept: workshop notes, KPI catalogs, report mockups (as supporting material)
   - Store parsed documents in requirements table
   - Chunking + embedding for semantic retrieval later

2. SEMANTIC PARSER (spec2sphere/pipeline/semantic_parser.py)
   - LLM-powered extraction from BRS:
     - business_domains, entities, facts, measures, KPIs
     - grain (dimensionality), time semantics, version semantics
     - source systems, security/role implications
     - non-functional requirements (performance, latency, volume)
   - Ambiguity detection: flag unclear, conflicting, or incomplete requirements
   - Confidence scoring per extracted element (high/medium/low with rationale)
   - Open questions register: auto-generated list of things that need clarification
   - Output: structured YAML/JSON stored in requirements.parsed_entities, parsed_kpis, parsed_grain, confidence, open_questions
   - Use scoped knowledge base for context (existing landscape, existing standards)

3. BW MODERNIZATION INTEGRATION
   - Wire existing migration/ module as an alternative intake path
   - BW metadata (from existing scanner) -> run through interpreter + classifier -> produce a "cleaned BRS equivalent"
   - Debt/workaround classification (existing classifier.py): tag each legacy artifact as business_rule | technical_debt | workaround | obsolete | unclear
   - Migration strategy mode assignment per object/domain: replicate | clean | redesign
   - This produces the same structured requirement output as the BRS parser, so the rest of the pipeline is identical

4. HLA GENERATOR (spec2sphere/pipeline/hla_generator.py)
   - Input: approved requirement interpretation + landscape inventory + knowledge base
   - LLM-powered architecture generation:
     - Domain decomposition
     - Layered architecture (RAW -> HARMONIZED -> MART -> CONSUMPTION)
     - Fact/dimension strategy
     - Key architecture decisions with alternatives and rationale
   - CROSS-PLATFORM PLACEMENT ENGINE (spec2sphere/pipeline/placement.py):
     - For each artifact, decide: DSP or SAC or both
     - Calculations: DSP view calculation vs SAC calculated measure
     - Filters: DSP input parameter vs SAC story filter
     - Hierarchies: DSP dimension vs SAC hierarchy
     - Aggregation: DSP pre-aggregated vs SAC runtime
     - Decision logged with rationale and confidence
   - SAC reporting strategy: recommend story vs analytic app vs custom widget per dashboard need
   - Output: hla_documents record (structured JSON + narrative prose), architecture_decisions records
   - Uses landscape knowledge (what already exists in the tenant) to avoid duplication and leverage reuse

5. APPROVAL GATE WORKFLOW (spec2sphere/governance/approvals.py)
   - Generic approval engine reusable across all pipeline stages
   - Submit artifact for review -> status: pending_review
   - Reviewer can: approve, reject (with reason), request rework (with comments)
   - Checklist support: predefined checklist items per artifact type (from spec Appendix B)
   - HLA checklist: business scope correct, entities identified, grain agreed, arch decisions documented, open questions acceptable
   - On approval: artifact status -> approved, unlock next pipeline stage
   - On rejection: artifact status -> rejected, notify creator
   - On rework: artifact status -> rework, back to creator with comments

6. PIPELINE UI
   - /ui/pipeline page: stage-by-stage progress view
     - Visual pipeline: Intake -> Interpretation -> HLA -> [Tech Spec] -> [Test Spec] -> [Build] -> [Deploy] -> [QA] -> [Release] -> [Docs]
     - Current stage highlighted, completed stages checkmarked, locked stages grayed out
     - Click stage to navigate to detail page
   - Stage progress driven by approval status of artifacts

7. REQUIREMENTS UI
   - /ui/pipeline/requirements page
   - Upload BRS document (file upload)
   - View parsed: entities, KPIs, facts, grain in structured cards
   - Confidence heatmap: green/yellow/red per element
   - Open questions list with severity
   - Edit parsed results (human correction before approval)
   - Submit for HLA generation (trigger Celery task)
   - For BW migration: show debt classification and migration strategy per object

8. ARCHITECTURE UI
   - /ui/pipeline/architecture page
   - HLA document viewer (prose + structured)
   - Architecture decision log: table of decisions with choice, alternatives, rationale
   - Cross-platform placement diagram: visual split of DSP vs SAC artifacts
   - Approval panel: checklist, comments, approve/reject/rework buttons
   - Version comparison: diff between HLA versions

9. NOTIFICATION SYSTEM
   - In-app notifications: when artifact is ready for review, when approval decision is made
   - Simple: notifications table + polling via HTMX (hx-trigger="every 30s")
   - Badge count in top bar

10. TESTS
    - Requirement parsing: test BRS extraction with sample documents (create 2-3 sample BRS docs in tests/fixtures/)
    - Confidence scoring: verify elements get appropriate confidence levels
    - BW integration: test migration module -> requirement output conversion
    - HLA generation: test architecture output structure and completeness
    - Cross-platform placement: test decision logic for known scenarios
    - Approval workflow: test state machine (pending -> approved/rejected/rework)
    - Scoping: all pipeline artifacts scoped to project

COMPLETION:
- Upload a sample BRS -> see parsed requirements with confidence + open questions
- Generate HLA -> see architecture with cross-platform placement decisions
- Approve HLA via checklist -> stage 2 unlocks
- BW metadata can also feed into the pipeline as alternative intake
- Pipeline progress view shows current stage
- All scoped to active workspace
- Create a git commit, push to Gitea, deploy via ops-bridge
```

---

## Session 4: Pipeline — Tech Spec + SAC Blueprint + Test Spec

```
You are building the second half of the Pipeline — turning approved architecture into technical specifications, SAC blueprints, and test specifications.

DESIGN SPEC: Read docs/superpowers/specs/2026-04-15-spec2sphere-design.md — Sections 6.5, 6.6, 8

PREREQUISITE: Sessions 1-3 complete. Platform foundation, knowledge engine, requirement-to-HLA pipeline with approval gates.

WHAT TO BUILD:

1. TECH SPEC GENERATOR (spec2sphere/pipeline/tech_spec_generator.py)
   - Input: approved HLA + knowledge base + landscape inventory
   - Generate technical object inventory:
     - One technical_objects record per artifact
     - Naming-compliant IDs (using customer naming conventions from knowledge base)
     - Object type (relational_view, analytic_model, dimension, fact, story, app)
     - Platform assignment (dsp | sac) from HLA placement decisions
     - Layer assignment (raw, harmonized, mart, consumption)
     - Source-to-target mapping
     - Join conditions
     - Calculations, transformations, business rules
     - Parameter and filter logic
   - Dependency graph construction: which objects depend on which
   - Deployment order: topological sort (reuse existing Kahn's algorithm from migration/architect.py)
   - SQL generation for DSP views: enhance existing migration/generator.py + sql_validator.py to work from tech spec objects
   - SQL validation: run all 8 DSP rules from existing sql_validator against every generated view
   - Store: tech_specs record + technical_objects records

2. SAC BLUEPRINT GENERATOR (spec2sphere/pipeline/blueprint_generator.py)
   - Input: approved HLA + design profile (resolved tokens + archetypes) + KPI mapping
   - Generate canonical SAC blueprint (YAML structure from spec Section 6.2):
     - Dashboard metadata (title, audience, archetype, style_profile)
     - Pages with layout archetype applied
     - Widgets per page with metric bindings
     - Interaction rules (global filters, page navigation, drill behavior)
     - Performance classification
   - Story vs Analytic App vs Custom Widget decision engine:
     - Story: standard reporting, moderate interaction, easy maintenance
     - App: complex interactivity, scripted behavior, guided flows
     - Custom Widget: unique UX, branded viz (rare, requires justification)
     - Decision logged with rationale and confidence
   - Apply design tokens: colors, typography, spacing from resolved profile
   - Widget archetype selection: match KPI type to best widget (e.g., variance -> waterfall, trend -> line chart, ranking -> horizontal bar)
   - Store: sac_blueprints record

3. TEST SPEC GENERATOR (spec2sphere/pipeline/test_generator.py)
   - Input: tech spec + blueprint + existing landscape (for regression baselines)
   - Two modes:
     - Preservation: new model must match current behavior
     - Improvement: approved redesign, expected deltas documented
   - Generate DSP test cases:
     - Structural: object existence, field types, grain consistency
     - Volume: row counts, distinct counts, null distributions
     - Business aggregates: KPI totals by major cuts (time, region, product)
     - Edge cases: empty periods, missing data, null/zero logic
     - Sample traces: detailed source-to-target record examples
   - Generate SAC test cases:
     - Data regression: KPI values match DSP source
     - Visual: page layout matches blueprint (screenshot comparison targets)
     - Interaction: filter behavior, navigation flow, drill paths
     - Design rules: archetype compliance, density, title quality
   - _dev copy pattern commands: generate SQL for CREATE ... AS SELECT to copy views to {name}_DEV
   - Golden query catalog: curated high-value regression queries per domain
   - Tolerance rules: exact | absolute(n) | percentage(p) | expected_delta(description)
   - Store: test_specs record with test_cases JSONB

4. TECH SPEC UI
   - /ui/pipeline/techspec page
   - Object inventory table: sortable by name, type, platform, layer, status
   - Dependency graph (vis.js): show deployment order, highlight critical path
   - SQL viewer (CodeMirror): view generated SQL per DSP object, syntax highlighting
   - Validation results: per-object pass/fail for naming, SQL rules, dependency checks
   - Approval panel: tech spec checklist, approve/reject/rework
   - Click object -> detail panel with full definition

5. SAC BLUEPRINT UI
   - /ui/pipeline/blueprint page
   - Blueprint overview: dashboard metadata, audience, archetype
   - Page previewer: render archetype layout as a schematic mockup (HTML/CSS approximation of the page structure — not pixel-perfect, but shows layout zones, widget placement, and KPI assignments)
   - Widget list per page: type, metric binding, size
   - Interaction map: filter strategy, navigation paths
   - Design profile: show applied tokens (colors, typography)
   - Artifact type decision: story vs app recommendation with rationale
   - Approval panel

6. TEST SPEC UI
   - /ui/pipeline/testspec page
   - Test case browser: filter by category (structural, volume, aggregate, edge_case, visual, interaction)
   - Tolerance settings editor: set tolerance per test or per category
   - Expected deltas editor: mark known acceptable changes with explanation
   - _dev copy commands viewer: show SQL for creating test copies
   - Golden query catalog: browse and edit curated queries
   - Test mode toggle: preservation vs improvement

7. DIFF VIEWER COMPONENT
   - Reusable Jinja2 partial for side-by-side comparison
   - Used for: HLA version diffs, tech spec version diffs, SQL changes, blueprint changes
   - Inline diff (additions green, removals red) and side-by-side mode
   - Wire into architecture UI (HLA versions) and tech spec UI (object changes)

8. TESTS
    - Tech spec generation: test object inventory from sample HLA
    - SQL generation: test against known DSP patterns (reuse existing migration tests where applicable)
    - SQL validation: all 8 rules pass for generated SQL
    - Blueprint generation: test YAML structure, archetype application, widget selection
    - Test spec generation: verify test cases cover all categories
    - _dev copy: test SQL generation for copy pattern
    - Tolerance engine: test exact, absolute, percentage, expected_delta matching
    - Approval: tech spec and blueprint approval flow

COMPLETION:
- Approved HLA -> generate tech spec with DSP objects + SQL + dependency graph
- Approved HLA -> generate SAC blueprint with pages, widgets, interactions
- Tech spec -> generate test spec with queries, tolerances, _dev copy commands
- All viewable and editable in UI
- Approval gates for tech spec and blueprint
- Diff viewer works for version comparison
- Create a git commit, push to Gitea, deploy via ops-bridge
```

---

## Session 5: DSP Factory + SAC Factory + Route Router

```
You are building the Factory modules — the execution engines that turn specifications into deployed artifacts.

DESIGN SPEC: Read docs/superpowers/specs/2026-04-15-spec2sphere-design.md — Sections 6.7-6.9, 7, 10.1 Route Router

PREREQUISITE: Sessions 1-4 complete. Full pipeline from requirements to tech spec + blueprint + test spec. Browser pool. Knowledge engine with landscape awareness.

WHAT TO BUILD:

1. ROUTE ROUTER (spec2sphere/factory/route_router.py)
   - Central decision engine: selects best execution route per artifact + action
   - Routes: click_guide | api | cdp | csn_import | manifest
   - Selection factors:
     - route_fitness score (from route_fitness table, learned over time)
     - artifact type (view, model, story, app, etc.)
     - action (create, update, read, delete, screenshot)
     - environment (sandbox/test/production — production requires higher safety)
     - confidence level
     - customer policy (some customers may restrict certain routes)
   - Mixed-route support: one deployment can use different routes for different steps
   - Fallback chain: if primary route fails, try next best route
   - Every execution updates route_fitness (success/failure/duration)

2. DSP FACTORY (spec2sphere/dsp_factory/)
   - artifact_generator.py:
     - SQL view definitions from tech spec (enhance existing generator.py)
     - CSN/JSON object definitions (from learned templates when available, template-based otherwise)
     - Deployment manifest: ordered list of objects with create/update flag and route assignment
   - deployer.py:
     - _dev copy execution: create {viewname}_DEV copies via CDP or SQL
     - Object deployment via CDP (graphical SQL editor interaction)
     - Object deployment via REST API (where DSP supports it)
     - Object deployment via CSN/JSON import (where format is known from Lab)
     - Rollback: retain prior object definition for reversal
   - readback.py:
     - After deployment, read back object definition from DSP
     - Compare expected vs actual definition (structural diff)
     - Report discrepancies
   - All operations use browser pool for CDP, scoped to tenant/environment

3. SAC FACTORY (spec2sphere/sac_factory/)
   - click_guide_generator.py:
     - From blueprint, generate step-by-step human instructions
     - Reference UI elements by label/position
     - Include decision notes, checklist, rollback hints
     - Output as structured Markdown
   - manifest_builder.py:
     - From blueprint, generate internal structured package
     - Page/widget manifest with all bindings
     - Transport assembly hints
   - api_adapter.py:
     - SAC Content API calls: list stories, read story metadata, transport operations
     - Model metadata reads
     - Environment inventory sync
   - playwright_adapter.py:
     - CDP-based UI automation for SAC
     - Create story: navigate to SAC, create new story, configure pages and widgets
     - Widget configuration: add charts, tables, KPI tiles with correct bindings
     - Filter setup: configure global and page-local filters
     - Navigation setup: configure page tabs, drill actions
     - Screenshot capture after each major step (evidence trail)
     - Uses browser pool, session-per-tenant
   - screenshot_engine.py:
     - Capture full-page and per-widget screenshots
     - Visual comparison: pixel diff + structural diff (element presence/absence)
     - Annotate differences on screenshot overlay
     - Store in artifact store per tenant/project

4. DATA RECONCILIATION ENGINE (spec2sphere/factory/reconciliation.py)
   - Execute baseline queries (before-change or existing model)
   - Execute candidate queries (new/changed model or _DEV copy)
   - Compare results row-by-row and aggregate-level
   - Delta classification:
     - pass: exact match
     - within_tolerance: delta within configured tolerance
     - expected_change: matches expected delta definition
     - probable_defect: unexpected difference, needs investigation
     - needs_review: ambiguous, requires human judgment
   - Store: reconciliation_results records
   - Generate comparison tables (like spec Section 6.8 example)

5. INTERACTION QA ENGINE (spec2sphere/sac_factory/interaction_qa.py)
   - Automated SAC testing via CDP:
     - Filter tests: apply each filter, verify data changes appropriately
     - Navigation tests: click navigation elements, verify correct page loads
     - Drill tests: click chart elements, verify drill-through behavior
     - Script tests (for analytic apps): trigger scripts, verify outcomes
   - Record pass/fail per test with screenshot evidence
   - Uses test spec generated in Session 4

6. DESIGN QA ENGINE (spec2sphere/sac_factory/design_qa.py)
   - Analyze deployed SAC content against blueprint and design rules:
     - Archetype compliance: does page layout match selected archetype?
     - Chart choice: appropriate chart types for data types?
     - KPI density: too many/too few KPIs per page?
     - Title quality: action-title grammar, conciseness
     - Filter usability: filters accessible and intuitive?
     - Navigation clarity: clear path between pages?
   - Produce per-page design score (reuse design scoring from Session 2)
   - Flag violations with specific recommendations

7. FACTORY MONITOR UI
   - /ui/factory page: live build/deploy progress
   - Deployment queue: pending, running, completed, failed tasks
   - Per-artifact: route decision, execution status, duration
   - Live VNC viewer embed: iframe to vnc_url for watching browser automation live (this is a demo killer feature)
   - Route decision log: why each route was chosen

8. RECONCILIATION UI
   - /ui/reconciliation page
   - Before/after comparison table (baseline vs candidate)
   - Delta classification badges (pass/tolerance/expected/defect/review)
   - Drill-through: click a row to see full query results
   - Comment and approve workflow per delta
   - Aggregate summary: % pass, % tolerance, % defect

9. VISUAL QA UI
   - /ui/visual-qa page
   - Screenshot slider: overlay before/after or blueprint vs actual
   - Design score breakdown per page
   - Interaction test results: pass/fail per test with screenshot evidence
   - Annotation: highlight differences on screenshots

10. ROUTE FITNESS DASHBOARD
    - /ui/lab/fitness page (or tab within factory page)
    - Per route, per object type: success rate, avg duration, failure reasons
    - Trend over time (chart)
    - Recommendations: which routes to prefer/avoid

11. TESTS
    - Route router: test selection logic, fallback chains, fitness scoring
    - DSP deployer: test _dev copy SQL generation, readback diff
    - SAC click guide: test instruction generation from blueprint
    - Reconciliation: test delta classification (exact, tolerance, expected, defect)
    - Visual comparison: test screenshot diff engine
    - Design QA: test scoring against known good/bad examples
    - Integration: end-to-end from tech spec -> deploy -> reconcile (can use mocked CDP for CI)

COMPLETION:
- Tech spec -> DSP Factory generates SQL + deployment manifest -> deploys to sandbox via CDP -> reads back and diffs
- Blueprint -> SAC Factory generates click guide + executes via CDP -> captures screenshots -> runs QA
- Reconciliation engine compares before/after query results with delta classification
- Visual QA shows screenshot comparison with design scores
- Factory monitor shows live progress with VNC viewer
- Route fitness tracked and displayed
- All scoped to workspace
- Create a git commit, push to Gitea, deploy via ops-bridge
```

---

## Session 6: Governance, Documentation, Artifact Lab, Polish

```
You are building the capstone session for Spec2Sphere — governance, documentation, the Artifact Lab, and end-to-end polish.

DESIGN SPEC: Read docs/superpowers/specs/2026-04-15-spec2sphere-design.md — Sections 7, 9, 12 (audit from multi-tenant spec)

PREREQUISITE: Sessions 1-5 complete. Full platform: multi-tenant foundation, knowledge engine, pipeline (requirements -> HLA -> tech spec -> blueprint -> test spec), DSP + SAC factories with reconciliation and visual QA.

WHAT TO BUILD:

1. AS-BUILT DOCUMENTATION GENERATOR (spec2sphere/governance/doc_generator.py)
   - Generate documentation from ACTUAL DEPLOYED STATE (not from the plan):
     - As-built technical doc: object definitions, SQL, dependencies, deployment order
     - As-built functional doc: business rules, KPI definitions, data flow narrative
     - SAC design doc: blueprint, actual screenshots, interaction map, design scores
   - Traceability matrix: requirement -> HLA decision -> tech spec object -> test case -> deployment result
   - Decision log: all architecture_decisions for the project with rationale
   - Reconciliation report: summary of all test results, accepted deltas, explanations
   - Release notes: what changed, why, who approved, known limitations
   - Output formats:
     - HTML (self-contained, single file with inline CSS — reuse existing report template pattern from migration/report.py)
     - PDF (via weasyprint — add to dependencies)
     - Markdown
   - Doc platform sync: push to BookStack/Confluence/Outline using existing doc_platform adapters

2. RELEASE PACKAGE ASSEMBLER (spec2sphere/governance/release.py)
   - Bundle for handover:
     - Deployment manifest
     - All generated artifacts (SQL, CSN, blueprints)
     - Reconciliation report
     - As-built documentation (technical + functional)
     - Approval records (who approved what, when)
     - Screenshots gallery
     - Decision log
     - Open issues register
   - Package as: ZIP file in artifact store, downloadable from UI
   - Version tracking: each release is a snapshot, previous releases retained

3. APPROVAL & RELEASE WORKFLOW
   - Final release approval gate (extends approval engine from Session 3):
     - Pre-conditions: HLA approved, tech spec approved, test spec approved, sandbox QA passed
     - Approval inputs displayed: all prior approvals, reconciliation summary, open issues
     - Outcomes: approved_for_production | approved_with_accepted_deltas | rework | redesign
   - Production deployment trigger (with explicit confirmation gate):
     - Only after release approval
     - Uses same factory engines as sandbox but with elevated safety checks
     - All routes require higher confidence threshold in production
     - Audit log entry for every production deployment action

4. ARTIFACT LEARNING LAB (spec2sphere/artifact_lab/)
   - lab_runner.py: orchestrates controlled experiments in sandbox
     - Create a reference object of specified type
     - Read back full definition
     - Modify one aspect (field, join, label, etc.)
     - Update the object
     - Read back again
     - Diff both versions
     - Store delta as learned pattern
   - experiment_tracker.py: CRUD for lab_experiments table
   - template_store.py: CRUD for learned_templates
     - Templates start unapproved
     - Graduation workflow: review experiment evidence -> mark approved -> available for production pipeline
   - mutation_catalog.py: catalog of safe/unsafe mutation types per object type
   - Lab supports both DSP and SAC:
     - DSP: view definition mutations (add field, change join, modify calculation)
     - SAC: story structure mutations (add page, add widget, change binding)
   - All experiments run in sandbox only (enforced by context envelope — lab_runner checks environment)
   - Integration with route_fitness: every lab execution updates fitness scores

5. SHARED LEARNING PROMOTION ENGINE (spec2sphere/governance/promotion.py)
   - Promote learnings up the knowledge hierarchy:
     - project -> customer: requires reviewer approval
     - customer -> global: requires anonymization + platform admin approval
   - Anonymization: strip customer-specific names, KPIs, object names from learned patterns
   - Promotion candidates auto-detected: patterns that appear across multiple projects/customers
   - Promotion UI: review candidate, see evidence, approve/reject
   - Anti-promotion rules enforced: no raw customer artifacts in global layer

6. CUSTOMER STYLE PROFILE LEARNING (spec2sphere/sac_factory/style_learning.py)
   - Track approved dashboard designs per customer
   - Learn preferences: favored layouts, chart types, density, title style
   - Update customer design profile based on approval patterns
   - Preference scores influence blueprint generation (future blueprints match customer taste)
   - All learning is per-customer, never leaks to other customers

7. REPORTS UI
   - /ui/reports page
   - Generated documentation browser: list all generated docs per project
   - Preview: render HTML docs inline
   - Export buttons: download HTML, PDF, Markdown
   - Doc platform sync status: show which docs are synced to BookStack/Confluence
   - Release packages: download ZIP bundles

8. LAB UI
   - /ui/lab page
   - Experiment log: list all lab experiments with status, object type, route
   - Experiment detail: input definition, output definition, diff visualization
   - Learned templates browser: view templates by platform/object_type, approval status
   - Template graduation: approve/reject buttons with evidence review
   - Mutation catalog: browse known safe/unsafe mutations per object type

9. AUDIT UI
   - /ui/audit page
   - Activity log: searchable, filterable by user, customer, project, action type, date range
   - Trace viewer: follow a trace_id through all related audit entries
   - Compliance summary: overview of approval coverage, missing approvals, policy violations

10. END-TO-END DEMO FLOW
    - Create a pre-configured demo scenario:
      - Sample customer "Horvath Demo" with design tokens
      - Sample BRS document (sales planning domain)
      - Pre-scanned DSP landscape (a few sample views)
    - One-click demo path: upload BRS -> auto-generate through pipeline stages -> show each artifact -> deploy to sandbox -> show reconciliation -> generate docs
    - This is the "wow factor" for the boss demo and customer pitches
    - Store demo fixtures in tests/fixtures/demo/

11. FINAL INTEGRATION + POLISH
    - End-to-end integration test: full pipeline from BRS upload to as-built documentation
    - Performance tuning: add database indexes, optimize heavy queries, Celery task priorities
    - Browser pool warmup: pre-start Chrome on first request to reduce latency
    - Error handling: graceful degradation when CDP fails (fall back to click guide)
    - Loading states: HTMX loading indicators for all long-running operations
    - Mobile responsiveness: basic responsive layout for cockpit (not priority but shouldn't break)
    - Module toggle verification: test that disabling each module cleanly hides its UI and routes

12. TESTS
    - Doc generation: test HTML/PDF/Markdown output for sample project data
    - Traceability: test full chain from requirement to deployment
    - Release package: test ZIP assembly with all components
    - Lab: test experiment create/read/diff cycle (mocked CDP for CI)
    - Template graduation: test approval workflow
    - Promotion: test anonymization, approval flow, anti-promotion rules
    - Style learning: test preference tracking and profile updates
    - End-to-end: full pipeline integration test

COMPLETION:
- Full pipeline works end-to-end: BRS -> requirements -> HLA -> tech spec + blueprint -> test spec -> deploy -> reconcile -> documentation
- As-built docs generated from actual deployed state
- Release packages downloadable as ZIP
- Artifact Lab runs experiments in sandbox, learns templates
- Shared learning promotion with anonymization
- Audit trail complete and browsable
- Demo scenario runs smoothly for boss/customer presentations
- All modules toggleable via config
- Create a git commit, push to Gitea, deploy via ops-bridge
```

---

## Session Dependency Map

```
Session 1: Platform Foundation
    ↓
Session 2: Intelligence Core + Knowledge
    ↓
Session 3: Pipeline — Requirements to Architecture
    ↓
Session 4: Pipeline — Tech Spec + Blueprint + Test Spec
    ↓
Session 5: DSP Factory + SAC Factory + Route Router
    ↓
Session 6: Governance, Docs, Lab, Polish
```

Strictly sequential. Each session depends on the previous.
