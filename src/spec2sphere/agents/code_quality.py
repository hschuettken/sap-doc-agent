"""Code Quality Agent — rule-based ABAP and HANA SQL code quality checks."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from spec2sphere.scanner.models import ScannedObject, ScanResult

# Keywords that indicate HANA SQL / Datasphere SQL view source.
# Must be checked BEFORE ABAP so that CREATE VIEW is not misidentified as ABAP.
_SQL_PATTERNS = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b",
    re.IGNORECASE,
)

# Known layer prefixes for naming-convention checks
_LAYER_PREFIXES: dict[str, list[str]] = {
    "raw": ["01_", "RAW_", "LT_", "RT_", "RF_"],
    "harmonized": ["02_", "HARM_", "RV_", "FV_", "MD_", "HV_"],
    "mart": ["03_", "MART_"],
}


def _is_sql(source_code: str) -> bool:
    return bool(_SQL_PATTERNS.search(source_code))


def _is_abap(source_code: str) -> bool:
    """Return True when source looks like ABAP (anything that isn't clearly SQL)."""
    return not _is_sql(source_code)


class CodeIssue(BaseModel):
    object_id: str
    rule: str
    severity: str  # "critical", "important", "minor"
    message: str
    line: Optional[int] = None


class CodeQualityAgent:
    """Performs rule-based ABAP and HANA SQL code quality analysis on scanned objects."""

    def check_object(self, obj: ScannedObject) -> list[CodeIssue]:
        """Run all code quality checks on a single object."""
        issues: list[CodeIssue] = []

        # Data model checks run on every object regardless of source_code
        for check in (
            self._check_layer_assignment,
            self._check_naming_prefix,
            self._check_description_quality,
        ):
            issues.extend(check(obj))

        if not obj.source_code:
            return issues

        # ABAP checks
        if _is_abap(obj.source_code):
            for check in (
                self._check_select_star,
                self._check_hardcoded_client,
                self._check_missing_where,
                self._check_magic_numbers,
                self._check_empty_catch,
                self._check_nested_select,
            ):
                issues.extend(check(obj))

        # SQL / Datasphere view checks
        if _is_sql(obj.source_code):
            for check in (
                self._check_sql_select_star,
                self._check_sql_union_missing_alias,
                self._check_sql_cross_space_star,
                self._check_sql_limit_without_parens,
                self._check_sql_hardcoded_dates,
            ):
                issues.extend(check(obj))

        return issues

    def check_all(self, result: ScanResult) -> list[CodeIssue]:
        """Run check_object on all objects in a ScanResult."""
        issues: list[CodeIssue] = []
        for obj in result.objects:
            issues.extend(self.check_object(obj))
        return issues

    # ------------------------------------------------------------------
    # ABAP rule checks
    # ------------------------------------------------------------------

    def _check_select_star(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect SELECT * FROM (excluding SELECT * INTO patterns)."""
        issues: list[CodeIssue] = []
        pattern = re.compile(r"SELECT\s+\*\s+FROM", re.IGNORECASE)
        exclude = re.compile(r"SELECT\s+\*\s+INTO", re.IGNORECASE)
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            if pattern.search(line) and not exclude.search(line):
                issues.append(
                    CodeIssue(
                        object_id=obj.object_id,
                        rule="select_star",
                        severity="important",
                        message="SELECT * used — select only required fields instead",
                        line=lineno,
                    )
                )
        return issues

    def _check_hardcoded_client(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect hardcoded SAP client numbers (3-digit strings like '000', '100', '800')."""
        issues: list[CodeIssue] = []
        pattern = re.compile(r"=\s*'(\d{3})'")
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            m = pattern.search(line)
            if m:
                issues.append(
                    CodeIssue(
                        object_id=obj.object_id,
                        rule="hardcoded_client",
                        severity="critical",
                        message=f"Hardcoded client number '{m.group(1)}' — use SY-MANDT instead",
                        line=lineno,
                    )
                )
        return issues

    def _check_missing_where(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect SELECT ... FROM statements without a WHERE clause on the same statement."""
        issues: list[CodeIssue] = []
        pattern = re.compile(r"\bSELECT\b.*\bFROM\b", re.IGNORECASE)
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            if pattern.search(line):
                if not re.search(r"\bWHERE\b", line, re.IGNORECASE):
                    issues.append(
                        CodeIssue(
                            object_id=obj.object_id,
                            rule="missing_where",
                            severity="important",
                            message="SELECT without WHERE clause may cause full table scan",
                            line=lineno,
                        )
                    )
        return issues

    def _check_magic_numbers(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect hardcoded date literals like '20251231'."""
        issues: list[CodeIssue] = []
        pattern = re.compile(r"'20\d{6}'")
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            if pattern.search(line):
                issues.append(
                    CodeIssue(
                        object_id=obj.object_id,
                        rule="magic_numbers",
                        severity="minor",
                        message="Hardcoded date literal found — use a variable or constant instead",
                        line=lineno,
                    )
                )
        return issues

    def _check_empty_catch(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect empty CATCH blocks (CATCH followed by period with no statements)."""
        issues: list[CodeIssue] = []
        pattern = re.compile(r"\bCATCH\b[^.]*\.", re.IGNORECASE)
        lines = obj.source_code.splitlines()
        in_catch = False
        catch_line = 0
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if re.search(r"\bCATCH\b", stripped, re.IGNORECASE):
                in_catch = True
                catch_line = lineno
                if pattern.search(stripped):
                    issues.append(
                        CodeIssue(
                            object_id=obj.object_id,
                            rule="empty_catch",
                            severity="important",
                            message="Empty CATCH block — handle or re-raise exceptions explicitly",
                            line=lineno,
                        )
                    )
                    in_catch = False
            elif in_catch:
                if stripped and not stripped.startswith("*") and not stripped.startswith('"'):
                    in_catch = False  # Non-empty catch
        return issues

    def _check_nested_select(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect SELECT statements inside LOOP...ENDLOOP blocks."""
        issues: list[CodeIssue] = []
        loop_depth = 0
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            stripped = line.strip()
            if re.match(r"\bLOOP\b", stripped, re.IGNORECASE):
                loop_depth += 1
            elif re.match(r"\bENDLOOP\b", stripped, re.IGNORECASE):
                loop_depth = max(0, loop_depth - 1)
            elif loop_depth > 0 and re.search(r"\bSELECT\b", stripped, re.IGNORECASE):
                issues.append(
                    CodeIssue(
                        object_id=obj.object_id,
                        rule="nested_select",
                        severity="critical",
                        message="SELECT inside LOOP — use JOIN or pre-fetch data before the loop",
                        line=lineno,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # HANA SQL / Datasphere view rule checks
    # ------------------------------------------------------------------

    def _check_sql_select_star(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect SELECT * in SQL views."""
        issues: list[CodeIssue] = []
        pattern = re.compile(r"\bSELECT\s+\*", re.IGNORECASE)
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            if pattern.search(line):
                issues.append(
                    CodeIssue(
                        object_id=obj.object_id,
                        rule="sql_select_star",
                        severity="important",
                        message="SELECT * in SQL view — always use explicit column list",
                        line=lineno,
                    )
                )
        return issues

    def _check_sql_union_missing_alias(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect UNION ALL where SELECT legs don't use AS column aliases."""
        issues: list[CodeIssue] = []
        source = obj.source_code
        if not re.search(r"\bUNION\s+ALL\b", source, re.IGNORECASE):
            return issues
        # Split on UNION ALL and check each SELECT leg for AS aliases
        legs = re.split(r"\bUNION\s+ALL\b", source, flags=re.IGNORECASE)
        for leg_idx, leg in enumerate(legs):
            # Find the SELECT portion of each leg
            select_match = re.search(r"\bSELECT\b(.*?)(?:\bFROM\b|$)", leg, re.IGNORECASE | re.DOTALL)
            if select_match:
                select_cols = select_match.group(1)
                # If no AS keyword found in the column list, flag it
                if not re.search(r"\bAS\b", select_cols, re.IGNORECASE):
                    issues.append(
                        CodeIssue(
                            object_id=obj.object_id,
                            rule="sql_union_missing_alias",
                            severity="important",
                            message=f"UNION ALL leg {leg_idx + 1} — column aliases (AS) required on every leg for consistency",
                        )
                    )
        return issues

    def _check_sql_cross_space_star(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect SELECT * combined with cross-space references like \"SPACE\".\"VIEW\"."""
        issues: list[CodeIssue] = []
        cross_space = re.compile(r'"[A-Z_][A-Z0-9_]*"\."[A-Z_][A-Z0-9_]*"', re.IGNORECASE)
        select_star = re.compile(r"\bSELECT\s+\*", re.IGNORECASE)
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            if select_star.search(line) and cross_space.search(line):
                issues.append(
                    CodeIssue(
                        object_id=obj.object_id,
                        rule="sql_cross_space_star",
                        severity="important",
                        message="SELECT * with cross-space reference — explicit columns prevent breakage when remote view schema changes",
                        line=lineno,
                    )
                )
        return issues

    def _check_sql_limit_without_parens(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect LIMIT inside UNION ALL without wrapping parentheses (HANA quirk)."""
        issues: list[CodeIssue] = []
        source = obj.source_code
        if not re.search(r"\bUNION\s+ALL\b", source, re.IGNORECASE):
            return issues
        # A LIMIT that is NOT preceded by ) on its leg (not wrapped in parens)
        # Heuristic: find LIMIT that appears between UNION ALL legs without a closing paren before it
        legs = re.split(r"\bUNION\s+ALL\b", source, flags=re.IGNORECASE)
        for leg_idx, leg in enumerate(legs):
            if re.search(r"\bLIMIT\b", leg, re.IGNORECASE):
                # Check if the leg ends with ) before LIMIT (i.e., is wrapped)
                limit_match = re.search(r"\bLIMIT\b", leg, re.IGNORECASE)
                if limit_match:
                    before_limit = leg[: limit_match.start()].rstrip()
                    if not before_limit.endswith(")"):
                        issues.append(
                            CodeIssue(
                                object_id=obj.object_id,
                                rule="sql_limit_without_parens",
                                severity="important",
                                message=f"LIMIT in UNION ALL leg {leg_idx + 1} without wrapping parentheses — wrap each SELECT leg in parens to avoid HANA parse errors",
                            )
                        )
        return issues

    def _check_sql_hardcoded_dates(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect hardcoded date strings in format 'YYYYMMDD' (starting with 19 or 20)."""
        issues: list[CodeIssue] = []
        pattern = re.compile(r"'((?:19|20)\d{6})'")
        for lineno, line in enumerate(obj.source_code.splitlines(), start=1):
            if pattern.search(line):
                issues.append(
                    CodeIssue(
                        object_id=obj.object_id,
                        rule="sql_hardcoded_dates",
                        severity="minor",
                        message="Hardcoded date string in SQL — use parameters or calculated date expressions instead",
                        line=lineno,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # Data model quality checks (run on all objects)
    # ------------------------------------------------------------------

    def _check_layer_assignment(self, obj: ScannedObject) -> list[CodeIssue]:
        """Flag objects with no layer assigned."""
        issues: list[CodeIssue] = []
        if not obj.layer or not obj.layer.strip():
            issues.append(
                CodeIssue(
                    object_id=obj.object_id,
                    rule="layer_assignment",
                    severity="minor",
                    message="No architecture layer assigned — assign to raw, harmonized, or mart layer",
                )
            )
        return issues

    def _check_naming_prefix(self, obj: ScannedObject) -> list[CodeIssue]:
        """Flag objects in a known layer where the name doesn't match expected prefix."""
        issues: list[CodeIssue] = []
        if not obj.layer:
            return issues
        layer_key = obj.layer.lower().strip()
        expected_prefixes = _LAYER_PREFIXES.get(layer_key)
        if expected_prefixes is None:
            return issues  # Unknown layer — no rule to enforce
        name_upper = obj.name.upper()
        if not any(name_upper.startswith(p.upper()) for p in expected_prefixes):
            issues.append(
                CodeIssue(
                    object_id=obj.object_id,
                    rule="naming_prefix",
                    severity="minor",
                    message=(
                        f"Object in '{obj.layer}' layer but name '{obj.name}' doesn't match "
                        f"expected prefixes: {', '.join(expected_prefixes)}"
                    ),
                )
            )
        return issues

    def _check_description_quality(self, obj: ScannedObject) -> list[CodeIssue]:
        """Flag objects with a description shorter than 10 characters."""
        issues: list[CodeIssue] = []
        if len(obj.description.strip()) < 10:
            issues.append(
                CodeIssue(
                    object_id=obj.object_id,
                    rule="description_quality",
                    severity="minor",
                    message="Description too brief for documentation — provide at least 10 characters",
                )
            )
        return issues
