# Spec2Sphere Design Specification
## Horvath Analytics Delivery Factory — AI-Governed SAP Datasphere + SAC Delivery Accelerator

**Date:** 2026-04-15
**Version:** 1.0
**Status:** Design approved
**Codename:** Spec2Sphere
**Commercial name:** Horvath Analytics Delivery Factory
**Foundation:** SAP Doc Agent v1.1.0 (existing codebase)

---

## 1. Vision

Spec2Sphere is a modular, multi-tenant delivery accelerator that translates business requirements and legacy SAP knowledge into validated, deployable SAP Datasphere objects and SAP Analytics Cloud dashboards — with governance gates, confidence scoring, reconciliation testing, and as-built documentation at every stage.

**One pipeline, two entry points:**
- **Greenfield:** BRS/KPI intent -> architecture -> implementation -> validation -> documentation
- **Migration:** BW metadata -> semantic interpretation -> debt classification -> clean target design -> implementation -> validation -> documentation

**The pipeline is the same regardless of entry point.** Only the intake differs.

---

## 2. Commercial Positioning

**Phase 1 (now):** Horvath IP-enabled delivery accelerator. Used by consultants in projects. Not sold as software.

**Phase 2 (after 2-5 projects):** Consulting-led managed accelerator with optional accelerator fee.

**Phase 3 (after maturity):** License/subscription-based offering.

**Module-to-pricing mapping:**

| Commercial Package | Price Range | Modules Required |
|---|---|---|
| Assessment / Documentation / Opportunity Scan | 25-60k | Core + Intelligence |
| Pilot / MVP Domain | 80-180k | + Pipeline + one Factory |
| Modernization Factory (program) | project-based +10-20% | All modules |
| Managed Accelerator | 80-200k setup + 5-20k/mo | All + multi-tenant |

---

## 3. Module Structure

The application ships as one Docker Compose stack. Modules are Python packages enabled/disabled via configuration. No code changes needed to toggle features.

```
src/spec2sphere/
  core/           # Always on — scanning, docs, knowledge, standards, design system
  migration/      # BW semantic interpretation, debt classification (exists today)
  pipeline/       # BRS -> HLA -> Tech Spec -> SAC Blueprint, approval gates
  dsp_factory/    # DSP artifact generation, deployment, reconciliation
  sac_factory/    # SAC blueprint -> multi-route execution, visual/data/interaction QA
  governance/     # Approval workflow, confidence scoring, traceability, RBAC
  artifact_lab/   # Sandbox experimentation, template learning, route fitness
  tenant/         # Multi-tenant: context envelope, policy stack, scoped storage
  llm/            # LLM provider abstraction (exists today, 7 providers)
  web/            # FastAPI + HTMX + Jinja2 cockpit (exists today)
  tasks/          # Celery workers and scheduling (exists today)
  browser/        # Containerized Chrome pool management
```

**Feature flag configuration (config.yaml):**
```yaml
modules:
  core: true                # always on
  migration_accelerator: true
  dsp_factory: true
  sac_factory: true
  governance: true
  artifact_lab: true
  multi_tenant: true        # false = single-tenant mode (simpler)
```

When a module is disabled, its routes are not registered, its Celery tasks are not loaded, and its UI sections are hidden.

---

## 4. Architecture

### 4.1 System Diagram

```
+---------------------------------------------------------------+
|                    Cockpit (HTMX + Jinja2)                     |
|  Workspace Switcher | Pipeline Stages | Factory Monitor |      |
|  Reports & Docs     | Artifact Lab    | Reconciliation  |      |
+---------------------------------------------------------------+
|              Context Envelope Middleware                        |
|  tenant_id | customer_id | project_id | policy_stack           |
|  allowed_tools | allowed_indices | sensitivity_level           |
+---------------------------------------------------------------+
|                      Module Layer                              |
|  +----------+ +----------+ +---------+ +----------+           |
|  |Intelli-  | |Pipeline &| |DSP      | |SAC       |           |
|  |gence Core| |Architect.| |Factory  | |Factory   |           |
|  +----------+ +----------+ +---------+ +----------+           |
|  +----------+ +----------+ +---------+ +----------+           |
|  |Migration | |Artifact  | |Delivery | |Governance|           |
|  |Accel.    | |Lab       | |& Docs   | |& RBAC    |           |
|  +----------+ +----------+ +---------+ +----------+           |
+---------------------------------------------------------------+
|                    Service Layer                               |
|  LLM Providers | Scoped Retrieval (pgvector) | Policy Stack   |
|  Audit Log     | Browser Pool               | Artifact Store  |
+---------------------------------------------------------------+
|                     Data Layer                                 |
|  PostgreSQL 16 (+ pgvector) | Redis 7 | Local FS / S3         |
|  All tables tenant-scoped   | Prefixed | Per-tenant dirs       |
+---------------------------------------------------------------+
|              Containerized Browser (Xvfb + VNC)                |
|  Chrome + CDP -- DSP & SAC tenant automation                   |
|  One session per tenant/environment, credential-scoped         |
|  VNC exposed for debugging and demos                           |
+---------------------------------------------------------------+
```

### 4.2 Container Stack (docker-compose.yml)

| Container | Role | Port |
|---|---|---|
| `web` | FastAPI + HTMX UI | 8260 -> 8080 |
| `worker` | Celery: `scan` (4), `llm` (2) queues | - |
| `worker-chrome` | Celery: `chrome` (1), `sac` (1) queues | - |
| `scheduler` | Celery Beat: nightly QA, weekly reports | - |
| `postgres` | PostgreSQL 16 + pgvector | 5432 |
| `redis` | Queue + cache + rate limiting | 6379 |
| `chrome` | Xvfb + Chrome + VNC server | 5900 (VNC), 9222 (CDP) |

**Total: 7 containers. One `docker compose up`.**

The Win11 VM (192.168.0.70) remains as a fallback CDP target, configurable via:
```yaml
browser:
  mode: container   # or "remote"
  remote_url: "http://192.168.0.70:9222"  # fallback
  vnc_enabled: true
  vnc_port: 5900
```

### 4.3 Key Architectural Decisions

1. **Monolith, not microservices.** One codebase, one image, multiple entrypoints. Simpler to deploy at client sites, simpler to demo, simpler to develop.

2. **pgvector for embeddings.** No separate vector DB. Tenant-scoped via `WHERE tenant_id = :tid`. Good enough for thousands of objects per customer.

3. **Context Envelope as FastAPI middleware.** Resolved from session + URL before every request. Injected into all DB queries, LLM calls, retrieval, and tool invocations. No operation without a valid envelope.

4. **Celery for all async work.** Scan jobs, LLM-heavy pipeline stages, browser automation, reconciliation queries — all Celery tasks. UI polls via HTMX for progress.

5. **Artifact store is filesystem.** Generated specs, SQL files, blueprints, screenshots, reports stored in `{data_dir}/{tenant_id}/{project_id}/`. Git-backed optionally. Not in the DB.

6. **Policy stack resolves once per session.** Five layers (platform -> Horvath -> accelerator -> customer -> project) merged into one resolved ruleset, cached in Redis. Rebuilt on workspace switch.

7. **Adaptive implementation routes.** DSP and SAC factories both use a Route Router that picks the best execution path per artifact type. Routes: Click Guide, API/REST, CDP/Playwright, CSN/JSON import. Route fitness is tracked and learned over time in the Artifact Lab.

---

## 5. Multi-Tenant Data Model

### 5.1 Three-Layer Knowledge Architecture

```
+------------------------------------------+
|          Global Layer (shared)            |
|  Generic SAP patterns, Horvath defaults,  |
|  anti-patterns, route fitness, archetypes |
+------------------------------------------+
         |
+------------------------------------------+
|     Customer Layer (per customer)         |
|  Guidelines, naming, branding, model      |
|  inventory, architecture decisions,       |
|  approved templates, learned preferences  |
+------------------------------------------+
         |
+------------------------------------------+
|    Project Layer (per engagement)         |
|  Active BRS, HLA, Tech Spec, blueprints,  |
|  drafts, approvals, test results,         |
|  reconciliation outputs, iteration state  |
+------------------------------------------+
```

### 5.2 Core Database Tables

```sql
-- Tenancy
CREATE TABLE tenants (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE customers (
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    branding JSONB DEFAULT '{}',
    policy_overrides JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE projects (
    id UUID PRIMARY KEY,
    customer_id UUID REFERENCES customers(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    environment TEXT DEFAULT 'sandbox',  -- sandbox | test | production
    status TEXT DEFAULT 'active',
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Users & RBAC
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT DEFAULT 'consultant',  -- admin | architect | consultant | developer | reviewer | viewer
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE user_customer_access (
    user_id UUID REFERENCES users(id),
    customer_id UUID REFERENCES customers(id),
    role_override TEXT,  -- optional per-customer role
    PRIMARY KEY (user_id, customer_id)
);

-- Knowledge & Standards
CREATE TABLE knowledge_items (
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    customer_id UUID REFERENCES customers(id),  -- NULL = global
    project_id UUID REFERENCES projects(id),    -- NULL = customer-level
    category TEXT NOT NULL,  -- standard | pattern | anti_pattern | naming | template | glossary
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    source TEXT,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Landscape Inventory (DSP + SAC objects)
CREATE TABLE landscape_objects (
    id UUID PRIMARY KEY,
    customer_id UUID REFERENCES customers(id),
    project_id UUID REFERENCES projects(id),
    platform TEXT NOT NULL,  -- dsp | sac | bw
    object_type TEXT NOT NULL,
    object_name TEXT NOT NULL,
    technical_name TEXT,
    layer TEXT,
    metadata JSONB DEFAULT '{}',
    documentation TEXT,
    dependencies JSONB DEFAULT '[]',
    last_scanned TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Pipeline: Requirements
CREATE TABLE requirements (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    title TEXT NOT NULL,
    business_domain TEXT,
    description TEXT,
    source_documents JSONB DEFAULT '[]',
    parsed_entities JSONB DEFAULT '{}',
    parsed_kpis JSONB DEFAULT '[]',
    parsed_grain JSONB DEFAULT '{}',
    confidence JSONB DEFAULT '{}',
    open_questions JSONB DEFAULT '[]',
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Pipeline: Architecture Decisions
CREATE TABLE architecture_decisions (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    requirement_id UUID REFERENCES requirements(id),
    topic TEXT NOT NULL,
    choice TEXT NOT NULL,
    alternatives JSONB DEFAULT '[]',
    rationale TEXT,
    platform_placement TEXT,  -- dsp | sac | both
    status TEXT DEFAULT 'draft',  -- draft | pending_review | approved | rejected
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Pipeline: HLA
CREATE TABLE hla_documents (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    requirement_id UUID REFERENCES requirements(id),
    version INT DEFAULT 1,
    content JSONB NOT NULL,  -- structured HLA
    narrative TEXT,          -- prose version
    status TEXT DEFAULT 'draft',
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Pipeline: Technical Specifications
CREATE TABLE tech_specs (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    hla_id UUID REFERENCES hla_documents(id),
    version INT DEFAULT 1,
    objects JSONB NOT NULL,       -- technical object inventory
    dependency_graph JSONB,
    deployment_order JSONB,
    status TEXT DEFAULT 'draft',
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Pipeline: Technical Objects (individual artifacts)
CREATE TABLE technical_objects (
    id UUID PRIMARY KEY,
    tech_spec_id UUID REFERENCES tech_specs(id),
    project_id UUID REFERENCES projects(id),
    name TEXT NOT NULL,
    object_type TEXT NOT NULL,    -- relational_view | analytic_model | story | app | dimension | fact
    platform TEXT NOT NULL,       -- dsp | sac
    layer TEXT,                   -- raw | harmonized | mart | consumption
    definition JSONB NOT NULL,   -- full object specification
    generated_artifact TEXT,     -- SQL, CSN JSON, SAC blueprint YAML
    implementation_route TEXT,   -- click_guide | api | cdp | csn_import | manifest
    route_confidence FLOAT,
    status TEXT DEFAULT 'planned', -- planned | generating | generated | deploying | deployed | verified | failed
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Pipeline: SAC Blueprints
CREATE TABLE sac_blueprints (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    tech_spec_id UUID REFERENCES tech_specs(id),
    title TEXT NOT NULL,
    audience TEXT,
    archetype TEXT,
    style_profile JSONB DEFAULT '[]',
    pages JSONB NOT NULL,
    interactions JSONB DEFAULT '{}',
    performance_class TEXT DEFAULT 'standard',
    status TEXT DEFAULT 'draft',
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Testing & Reconciliation
CREATE TABLE test_specs (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    tech_spec_id UUID REFERENCES tech_specs(id),
    version INT DEFAULT 1,
    test_mode TEXT DEFAULT 'preservation',  -- preservation | improvement
    test_cases JSONB NOT NULL,
    tolerance_rules JSONB DEFAULT '{}',
    expected_deltas JSONB DEFAULT '[]',
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE reconciliation_results (
    id UUID PRIMARY KEY,
    test_spec_id UUID REFERENCES test_specs(id),
    project_id UUID REFERENCES projects(id),
    test_case_key TEXT NOT NULL,
    baseline_value JSONB,
    candidate_value JSONB,
    delta JSONB,
    delta_status TEXT,  -- pass | within_tolerance | expected_change | probable_defect | needs_review
    explanation TEXT,
    approved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Visual QA (SAC)
CREATE TABLE visual_qa_results (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    blueprint_id UUID REFERENCES sac_blueprints(id),
    page_id TEXT NOT NULL,
    screenshot_path TEXT,
    expected_layout TEXT,
    result TEXT,  -- pass | major_diff | minor_diff | missing_element
    differences JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Artifact Lab
CREATE TABLE lab_experiments (
    id UUID PRIMARY KEY,
    customer_id UUID REFERENCES customers(id),
    platform TEXT NOT NULL,      -- dsp | sac
    object_type TEXT NOT NULL,
    experiment_type TEXT NOT NULL, -- create | modify | delete | read_back
    input_definition JSONB,
    output_definition JSONB,
    diff JSONB,
    route_used TEXT,
    success BOOLEAN,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE learned_templates (
    id UUID PRIMARY KEY,
    customer_id UUID REFERENCES customers(id),  -- NULL = global
    platform TEXT NOT NULL,
    object_type TEXT NOT NULL,
    template_definition JSONB NOT NULL,
    mutation_rules JSONB DEFAULT '{}',
    deployment_hints JSONB DEFAULT '{}',
    confidence FLOAT DEFAULT 0.5,
    approved BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Route Fitness Tracking
CREATE TABLE route_fitness (
    id UUID PRIMARY KEY,
    customer_id UUID REFERENCES customers(id),  -- NULL = global
    platform TEXT NOT NULL,
    object_type TEXT NOT NULL,
    action TEXT NOT NULL,        -- create | update | read | delete | screenshot
    route TEXT NOT NULL,         -- click_guide | api | cdp | csn_import | manifest
    attempts INT DEFAULT 0,
    successes INT DEFAULT 0,
    avg_duration_seconds FLOAT,
    last_failure_reason TEXT,
    fitness_score FLOAT DEFAULT 0.5,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Approvals (generic)
CREATE TABLE approvals (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    artifact_type TEXT NOT NULL,  -- hla | tech_spec | test_spec | sac_blueprint | release
    artifact_id UUID NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending | approved | rejected | rework
    reviewer_id UUID REFERENCES users(id),
    comments TEXT,
    checklist JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- Audit Log
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID,
    customer_id UUID,
    project_id UUID,
    user_id UUID,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    policy_stack_version TEXT,
    retrieval_sources JSONB,
    tool_calls JSONB,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Design System (SAC)
CREATE TABLE design_tokens (
    id UUID PRIMARY KEY,
    customer_id UUID REFERENCES customers(id),  -- NULL = Horvath default
    token_type TEXT NOT NULL,   -- color | typography | spacing | density | emphasis
    token_name TEXT NOT NULL,
    token_value JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(customer_id, token_type, token_name)
);

CREATE TABLE layout_archetypes (
    id UUID PRIMARY KEY,
    customer_id UUID REFERENCES customers(id),  -- NULL = Horvath default
    name TEXT NOT NULL,
    description TEXT,
    archetype_type TEXT,  -- exec_overview | variance_analysis | drill_page | table_first | guided_analysis
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 5.3 Context Envelope

Every request resolves a context envelope before any business logic executes:

```python
@dataclass
class ContextEnvelope:
    tenant_id: UUID
    customer_id: UUID
    project_id: UUID | None
    environment: str                    # sandbox | test | production
    user_id: UUID
    role: str
    allowed_knowledge_layers: list[str] # ["global", "customer", "project"]
    allowed_connectors: list[str]
    active_policy_stack: ResolvedPolicyStack
    active_design_profile: str | None
    sensitivity_level: str              # public | internal | confidential | restricted
    trace_id: str
```

FastAPI dependency:
```python
async def get_context(request: Request, db: AsyncSession) -> ContextEnvelope:
    # 1. Resolve tenant + customer + project from session/URL
    # 2. Check user access
    # 3. Build policy stack (5 layers, cached in Redis)
    # 4. Determine allowed knowledge layers, connectors, tools
    # 5. Return envelope
    ...
```

All DB queries use `ScopedQuery(ctx)` which automatically adds tenant/customer/project WHERE clauses. The LLM service receives the envelope and constructs prompts with explicit scope instructions.

---

## 6. The Pipeline (Stages 0-9)

### 6.1 Stage Overview

```
Stage 0: Context & Standards Intake
Stage 1: Requirement Intake & Semantic Parsing
Stage 2: HLA Generation (cross-platform: DSP + SAC)
Stage 3: Technical Specification / SAC Blueprint
Stage 4: Test Specification Generation
Stage 5: Build Artifact Generation
Stage 6: Sandbox Deployment (+ _dev copy pattern)
Stage 7: Reconciliation & QA
Stage 8: Approval & Release
Stage 9: As-Built Documentation
```

### 6.2 Stage 0 — Context & Standards Intake

**Input:** Development guidelines (PDF/Word/Markdown), naming conventions, anti-pattern catalog, existing DSP/SAC tenant metadata snapshot, Horvath design guide, customer branding assets.

**Processing:**
- PDF/Word ingestion via pdfplumber + python-docx (exists today)
- LLM extraction of structured rules from prose documents
- Embedding generation for semantic search (pgvector)
- DSP tenant scan via MCP + CDP
- SAC tenant scan via API + CDP
- Object dependency graph construction
- Design token extraction from customer style guides

**Output:** Populated knowledge_items table, landscape_objects inventory, design_tokens, layout_archetypes. The knowledge base that all later stages reason over.

**This stage runs on every new customer onboarding and can be re-run incrementally.**

### 6.3 Stage 1 — Requirement Intake & Semantic Parsing

**Input:** BRS document, workshop notes, KPI catalog, report mockups, legacy BW metadata (if migration).

**Processing:**
- Document parsing + chunking
- LLM extraction: entities, facts, KPIs, grain, time semantics, security implications, ambiguities
- For migration: BW metadata interpretation via existing migration/ module (chain analysis, classifier, interpreter)
- Debt/workaround classification (migration only)
- Confidence scoring per extracted element
- Open questions register generation

**Output:** Populated requirements record with structured parsed_entities, parsed_kpis, parsed_grain, confidence map, and open_questions.

### 6.4 Stage 2 — HLA Generation

**Input:** Approved requirement interpretation + landscape inventory + knowledge base.

**Key innovation: cross-platform placement.**
The architect agent knows both DSP and SAC and makes deliberate decisions about where each piece lives:
- Calculations in DSP views vs SAC calculated measures
- Filters as DSP input parameters vs SAC story filters
- Hierarchies in DSP vs SAC hierarchy dimensions
- Aggregation at DSP level vs SAC runtime

**Processing:**
- Domain decomposition
- Layered architecture proposal (RAW -> HARMONIZED -> MART -> CONSUMPTION)
- Fact/dimension strategy
- SAC reporting strategy (story vs analytic app vs custom widget)
- Integration point design
- Architecture decision log generation

**Output:** HLA document (structured + narrative), architecture_decisions records.

**Approval gate:** Human review required before Stage 3.

### 6.5 Stage 3 — Technical Specification + SAC Blueprint

**Input:** Approved HLA + knowledge base + landscape inventory.

**DSP output:**
- Technical object inventory (technical_objects records)
- Naming-compliant object IDs
- Source-to-target mapping
- Joins, calculations, transformations
- Dependency graph + deployment order
- SQL for each view (generated via existing generator.py, enhanced)

**SAC output:**
- SAC blueprint (canonical YAML representation)
- Page/widget layout per archetype
- Widget-to-model bindings
- Filter strategy
- Navigation map
- Design tokens applied
- Implementation route recommendation per artifact

**Output:** tech_specs record, technical_objects records, sac_blueprints record.

**Approval gate:** Technical review required before Stage 4.

### 6.6 Stage 4 — Test Specification Generation

**Test modes:**
- **Preservation:** new implementation must match current behavior
- **Improvement:** approved redesign, differences are expected and documented

**DSP test categories:**
- Structural tests (object existence, field types, grain)
- Data volume tests (row counts, distinct counts, null distributions)
- Business aggregate tests (KPI totals by important cuts)
- Edge-case tests (empty periods, missing data, null/zero logic)
- Sample-level trace tests

**SAC test categories:**
- Data regression (KPI values match DSP source)
- Visual regression (screenshots match blueprint layout)
- Interaction QA (filters, navigation, drill behavior)
- Design rules QA (archetype compliance, density, readability)
- Performance QA (load time, widget count, scripting complexity)

**The _dev copy pattern for safe testing (DSP):**
1. Copy target DSP view to `{viewname}_DEV`
2. Apply changes to `_DEV` version only
3. Run test queries against both original and `_DEV`
4. Compare results
5. If tests pass, apply changes to real view (with approval)
6. Clean up `_DEV` copies

**Safe testing for SAC:**
SAC does not support direct view copying like DSP. Instead:
1. Create candidate story/app in a sandbox/test space (separate from production)
2. Bind to same data model as production version
3. Run data regression queries against both versions
4. Capture screenshots for visual comparison
5. After approval, transport to production space or recreate there

**Output:** test_specs record with executable query packs.

### 6.7 Stage 5 — Build Artifact Generation

**DSP artifacts:**
- SQL view definitions (template-driven for simple, LLM-assisted for complex)
- CSN/JSON object definitions (learned via Artifact Lab)
- Deployment manifest with dependency ordering

**SAC artifacts:**
- Canonical blueprint YAML
- Route-specific execution plans per artifact:
  - **Click Guide:** step-by-step instructions with element references
  - **API/REST:** supported SAC API calls for metadata/transport operations
  - **CDP/Playwright:** automated UI interaction sequences
  - **CSN/JSON import:** package assembly for import where supported

**Route Router logic:**
```python
def select_route(artifact, action, env, fitness_db) -> Route:
    candidates = get_supported_routes(artifact.type, action)
    for route in candidates:
        route.score = fitness_db.get_score(artifact.type, action, route)
        if env == "production":
            route.score *= route.safety_multiplier
    return max(candidates, key=lambda r: r.score)
```

**Output:** Generated artifacts in artifact store, deployment manifest.

### 6.8 Stage 6 — Sandbox Deployment

**DSP deployment:**
1. Deploy `_DEV` copies first (safe testing)
2. Execute via selected route (CDP, REST API, CSN import)
3. Read back deployed object definitions
4. Compare expected vs actual (diff)
5. Store deployment report

**SAC deployment:**
1. Create in sandbox/test space
2. Execute via selected route (mixed-route: manifest for structure, API for metadata, CDP for UI-only steps)
3. Capture screenshots of each page
4. Validate structure against blueprint

**Browser pool management:**
- One Chrome session per tenant/environment
- Session isolation (no cross-tenant cookies/state)
- VNC available for live demo viewing
- Screenshot capture for QA evidence

**Output:** Sandbox deployment report, structural validation report, screenshots.

### 6.9 Stage 7 — Reconciliation & QA

**Data reconciliation (DSP):**
1. Execute baseline queries (before-change or existing model)
2. Execute candidate queries (new/changed model)
3. Compare results automatically
4. Classify deltas: pass | within_tolerance | expected_change | probable_defect | needs_review
5. Generate reconciliation report

**Visual reconciliation (SAC):**
1. Capture candidate screenshots
2. Compare against blueprint expectations
3. Check page completeness, widget presence, layout alignment
4. Generate visual regression report

**Interaction QA (SAC):**
1. Automated filter testing via CDP
2. Navigation flow validation
3. Drill behavior verification
4. Script execution testing (for analytic apps)

**Design QA (SAC):**
- Archetype compliance scoring
- Chart choice validation
- KPI count per page
- Title quality assessment (action-title grammar)
- Layout density check
- Overall design quality score

**Output:** reconciliation_results records, visual_qa_results records, QA reports.

### 6.10 Stage 8 — Approval & Release

**Approval inputs required:**
- HLA approved version
- Tech Spec / SAC Blueprint approved version
- Test Spec approved version
- Sandbox validation results
- Reconciliation report
- Open issue register

**Approval outcomes:**
- Approved for production
- Approved with accepted deltas (documented)
- Rework required
- Redesign required

**Production deployment** only after explicit GO. Uses the same route system as sandbox, but with elevated safety checks and approval requirements.

### 6.11 Stage 9 — As-Built Documentation

**Generated automatically from what was actually deployed (not from the plan):**
- As-built technical documentation (object definitions, SQL, dependencies)
- As-built functional documentation (business rules, KPI definitions, data flow)
- Reconciliation report (what changed, why, who approved)
- Decision log (all architecture decisions with rationale)
- Traceability matrix (requirement -> HLA -> tech spec -> object -> test)
- Release notes
- SAC design documentation (blueprint, screenshots, interaction map)

**Output formats:** HTML (self-contained), PDF, Markdown. Optionally synced to doc platforms (BookStack, Confluence, Outline) via existing adapters.

---

## 7. The Artifact Learning Lab

### 7.1 Purpose

Learn platform-specific artifact syntax, mutation behavior, and deployment patterns through controlled sandbox experimentation. Not for learning business semantics — for learning how DSP and SAC actually behave.

### 7.2 Learning Loop

```
1. Create a reference object in sandbox space
2. Read back the full object definition
3. Modify one aspect
4. Update the object (via selected route)
5. Read back again
6. Diff both versions
7. Store the delta as a reusable pattern
8. Update route fitness scores
```

### 7.3 What It Learns

**DSP:**
- Required vs optional fields in view definitions
- CSN/JSON patterns per object type
- Behavior of labels, joins, associations, parameters
- Dependency sequencing requirements
- Safe vs unsafe mutation types
- Which routes work for which operations

**SAC:**
- Story/app JSON structure patterns
- Widget configuration patterns
- Theme and styling application behavior
- Transport packaging requirements
- Which operations work via API vs need CDP
- Fragile UI automation steps to avoid

### 7.4 Template Graduation

Learned templates start with `approved = false`. Only after explicit review and validation do they get promoted to `approved = true` and become available for the main build pipeline.

### 7.5 Route Fitness

Every route execution (success or failure) updates the `route_fitness` table. Over time, the Route Router gets better at picking the right implementation path per artifact type, per tenant.

---

## 8. SAC Design System

### 8.1 Design Token Layers

```
Horvath Default -> Customer Override
```

**Token types:**
- **Color roles:** primary, secondary, accent, success, warning, danger, neutral, background, surface, text
- **Typography roles:** heading, subheading, body, caption, kpi_value, kpi_label
- **Spacing classes:** compact, standard, spacious
- **Density classes:** dense (analyst), medium (management), sparse (executive)
- **Emphasis roles:** highlight, variance_positive, variance_negative, target_line

### 8.2 Layout Archetypes

| Archetype | Use Case | Structure |
|---|---|---|
| exec_overview | Executive KPI dashboard | KPI header + 3 panels |
| management_cockpit | Multi-tab management view | Tab navigation + filter sidebar |
| variance_analysis | Plan vs actual | Waterfall + variance table |
| regional_performance | Geographic breakdown | Map/bar + drill table |
| product_drill | Product hierarchy analysis | Filter left + table/chart combo |
| driver_analysis | KPI driver breakdown | Waterfall + driver table |
| exception_dashboard | Alert/exception focus | Traffic light + exception list |
| table_first | Analyst workspace | Dense table + mini charts |
| guided_analysis | App-like exploration | Step navigation + dynamic panels |

### 8.3 Widget Archetypes

KPI tiles, trend tiles, variance charts, ranked bars, waterfall views, driver tables, matrix tables, detail tables, commentary panels, navigation buttons, filter sidebars.

Each archetype defines: required bindings, recommended size, density compatibility, chart type selection rules.

### 8.4 Design Quality Score

Every generated or imported dashboard gets a score (0-100) based on:
- Archetype compliance (30%)
- Layout consistency & readability (25%)
- Chart choice appropriateness (15%)
- Title quality (10%)
- Filter usability (10%)
- Navigation clarity (10%)

---

## 9. Multi-Tenant Deep Dive

### 9.1 Policy Stack Resolution

```
Layer 1: Platform base rules (security, tenancy, logging, tool safety)
Layer 2: Horvath default rules (methodology, best practices, baseline standards)
Layer 3: Shared accelerator rules (generic SAP implementation/design rules)
Layer 4: Customer override rules (naming, branding, architecture, governance)
Layer 5: Project exception rules (specific decisions for one engagement)
```

Resolution: later layers override earlier layers. Conflicts are logged. The resolved stack is cached in Redis per session.

### 9.2 Scoped Retrieval

```python
async def scoped_search(ctx: ContextEnvelope, query: str, top_k: int = 10):
    # Search priority: project > customer > global
    results = []
    if "project" in ctx.allowed_knowledge_layers and ctx.project_id:
        results += await search_knowledge(query, project_id=ctx.project_id, top_k=top_k)
    if "customer" in ctx.allowed_knowledge_layers:
        results += await search_knowledge(query, customer_id=ctx.customer_id, top_k=top_k)
    if "global" in ctx.allowed_knowledge_layers:
        results += await search_knowledge(query, customer_id=None, top_k=top_k)
    # Deduplicate, re-rank by relevance + specificity, tag source layer
    return rerank_and_tag(results, top_k)
```

Every retrieved chunk is tagged with its source layer for transparency.

### 9.3 Workspace Switching

When the user switches customer or project:
1. Terminate old scoped sessions
2. Clear scoped Redis caches
3. Rebuild policy stack
4. Remap retrieval indices
5. Remap connector credentials
6. Rebuild prompt context
7. Refresh cockpit UI (all badges, artifact lists, pipeline state)

Technically a hard reset. UX-wise, a dropdown selection.

### 9.4 Shared Learning Promotion

```
Project learning -> Customer learning (requires approval)
Customer learning -> Global learning (requires anonymization + approval)
```

**Promotion criteria:**
- Generic enough (no customer-specific names/KPIs)
- Confidentiality-safe
- Reusable across tenants
- Approved by platform governance role

---

## 10. Cockpit UI

### 10.1 Page Structure

The cockpit extends the existing HTMX + Jinja2 web UI with new sections:

| Page | Module | Purpose |
|---|---|---|
| **Dashboard** | Core | Overview: active projects, pipeline progress, recent activity |
| **Workspace** | Tenant | Customer/project selector, environment switcher, active badges |
| **Knowledge** | Core | Browse/search knowledge base, standards, design tokens |
| **Landscape** | Core | DSP + SAC object inventory, dependency graph, design scores |
| **Pipeline** | Pipeline | Stage-by-stage progress: intake -> HLA -> tech spec -> build -> QA -> release |
| **Requirements** | Pipeline | BRS viewer, parsed entities, KPIs, open questions, confidence map |
| **Architecture** | Pipeline | HLA viewer, decision log, cross-platform placement diagram |
| **Tech Spec** | Pipeline | Object inventory, dependency graph, SQL viewer, blueprint viewer |
| **Factory** | DSP/SAC Factory | Build progress, route decisions, deployment status |
| **Lab** | Artifact Lab | Experiment log, learned templates, route fitness dashboard |
| **Reconciliation** | Governance | Before/after comparison, delta classification, approval workflow |
| **Visual QA** | SAC Factory | Screenshot comparison, design score, interaction test results |
| **Reports** | Governance | Generated documentation, export options (HTML/PDF/Markdown) |
| **Approvals** | Governance | Pending approvals, checklists, sign-off workflow |
| **Settings** | Core | LLM config, module toggles, browser config, user management |
| **Audit** | Governance | Activity log, trace viewer, compliance reports |

### 10.2 Design Language

Existing Horvath brand: petrol (#05415A), gold (#C8963E), Georgia headings, Inter body. Extended with:
- Pipeline stage indicators (progress bar with stage badges)
- Confidence heatmaps (green/yellow/red)
- Diff viewers (side-by-side, inline)
- Screenshot comparison (slider overlay)
- Dependency graph (vis.js, already integrated)

---

## 11. Rename Strategy

The package renames from `sap_doc_agent` to `spec2sphere`:

```
src/sap_doc_agent/ -> src/spec2sphere/
```

- Python package: `spec2sphere`
- CLI entry point: `spec2sphere` (alias: `sap-doc-agent` for backwards compat)
- Docker image: `spec2sphere`
- Git repo: stays `sap-doc-agent` for now (rename later if needed)

---

## 12. Dev Sessions

### Session 1: Platform Foundation
**Scope:** Rename + multi-tenant data model + context envelope + module system + containerized Chrome

**What gets built:**
- Rename `sap_doc_agent` -> `spec2sphere` across entire codebase
- Alembic setup + initial migration with full schema from Section 5.2
- Context envelope middleware (FastAPI dependency)
- Scoped query helper (`ScopedQuery(ctx)`)
- Policy stack engine (5-layer resolution, Redis-cached)
- Feature flag module system (config.yaml -> route registration)
- Tenant/customer/project CRUD API + UI pages
- User model + RBAC (role-based route guards)
- Workspace switcher UI component (dropdown + hard reset)
- Containerized Chrome service (Dockerfile: Xvfb + Chrome + VNC)
- Browser pool manager (session-per-tenant, CDP connection broker)
- Audit log middleware (every request logged with context)
- Update docker-compose.yml with chrome container
- All existing tests updated for new package name
- New tests: context envelope, policy stack, scoped queries, RBAC, browser pool

**Existing code preserved:** LLM providers, migration module, scanner, agents, web UI, Celery tasks — all moved under new package name, existing functionality unbroken.

**Entry point:** This session transforms the single-tenant doc agent into a multi-tenant platform shell. Every subsequent session builds modules on top of this foundation.

---

### Session 2: Intelligence Core + Knowledge Engine
**Scope:** Tenant scanning, knowledge graph, standards intake, design system, documentation audit

**What gets built:**
- Knowledge item CRUD + pgvector embedding storage + scoped semantic search
- Standards intake pipeline: PDF/Word -> LLM extraction -> structured rules -> knowledge_items
- Design token system: Horvath defaults + customer override layer
- Layout archetype definitions (9 archetypes from Section 8.2)
- Widget archetype definitions
- DSP tenant scanner enhancement: full object inventory -> landscape_objects table (scoped)
- SAC tenant scanner: content inventory via API + CDP (stories, apps, models, folders, transports)
- Object dependency graph builder (cross-platform: DSP + SAC objects in one graph)
- Documentation audit engine: compare existing object docs against loaded standards, produce scorecard
- Design quality scoring engine for SAC content (Section 8.4)
- Knowledge browser UI page (search, browse by category, filter by layer)
- Landscape explorer UI page (DSP + SAC objects, dependency graph, design scores)
- Migration grouping recommendations (wave planning based on criticality/complexity/debt)
- Tests: knowledge search scoping (no cross-tenant leakage), scanner integration, scoring

**Builds on:** Session 1 (context envelope, scoped queries, browser pool, tenant model)

---

### Session 3: Pipeline — Requirement to Architecture
**Scope:** BRS intake, semantic parsing, HLA generation, cross-platform architecture, approval gates

**What gets built:**
- Requirement intake engine: parse BRS documents (PDF/Word/Markdown/plain text)
- Semantic parser: LLM-powered extraction of entities, KPIs, facts, grain, time/version semantics, security implications, ambiguities
- Confidence scoring per extracted element
- Open questions register with auto-detection of ambiguity
- HLA generator: produces structured architecture from requirements + landscape knowledge
- Cross-platform placement engine: decides DSP vs SAC for each artifact (calculations, filters, hierarchies, aggregations)
- Architecture decision log generator (choice + alternatives + rationale per decision)
- BW modernization pre-flow integration: connect existing migration/ module as an alternative intake path (BW metadata -> semantic interpretation -> cleaned BRS equivalent)
- Migration strategy mode assignment per object/domain: replicate | clean | redesign
- Approval gate workflow: submit for review -> pending -> approved/rejected/rework
- Approval checklist templates (HLA checklist from appendix)
- Pipeline UI: stage-by-stage progress view with current stage highlighted
- Requirements UI: parsed entities, KPIs, grain, confidence heatmap, open questions
- Architecture UI: HLA viewer, decision log, placement diagram (DSP vs SAC split)
- Approval UI: review artifact, checklist, comment, approve/reject
- Notification system: when artifact is ready for review (in-app + optional email)
- Tests: requirement parsing, HLA generation quality, approval state machine, scoping

**Builds on:** Session 2 (knowledge base for landscape-aware HLA generation, standards for compliance checking)

---

### Session 4: Pipeline — Tech Spec + SAC Blueprint + Test Spec
**Scope:** Technical specification, SAC blueprint, test specification generation

**What gets built:**
- Tech spec generator: approved HLA -> detailed object inventory with naming-compliant IDs, source-to-target mapping, joins, calculations, dependency graph, deployment order
- Enhance existing migration/generator.py to work within pipeline flow (reuse SQL generation, sql_validator)
- SAC blueprint generator: approved HLA -> canonical YAML blueprint with pages, widgets, bindings, filters, navigation, style profile applied
- Story vs Analytic App vs Custom Widget decision engine (rules from Section 9.2 of SAC spec)
- Test spec generator: tech spec -> executable test cases (both DSP and SAC)
- _dev copy pattern logic: generate copy commands, test queries for both original and _DEV views
- Golden query catalog: curated high-value regression queries per domain
- Tolerance rule engine: exact | absolute | percentage | expected_delta
- Tech spec UI: object inventory table, dependency graph (vis.js), SQL viewer (CodeMirror), deployment order
- SAC blueprint UI: page previewer (archetype mockup rendering), widget list, interaction map
- Test spec UI: test case browser, tolerance settings, expected deltas editor
- Diff viewer: compare versions of specs side-by-side
- Tests: tech spec generation, blueprint generation, test case generation, _dev naming

**Builds on:** Session 3 (approved HLA as input, approval workflow reused for tech spec gate)

---

### Session 5: DSP Factory + SAC Factory + Route Router
**Scope:** Artifact generation, multi-route execution, sandbox deployment, reconciliation, visual QA

**What gets built:**
- Route Router: selects best execution route per artifact/action based on route_fitness scores + environment + risk
- DSP artifact generator: SQL view definitions (enhanced existing generator), CSN/JSON definitions (template + Lab-learned)
- DSP deployment engine: execute via CDP or REST API, with _dev copy safety pattern
- DSP read-back + diff: export deployed object definition, compare against expected
- SAC click guide generator: step-by-step human instructions with element references
- SAC manifest/package builder: canonical blueprint -> structured package
- SAC API adapter: supported metadata/transport operations
- SAC Playwright automation: UI interaction sequences for sandbox
- SAC screenshot capture + visual comparison engine (pixel diff + structural diff)
- Data reconciliation engine: execute baseline vs candidate queries, compare, classify deltas
- Interaction QA engine: automated filter/navigation/drill testing via CDP
- Design QA engine: archetype compliance, chart choice, density, title quality scoring
- Mixed-route execution orchestrator: one dashboard can use multiple routes
- Factory monitor UI: build progress, route decisions, deployment status, live VNC viewer embed
- Reconciliation UI: before/after comparison table, delta classification, drill-through, approval
- Visual QA UI: screenshot slider comparison, design score breakdown, interaction test results
- Route fitness dashboard: success rates, durations, fragility warnings per route/object type
- Tests: route selection logic, reconciliation classification, visual diff, deployment flow

**Builds on:** Session 4 (tech specs + blueprints as input), Session 1 (browser pool for CDP), Session 2 (landscape awareness for read-back comparison)

---

### Session 6: Governance, Documentation, Artifact Lab, Polish
**Scope:** As-built docs, traceability, Artifact Lab, release workflow, shared learning promotion, final polish

**What gets built:**
- As-built documentation generator: generates from actual deployed state (not plan), covers both DSP + SAC
- Traceability matrix generator: requirement -> HLA -> tech spec -> object -> test (full chain)
- Decision log aggregator: all architecture decisions across a project with rationale
- Release package assembler: deployment manifest + reconciliation report + as-built docs + approval records
- Report export: self-contained HTML, PDF (via weasyprint or similar), Markdown
- Doc platform sync: push as-built docs to BookStack/Confluence/Outline (existing adapters)
- Artifact Lab: controlled create/read/modify/diff loops in sandbox
- Lab experiment tracking + learned template storage
- Template graduation workflow (unapproved -> reviewed -> approved)
- Route fitness learning: update scores from every deployment execution
- Shared learning promotion engine: customer -> global with anonymization + approval gate
- Customer style profile learning: track approved designs, preferred layouts, chart choices
- Reports UI: generated documentation browser, export buttons, doc platform sync status
- Lab UI: experiment log, learned templates browser, route fitness analytics
- Audit UI: activity log with filters, trace viewer, compliance summary
- Feature flag UI: module toggles in settings page
- End-to-end demo flow: BRS upload -> pipeline stages -> deployed + documented (one-click demo path)
- Final integration tests: full pipeline flow from requirement to documentation
- Performance tuning: query optimization, Celery task prioritization, browser pool warmup

**Builds on:** All previous sessions. This is the capstone that ties everything together.

---

## 13. Migration from SAP Doc Agent

### 13.1 What Gets Kept
- LLM provider abstraction (7 providers) -> moved to `spec2sphere/llm/`
- Migration module (chain analysis, classifier, interpreter, architect, generator, sql_validator) -> moved to `spec2sphere/migration/`
- Scanner module (CDP, MCP, orchestrator) -> moved to `spec2sphere/core/scanner/`
- Agent module (doc_qa, code_quality, brs_traceability, report_generator) -> moved to `spec2sphere/core/agents/`
- Doc platform adapters -> moved to `spec2sphere/core/doc_platform/`
- Git backend adapters -> moved to `spec2sphere/core/git_backend/`
- Web UI framework (FastAPI + Jinja2 + HTMX + Tailwind) -> extended
- Celery task infrastructure -> extended with new queues
- Standards module -> enhanced into full knowledge engine
- Docker Compose structure -> extended with chrome container

### 13.2 What Gets Replaced
- Single-tenant DB schema -> multi-tenant schema with context envelope
- Simple auth (shared password) -> user model with RBAC
- File-based object storage -> PostgreSQL landscape_objects + filesystem artifacts
- No approval workflow -> full approval gate system

### 13.3 Backwards Compatibility
- `sap-doc-agent` CLI alias preserved
- Existing config.yaml format supported (auto-migrated to new format)
- Single-tenant mode available when `multi_tenant: false`
- All existing API endpoints preserved under `/api/v1/` (legacy endpoints)

---

## 14. Technology Stack Summary

| Component | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, Uvicorn |
| Frontend | Jinja2, HTMX, Tailwind CSS (CDN), vis.js, CodeMirror |
| Database | PostgreSQL 16 + pgvector |
| Queue | Redis 7 + Celery |
| LLM | 7 providers: Azure OpenAI, OpenAI, Anthropic, Gemini, vLLM, Ollama, Router |
| Browser | Containerized Chrome (Xvfb + VNC) + fallback Win11 VM |
| SAP DSP | MCP tools + CDP/Playwright + REST API |
| SAP SAC | Content API + CDP/Playwright + transport packaging |
| SAP BW | ABAP scanner programs (existing) |
| Embeddings | pgvector (dimension configurable per LLM provider: 1536 for OpenAI, 768 for nomic-embed, etc.) |
| Auth | bcrypt + itsdangerous sessions + RBAC |
| Docs | pdfplumber, python-docx, weasyprint (PDF export) |
| Monitoring | OpenTelemetry + Prometheus + structured JSON logs |
| Config | YAML (Pydantic validation) + env vars |

---

## 15. Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| DSP object definition format changes between versions | High | Artifact Lab learns per-tenant; templates version-pinned |
| SAC UI automation fragility | Medium | Route Router falls back to click guide; VNC for debugging |
| Cross-tenant data leakage | Critical | Context envelope enforced at middleware level; scoped queries; audit log |
| LLM hallucination in architecture/spec generation | High | Confidence scoring; evidence links; mandatory human approval gates |
| Blind technical debt replication (BW migration) | High | Debt/workaround classifier; migration strategy modes; reconciliation |
| Over-trust in polished AI artifacts | Medium | Structured artifacts with open questions; reconciliation testing |
| Demo complexity (too many moving parts) | Medium | End-to-end demo flow with pre-configured scenario |

---

## 16. Success Metrics

| Category | Metric |
|---|---|
| Delivery | Time from BRS to approved tech spec |
| Delivery | Time from tech spec to deployed sandbox |
| Delivery | Documentation generation time vs manual |
| Quality | % objects compliant with standards on first pass |
| Quality | Reconciliation defects caught before production |
| Quality | Design quality score improvement over iterations |
| Learning | Template coverage per object type |
| Learning | Route fitness improvement over time |
| Learning | Lab experiment success rate |
| Business | Consultant productivity uplift |
| Business | Reuse rate of architecture/object templates |
| Business | Assessment-to-project conversion rate |
