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
