# SAP Doc Agent — Web UI Design Spec

## Goal

Replace the current minimal inline-HTML landing page with a professional, modern web UI that serves as both an operational dashboard (for Henning) and a client-facing product demo (for Horvath clients). The UI provides three tiers of interaction: read-only monitoring, operational controls, and full system configuration.

## Architecture

**Stack:** FastAPI + Jinja2 templates + Tailwind CSS (CDN) + HTMX + vis.js (dependency graph) + CodeMirror (config editor, CDN)

No build step. No node_modules. All frontend dependencies loaded via CDN. The UI is server-rendered with HTMX for reactive partial-page updates. One JS file for the dependency graph (vis.js). One JS file for the config editor (CodeMirror).

**Why this stack:**
- Jinja2 is native to FastAPI — no new toolchain
- HTMX gives SPA-like UX (partial page swaps, polling, SSE) without JavaScript complexity
- Tailwind via CDN provides professional styling with utility classes
- vis.js and CodeMirror are the only client-side JS — loaded via CDN script tags
- No build step means the Docker image stays simple

**Routing:**
- `/ui/*` — all UI page routes (HTML responses, HTMX fragments)
- `/api/*` — existing JSON API (unchanged, still serves M365 Copilot)
- `/` — redirects to `/ui/dashboard` for browser requests (keeps API root for programmatic access via Accept header)

**File structure inside `src/sap_doc_agent/web/`:**
```
web/
├── server.py              # Existing — API endpoints stay here, mounts UI router
├── ui.py                  # New — FastAPI router for all /ui/* routes
├── auth.py                # New — password middleware + session cookie
├── templates/
│   ├── base.html          # Shell: sidebar, topbar, HTMX content area
│   ├── login.html         # Password login page
│   └── partials/
│       ├── dashboard.html
│       ├── objects.html
│       ├── object_detail.html
│       ├── quality.html
│       ├── graph.html
│       ├── audit.html
│       ├── scanner.html
│       ├── settings.html
│       └── reports.html
└── static/
    ├── style.css          # Minimal custom CSS (Tailwind does the rest)
    └── graph.js           # vis.js graph initialization + interaction
```

## Authentication

**Phase 1 (this spec):** Simple shared password.
- Login page at `/ui/login` with single password field
- Password stored as bcrypt hash in envctl (`SAP_DOC_AGENT_UI_PASSWORD`)
- On successful login, set an httponly session cookie (signed, 24h TTL)
- Middleware on all `/ui/*` routes checks cookie; redirects to login if missing/expired
- API endpoints (`/api/*`) remain unauthenticated (M365 Copilot needs them)

**Phase 2 (future):** Role-based auth with admin (full access) vs viewer (read-only). The middleware is designed to make this swap easy — the session cookie already carries a role field (set to "admin" in Phase 1).

## Pages

### 1. Dashboard (`/ui/dashboard`)

The landing page after login. Overview of the entire system at a glance.

**Layout:** Grid of status cards + quick actions + recent activity.

**Widgets:**
- **Object Count** — total scanned objects, broken down by type (donut chart via inline SVG)
- **Quality Score** — overall percentage as a circular gauge, color-coded (green >70%, amber 40-70%, red <40%)
- **Last Scan** — timestamp, duration, scanner used, object count delta
- **System Health** — connection status indicators for: SAP system(s), doc platform, git backend, LLM provider. Green/amber/red dots.
- **Critical Issues** — top 5 most severe QA or code quality findings, linked to object detail
- **Quick Actions** — buttons: "Run Full Scan", "Run Audit", "Sync to Doc Platform". Each triggers a POST via HTMX, shows a spinner, then updates the dashboard on completion.

**Auto-refresh:** Status cards poll every 30s via `hx-trigger="every 30s"`.

### 2. Objects (`/ui/objects`)

Browse and search all scanned SAP objects.

**Layout:** Filter bar on top, data table below.

**Filter bar:**
- Text search (searches name, technical_name, description)
- Type dropdown (view, adso, transformation, etc.)
- Layer dropdown (raw, harmonized, reporting, etc.)
- Space dropdown (populated from scan data)

**Table columns:** Name (linked), Type (badge), Layer (badge), Space, Quality Score (color-coded), Last Scanned (relative time).

**Sorting:** Click column headers to sort. Default: name ascending.

**Pagination:** 50 objects per page, HTMX-powered pagination (no full reload).

**Click row** → navigates to object detail.

### 3. Object Detail (`/ui/objects/{object_id}`)

Full view of a single scanned object.

**Layout:** Two-column on wide screens. Left: object metadata + rendered markdown. Right: sidebar with dependencies, quality issues, actions.

**Left column:**
- Object header: business name (H1), technical name, type badge, layer badge, space, status, owner
- Rendered markdown content (description, columns table, SQL definition)
- Screenshots (if available)

**Right column (sidebar):**
- **Dependencies panel:** upstream (reads from) and downstream (read by) as clickable links
- **Quality Issues:** list of findings for this object with severity badges
- **Actions:** "View in BookStack", "Re-scan", "Edit in Doc Platform"

### 4. Quality (`/ui/quality`)

Quality assessment across all objects.

**Layout:** Summary bar + tabbed view + issue list.

**Summary bar:** Overall score gauge, counts by severity (critical/important/minor as colored badges).

**Tabs:**
- **Doc QA** — documentation quality issues (missing descriptions, too-short sections, naming violations)
- **Code Quality** — ABAP + SQL findings (SELECT *, hardcoded clients, magic numbers, etc.)
- **BRS Traceability** — unlinked requirements, orphan objects, trace confidence scores

**Issue list:** Grouped by object (accordion). Each issue shows: severity badge, rule ID, message, affected field/line. Click object name to navigate to detail.

**Export:** "Download Report" button generates and downloads the HTML report.

### 5. Dependency Graph (`/ui/graph`)

Interactive network visualization of all object dependencies.

**Implementation:** vis.js Network loaded via CDN. Graph data fetched from `/api/objects` + `graph.json`.

**Node styling:**
- Color by object type (consistent palette: views=blue, ADSOs=green, transformations=orange, etc.)
- Size by connection count (more connections = larger node)
- Label: business name or technical name

**Edge styling:**
- Labeled by dependency type (reads_from, writes_to, etc.)
- Arrows showing direction

**Interactions:**
- Zoom/pan (mouse wheel + drag)
- Click node → info panel slides in from right with object summary + "View Detail" link
- Double-click node → navigate to object detail page
- Physics-based layout with stabilization

**Filters (top bar):**
- Filter by space, layer, object type
- Search box to highlight/focus a specific node

### 6. Reports (`/ui/reports`)

View and download generated reports.

**Layout:** Card grid of available reports.

**Report cards:** Title, generation date, file size, preview snippet. Click to view full report (rendered HTML). Download button for each.

**Reports available:** Summary, Doc QA Report, Code Quality Report, BRS Traceability Report.

### 7. Audit (`/ui/audit`)

Run documentation audits — the core product feature.

**Layout:** Three-step wizard.

**Step 1 — Upload:**
- Drag-and-drop zone for PDF/markdown files
- File list with remove buttons
- Optional: upload or paste client documentation standard (PDF or text)
- Name field for the audit (e.g., "Client X Q2 Review")

**Step 2 — Configure:**
- Scope selector: system-level or application-level
- Standard to evaluate against: Horvath only, client only, or both (default: both if client standard provided)

**Step 3 — Run & Results:**
- "Start Audit" button → POST to `/api/audit`
- Progress indicator (spinner + status text)
- Results rendered inline: overall score, per-document scores, section-by-section findings, gap analysis (if dual-standard), suggestions
- "Download Report" button (HTML export)

### 8. Scanner (`/ui/scanner`)

Manage and trigger SAP system scans.

**Layout:** Scanner cards + scan history.

**Scanner cards:** One card per configured scanner (e.g., "Horvath DSP — CDP Scanner"). Each shows:
- Status: idle / running / error / not configured
- Last scan: timestamp + object count
- "Start Scan" button (disabled if running)
- "Configure" link → settings page

**Scan progress:** When a scan is running, the card expands to show live log output streamed via SSE (`hx-ext="sse"`, `sse-connect="/ui/scanner/stream"`).

**Scan history:** Table below cards with: timestamp, scanner, duration, objects found, status (success/failed/partial).

### 9. Settings (`/ui/settings`)

Full system configuration.

**Layout:** Tabbed sections matching config.yaml structure.

**Tabs:**
- **SAP Systems** — add/edit/remove BW/4HANA and Datasphere connections (host, client, credentials reference, namespace filters)
- **Doc Platform** — select type (BookStack/Outline/Confluence), configure URL + credentials
- **Git Backend** — select type (GitHub/Gitea), configure repo URLs + token reference
- **LLM** — select mode (noop/direct/copilot_passthrough), configure endpoint + model
- **Scan Scope** — namespace filters, object type inclusion/exclusion
- **General** — UI password change, output directory path

**Config editing:** Each tab presents a form with labeled fields (not raw YAML). "Save" validates against the Pydantic config model and returns inline errors if invalid. "Test Connection" buttons where applicable (SAP, doc platform, git, LLM).

**Advanced mode:** Toggle to show raw YAML in a CodeMirror editor for power users who prefer editing config directly.

## Visual Design

Inspired by the Horvath corporate website (horvath-partners.com). Professional, clean, confident — not playful.

**Color palette (Horvath-aligned):**
- **Primary:** Deep petrol/teal `#05415A` — sidebar background, primary buttons, active nav states. This is Horvath's signature brand color.
- **Text:** Dark charcoal `#353434` — body text (not pure black, softer on the eyes)
- **Headings:** `#1a2332` — slightly darker than body for hierarchy
- **Background:** White `#FFFFFF` content area, light gray `#F5F5F5` for alternating sections and card backgrounds
- **Accent:** Warm gold `#C8963E` — sparingly, for highlights, active indicators, quality score gauges. Echoes the gold tones from Horvath's hero sections.
- **Status:** `#16A34A` green (healthy/good), `#D97706` amber (warning), `#DC2626` red (critical/error)
- **Borders:** `#E5E5E5` — subtle, minimal. Cards rely on shadow more than border.

**Typography:**
- Headings: `Georgia, 'Times New Roman', serif` — echoes Horvath's serif headings ("Corporate E"), gives a consulting-firm gravitas
- Body: `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` — clean, modern sans-serif for readability (Inter loaded via Google Fonts CDN, system stack fallback)
- Font sizes: restrained. 14px body, 13px table cells, 24px page titles, 18px section headings

**Layout principles (from Horvath site):**
- Generous whitespace — don't crowd elements
- Cards with subtle `box-shadow: 0 1px 3px rgba(0,0,0,0.08)` and `border-radius: 6px` — no heavy borders
- Clean horizontal lines to separate sections, not boxes within boxes
- Tables with light gray alternating rows (`#F9FAFB`), subtle hover (`#F0F0F0`)
- Badges: small, pill-shaped, muted colors (not neon). Type badges use the petrol palette at varying opacity.

**Buttons:**
- Primary: petrol `#05415A` background, white text, subtle hover darkening
- Secondary: white background, petrol border, petrol text
- Danger: red outlined, red text (not filled red — too aggressive for a consulting tool)
- All buttons: `border-radius: 4px`, no uppercase transforms, medium font weight

**Toast notifications:** Slide in from top-right, auto-dismiss after 5s. Muted colors matching status palette.

**Responsive:** Desktop-first (primary use case). Tablet works — sidebar collapses to hamburger. Mobile is not broken but not optimized.

**Branding:** Sidebar header shows "SAP Doc Agent" in serif font with a subtle horizontal rule below. Optional: small "powered by Horvath" tagline in sidebar footer for client-facing contexts.

## Data Flow

**All UI data comes from existing API endpoints and filesystem reads:**
- Dashboard stats → `GET /api/objects` + `GET /api/quality` + `GET /health`
- Object list/detail → `GET /api/objects` + `GET /api/objects/{id}`
- Quality data → `GET /api/quality` + filesystem reads from `output/reports/`
- Graph data → filesystem read of `output/graph.json`
- Audit → `POST /api/audit`
- Scanner status → new endpoint `GET /api/scanner/status`
- Scanner trigger → new endpoint `POST /api/scanner/start`
- Scanner log stream → new endpoint `GET /api/scanner/stream` (SSE)
- Settings read → new endpoint `GET /api/settings`
- Settings write → new endpoint `PUT /api/settings`
- Connection test → new endpoint `POST /api/settings/test/{component}`

**New API endpoints needed:**
- `GET /api/scanner/status` — status of each configured scanner
- `POST /api/scanner/start` — trigger a scan (accepts scanner type + scope)
- `GET /api/scanner/stream` — SSE stream of scan progress/logs
- `GET /api/settings` — current config (sanitized, no secrets in plaintext)
- `PUT /api/settings` — update config (validates via Pydantic, writes YAML)
- `POST /api/settings/test/{component}` — test connection for a specific integration
- `GET /api/dashboard/stats` — aggregated dashboard data (avoids multiple API calls from the UI)

## Error Handling

- API errors render as toast notifications (HTMX `hx-trigger` response headers)
- Scanner failures show error state on the scanner card with last error message
- Config validation errors render inline next to the offending field
- Network errors (HTMX request fails) show a global "Connection lost" banner with retry button

## Testing Strategy

- Backend: pytest for new API endpoints and auth middleware
- Templates: render each template with sample data, assert key elements present
- No frontend test framework (no JS build = no Jest). Manual verification via browser.

## Out of Scope

- Multi-user / role-based auth (Phase 2)
- Real-time collaboration
- Mobile-optimized layout
- Internationalization
- Dark mode (nice-to-have for later)
