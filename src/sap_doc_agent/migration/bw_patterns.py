"""BW anti-pattern / simplification knowledge base.

Each pattern has a name, description, detection rules (regex on source code
or structural checks on chain metadata), default classification, DSP equivalent,
and rationale. Patterns are structured data — new ones are added as the KB grows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from sap_doc_agent.migration.models import MigrationClassification


@dataclass
class BWPattern:
    """A known BW implementation pattern with migration guidance."""

    name: str
    description: str
    classification: MigrationClassification
    dsp_equivalent: str
    rationale: str
    # Detection: regex patterns to search in ABAP source code
    source_regexes: list[str] = field(default_factory=list)
    # Detection: structural checks on chain/step metadata keys
    metadata_checks: list[str] = field(default_factory=list)
    # Tags for grouping/filtering
    tags: list[str] = field(default_factory=list)

    def matches_source(self, source_code: str) -> bool:
        """Check if any source regex matches the given ABAP code."""
        if not source_code or not self.source_regexes:
            return False
        for pattern in self.source_regexes:
            if re.search(pattern, source_code, re.IGNORECASE | re.MULTILINE):
                return True
        return False

    def matches_metadata(self, metadata: dict) -> bool:
        """Check if metadata matches structural conditions."""
        if not self.metadata_checks:
            return False
        for check in self.metadata_checks:
            if _eval_metadata_check(check, metadata):
                return True
        return False


def _eval_metadata_check(check: str, metadata: dict) -> bool:
    """Evaluate a simple metadata check expression.

    Supported forms:
    - "key_exists:field_name" — True if field_name exists in metadata
    - "last_run_months_ago:>12" — True if last_run is >12 months ago
    - "type:VALUE" — True if metadata["type"] == VALUE
    - "fields_count:>N" — True if len(metadata.get("fields",[])) > N
    - "empty_source" — True if source_code is empty/whitespace
    """
    if check == "empty_source":
        # Only match if source_code key is explicitly present and empty
        if "source_code" not in metadata:
            return False
        return not metadata["source_code"].strip()

    if ":" not in check:
        return False

    key, value = check.split(":", 1)

    if key == "key_exists":
        return value in metadata

    if key == "type":
        return metadata.get("type", "").upper() == value.upper()

    if key == "last_run_months_ago":
        last_run = metadata.get("last_run", "")
        if not last_run:
            return False
        try:
            from datetime import datetime, timezone

            if isinstance(last_run, str):
                # Parse ISO format or YYYY-MM-DD
                lr = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            else:
                lr = last_run
            now = datetime.now(timezone.utc)
            months = (now.year - lr.year) * 12 + (now.month - lr.month)
            op_val = value.lstrip("><= ")
            if value.startswith(">"):
                return months > int(op_val)
            if value.startswith("<"):
                return months < int(op_val)
            return months == int(op_val)
        except (ValueError, TypeError):
            return False

    if key == "fields_count":
        count = len(metadata.get("fields", []))
        op_val = value.lstrip("><= ")
        try:
            n = int(op_val)
        except ValueError:
            return False
        if value.startswith(">"):
            return count > n
        if value.startswith("<"):
            return count < n
        return count == n

    return False


# ---------- Pattern definitions ----------

BW_PATTERNS: list[BWPattern] = [
    # --- SIMPLIFY patterns ---
    BWPattern(
        name="year_partitioned_union",
        description="MultiProvider UNION ALL across year-partitioned ADSOs",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="One view with date filter",
        rationale="Year partitioning was a BW performance workaround. DSP handles this natively.",
        source_regexes=[r"UNION\s+ALL.*(?:year|jahrgang|yyyy)", r"partitioned.*adso"],
        metadata_checks=["key_exists:partition_key"],
        tags=["multiprovider", "performance"],
    ),
    BWPattern(
        name="tcurr_conversion",
        description="Currency conversion via TCURR table lookup in ABAP routine",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="CASE WHEN or currency dimension with conversion view",
        rationale="ABAP TCURR lookup translates to a simple SQL join or CASE WHEN in DSP.",
        source_regexes=[
            r"tcurr",
            r"currency.*conver",
            r"ukurs",
            r"kurst\s*=\s*'M'",
            r"fcurr.*tcurr",
        ],
        tags=["currency", "abap_routine"],
    ),
    BWPattern(
        name="virtual_provider_bapi",
        description="Virtual Provider with BAPI exit for simple filtering",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="SQL view with WHERE clause",
        rationale="Virtual Providers with simple BAPI exits are just parameterized views.",
        source_regexes=[r"call\s+function\s+['\"]bapi", r"virtual.*provider", r"rsdri_infoprov"],
        tags=["virtual_provider"],
    ),
    BWPattern(
        name="infoobject_compounding",
        description="InfoObject compounding (e.g. 0CUSTOMER + 0SALESORG)",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="Two separate dimension columns with association",
        rationale="Compounding was BW-specific. In DSP, use separate columns with star schema.",
        source_regexes=[r"compounding", r"compound.*key"],
        metadata_checks=["key_exists:compound_with"],
        tags=["infoobject", "modeling"],
    ),
    BWPattern(
        name="non_cumulative_keyfigure",
        description="Non-cumulative key figure with exception aggregation",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="Standard measure with time logic in view",
        rationale="Non-cumulative KFs are a BW concept. In DSP, use window functions or snapshot logic.",
        source_regexes=[r"non.?cumul", r"exception.*aggreg", r"0cumul"],
        tags=["keyfigure", "modeling"],
    ),
    BWPattern(
        name="empty_routines",
        description="Transformation with empty start/end routines (no-op)",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="May not need transformation at all — direct mapping in view",
        rationale="Empty routines indicate the transformation is just field mapping, which is trivial in DSP.",
        metadata_checks=["empty_source"],
        tags=["empty", "routine"],
    ),
    BWPattern(
        name="read_table_lookup",
        description="READ TABLE lookup on internal table (master data join)",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="SQL JOIN in view",
        rationale="ABAP READ TABLE is a manual hash-join. In DSP, use SQL JOIN.",
        source_regexes=[
            r"read\s+table\s+\w+\s+into",
            r"read\s+table\s+\w+\s+with\s+key",
            r"read\s+table\s+\w+\s+assigning",
        ],
        tags=["abap_routine", "lookup"],
    ),
    BWPattern(
        name="aggregation_across_steps",
        description="Aggregation logic spread across multiple transformation steps",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="Single GROUP BY in one view",
        rationale="BW often splits aggregation due to DSO staging. DSP can do it in one SQL view.",
        source_regexes=[r"collect\s+\w+\s+into", r"sum\b.*group\b"],
        tags=["aggregation", "multi_step"],
    ),
    BWPattern(
        name="multiprovider_union",
        description="MultiProvider union combining ADSOs without transformation",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="UNION ALL view or single source with filter",
        rationale="MultiProvider union is just SQL UNION ALL. Often the partitioning is unnecessary in DSP.",
        source_regexes=[r"union\s+all"],
        metadata_checks=["type:COMPOSITE"],
        tags=["multiprovider", "union"],
    ),
    BWPattern(
        name="hardcoded_company_code",
        description="Hardcoded company code filter in ABAP routine",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="Parameterized WHERE clause or Data Access Control",
        rationale="Hardcoded BUKRS filter should be parameterized in DSP for multi-tenant use.",
        source_regexes=[
            r"bukrs\s*(?:=|IN)\s*['\(]",
            r"company.?code.*(?:=|IN)",
            r"delete.*where\s+bukrs",
        ],
        tags=["filter", "hardcoded"],
    ),
    BWPattern(
        name="field_symbol_loop",
        description="FIELD-SYMBOL loop processing SOURCE_PACKAGE records",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="SQL transformation (WHERE, CASE WHEN, JOIN)",
        rationale="Row-by-row ABAP processing usually translates to set-based SQL.",
        source_regexes=[
            r"field-symbol.*<\w+>",
            r"loop\s+at\s+source_package\s+assigning",
            r"assigning\s+field-symbol",
        ],
        tags=["abap_routine", "loop"],
    ),
    BWPattern(
        name="delete_source_package",
        description="DELETE SOURCE_PACKAGE WHERE — row filtering in start routine",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="WHERE clause in SQL view",
        rationale="Start routine filtering translates directly to SQL WHERE.",
        source_regexes=[r"delete\s+source_package\s+where"],
        tags=["filter", "routine"],
    ),
    BWPattern(
        name="conditional_field_mapping",
        description="IF/CASE logic in field routine for conditional field values",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="CASE WHEN expression in SQL view",
        rationale="ABAP IF/CASE → SQL CASE WHEN is a direct translation.",
        source_regexes=[
            r"if\s+source_fields-\w+\s*(?:=|<>|>|<)",
            r"case\s+source_fields-\w+",
            r"result\s*=\s*(?:source_fields-|')",
        ],
        tags=["field_routine", "conditional"],
    ),
    # --- REPLACE patterns ---
    BWPattern(
        name="process_chain_full_reload",
        description="Process chain: delete → full load → rebuild index",
        classification=MigrationClassification.REPLACE,
        dsp_equivalent="Replication flow with delta (native DSP)",
        rationale="Full-reload-and-reindex is a BW pattern. DSP replication flows handle delta natively.",
        source_regexes=[r"full\s*load", r"delete.*insert.*rebuild"],
        metadata_checks=["key_exists:process_chain_type"],
        tags=["process_chain", "loading"],
    ),
    BWPattern(
        name="process_chain_scheduled_load",
        description="Process chain: scheduled full/delta load",
        classification=MigrationClassification.REPLACE,
        dsp_equivalent="Replication flow with schedule",
        rationale="Scheduled loading is native in DSP replication flows.",
        metadata_checks=["key_exists:schedule"],
        tags=["process_chain", "scheduling"],
    ),
    BWPattern(
        name="manual_delta_handling",
        description="Manual delta handling by comparing timestamps in ABAP",
        classification=MigrationClassification.REPLACE,
        dsp_equivalent="Native delta/CDC in replication flow",
        rationale="Manual delta logic is unnecessary — DSP replication flows do CDC natively.",
        source_regexes=[
            r"delta.*timestamp",
            r"sy-datum",
            r"last_load.*date",
            r"where.*(?:erdat|aedat|cpudt)\s*>",
        ],
        tags=["delta", "loading"],
    ),
    BWPattern(
        name="authority_checks",
        description="Authority checks in ABAP routines (SU53-style)",
        classification=MigrationClassification.REPLACE,
        dsp_equivalent="DSP Data Access Controls (DAC)",
        rationale="BW authority checks translate to DSP DACs, which are declarative.",
        source_regexes=[
            r"authority.?check",
            r"su53",
            r"rsec",
            r"rssm_authorization",
        ],
        tags=["authorization", "security"],
    ),
    BWPattern(
        name="hierarchy_navigation",
        description="Hierarchy navigation via KNVH, SETLEAF, or hierarchy tables",
        classification=MigrationClassification.REPLACE,
        dsp_equivalent="DSP Hierarchy view or parent-child association",
        rationale="BW hierarchy tables have DSP-native hierarchy support.",
        source_regexes=[r"knvh", r"setleaf", r"rsthierarchy", r"hierarchy.*node"],
        tags=["hierarchy", "master_data"],
    ),
    # --- DROP candidates ---
    BWPattern(
        name="dead_process_chain",
        description="Process chain with no execution in >12 months",
        classification=MigrationClassification.DROP,
        dsp_equivalent="N/A — do not migrate",
        rationale="No recent execution suggests the chain is inactive/superseded.",
        metadata_checks=["last_run_months_ago:>12"],
        tags=["inactive", "process_chain"],
    ),
    BWPattern(
        name="unused_bex_query",
        description="BEx query with 0 executions in 12 months",
        classification=MigrationClassification.DROP,
        dsp_equivalent="N/A — do not migrate",
        rationale="Zero query usage means no business consumer.",
        metadata_checks=["key_exists:usage_count_zero"],
        tags=["inactive", "query"],
    ),
    BWPattern(
        name="test_objects",
        description="Objects with test/demo naming patterns (ZT, TEST, DEMO, TMP)",
        classification=MigrationClassification.DROP,
        dsp_equivalent="N/A — do not migrate",
        rationale="Test/demo objects should not be migrated to production DSP.",
        source_regexes=[r"(?:^|\s)(?:ZT|TEST|DEMO|TMP)_"],
        tags=["test", "naming"],
    ),
    # --- CLARIFY patterns ---
    BWPattern(
        name="complex_abap_routine",
        description="ABAP routine >200 lines with complex branching",
        classification=MigrationClassification.CLARIFY,
        dsp_equivalent="Requires manual analysis",
        rationale="Complex ABAP exceeds automated translation confidence. Needs human review.",
        source_regexes=[],
        tags=["complex", "manual_review"],
    ),
    BWPattern(
        name="dynamic_sql",
        description="Dynamic SQL construction or EXEC SQL in ABAP",
        classification=MigrationClassification.CLARIFY,
        dsp_equivalent="Requires manual analysis",
        rationale="Dynamic SQL patterns cannot be statically analyzed.",
        source_regexes=[r"exec\s+sql", r"cl_sql_statement", r"native\s+sql"],
        tags=["dynamic", "complex"],
    ),
    BWPattern(
        name="external_api_call",
        description="RFC/HTTP calls to external systems from transformation",
        classification=MigrationClassification.CLARIFY,
        dsp_equivalent="May need task chain or external integration",
        rationale="External API calls suggest side-effects that need architecture review.",
        source_regexes=[
            r"call\s+function\s+['\"](?!bapi)",
            r"http.*destination",
            r"rfc\s+destination",
        ],
        tags=["external", "integration"],
    ),
    BWPattern(
        name="custom_exit",
        description="Custom exit or enhancement implementation",
        classification=MigrationClassification.CLARIFY,
        dsp_equivalent="Requires analysis — may be DSP task chain or custom logic",
        rationale="Customer exits contain custom business logic that needs individual assessment.",
        source_regexes=[r"customer.?exit", r"badi\s", r"enhancement\s+implementation"],
        tags=["exit", "custom"],
    ),
    BWPattern(
        name="cross_system_lookup",
        description="Cross-system data lookup (reading from non-BW tables)",
        classification=MigrationClassification.CLARIFY,
        dsp_equivalent="May need replication flow or remote table",
        rationale="Cross-system reads need architecture decisions about data locality in DSP.",
        source_regexes=[r"select.*from\s+\w+\s+client\s+specified", r"select.*dbcon"],
        tags=["cross_system", "lookup"],
    ),
    # --- Additional SIMPLIFY patterns ---
    BWPattern(
        name="move_corresponding",
        description="MOVE-CORRESPONDING for field mapping between structures",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="Column mapping in view definition",
        rationale="MOVE-CORRESPONDING is just field-to-field mapping, native in DSP views.",
        source_regexes=[r"move-corresponding"],
        tags=["field_mapping", "routine"],
    ),
    BWPattern(
        name="string_concatenation",
        description="String concatenation for composite keys",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="CONCAT() function in SQL view",
        rationale="ABAP CONCATENATE → SQL CONCAT is direct.",
        source_regexes=[r"concatenate\s+\S+", r"&&.*into\s+\w+"],
        tags=["string", "routine"],
    ),
    BWPattern(
        name="date_conversion",
        description="Date format conversion (YYYYMMDD ↔ internal)",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="TO_DATE/TO_VARCHAR date functions",
        rationale="Date formatting is trivial SQL.",
        source_regexes=[r"budat.*\(\d\)", r"datum.*\+\d", r"sy-datum"],
        tags=["date", "conversion"],
    ),
    BWPattern(
        name="abap_select_star",
        description="SELECT * FROM database table in routine",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="SQL JOIN or subquery in view",
        rationale="Inline SELECT in ABAP routine = a join that belongs in the view layer.",
        source_regexes=[r"select\s+\*\s+from\s+\w+\s+into\s+table"],
        tags=["abap_routine", "select"],
    ),
    BWPattern(
        name="internal_table_sort",
        description="SORT internal table for binary search in routine",
        classification=MigrationClassification.SIMPLIFY,
        dsp_equivalent="SQL JOIN (DB handles sort/search natively)",
        rationale="Manual sort+binary search is just an indexed join in SQL.",
        source_regexes=[r"sort\s+\w+.*by\b", r"binary\s+search"],
        tags=["abap_routine", "performance"],
    ),
]

# Quick lookup by pattern name
PATTERNS_BY_NAME: dict[str, BWPattern] = {p.name: p for p in BW_PATTERNS}


def detect_patterns(source_code: str, metadata: Optional[dict] = None) -> list[BWPattern]:
    """Detect all matching BW patterns in given source code and metadata."""
    metadata = metadata or {}
    matched = []
    for pattern in BW_PATTERNS:
        if pattern.matches_source(source_code) or pattern.matches_metadata(metadata):
            matched.append(pattern)
    return matched


def detect_pattern_names(source_code: str, metadata: Optional[dict] = None) -> list[str]:
    """Return names of all matching patterns."""
    return [p.name for p in detect_patterns(source_code, metadata)]
