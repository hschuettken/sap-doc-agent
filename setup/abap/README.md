# ABAP Scanner — Installation Guide

## Prerequisites

- SAP BW/4HANA system with developer access (SE38, SE11, SE80 or ADT)
- Developer key for your user
- Transport request for the development package

## Table Setup

Before running the setup program, create these tables in SE11:

### ZDOC_AGENT_CFG (Configuration)
| Field | Type | Length | Description |
|-------|------|--------|-------------|
| MANDT | CLNT | 3 | Client |
| CFG_KEY | CHAR | 30 | Configuration key |
| CFG_VALUE | CHAR | 255 | Configuration value |

Primary key: MANDT, CFG_KEY

### ZDOC_AGENT_SCAN (Scan Results)
| Field | Type | Length | Description |
|-------|------|--------|-------------|
| MANDT | CLNT | 3 | Client |
| OBJECT_KEY | CHAR | 60 | Unique object identifier |
| OBJECT_TYPE | CHAR | 20 | Object type (ADSO, CLASS, etc.) |
| DESCRIPTION | CHAR | 255 | Object description |
| PACKAGE | CHAR | 30 | ABAP package |
| OWNER | CHAR | 12 | Last changed by |
| LAST_SCAN | DEC | 15 | Timestamp of last scan |
| CONTENT_HASH | CHAR | 64 | SHA-256 content hash |
| SOURCE_CODE | STRG | | Extracted source code |
| METADATA | STRG | | JSON metadata |

Primary key: MANDT, OBJECT_KEY

### ZDOC_AGENT_DEPS (Dependencies)
| Field | Type | Length | Description |
|-------|------|--------|-------------|
| MANDT | CLNT | 3 | Client |
| SOURCE_KEY | CHAR | 60 | Source object key |
| TARGET_KEY | CHAR | 60 | Target object key |
| DEP_TYPE | CHAR | 20 | Dependency type |

Primary key: MANDT, SOURCE_KEY, TARGET_KEY, DEP_TYPE

## Installation

1. Create tables in SE11 (see above)
2. Create report `Z_DOC_AGENT_SETUP` in SE38, paste the source
3. Create report `Z_DOC_AGENT_SCAN` in SE38, paste the source
4. Run `Z_DOC_AGENT_SETUP` to configure transport backend and Git connection
5. Run `Z_DOC_AGENT_SCAN` with your top-level providers to start scanning

## Transport Backends

### API (recommended for demo)
Direct HTTP push to GitHub/Gitea REST API. Requires:
- Git repo URL (e.g., `https://api.github.com/repos/user/sap-doc-agent`)
- Personal access token with repo scope

### File Drop
Writes files to application server path. A Linux cron job picks them up.
Requires AL11 path configured.

### abapGit
Delegates to abapGit for Git sync. Requires abapGit installed.
(Stub — not yet implemented)

## Known Limitations

- Table creation must be done manually via SE11 (programmatic DDIC creation is complex)
- Transformation source code extraction depends on system version
- Some BW table names may differ between BW/4HANA versions
- abapGit transport backend is a stub
- WHERE-USED analysis via CROSS/WBCROSSGT may be incomplete for newer object types
