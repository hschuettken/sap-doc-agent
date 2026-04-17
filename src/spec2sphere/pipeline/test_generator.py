"""Test specification generator.

Generates structured test specifications from technical specs and SAC blueprints.
Supports two modes:
  - preservation: new model must match current behavior exactly (or within tolerance)
  - improvement: approved redesign with expected deltas documented

Test categories produced:
  DSP: structural, volume, aggregate, edge_case, sample_trace
  SAC: data_regression, visual, interaction, design_rule
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from spec2sphere.db import _get_conn
from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schema for LLM test case generation
# ---------------------------------------------------------------------------

_DSP_TEST_CASES_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "structural": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "query": {"type": "string"},
                    "expected": {"type": "object"},
                    "notes": {"type": "string"},
                },
                "required": ["title", "query"],
            },
        },
        "volume": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "query": {"type": "string"},
                    "expected": {"type": "object"},
                    "tolerance_type": {"type": "string", "enum": ["exact", "absolute", "percentage"]},
                    "tolerance_value": {"type": "number"},
                },
                "required": ["title", "query"],
            },
        },
        "aggregate": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "query": {"type": "string"},
                    "cut_dimension": {"type": "string"},
                    "tolerance_type": {"type": "string", "enum": ["exact", "absolute", "percentage"]},
                    "tolerance_value": {"type": "number"},
                },
                "required": ["title", "query"],
            },
        },
        "edge_case": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "scenario": {"type": "string"},
                    "query": {"type": "string"},
                    "expected": {"type": "object"},
                },
                "required": ["title", "scenario", "query"],
            },
        },
        "sample_trace": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "source_query": {"type": "string"},
                    "target_query": {"type": "string"},
                    "join_key": {"type": "string"},
                },
                "required": ["title", "description"],
            },
        },
    },
    "required": ["structural", "volume", "aggregate", "edge_case", "sample_trace"],
}

_SAC_TEST_CASES_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "data_regression": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "blueprint_page": {"type": "string"},
                    "widget_id": {"type": "string"},
                    "source_query": {"type": "string"},
                    "tolerance_type": {"type": "string", "enum": ["exact", "absolute", "percentage"]},
                    "tolerance_value": {"type": "number"},
                },
                "required": ["title", "blueprint_page"],
            },
        },
        "visual": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "blueprint_page": {"type": "string"},
                    "expected_layout": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["title", "blueprint_page", "expected_layout"],
            },
        },
        "interaction": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "blueprint_page": {"type": "string"},
                    "interaction_type": {
                        "type": "string",
                        "enum": ["filter", "navigation", "drill", "input_control"],
                    },
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "expected_result": {"type": "string"},
                },
                "required": ["title", "blueprint_page", "interaction_type"],
            },
        },
        "design_rule": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "rule": {"type": "string"},
                    "archetype": {"type": "string"},
                    "check": {"type": "string"},
                },
                "required": ["title", "rule"],
            },
        },
    },
    "required": ["data_regression", "visual", "interaction", "design_rule"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d


def _parse_jsonb(value) -> object:
    """Safely parse a JSONB value that may already be a dict/list or a JSON string."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


async def _fetch_tech_spec(conn, tech_spec_id: str, project_id) -> dict:
    if project_id is not None:
        row = await conn.fetchrow(
            "SELECT * FROM tech_specs WHERE id = $1::uuid AND project_id = $2",
            tech_spec_id,
            project_id,
        )
    else:
        row = await conn.fetchrow(
            "SELECT * FROM tech_specs WHERE id = $1::uuid",
            tech_spec_id,
        )
    if row is None:
        raise ValueError(f"TechSpec {tech_spec_id} not found")
    return _row_to_dict(row)


async def _fetch_technical_objects(conn, tech_spec_id: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM technical_objects WHERE tech_spec_id = $1::uuid ORDER BY created_at",
        tech_spec_id,
    )
    return [_row_to_dict(r) for r in rows]


async def _fetch_blueprint(conn, blueprint_id: str, project_id) -> Optional[dict]:
    if project_id is not None:
        row = await conn.fetchrow(
            "SELECT * FROM sac_blueprints WHERE id = $1::uuid AND project_id = $2",
            blueprint_id,
            project_id,
        )
    else:
        row = await conn.fetchrow(
            "SELECT * FROM sac_blueprints WHERE id = $1::uuid",
            blueprint_id,
        )
    if row is None:
        return None
    return _row_to_dict(row)


def _quote_object_name(name: str) -> str:
    """Double-quote SAP-style object names that may contain numbers/special chars."""
    return f'"{name}"'


# ---------------------------------------------------------------------------
# DEV copy commands
# ---------------------------------------------------------------------------


def generate_dev_copy_commands(objects: list[dict]) -> list[dict]:
    """For each DSP object in the list, generate SQL to create a _DEV copy.

    Returns:
        [{"object_name": str, "sql": str}]
    """
    commands: list[dict] = []
    for obj in objects:
        name = obj.get("name") or obj.get("object_name") or ""
        if not name:
            continue
        platform = (obj.get("platform") or "dsp").lower()
        if platform not in ("dsp", ""):
            continue
        q_src = _quote_object_name(name)
        q_dev = _quote_object_name(f"{name}_DEV")
        sql = f"CREATE TABLE {q_dev} AS SELECT * FROM {q_src}"
        commands.append({"object_name": name, "sql": sql})
    return commands


# ---------------------------------------------------------------------------
# Golden query catalog
# ---------------------------------------------------------------------------


def build_golden_queries(objects: list[dict], test_cases: list[dict]) -> list[dict]:
    """Select high-value regression queries from the aggregate and volume test cases.

    Prioritises:
      1. Aggregate tests with a named cut_dimension (most diagnostic value)
      2. Volume tests for leaf-layer objects (row count sanity)

    Returns:
        [{"name": str, "category": str, "sql": str, "expected_behavior": str}]
    """
    golden: list[dict] = []
    seen: set[str] = set()

    for tc in test_cases:
        category = tc.get("category", "")
        query = tc.get("query", "")
        if not query or query in seen:
            continue

        if category == "aggregate":
            golden.append(
                {
                    "name": tc.get("title", "Aggregate regression"),
                    "category": "aggregate",
                    "sql": query,
                    "expected_behavior": (
                        f"Totals by {tc.get('cut_dimension', 'dimension')} "
                        f"match baseline within tolerance {tc.get('tolerance', {})}"
                    ),
                }
            )
            seen.add(query)

    for tc in test_cases:
        category = tc.get("category", "")
        query = tc.get("query", "")
        if not query or query in seen:
            continue
        if category == "volume":
            golden.append(
                {
                    "name": tc.get("title", "Volume check"),
                    "category": "volume",
                    "sql": query,
                    "expected_behavior": f"Row count within tolerance {tc.get('tolerance', {})}",
                }
            )
            seen.add(query)

    # Cap at 20 golden queries to keep the catalog focused
    return golden[:20]


# ---------------------------------------------------------------------------
# Tolerance checker
# ---------------------------------------------------------------------------


def check_tolerance(baseline, candidate, rule: dict) -> dict:
    """Apply a tolerance rule to compare baseline vs candidate values.

    Args:
        baseline: The reference value (scalar — int/float)
        candidate: The new value to compare
        rule: {"type": "exact"|"absolute"|"percentage"|"expected_delta",
               "value": ...,          # threshold for absolute/percentage
               "description": ...}    # human note for expected_delta

    Returns:
        {"passed": bool, "delta": ..., "explanation": str}
    """
    rule_type = rule.get("type", "exact")

    try:
        b = float(baseline)
        c = float(candidate)
        delta = c - b
    except (TypeError, ValueError):
        # Non-numeric: fall back to equality check
        passed = baseline == candidate
        return {
            "passed": passed,
            "delta": None,
            "explanation": "Exact string/non-numeric comparison"
            if passed
            else f"Mismatch: {baseline!r} != {candidate!r}",
        }

    if rule_type == "exact":
        passed = b == c
        return {
            "passed": passed,
            "delta": delta,
            "explanation": "Exact match" if passed else f"Delta {delta} (exact match required)",
        }

    if rule_type == "absolute":
        threshold = float(rule.get("value", 0))
        passed = abs(delta) <= threshold
        return {
            "passed": passed,
            "delta": delta,
            "explanation": (
                f"Absolute delta {abs(delta):.6f} within threshold {threshold}"
                if passed
                else f"Absolute delta {abs(delta):.6f} exceeds threshold {threshold}"
            ),
        }

    if rule_type == "percentage":
        threshold_pct = float(rule.get("value", 0))
        if b == 0:
            passed = c == 0
            pct = 0.0 if passed else float("inf")
        else:
            pct = abs(delta / b) * 100
            passed = pct <= threshold_pct
        return {
            "passed": passed,
            "delta": delta,
            "explanation": (
                f"Percentage delta {pct:.2f}% within threshold {threshold_pct}%"
                if passed
                else f"Percentage delta {pct:.2f}% exceeds threshold {threshold_pct}%"
            ),
        }

    if rule_type == "expected_delta":
        description = rule.get("description", "Known acceptable change")
        return {
            "passed": True,  # expected_delta always passes — it is documented and approved
            "delta": delta,
            "explanation": f"Expected delta (approved): {description}",
        }

    return {
        "passed": False,
        "delta": delta,
        "explanation": f"Unknown tolerance rule type: {rule_type!r}",
    }


# ---------------------------------------------------------------------------
# LLM-assisted test case generation per object
# ---------------------------------------------------------------------------


async def _generate_dsp_tests_for_object(
    obj: dict,
    llm: LLMProvider,
    test_mode: str,
    counter: dict,
) -> list[dict]:
    """Call LLM to generate DSP test cases for one technical object.

    counter is a mutable dict used to assign sequential test IDs across calls.
    Returns a flat list of test case dicts.
    """
    name = obj.get("name", "unknown")
    definition = _parse_jsonb(obj.get("definition") or {})
    layer = obj.get("layer") or ""
    obj_type = obj.get("object_type") or ""

    obj_summary = json.dumps(
        {
            "name": name,
            "type": obj_type,
            "layer": layer,
            "definition": definition,
        },
        indent=2,
    )

    system_prompt = (
        "You are a senior SAP Data Sphere QA engineer. "
        "Generate comprehensive regression test cases for a DSP technical object. "
        "Each test case must include a runnable SQL query and clear pass criteria. "
        'Use double-quoted identifiers for SAP object names (e.g. SELECT COUNT(*) FROM "02_RV_SALES_CLEAN"). '
        "For aggregate tests, vary the GROUP BY dimension to cover time, region, and product cuts where applicable."
    )

    mode_instruction = (
        "Test mode is 'preservation': tests verify the new model produces identical results to the legacy system."
        if test_mode == "preservation"
        else "Test mode is 'improvement': tests document expected deltas from the redesign and verify they are intentional."
    )

    prompt = (
        f"Generate test cases for the following DSP object:\n\n{obj_summary}\n\n"
        f"{mode_instruction}\n\n"
        "Cover ALL five categories:\n"
        "1. structural — verify object existence, column names, data types, grain consistency\n"
        "2. volume — row counts, distinct counts, null distributions\n"
        "3. aggregate — KPI totals grouped by major business cuts (time/period, region, product, cost centre)\n"
        "4. edge_case — empty periods, missing source data, null/zero value handling\n"
        "5. sample_trace — source-to-target record examples with join keys\n\n"
        "For each test provide: title, SQL query, expected result structure, tolerance type."
    )

    result = await generate_json_with_retry(
        provider=llm,
        prompt=prompt,
        schema=_DSP_TEST_CASES_SCHEMA,
        system=system_prompt,
        max_retries=2,
        tier="test_generator",
        data_in_context=True,
    )

    if result is None:
        logger.warning("LLM returned no DSP tests for object %s, using minimal fallback", name)
        result = {
            "structural": [
                {
                    "title": f"Object {name} is accessible",
                    "query": f"SELECT 1 FROM {_quote_object_name(name)} LIMIT 1",
                    "expected": {"accessible": True},
                }
            ],
            "volume": [],
            "aggregate": [],
            "edge_case": [],
            "sample_trace": [],
        }

    tests: list[dict] = []

    category_defaults: dict[str, dict] = {
        "structural": {"type": "exact"},
        "volume": {"type": "percentage", "value": 5},
        "aggregate": {"type": "percentage", "value": 1},
        "edge_case": {"type": "exact"},
        "sample_trace": {"type": "exact"},
    }

    for category, items in result.items():
        if not isinstance(items, list):
            continue
        for item in items:
            n = counter.get(category, 0) + 1
            counter[category] = n
            test_id = f"{category}_{n:02d}"

            tolerance: dict
            if category in ("volume", "aggregate"):
                t_type = item.get("tolerance_type") or category_defaults[category]["type"]
                t_val = item.get("tolerance_value")
                if t_val is not None:
                    tolerance = {"type": t_type, "value": t_val}
                else:
                    tolerance = dict(category_defaults[category])
            else:
                tolerance = dict(category_defaults[category])

            tc: dict = {
                "test_id": test_id,
                "category": category,
                "object_name": name,
                "title": item.get("title", f"{category} check {n}"),
                "query": item.get("query") or item.get("source_query") or "",
                "tolerance": tolerance,
            }

            if "expected" in item:
                tc["expected"] = item["expected"]
            if category == "aggregate" and "cut_dimension" in item:
                tc["cut_dimension"] = item["cut_dimension"]
            if category == "sample_trace":
                if "target_query" in item:
                    tc["target_query"] = item["target_query"]
                if "join_key" in item:
                    tc["join_key"] = item["join_key"]
                if "description" in item:
                    tc["description"] = item["description"]
            if "notes" in item:
                tc["notes"] = item["notes"]

            tests.append(tc)

    return tests


async def _generate_sac_tests_for_blueprint(
    blueprint: dict,
    llm: LLMProvider,
    test_mode: str,
    counter: dict,
) -> list[dict]:
    """Call LLM to generate SAC test cases for a blueprint.

    Returns a flat list of SAC test case dicts.
    """
    pages = _parse_jsonb(blueprint.get("pages") or [])
    archetype = blueprint.get("archetype") or ""
    audience = blueprint.get("audience") or ""
    title = blueprint.get("title") or "SAC Blueprint"

    bp_summary = json.dumps(
        {
            "title": title,
            "archetype": archetype,
            "audience": audience,
            "page_count": len(pages) if isinstance(pages, list) else 0,
            "pages": (pages[:3] if isinstance(pages, list) else []),
        },
        indent=2,
    )

    system_prompt = (
        "You are a senior SAP Analytics Cloud QA engineer. "
        "Generate comprehensive test cases for an SAC story/application blueprint. "
        "Cover data integrity, visual layout conformance, user interaction flows, and design rule compliance. "
        "Reference specific page IDs and widget IDs from the blueprint where possible."
    )

    mode_instruction = (
        "Test mode is 'preservation': SAC output must match the legacy BW/BO report values exactly."
        if test_mode == "preservation"
        else "Test mode is 'improvement': document expected visual/functional improvements as approved deltas."
    )

    prompt = (
        f"Generate SAC test cases for the following blueprint:\n\n{bp_summary}\n\n"
        f"{mode_instruction}\n\n"
        "Cover ALL four categories:\n"
        "1. data_regression — KPI values in SAC widgets must match DSP source queries\n"
        "2. visual — page layouts must match blueprint archetypes and spacing rules\n"
        "3. interaction — filter controls, drill-down paths, and navigation flows\n"
        "4. design_rule — archetype compliance, title quality, widget density\n\n"
        "For each test provide: title, blueprint_page, expected result or step list."
    )

    result = await generate_json_with_retry(
        provider=llm,
        prompt=prompt,
        schema=_SAC_TEST_CASES_SCHEMA,
        system=system_prompt,
        max_retries=2,
        tier="test_generator",
        data_in_context=True,
    )

    if result is None:
        logger.warning("LLM returned no SAC tests for blueprint %s, using minimal fallback", blueprint.get("id"))
        result = {
            "data_regression": [
                {
                    "title": f"Blueprint '{title}' data loads",
                    "blueprint_page": "p1",
                    "source_query": "-- check KPIs load without error",
                }
            ],
            "visual": [],
            "interaction": [],
            "design_rule": [],
        }

    tests: list[dict] = []

    for category, items in result.items():
        if not isinstance(items, list):
            continue
        for item in items:
            n = counter.get(f"sac_{category}", 0) + 1
            counter[f"sac_{category}"] = n
            test_id = f"{category}_{n:02d}"

            tc: dict = {
                "test_id": test_id,
                "category": category,
                "blueprint_page": item.get("blueprint_page", "p1"),
                "title": item.get("title", f"{category} check {n}"),
            }

            if category == "data_regression":
                if "widget_id" in item:
                    tc["widget_id"] = item["widget_id"]
                if "source_query" in item:
                    tc["source_query"] = item["source_query"]
                t_type = item.get("tolerance_type", "exact")
                t_val = item.get("tolerance_value")
                tc["tolerance"] = {"type": t_type, "value": t_val} if t_val is not None else {"type": t_type}

            elif category == "visual":
                tc["expected_layout"] = item.get("expected_layout", f"{archetype} archetype")
                tc["tolerance"] = {
                    "type": "expected_delta",
                    "description": item.get("notes", "Minor spacing differences acceptable"),
                }

            elif category == "interaction":
                tc["interaction_type"] = item.get("interaction_type", "filter")
                if "steps" in item:
                    tc["steps"] = item["steps"]
                if "expected_result" in item:
                    tc["expected_result"] = item["expected_result"]
                tc["tolerance"] = {"type": "exact"}

            elif category == "design_rule":
                tc["rule"] = item.get("rule", "")
                if "archetype" in item:
                    tc["archetype"] = item["archetype"]
                if "check" in item:
                    tc["check"] = item["check"]
                tc["tolerance"] = {"type": "exact"}

            tests.append(tc)

    return tests


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def generate_test_spec(
    tech_spec_id: str,
    ctx: ContextEnvelope,
    llm: LLMProvider,
    blueprint_id: Optional[str] = None,
    test_mode: str = "preservation",
) -> dict:
    """Generate a test specification from a tech spec and optional SAC blueprint.

    Args:
        tech_spec_id: UUID of the tech_specs record.
        ctx: Request context envelope (used for project scoping).
        llm: LLM provider instance.
        blueprint_id: Optional UUID of the sac_blueprints record.
        test_mode: "preservation" (match current behavior) or "improvement" (document redesign deltas).

    Returns:
        {"test_spec_id": str, "test_case_count": int, "dsp_tests": int, "sac_tests": int,
         "mode": str, "status": "draft"}
    """
    if test_mode not in ("preservation", "improvement"):
        raise ValueError(f"Invalid test_mode: {test_mode!r}. Must be 'preservation' or 'improvement'.")

    # --- 1. Fetch tech spec + technical objects ---
    conn = await _get_conn()
    try:
        tech_spec = await _fetch_tech_spec(conn, tech_spec_id, ctx.project_id)
        objects = await _fetch_technical_objects(conn, tech_spec_id)

        blueprint: Optional[dict] = None
        if blueprint_id:
            blueprint = await _fetch_blueprint(conn, blueprint_id, ctx.project_id)
            if blueprint is None:
                logger.warning("Blueprint %s not found, skipping SAC tests", blueprint_id)
    finally:
        await conn.close()

    project_id = tech_spec.get("project_id") or ctx.project_id

    # --- 2. Generate DSP test cases per object ---
    dsp_tests: list[dict] = []
    counter: dict = {}  # shared counter for sequential test IDs across objects

    dsp_objects = [o for o in objects if (o.get("platform") or "dsp").lower() == "dsp"]
    if not dsp_objects:
        # Fall back to objects list inside tech_spec.objects JSONB
        spec_objects = _parse_jsonb(tech_spec.get("objects") or [])
        if isinstance(spec_objects, list):
            dsp_objects = [
                {
                    "name": o.get("name") or o.get("object_name", ""),
                    "platform": "dsp",
                    "object_type": o.get("type", ""),
                    "layer": o.get("layer", ""),
                    "definition": o,
                }
                for o in spec_objects
                if isinstance(o, dict) and (o.get("name") or o.get("object_name"))
            ]

    for obj in dsp_objects:
        try:
            obj_tests = await _generate_dsp_tests_for_object(obj, llm, test_mode, counter)
            dsp_tests.extend(obj_tests)
        except Exception as exc:
            logger.warning("DSP test generation failed for object %s: %s", obj.get("name"), exc)

    # --- 3. Generate SAC test cases (if blueprint provided) ---
    sac_tests: list[dict] = []
    if blueprint is not None:
        try:
            sac_tests = await _generate_sac_tests_for_blueprint(blueprint, llm, test_mode, counter)
        except Exception as exc:
            logger.warning("SAC test generation failed for blueprint %s: %s", blueprint_id, exc)

    # --- 4. Generate _DEV copy commands ---
    dev_copy_commands = generate_dev_copy_commands(dsp_objects)

    # --- 5. Build golden query catalog ---
    golden_queries = build_golden_queries(dsp_objects, dsp_tests)

    # --- 6. Build tolerance_rules and expected_deltas ---
    tolerance_rules: dict = {
        "default_dsp": {
            "structural": {"type": "exact"},
            "volume": {"type": "percentage", "value": 5},
            "aggregate": {"type": "percentage", "value": 1},
            "edge_case": {"type": "exact"},
            "sample_trace": {"type": "exact"},
        },
        "default_sac": {
            "data_regression": {"type": "exact"},
            "visual": {"type": "expected_delta", "description": "Minor spacing differences acceptable"},
            "interaction": {"type": "exact"},
            "design_rule": {"type": "exact"},
        },
    }

    expected_deltas: list[dict] = []
    if test_mode == "improvement":
        for tc in dsp_tests + sac_tests:
            if tc.get("tolerance", {}).get("type") == "expected_delta":
                expected_deltas.append(
                    {
                        "test_id": tc.get("test_id"),
                        "object": tc.get("object_name") or tc.get("blueprint_page"),
                        "description": tc.get("tolerance", {}).get("description", ""),
                    }
                )

    # --- 7. Assemble test_cases JSONB payload ---
    test_cases_payload: dict = {
        "dsp_tests": dsp_tests,
        "sac_tests": sac_tests,
        "dev_copy_commands": dev_copy_commands,
        "golden_queries": golden_queries,
    }

    # --- 8. Insert test_specs record ---
    test_spec_id = uuid.uuid4()
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO test_specs
                (id, project_id, tech_spec_id, version, test_mode,
                 test_cases, tolerance_rules, expected_deltas, status, created_at)
            VALUES ($1, $2, $3::uuid, 1, $4, $5::jsonb, $6::jsonb, $7::jsonb, 'draft', NOW())
            """,
            test_spec_id,
            project_id,
            tech_spec_id,
            test_mode,
            json.dumps(test_cases_payload),
            json.dumps(tolerance_rules),
            json.dumps(expected_deltas),
        )
    finally:
        await conn.close()

    total_dsp = len(dsp_tests)
    total_sac = len(sac_tests)
    total = total_dsp + total_sac

    logger.info(
        "Generated test_spec %s for tech_spec %s: %d DSP tests, %d SAC tests, mode=%s",
        test_spec_id,
        tech_spec_id,
        total_dsp,
        total_sac,
        test_mode,
    )

    return {
        "test_spec_id": str(test_spec_id),
        "test_case_count": total,
        "dsp_tests": total_dsp,
        "sac_tests": total_sac,
        "mode": test_mode,
        "status": "draft",
    }


async def get_test_spec(test_spec_id: str, project_id=None) -> Optional[dict]:
    """Fetch a test spec by ID, optionally scoped to a project.

    JSONB columns (test_cases, tolerance_rules, expected_deltas) are parsed
    into Python objects before returning.
    """
    conn = await _get_conn()
    try:
        if project_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM test_specs WHERE id = $1::uuid AND project_id = $2",
                test_spec_id,
                project_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM test_specs WHERE id = $1::uuid",
                test_spec_id,
            )
        if row is None:
            return None
        result = _row_to_dict(row)
        for field in ("test_cases", "tolerance_rules", "expected_deltas"):
            if field in result:
                result[field] = _parse_jsonb(result[field])
        return result
    finally:
        await conn.close()


async def list_test_specs(
    ctx: ContextEnvelope,
    tech_spec_id: Optional[str] = None,
) -> list[dict]:
    """List test specs for the active project, optionally filtered by tech_spec_id.

    Returns lightweight records (excludes test_cases JSONB for list performance).
    """
    if ctx.project_id is None:
        return []

    conditions: list[str] = ["project_id = $1"]
    params: list = [ctx.project_id]
    idx = 2

    if tech_spec_id is not None:
        conditions.append(f"tech_spec_id = ${idx}::uuid")
        params.append(tech_spec_id)
        idx += 1

    sql = (
        f"SELECT id, project_id, tech_spec_id, version, test_mode, "
        f"tolerance_rules, expected_deltas, status, created_at "
        f"FROM test_specs WHERE {' AND '.join(conditions)} ORDER BY created_at DESC"
    )

    conn = await _get_conn()
    try:
        rows = await conn.fetch(sql, *params)
        results = []
        for row in rows:
            d = _row_to_dict(row)
            for field in ("tolerance_rules", "expected_deltas"):
                if field in d:
                    d[field] = _parse_jsonb(d[field])
            results.append(d)
        return results
    finally:
        await conn.close()
