"""DSP SQL Validator — rule-based syntax checks for generated SQL.

Each rule corresponds to a known DSP SQL quirk from KNOWLEDGE.md.
Rules are applied statically (regex/string analysis), not by executing SQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SQLViolation:
    """A single SQL rule violation."""

    rule_id: str
    message: str
    severity: str  # "error" or "warning"
    line: int = 0  # 0 = applies to whole statement
    suggestion: str = ""


@dataclass
class SQLValidationResult:
    """Result of validating a DSP SQL statement."""

    violations: list[SQLViolation] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.violations) == 0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")


def validate_dsp_sql(sql: str) -> SQLValidationResult:
    """Validate a DSP SQL statement against all known rules.

    Returns a SQLValidationResult with any violations found.
    """
    if not sql.strip():
        return SQLValidationResult()

    violations: list[SQLViolation] = []

    violations.extend(_check_no_cte(sql))
    violations.extend(_check_limit_in_union(sql))
    violations.extend(_check_union_aliases(sql))
    violations.extend(_check_no_select_star_cross_space(sql))
    violations.extend(_check_cross_space_prefix(sql))
    violations.extend(_check_no_arrow_in_comments(sql))
    violations.extend(_check_datab_desc_in_row_number(sql))
    violations.extend(_check_varchar_date_comparison(sql))

    return SQLValidationResult(violations=violations)


# --- Individual rule checks ---


def _check_no_cte(sql: str) -> list[SQLViolation]:
    """Rule: no_cte — WITH/CTE clauses are not supported."""
    # Match WITH at the start of statement or after a semicolon, followed by identifier AS
    if re.search(r"(?:^|;)\s*WITH\s+\w+\s+AS\s*\(", sql, re.IGNORECASE | re.MULTILINE):
        return [
            SQLViolation(
                rule_id="no_cte",
                message="WITH/CTE clauses are not supported in DSP SQL. Use inline subqueries.",
                severity="error",
                suggestion="Replace WITH cte AS (...) SELECT ... with SELECT ... FROM (...) cte",
            )
        ]
    return []


def _check_limit_in_union(sql: str) -> list[SQLViolation]:
    """Rule: limit_in_union — LIMIT inside UNION ALL must be wrapped in parentheses."""
    if "union" not in sql.lower():
        return []

    # Find LIMIT that's not preceded by opening paren on the same SELECT leg
    # Pattern: LIMIT N followed by UNION ALL, but NOT inside parentheses
    # Simple heuristic: look for "LIMIT N\n...UNION ALL" without a leading "("
    lines = sql.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip().upper()
        if "LIMIT" in stripped and not stripped.startswith("("):
            # Check if there's a UNION ALL nearby
            context = "\n".join(lines[max(0, i - 2) : i + 3]).upper()
            if "UNION ALL" in context or "UNION" in context:
                return [
                    SQLViolation(
                        rule_id="limit_in_union",
                        message="LIMIT inside UNION ALL must be wrapped in parentheses.",
                        severity="error",
                        line=i + 1,
                        suggestion="Wrap each SELECT ... LIMIT N in parentheses: (SELECT ... LIMIT N)",
                    )
                ]
    return []


def _check_union_aliases(sql: str) -> list[SQLViolation]:
    """Rule: union_aliases — column aliases required on every UNION ALL leg."""
    upper = sql.upper()
    if "UNION ALL" not in upper and "UNION" not in upper:
        return []

    # Split by UNION ALL (case insensitive)
    legs = re.split(r"\bUNION\s+ALL\b", sql, flags=re.IGNORECASE)
    if len(legs) < 2:
        return []

    for i, leg in enumerate(legs):
        leg_stripped = leg.strip()
        if not leg_stripped:
            continue
        # Check if this leg has AS aliases (look for AS "..." or AS identifier)
        # First leg often has aliases; check subsequent legs
        if i > 0:
            # Simple check: does this leg have AS keyword in its SELECT clause?
            select_match = re.search(r"SELECT\s+(.+?)(?:FROM|$)", leg_stripped, re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = select_match.group(1)
                if " AS " not in select_clause.upper() and " as " not in select_clause:
                    return [
                        SQLViolation(
                            rule_id="union_aliases",
                            message=f"UNION ALL leg {i + 1} is missing column aliases.",
                            severity="error",
                            suggestion='Add AS "column_name" to every column in every UNION ALL leg.',
                        )
                    ]
    return []


def _check_no_select_star_cross_space(sql: str) -> list[SQLViolation]:
    """Rule: no_select_star_cross_space — SELECT * fails on cross-space joins."""
    # Check for SELECT * combined with cross-space reference pattern "SPACE"."view"
    has_select_star = bool(re.search(r"\bSELECT\s+\*", sql, re.IGNORECASE))
    has_cross_space = bool(re.search(r'"[A-Za-z0-9_]+"\."\w+"', sql))

    if has_select_star and has_cross_space:
        return [
            SQLViolation(
                rule_id="no_select_star_cross_space",
                message="SELECT * fails on cross-space joins. Use explicit column names.",
                severity="error",
                suggestion='Replace SELECT * with SELECT a."COL1", a."COL2" ...',
            )
        ]
    return []


def _check_cross_space_prefix(sql: str) -> list[SQLViolation]:
    """Rule: cross_space_prefix — cross-space references must use quoted \"SPACE\".\"view\" format."""
    # Detect unquoted dot-separated identifiers that look like space.view references
    # Pattern: word.word where both are uppercase/mixed and NOT inside quotes
    # This catches: OTHER_SPACE.view_name but not "OTHER_SPACE"."view_name"
    # Also catches: SAP_ADMIN.my_view but not "SAP_ADMIN"."my_view"
    if re.search(r'(?<!")\b[A-Z][A-Z0-9_]+\.\w+\b(?!")', sql):
        return [
            SQLViolation(
                rule_id="cross_space_prefix",
                message='Cross-space references must use quoted format: "SPACE"."view_name".',
                severity="warning",
                suggestion='Use "SPACE_NAME"."view_name" with double quotes.',
            )
        ]
    return []


def _check_no_arrow_in_comments(sql: str) -> list[SQLViolation]:
    """Rule: no_arrow_in_comments — avoid --> inside block comments."""
    # Find block comments and check for -->
    for match in re.finditer(r"/\*.*?\*/", sql, re.DOTALL):
        comment = match.group()
        if "-->" in comment:
            return [
                SQLViolation(
                    rule_id="no_arrow_in_comments",
                    message="Avoid --> inside block comments. DSP parser may misread it.",
                    severity="warning",
                    suggestion="Use -- (two dashes) or => instead of -->",
                )
            ]
    return []


def _check_datab_desc_in_row_number(sql: str) -> list[SQLViolation]:
    """Rule: datab_desc_in_row_number — ROW_NUMBER ORDER BY should include DATAB DESC."""
    # Find ROW_NUMBER() OVER (... ORDER BY ...) patterns
    row_number_pattern = re.compile(r"ROW_NUMBER\s*\(\s*\)\s*OVER\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)
    for match in row_number_pattern.finditer(sql):
        over_clause = match.group(1)
        # Check if ORDER BY exists but DATAB DESC is missing
        if re.search(r"ORDER\s+BY", over_clause, re.IGNORECASE):
            if not re.search(r"DATAB\s+DESC", over_clause, re.IGNORECASE):
                return [
                    SQLViolation(
                        rule_id="datab_desc_in_row_number",
                        message="ROW_NUMBER ORDER BY is missing DATAB DESC for validity period handling.",
                        severity="warning",
                        suggestion="Add DATAB DESC to ensure the most recent validity period wins.",
                    )
                ]
    return []


def _check_varchar_date_comparison(sql: str) -> list[SQLViolation]:
    """Rule: varchar_date_comparison — date comparisons must use VARCHAR YYYYMMDD."""
    # Check for DATAB/DATBI compared against date functions instead of string literals
    date_fields = ["DATAB", "DATBI"]
    for field_name in date_fields:
        pattern = rf"\b{field_name}\b\s*(?:<=?|>=?|=)\s*(?:CURRENT_DATE|NOW\(\)|SYSDATE|TO_DATE)"
        if re.search(pattern, sql, re.IGNORECASE):
            return [
                SQLViolation(
                    rule_id="varchar_date_comparison",
                    message=f"{field_name} compared against date function. SAP stores dates as VARCHAR YYYYMMDD.",
                    severity="warning",
                    suggestion=f"Use string comparison: {field_name} <= '20260101'",
                )
            ]
    return []
