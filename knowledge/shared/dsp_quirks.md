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
