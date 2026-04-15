"""Seed SAP knowledge base with canonical reference files."""

from __future__ import annotations

from pathlib import Path

SEED_FILES = [
    "dsp_quirks.md",
    "hana_sql.md",
    "cdp_playbook.md",
    "ui_mapping.md",
    "best_practices.md",
]

_CONTENT: dict[str, str] = {
    "dsp_quirks.md": """\
# SAP Datasphere Quirks

## Ace Editor — Changes Don't Trigger Save
The Ace editor used in SQL views and transformation scripts does not fire
standard browser `change` events. A `Ctrl+S` keypress or explicit save button
click is required to persist edits. Programmatic `input` events injected via
CDP do not mark the file as dirty — always follow injected text with a
`cdp_press_key(key="s", modifiers=["Control"])` to flush the buffer.

## Cross-Space Access
Objects in Space A cannot reference objects in Space B directly unless a
data-sharing agreement (DSA) has been accepted. Attempting to create a
dependent view across spaces without a DSA yields a misleading "object not
found" error rather than a permissions error.

## Graphical Views Expose Business Names
The graphical modeler shows business names (alias labels) rather than
technical names. When generating SQL from a graphical view, always resolve
aliases back to technical column names before comparing schemas.

## Data Viewer Row Limit
The built-in Data Viewer caps preview results at 1 000 rows and applies an
implicit ORDER BY ROWID. Never use Data Viewer output as ground-truth for
aggregate queries — run the SQL directly via the SQL Console instead.

## Local Tables vs. Remote Tables
Local tables are stored in the SAP HANA underlying tenant database. Remote
tables are proxies to source systems via SDI adapters. Replication status
(QUEUED / ACTIVE / ERROR) must be checked before reading remote table data
in automated pipelines.
""",
    "hana_sql.md": """\
# SAP HANA SQL Patterns and Gotchas

## LIMIT Inside UNION ALL
SAP HANA does not allow a bare LIMIT clause on a UNION ALL leg. Wrap each
leg in a subquery:

```sql
SELECT * FROM (SELECT col FROM t1 ORDER BY col LIMIT 10)
UNION ALL
SELECT * FROM (SELECT col FROM t2 ORDER BY col LIMIT 10);
```

## Alias Required on Every UNION Leg
All column aliases must be consistent across every UNION / UNION ALL leg.
Omitting an alias on any leg causes a "column name mismatch" parse error
even when the data types are compatible.

## DATAB / DATBI Are VARCHAR, Not DATE
SAP master-data validity fields (DATAB = valid-from, DATBI = valid-to) are
stored as VARCHAR(8) in the format YYYYMMDD. Always cast when comparing:

```sql
WHERE TO_DATE(DATAB, 'YYYYMMDD') <= CURRENT_DATE
  AND TO_DATE(DATBI, 'YYYYMMDD') >= CURRENT_DATE
```

## String Aggregation
SAP HANA uses `STRING_AGG(col, delimiter ORDER BY sort_col)` — not
`GROUP_CONCAT`. The ORDER BY clause inside STRING_AGG is mandatory in some
engine versions; always include it for portability.

## Calculated Views — No DML
Calculated views (CV) in HANA are read-only projections. Any attempt to
INSERT / UPDATE / DELETE against a CV raises "feature not supported."
Always target the underlying base tables for write operations.
""",
    "cdp_playbook.md": """\
# CDP Automation Playbook for SAP Datasphere

## Golden Rules

1. **Never cdp_navigate on an unsaved tab.** Datasphere does not auto-save
   open editors. Navigating away without saving silently discards all
   pending changes. Always call the save action (Ctrl+S or the toolbar
   button) and wait for the "Saved" toast before issuing any navigation.

2. **Use Playwright-style selectors, not XPath.** SAP UI5 renders dynamic
   IDs on every page load. Stable selectors are CSS class-based
   (`.sapMButton`, `[data-sap-ui-type]`) or aria-label attributes.

3. **Wait for the busy indicator to clear.** After any save or deploy
   action, poll for the absence of `.sapUiLocalBusyIndicator` before
   proceeding. A 500 ms interval with a 30 s timeout is sufficient for
   most operations.

4. **Tab identity is URL-path based.** Each open object in Datasphere
   occupies a hash-routed URL. Parse `window.location.hash` to determine
   which object is currently focused before issuing key presses.

5. **Deployment vs. Save.** Saving a view persists it in draft state.
   Deployment compiles and activates it for consumers. These are separate
   actions — a saved but undeployed view is invisible to dependent objects.

## Common Failure Modes

- **Stale session**: Datasphere sessions expire after ~2 h of inactivity.
  Detect via a redirect to the login page (`/login?reason=SESSION_EXPIRED`).
- **Conflict on deploy**: Two agents deploying the same object concurrently
  cause a lock error. Serialise deployments with a Redis-backed mutex.
""",
    "ui_mapping.md": """\
# SAP UI5 CSS Selector Patterns

## General Navigation Elements

| Element                  | Stable Selector                                      |
|--------------------------|------------------------------------------------------|
| Shell header             | `#shell-header`                                      |
| Side navigation          | `.sapUshellShellHead`                                |
| Primary toolbar          | `.sapMIBar-CTX`                                      |
| Save button (toolbar)    | `[data-sap-ui-type="sap.m.Button"][title="Save"]`    |
| Deploy button            | `[data-sap-ui-type="sap.m.Button"][title="Deploy"]`  |
| Busy overlay             | `.sapUiLocalBusyIndicator`                           |
| Toast / message strip    | `.sapMMsgStrip`                                      |
| Dialog confirm           | `.sapMDialogScrollCont .sapMBtn:last-child`          |

## Datasphere-Specific Selectors

| Element                       | Selector                                             |
|-------------------------------|------------------------------------------------------|
| Space switcher dropdown       | `[id$="spaceSelector"]`                              |
| Object tree panel             | `.sapSuiteUiCommonsNetworkGraphNode`                 |
| SQL console editor area       | `.ace_editor`                                        |
| Column mapping row            | `[data-column-name]`                                 |
| Validation message list       | `.sapMMessageView .sapMListItems`                    |

## Notes on Dynamic IDs
SAP UI5 generates control IDs like `__button12` that change on every render.
Never hardcode these. Prefer `aria-label`, `title`, or `data-sap-*`
attribute selectors which remain stable across sessions.
""",
    "best_practices.md": """\
# SAP Datasphere / BW/4HANA Best Practices

## 4-Layer Architecture

All data models should follow the four-layer pattern:

1. **RAW** — Ingested source data, no transformations. Column names match
   source system field names. No business logic.
2. **HARMONIZED** — Cleaned, typed, and deduplicated. DATE fields cast from
   VARCHAR(8). Currency amounts normalised to EUR. Keys resolved via
   InfoObjects or lookup tables.
3. **MART** — Business-domain aggregations. One mart per subject area
   (Sales, Finance, HR). Optimised for query performance with appropriate
   partitioning and indexes.
4. **CONSUMPTION** — Thin analytical views surfaced to BI tools (SAC,
   Analysis for Office). Column labels in business language. Measures
   formatted with units.

## Naming Conventions

- **Technical names**: `Z_<LAYER>_<DOMAIN>_<OBJECT>` e.g. `Z_HRM_SALES_ORDER`
- **Business names** (alias): Sentence case, spaces allowed, max 60 chars.
- **Transformations**: Suffix `_TF` e.g. `Z_HRM_SALES_ORDER_TF`
- **Process chains**: Prefix `PC_` e.g. `PC_DAILY_SALES_LOAD`

## Persistence Strategy

- Use **in-memory** (no persistence) for HARMONIZED views queried in
  real-time from MART layer.
- Use **replicated** persistence for RAW tables sourced from remote systems
  to avoid runtime SDI latency.
- Use **snapshot** persistence for MART aggregations refreshed on a schedule.
- Never enable persistence on CONSUMPTION views — they should always read
  live from the MART layer.

## Change Management
All structural changes (column add/remove, key change) must be deployed in
a transport request. Schema-only changes can be hotfixed in DEV and
transported to PROD via the standard CTS+ route. Never edit PROD directly.
""",
}


def seed_knowledge(target_dir: Path, force: bool = False) -> None:
    """Write canonical SAP knowledge files to target_dir/shared/.

    Args:
        target_dir: Root directory for the knowledge base.
        force: If True, overwrite existing files. If False (default), skip them.
    """
    shared_dir = target_dir / "shared"
    tenants_dir = target_dir / "tenants"
    shared_dir.mkdir(parents=True, exist_ok=True)
    tenants_dir.mkdir(parents=True, exist_ok=True)

    for filename in SEED_FILES:
        dest = shared_dir / filename
        if dest.exists() and not force:
            continue
        dest.write_text(_CONTENT[filename], encoding="utf-8")
