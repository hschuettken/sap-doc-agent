"""Doc QA Agent — validates documentation against quality standards."""

from __future__ import annotations
import re
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field
from spec2sphere.scanner.models import ScanResult, ScannedObject
from spec2sphere.llm.base import LLMProvider


class QualityRule(BaseModel):
    id: str
    name: str
    severity: str  # "critical", "important", "minor"
    check_type: str  # "field_required", "min_length", "pattern", "naming_convention"
    field: Optional[str] = None
    min_length: Optional[int] = None
    pattern: Optional[str] = None
    message: str = ""


class QualityStandard(BaseModel):
    name: str
    rules: list[QualityRule] = Field(default_factory=list)


class QualityIssue(BaseModel):
    object_id: str
    rule_id: str
    severity: str
    message: str
    field: Optional[str] = None


class QAReport(BaseModel):
    standard_name: str
    objects_checked: int = 0
    issues: list[QualityIssue] = Field(default_factory=list)
    total_checks: int = 0
    checks_passed: int = 0

    @property
    def score(self) -> float:
        if self.total_checks == 0:
            return 100.0
        return round((self.checks_passed / self.total_checks) * 100, 1)

    @property
    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        return counts


def load_standard(path: Path) -> QualityStandard:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return QualityStandard.model_validate(raw)


class DocQAAgent:
    def __init__(self, standards: list[QualityStandard], llm: Optional[LLMProvider] = None):
        self._standards = standards
        self._llm = llm

    def check_object(self, obj: ScannedObject) -> list[QualityIssue]:
        issues = []
        for std in self._standards:
            for rule in std.rules:
                issue = self._run_rule(rule, obj)
                if issue:
                    issues.append(issue)
        return issues

    def check_all(self, result: ScanResult) -> QAReport:
        all_issues: list[QualityIssue] = []
        total_rules = sum(len(s.rules) for s in self._standards)
        total_checks = len(result.objects) * total_rules
        for obj in result.objects:
            obj_issues = self.check_object(obj)
            all_issues.extend(obj_issues)
        combined_name = " + ".join(s.name for s in self._standards)
        return QAReport(
            standard_name=combined_name,
            objects_checked=len(result.objects),
            issues=all_issues,
            total_checks=total_checks,
            checks_passed=total_checks - len(all_issues),
        )

    def _run_rule(self, rule: QualityRule, obj: ScannedObject) -> Optional[QualityIssue]:
        if rule.check_type == "field_required":
            value = getattr(obj, rule.field, "")
            if not value:
                return QualityIssue(
                    object_id=obj.object_id,
                    rule_id=rule.id,
                    severity=rule.severity,
                    message=rule.message or f"Missing required field: {rule.field}",
                    field=rule.field,
                )

        elif rule.check_type == "min_length":
            value = getattr(obj, rule.field, "")
            if len(value) < (rule.min_length or 0):
                return QualityIssue(
                    object_id=obj.object_id,
                    rule_id=rule.id,
                    severity=rule.severity,
                    message=rule.message or f"Field '{rule.field}' too short (min {rule.min_length})",
                    field=rule.field,
                )

        elif rule.check_type == "pattern":
            value = getattr(obj, rule.field, "")
            if value and rule.pattern and not re.match(rule.pattern, value):
                return QualityIssue(
                    object_id=obj.object_id,
                    rule_id=rule.id,
                    severity=rule.severity,
                    message=rule.message or f"Field '{rule.field}' doesn't match pattern",
                    field=rule.field,
                )

        elif rule.check_type == "naming_convention":
            # Check name matches expected prefix for the layer
            if obj.layer and rule.pattern:
                expected_prefixes = rule.pattern.split("|")
                if not any(obj.name.startswith(p) for p in expected_prefixes):
                    return QualityIssue(
                        object_id=obj.object_id,
                        rule_id=rule.id,
                        severity=rule.severity,
                        message=rule.message or f"Name doesn't follow convention for {obj.layer} layer",
                        field="name",
                    )
        return None
