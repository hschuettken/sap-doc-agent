"""Code Quality Agent — rule-based ABAP code quality checks."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from sap_doc_agent.scanner.models import ScannedObject, ScanResult


class CodeIssue(BaseModel):
    object_id: str
    rule: str
    severity: str  # "critical", "important", "minor"
    message: str
    line: Optional[int] = None


class CodeQualityAgent:
    """Performs rule-based ABAP code quality analysis on scanned objects."""

    def check_object(self, obj: ScannedObject) -> list[CodeIssue]:
        """Run all code quality checks on a single object. Returns empty list if no source_code."""
        if not obj.source_code:
            return []

        issues: list[CodeIssue] = []
        for check in (
            self._check_select_star,
            self._check_hardcoded_client,
            self._check_missing_where,
            self._check_magic_numbers,
            self._check_empty_catch,
            self._check_nested_select,
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
    # Individual rule checks
    # ------------------------------------------------------------------

    def _check_select_star(self, obj: ScannedObject) -> list[CodeIssue]:
        """Detect SELECT * FROM (excluding SELECT * INTO patterns)."""
        issues: list[CodeIssue] = []
        # Match SELECT * FROM but not SELECT * INTO (where INTO immediately follows *)
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
        # Match = '000', = '100', = '800' etc. — 3-digit clients in single quotes
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
        # Look for lines that contain SELECT and FROM but not WHERE
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
        # Match CATCH ... . on same line with no statements between
        pattern = re.compile(r"\bCATCH\b[^.]*\.", re.IGNORECASE)
        lines = obj.source_code.splitlines()
        in_catch = False
        catch_line = 0
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if re.search(r"\bCATCH\b", stripped, re.IGNORECASE):
                in_catch = True
                catch_line = lineno
                # Check if CATCH and period are on the same line with nothing between
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
