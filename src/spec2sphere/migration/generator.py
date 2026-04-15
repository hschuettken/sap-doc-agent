"""DSP Code Generator: view specs → DSP SQL with traceability comments.

Simple views (filter/rename/aggregate with clear sql_logic) use template-based
generation. Complex views use LLM with DSP SQL rules injected into the system
prompt. All generated SQL is validated through sql_validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jinja2 import Template

from spec2sphere.llm.base import LLMProvider
from spec2sphere.migration.dsp_patterns import DSP_SQL_RULES
from spec2sphere.migration.models import TargetArchitecture, ViewSpec
from spec2sphere.migration.sql_validator import SQLValidationResult, validate_dsp_sql

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _build_system_prompt() -> str:
    """Build the generator system prompt with DSP SQL rules as hard constraints."""
    rules_text = "\n".join(f"- [{r.severity.upper()}] {r.rule_id}: {r.description}" for r in DSP_SQL_RULES)
    return (
        "You are an SAP Datasphere SQL developer. Generate clean, deployable DSP SQL.\n\n"
        "MANDATORY DSP SQL RULES — violations will cause deployment failure:\n"
        f"{rules_text}\n\n"
        "Return ONLY the SQL code. No markdown fences, no explanation."
    )


_GENERATE_SYSTEM = _build_system_prompt()


@dataclass
class GeneratedSQL:
    """Result of generating SQL for a single view."""

    technical_name: str
    space: str
    layer: str
    sql: str
    validation_result: Optional[SQLValidationResult] = None
    needs_manual_edit: bool = False
    generation_method: str = ""  # "template" or "llm" or "fallback"


def _is_simple_view(view: ViewSpec) -> bool:
    """Determine if a view is simple enough for template-based generation."""
    if not view.columns:
        return False
    if not view.source_objects:
        return False
    # Simple: has columns, has source, sql_logic is straightforward
    logic = view.sql_logic.upper()
    # Complex indicators: JOINs, subqueries, window functions, aggregation
    complex_indicators = [
        "JOIN",
        "ROW_NUMBER",
        "OVER (",
        "CASE WHEN",
        "UNION ALL",
        "GROUP BY",
        "SUM(",
        "AVG(",
        "COUNT(",
    ]
    return not any(ind in logic for ind in complex_indicators)


def _generate_template_sql(view: ViewSpec) -> str:
    """Generate SQL from a simple view spec using templates."""
    lines = []

    # Traceability header
    lines.append(f"-- View: {view.technical_name}")
    lines.append(f"-- Description: {view.description}")
    if view.source_chains:
        lines.append(f"-- Source: BW chain(s) {', '.join(view.source_chains)}")
    if view.collapsed_bw_steps:
        lines.append(f"-- Replaces BW steps: {', '.join(view.collapsed_bw_steps)}")
    if view.collapse_rationale:
        lines.append(f"-- Collapse rationale: {view.collapse_rationale}")
    lines.append("")

    # If sql_logic is provided, use it as the base
    if view.sql_logic:
        lines.append(view.sql_logic)
    else:
        # Generate from columns and source
        col_exprs = []
        for col in view.columns:
            if col.source_field and col.source_field != col.name:
                col_exprs.append(f'  "{col.source_field}" AS "{col.name}"')
            else:
                col_exprs.append(f'  "{col.name}"')

        source = view.source_objects[0] if view.source_objects else "UNKNOWN_SOURCE"
        lines.append("SELECT")
        lines.append(",\n".join(col_exprs))
        lines.append(f'FROM "{source}"')

    return "\n".join(lines)


def _load_generate_template() -> Template:
    template_path = _PROMPT_DIR / "generate_sql.md"
    return Template(template_path.read_text())


def _build_generate_prompt(view: ViewSpec) -> str:
    """Build the LLM prompt for SQL generation."""
    template = _load_generate_template()
    return template.render(
        technical_name=view.technical_name,
        space=view.space,
        layer=view.layer,
        semantic_usage=view.semantic_usage,
        description=view.description,
        source_objects=view.source_objects,
        source_chains=view.source_chains,
        collapsed_bw_steps=view.collapsed_bw_steps,
        collapse_rationale=view.collapse_rationale,
        columns=[c.model_dump() for c in view.columns],
        sql_logic=view.sql_logic,
        persistence=view.persistence,
    )


async def generate_sql_for_view(
    view: ViewSpec,
    llm: LLMProvider,
) -> GeneratedSQL:
    """Generate DSP SQL for a single view specification.

    Uses template-based generation for simple views, LLM for complex views.
    All generated SQL is validated against DSP SQL rules.
    """
    if _is_simple_view(view):
        sql = _generate_template_sql(view)
        method = "template"
    else:
        sql = await _generate_with_llm(view, llm)
        method = "llm" if sql else "fallback"

    if not sql:
        # Final fallback: use the sql_logic sketch with traceability
        sql = _generate_fallback_sql(view)
        method = "fallback"

    validation = validate_dsp_sql(sql)
    needs_edit = method == "fallback" or validation.error_count > 0

    return GeneratedSQL(
        technical_name=view.technical_name,
        space=view.space,
        layer=view.layer,
        sql=sql,
        validation_result=validation,
        needs_manual_edit=needs_edit,
        generation_method=method,
    )


async def _generate_with_llm(view: ViewSpec, llm: LLMProvider) -> str:
    """Generate SQL using LLM with DSP rules in the prompt."""
    prompt = _build_generate_prompt(view)
    result = await llm.generate(prompt, system=_GENERATE_SYSTEM)
    if not result:
        return ""
    # Strip markdown fences if present
    sql = result.strip()
    if sql.startswith("```"):
        lines = sql.split("\n")
        # Remove first and last lines if they're fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        sql = "\n".join(lines)
    return sql


def _generate_fallback_sql(view: ViewSpec) -> str:
    """Fallback: wrap the sql_logic sketch with traceability comments."""
    lines = [
        f"-- TODO: Manual review required for {view.technical_name}",
        f"-- Description: {view.description}",
    ]
    if view.source_chains:
        lines.append(f"-- Source: BW chain(s) {', '.join(view.source_chains)}")
    if view.collapsed_bw_steps:
        lines.append(f"-- Replaces BW steps: {', '.join(view.collapsed_bw_steps)}")
    lines.append("")
    lines.append(view.sql_logic if view.sql_logic else "-- No SQL logic provided")
    return "\n".join(lines)


async def generate_sql_for_architecture(
    architecture: TargetArchitecture,
    llm: LLMProvider,
) -> list[GeneratedSQL]:
    """Generate SQL for all views in a target architecture."""
    results = []
    for view in architecture.views:
        result = await generate_sql_for_view(view, llm)
        results.append(result)
    return results
