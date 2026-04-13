# ABAP Scanner — Horvath Demo Installation

Step-by-step guide to install the SAP Doc Agent scanner on the Horvath demo BW/4HANA system.

**Time required:** ~15 minutes
**Access needed:** SE11 + SE38 (or ADT/Eclipse)

---

## Step 1: Create Package (optional)

If you want to keep things organized:
- Transaction: **SE80** or **SE21**
- Create package: `ZDOC_AGENT`
- Description: "SAP Documentation Agent"
- Transport request: create a new one or use an existing workbench request

Or just use `$TMP` for the demo (no transport needed).

---

## Step 2: Create Tables in SE11

### Table 1: ZDOC_AGENT_CFG

1. Go to **SE11** → enter `ZDOC_AGENT_CFG` → click **Create**
2. Short description: `Doc Agent Configuration`
3. Delivery class: **A** (Application table)
4. Fields:

| Field | Key | Data Element / Type | Length |
|-------|-----|---------------------|--------|
| MANDT | X | MANDT | 3 |
| CFG_KEY | X | CHAR30 (or just type CHAR) | 30 |
| CFG_VALUE | | CHAR255 (or just type CHAR) | 255 |

5. Tab **Technical Settings**: Data class `APPL0`, Size category `0`
6. **Activate**

### Table 2: ZDOC_AGENT_SCAN

1. SE11 → `ZDOC_AGENT_SCAN` → Create
2. Short description: `Doc Agent Scan Results`
3. Fields:

| Field | Key | Data Element / Type | Length |
|-------|-----|---------------------|--------|
| MANDT | X | MANDT | 3 |
| OBJECT_KEY | X | CHAR60 | 60 |
| OBJECT_TYPE | | CHAR20 | 20 |
| DESCRIPTION | | CHAR255 | 255 |
| PACKAGE | | CHAR30 | 30 |
| OWNER | | CHAR12 | 12 |
| LAST_SCAN | | DEC | 15 |
| CONTENT_HASH | | CHAR64 | 64 |
| SOURCE_CODE | | STRING (type STRG) | |
| METADATA | | STRING (type STRG) | |

5. Technical Settings: Data class `APPL0`, Size category `0`
6. Activate

**Note on STRING fields:** In SE11, for SOURCE_CODE and METADATA, choose type category "String" (STRG). If your system version doesn't support STRING in transparent tables, use LCHR with a preceding INT2 length field — but most BW/4HANA systems support STRING directly.

### Table 3: ZDOC_AGENT_DEPS

1. SE11 → `ZDOC_AGENT_DEPS` → Create
2. Short description: `Doc Agent Dependencies`
3. Fields:

| Field | Key | Data Element / Type | Length |
|-------|-----|---------------------|--------|
| MANDT | X | MANDT | 3 |
| SOURCE_KEY | X | CHAR60 | 60 |
| TARGET_KEY | X | CHAR60 | 60 |
| DEP_TYPE | X | CHAR20 | 20 |

4. Technical Settings: Data class `APPL0`, Size category `0`
5. Activate

---

## Step 3: Create Programs in SE38

### Program 1: Z_DOC_AGENT_SETUP

1. Go to **SE38** → enter `Z_DOC_AGENT_SETUP` → click **Create**
2. Title: `SAP Doc Agent — Setup & Configuration`
3. Type: **Executable program**
4. Package: `ZDOC_AGENT` or `$TMP`
5. **Copy-paste** the entire contents of `z_doc_agent_setup.abap` from this repo
6. **Activate**

### Program 2: Z_DOC_AGENT_SCAN

1. SE38 → `Z_DOC_AGENT_SCAN` → Create
2. Title: `SAP Doc Agent — BW/4HANA Scanner`
3. Type: **Executable program**
4. Package: `ZDOC_AGENT` or `$TMP`
5. **Copy-paste** the entire contents of `z_doc_agent_scan.abap` from this repo
6. **Activate**

**Note:** The scan program is ~1200 lines. If copy-paste truncates, try:
- ADT/Eclipse: create the report there instead (better for large sources)
- SE38: paste in chunks — first the top-level REPORT + types + selection screen, activate, then add the FORMs

---

## Step 4: Run Setup

1. Execute **Z_DOC_AGENT_SETUP** (F8 or SA38)
2. Fill the selection screen:

| Parameter | Value for Horvath Demo |
|-----------|----------------------|
| Transport Backend (P_TRANS) | `P` (API) |
| Git API URL (P_GITURL) | `https://api.github.com/repos/hschuettken/sap-doc-agent-output` |
| API Token (P_TOKEN) | `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` |
| Namespace Filter (P_NSFILTR) | `Z*` (or `*` to scan everything) |
| AL11 Path (P_ALPATH) | *(leave empty — not using filedrop)* |

3. Execute — should show:
   ```
   Checking DDIC table existence...
     [OK]      ZDOC_AGENT_CFG
     [OK]      ZDOC_AGENT_SCAN
     [OK]      ZDOC_AGENT_DEPS
   
   Writing configuration to ZDOC_AGENT_CFG...
     Wrote 6 config entries.
   
   Stored configuration:
   ──────────────────────────────────────────────────
     API_TOKEN                 : ghp_****(masked)****
     GIT_URL                   : https://api.github.com/repos/hschuettken/sap-doc-agent-output
     NAMESPACE_FILTER          : Z*
     SETUP_TIMESTAMP           : 20260413...
     TRANSPORT_BACKEND         : P
     TRANSPORT_LABEL           : API (GitHub/Gitea)
   ──────────────────────────────────────────────────
   
   Setup complete. Run Z_DOC_AGENT_SCAN to start scanning.
   ```

---

## Step 5: Run Scanner (First Test)

1. Execute **Z_DOC_AGENT_SCAN**
2. Fill the selection screen:

| Parameter | Value |
|-----------|-------|
| Providers (S_PROVDR) | Enter 1-2 provider names you know exist in the system |
| Max Depth (P_DEPTH) | `5` (start small) |
| Dry Run (P_DRYRUN) | `X` (check this first to see what would be scanned) |

3. Review the dry run output — it shows what objects would be scanned
4. If it looks right, uncheck P_DRYRUN and run again for real
5. Check the output repo: https://github.com/hschuettken/sap-doc-agent-output

---

## Troubleshooting

### "Table ZDOC_AGENT_CFG does not exist"
→ Go back to Step 2, create the tables in SE11, activate them

### "No providers found for selection"
→ The provider names are case-sensitive. Check the exact names in RSA1 or via:
```sql
SELECT INFOPROV FROM RSOADSO WHERE INFOPROV LIKE 'Z%'
```

### "HTTP connection failed" during scan push
→ Check if the BW system can reach api.github.com (may need proxy settings)
→ Try SM59 to create an RFC destination for testing HTTP connectivity

### "Authorization error" on GitHub API
→ Verify the token is correct and has `repo` scope
→ Check if the token has expired

### Tables created but STRING fields don't work
→ On older systems, replace SOURCE_CODE and METADATA with:
- `SOURCE_LEN` INT2 (preceding length field)
- `SOURCE_CODE` LCHR with length ref to SOURCE_LEN
- Same pattern for METADATA

### Scanner finds 0 objects
→ Run with namespace filter `*` to include SAP standard
→ Check if BW tables (RSOADSO, RSDCUBE, etc.) are populated — empty tables = wrong system

---

## What Happens After a Scan

The scanner pushes JSON-formatted files to the GitHub output repo:
- `objects/<type>/<name>.json` — one file per scanned object
- `graph.json` — dependency graph
- `scan_log.json` — scan metadata (timestamp, counts, errors)

The Python pipeline then picks these up:
```bash
cd /home/hesch/dev/projects/sap-doc-agent
source .venv/bin/activate
sap-doc-agent --config config.demo.yaml --scanner cdp --cdp-data <path-to-bw-output> --sync --qa --report --all
```

---

## Quick Reference

| What | Where |
|------|-------|
| ABAP source files | `setup/abap/z_doc_agent_setup.abap`, `z_doc_agent_scan.abap` |
| Output repo (GitHub) | https://github.com/hschuettken/sap-doc-agent-output |
| Output repo (Gitea) | http://192.168.0.64:3000/atlas/sap-doc-agent-output |
| GitHub PAT | stored in envctl as `GITHUB_PAT_GITEA_MIRROR` |
| BookStack | http://192.168.0.50:8253 (admin@admin.com / password) |
