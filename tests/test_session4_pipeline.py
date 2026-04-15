"""Tests for Session 4: Pipeline — Tech Spec, Blueprint, and Test Generator.

Covers:
  - Tech Spec Generator (generate_tech_spec, naming prefix, topological sort,
    SQL validation, SAC skip, get_tech_spec, list_tech_specs)
  - Blueprint Generator (generate_blueprint, artifact type decision,
    widget type selection, performance classification, design tokens, LLM fallback)
  - Test Generator (generate_test_spec, test modes, dev copy commands,
    golden queries, tolerance checks)
  - SQL Validation integration (CTE detection, clean SQL)
  - Approval checklist items for tech_spec and sac_blueprint

All database calls are intercepted via patch("...._get_conn") returning an
AsyncMock connection.  No real database is required.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spec2sphere.tenant.context import ContextEnvelope


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_ctx(project_id=None) -> ContextEnvelope:
    return ContextEnvelope.single_tenant(
        tenant_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
    )


def make_mock_conn():
    conn = AsyncMock()
    conn.close = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetchval = AsyncMock(return_value=0)
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    return conn


def make_mock_llm(json_response=None):
    llm = AsyncMock()
    llm.is_available = MagicMock(return_value=True)
    llm.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    llm.generate_json = AsyncMock(return_value=json_response or {})
    return llm


class _DictRecord(dict):
    """Fake asyncpg Record — supports both dict[key] and attribute access."""

    pass


def _make_hla_row(
    hla_id=None,
    project_id=None,
    status="approved",
    views=None,
    sac_strategy=None,
    narrative="Test HLA narrative",
):
    """Build a minimal HLA document DB row."""
    content = {
        "views": views or [],
        "sac_reporting_strategy": sac_strategy or [],
    }
    return _DictRecord(
        {
            "id": hla_id or uuid.uuid4(),
            "project_id": project_id or uuid.uuid4(),
            "status": status,
            "narrative": narrative,
            "content": json.dumps(content),
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )


def _make_tech_spec_row(
    spec_id=None,
    project_id=None,
    objects=None,
    dep_graph=None,
    deployment_order=None,
):
    return _DictRecord(
        {
            "id": spec_id or uuid.uuid4(),
            "project_id": project_id or uuid.uuid4(),
            "hla_id": str(uuid.uuid4()),
            "version": 1,
            "status": "draft",
            "approved_by": None,
            "approved_at": None,
            "objects": json.dumps(objects or []),
            "dependency_graph": json.dumps(dep_graph or {}),
            "deployment_order": json.dumps(deployment_order or []),
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )


def _make_tech_obj_row(name="02_RV_SALES", platform="dsp", layer="harmonized", definition=None):
    return _DictRecord(
        {
            "id": uuid.uuid4(),
            "tech_spec_id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "name": name,
            "object_type": "relational_view",
            "platform": platform,
            "layer": layer,
            "definition": json.dumps(definition or {"columns": [], "sql": "SELECT 1"}),
            "generated_artifact": "SELECT 1",
            "implementation_route": "api",
            "route_confidence": 0.85,
            "status": "planned",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )


# ---------------------------------------------------------------------------
# Tech Spec Generator Tests
# ---------------------------------------------------------------------------


class TestTechSpecGenerator:
    """Tests for spec2sphere.pipeline.tech_spec_generator."""

    @pytest.mark.asyncio
    async def test_generate_tech_spec_from_hla(self):
        """generate_tech_spec creates tech_spec + technical_objects records."""
        ctx = make_ctx()
        project_id = ctx.project_id
        hla_id = str(uuid.uuid4())

        views = [
            {
                "name": "RV_SALES",
                "layer": "HARMONIZED",
                "type": "relational_dataset",
                "sources": [],
                "columns": [{"name": "KUNNR"}],
                "platform_placement": "dsp",
            }
        ]
        hla_row = _make_hla_row(hla_id=hla_id, project_id=project_id, views=views)

        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=hla_row)

        llm_detail = {
            "columns": [{"name": "KUNNR", "data_type": "NVARCHAR(10)", "is_key": True}],
            "sql": 'SELECT KUNNR FROM "01_LT_KNA1"',
        }

        with (
            patch(
                "spec2sphere.pipeline.tech_spec_generator._get_conn",
                new_callable=AsyncMock,
                return_value=conn,
            ),
            patch(
                "spec2sphere.pipeline.tech_spec_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=llm_detail,
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ) as _mock_kb,
        ):
            from spec2sphere.pipeline.tech_spec_generator import generate_tech_spec

            result = await generate_tech_spec(hla_id=hla_id, ctx=ctx, llm=make_mock_llm())

        assert "tech_spec_id" in result
        assert result["object_count"] == 1
        assert result["dsp_objects"] == 1
        assert result["sac_objects"] == 0
        assert result["status"] == "draft"

    def test_naming_prefix_applied(self):
        """_apply_naming_prefix prepends correct layer prefix and does not double-prefix."""
        from spec2sphere.pipeline.tech_spec_generator import _apply_naming_prefix

        # raw layer
        assert _apply_naming_prefix("VBAP", "raw") == "01_LT_VBAP"
        # harmonized layer
        assert _apply_naming_prefix("SALES_CLEAN", "harmonized") == "02_RV_SALES_CLEAN"
        # mart layer
        assert _apply_naming_prefix("FACT_SALES", "mart") == "03_FV_FACT_SALES"
        # consumption layer
        assert _apply_naming_prefix("CV_REVENUE", "consumption") == "04_CV_CV_REVENUE"
        # already prefixed — should not double-add
        assert _apply_naming_prefix("02_RV_SALES_CLEAN", "harmonized") == "02_RV_SALES_CLEAN"
        # wrong prefix gets replaced
        result = _apply_naming_prefix("01_LT_SALES_CLEAN", "harmonized")
        assert result.startswith("02_RV_")

    def test_topological_sort_order(self):
        """_topological_sort produces correct deployment order for a chain A->B->C."""
        from spec2sphere.pipeline.tech_spec_generator import _topological_sort

        # A has no deps, B depends on A, C depends on B
        names = ["C", "A", "B"]
        dep_graph = {
            "A": [],
            "B": ["A"],
            "C": ["B"],
        }
        layer_by_name = {"A": "raw", "B": "harmonized", "C": "mart"}

        ordered = _topological_sort(names, dep_graph, layer_by_name)

        assert ordered.index("A") < ordered.index("B")
        assert ordered.index("B") < ordered.index("C")

    @pytest.mark.asyncio
    async def test_sql_generation_and_validation(self):
        """SQL with CTE causes a validation error count > 0."""
        from spec2sphere.pipeline.tech_spec_generator import _generate_dsp_object_detail

        view = {
            "name": "02_RV_SALES",
            "layer": "harmonized",
            "type": "relational_dataset",
            "sources": [],
            "columns": [],
        }
        # LLM returns SQL with a CTE — this violates the no-CTE DSP rule
        cte_sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
        llm_detail = {"columns": [], "sql": cte_sql}

        with patch(
            "spec2sphere.pipeline.tech_spec_generator.generate_json_with_retry",
            new_callable=AsyncMock,
            return_value=llm_detail,
        ):
            _definition, _sql, error_count = await _generate_dsp_object_detail(
                view=view,
                hla_context={},
                llm=make_mock_llm(),
            )

        assert error_count > 0

    @pytest.mark.asyncio
    async def test_sac_objects_skip_sql(self):
        """Objects with platform_placement='sac' should not call the LLM for SQL."""
        ctx = make_ctx()
        hla_id = str(uuid.uuid4())

        views = [
            {
                "name": "SALES_OVERVIEW",
                "layer": "CONSUMPTION",
                "type": "analytic_model",
                "sources": [],
                "platform_placement": "sac",
            }
        ]
        hla_row = _make_hla_row(hla_id=hla_id, project_id=ctx.project_id, views=views)

        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=hla_row)

        llm_mock = make_mock_llm()

        with (
            patch(
                "spec2sphere.pipeline.tech_spec_generator._get_conn",
                new_callable=AsyncMock,
                return_value=conn,
            ),
            patch(
                "spec2sphere.pipeline.tech_spec_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_llm_call,
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            from spec2sphere.pipeline.tech_spec_generator import generate_tech_spec

            result = await generate_tech_spec(hla_id=hla_id, ctx=ctx, llm=llm_mock)

        # SAC object should not trigger any LLM calls for SQL generation
        mock_llm_call.assert_not_called()
        assert result["sac_objects"] == 1
        assert result["dsp_objects"] == 0

    @pytest.mark.asyncio
    async def test_get_tech_spec(self):
        """get_tech_spec fetches a record and parses JSONB columns."""
        spec_id = str(uuid.uuid4())
        objects = ["02_RV_SALES"]
        dep_graph = {"02_RV_SALES": []}
        deployment_order = [{"order": 1, "name": "02_RV_SALES"}]

        row = _make_tech_spec_row(
            spec_id=spec_id,
            objects=objects,
            dep_graph=dep_graph,
            deployment_order=deployment_order,
        )
        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch(
            "spec2sphere.pipeline.tech_spec_generator._get_conn",
            new_callable=AsyncMock,
            return_value=conn,
        ):
            from spec2sphere.pipeline.tech_spec_generator import get_tech_spec

            result = await get_tech_spec(spec_id)

        assert result is not None
        assert isinstance(result["objects"], list)
        assert isinstance(result["dependency_graph"], dict)
        assert isinstance(result["deployment_order"], list)

    @pytest.mark.asyncio
    async def test_list_tech_specs(self):
        """list_tech_specs returns a list of records scoped to the project."""
        ctx = make_ctx()
        rows = [_make_tech_spec_row(project_id=ctx.project_id) for _ in range(3)]

        conn = make_mock_conn()
        conn.fetch = AsyncMock(return_value=rows)

        with patch(
            "spec2sphere.pipeline.tech_spec_generator._get_conn",
            new_callable=AsyncMock,
            return_value=conn,
        ):
            from spec2sphere.pipeline.tech_spec_generator import list_tech_specs

            results = await list_tech_specs(ctx)

        assert len(results) == 3


# ---------------------------------------------------------------------------
# Blueprint Generator Tests
# ---------------------------------------------------------------------------


class TestBlueprintGenerator:
    """Tests for spec2sphere.pipeline.blueprint_generator."""

    @pytest.mark.asyncio
    async def test_generate_blueprint_from_hla(self):
        """generate_blueprint creates sac_blueprints record with pages and interactions."""
        ctx = make_ctx()
        hla_id = str(uuid.uuid4())

        sac_strategy = [
            {
                "dashboard_need": "Sales Executive Overview",
                "recommendation": "story",
                "rationale": "Standard exec reporting",
                "audience": "executives",
                "archetype": "executive_summary",
            }
        ]
        hla_row = _make_hla_row(
            hla_id=hla_id,
            project_id=ctx.project_id,
            sac_strategy=sac_strategy,
        )

        blueprint_llm_response = {
            "title": "Sales Executive Overview",
            "artifact_type": "story",
            "artifact_type_rationale": "Standard reporting need",
            "artifact_type_confidence": 0.85,
            "pages": [
                {
                    "page_id": "p1",
                    "title": "Overview",
                    "layout_archetype": "executive_summary",
                    "widgets": [
                        {
                            "widget_id": "w1",
                            "type": "kpi_tile",
                            "title": "Revenue",
                            "metric_binding": {"kpi": "revenue", "dimensions": ["time"]},
                            "size": {"cols": 3, "rows": 2},
                            "position": {"col": 0, "row": 0},
                        }
                    ],
                }
            ],
            "interactions": {
                "global_filters": [{"dimension": "time_period", "type": "dropdown"}],
                "page_navigation": [],
                "drill_behavior": [],
            },
        }

        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=hla_row)
        conn.fetch = AsyncMock(return_value=[])  # no design tokens or archetypes

        with (
            patch(
                "spec2sphere.pipeline.blueprint_generator._get_conn",
                new_callable=AsyncMock,
                return_value=conn,
            ),
            patch(
                "spec2sphere.pipeline.blueprint_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=blueprint_llm_response,
            ),
        ):
            from spec2sphere.pipeline.blueprint_generator import generate_blueprint

            result = await generate_blueprint(hla_id=hla_id, ctx=ctx, llm=make_mock_llm())

        assert "blueprint_id" in result
        assert result["artifact_type"] == "story"
        assert result["page_count"] == 1
        assert result["widget_count"] == 1
        assert result["status"] == "draft"

    def test_artifact_type_decision_story(self):
        """Standard dashboard need resolves to 'story'."""
        from spec2sphere.pipeline.blueprint_generator import _decide_artifact_type

        need = {
            "dashboard_need": "Executive Sales Overview",
            "recommendation": "story",
            "archetype": "executive_summary",
        }
        artifact_type, rationale, confidence = _decide_artifact_type(need)
        assert artifact_type == "story"
        assert confidence > 0.0

    def test_artifact_type_decision_analytic_application(self):
        """Complex interactive need resolves to 'analytic_application'."""
        from spec2sphere.pipeline.blueprint_generator import _decide_artifact_type

        need = {
            "dashboard_need": "Complex planning workflow with guided input",
            "recommendation": "analytic_application",
            "archetype": "workflow",
        }
        artifact_type, _rationale, _confidence = _decide_artifact_type(need)
        assert artifact_type == "analytic_application"

    def test_artifact_type_decision_custom_widget(self):
        """Unique branded visualisation resolves to 'custom_widget'."""
        from spec2sphere.pipeline.blueprint_generator import _decide_artifact_type

        need = {
            "dashboard_need": "Unique branded embedded visualization",
            "recommendation": "custom_widget",
            "rationale": "requires custom branded look and embedded experience",
        }
        artifact_type, _rationale, _confidence = _decide_artifact_type(need)
        assert artifact_type == "custom_widget"

    def test_widget_type_selection_variance(self):
        """KPI type 'variance' maps to chart_waterfall."""
        from spec2sphere.pipeline.blueprint_generator import _KPI_TO_WIDGET

        assert _KPI_TO_WIDGET["variance"] == "chart_waterfall"

    def test_widget_type_selection_trend(self):
        """KPI type 'trend' maps to chart_line."""
        from spec2sphere.pipeline.blueprint_generator import _KPI_TO_WIDGET

        assert _KPI_TO_WIDGET["trend"] == "chart_line"

    def test_widget_type_selection_ranking(self):
        """KPI type 'ranking' maps to chart_bar_horizontal."""
        from spec2sphere.pipeline.blueprint_generator import _KPI_TO_WIDGET

        assert _KPI_TO_WIDGET["ranking"] == "chart_bar_horizontal"

    def test_performance_classification_lightweight(self):
        """Fewer than 5 widgets = lightweight."""
        from spec2sphere.pipeline.blueprint_generator import _determine_performance_class

        assert _determine_performance_class(0) == "lightweight"
        assert _determine_performance_class(4) == "lightweight"

    def test_performance_classification_standard(self):
        """5 to 15 widgets = standard."""
        from spec2sphere.pipeline.blueprint_generator import _determine_performance_class

        assert _determine_performance_class(5) == "standard"
        assert _determine_performance_class(15) == "standard"

    def test_performance_classification_heavy(self):
        """More than 15 widgets = heavy."""
        from spec2sphere.pipeline.blueprint_generator import _determine_performance_class

        assert _determine_performance_class(16) == "heavy"
        assert _determine_performance_class(100) == "heavy"

    def test_design_tokens_applied(self):
        """_apply_style_tokens attaches style_tokens to widget when tokens are present."""
        from spec2sphere.pipeline.blueprint_generator import _apply_style_tokens

        widget = {"widget_id": "w1", "type": "kpi_tile", "title": "Revenue"}
        design_tokens = [
            {"token_type": "color", "token_name": "brand_primary", "token_value": "#003366"},
            {"token_type": "typography", "token_name": "font_default", "token_value": "Arial"},
        ]

        result = _apply_style_tokens(widget, design_tokens)

        assert "style_tokens" in result
        assert "color_series" in result["style_tokens"]
        assert "font_family" in result["style_tokens"]

    @pytest.mark.asyncio
    async def test_blueprint_fallback_on_llm_failure(self):
        """When LLM returns None a minimal valid blueprint is still produced and stored."""
        ctx = make_ctx()
        hla_id = str(uuid.uuid4())

        sac_strategy = [
            {
                "dashboard_need": "Fallback Blueprint",
                "recommendation": "story",
                "archetype": "executive_summary",
                "audience": "all",
            }
        ]
        hla_row = _make_hla_row(
            hla_id=hla_id,
            project_id=ctx.project_id,
            sac_strategy=sac_strategy,
        )

        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=hla_row)
        conn.fetch = AsyncMock(return_value=[])

        with (
            patch(
                "spec2sphere.pipeline.blueprint_generator._get_conn",
                new_callable=AsyncMock,
                return_value=conn,
            ),
            patch(
                "spec2sphere.pipeline.blueprint_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=None,  # LLM failure
            ),
        ):
            from spec2sphere.pipeline.blueprint_generator import generate_blueprint

            result = await generate_blueprint(hla_id=hla_id, ctx=ctx, llm=make_mock_llm())

        # Minimal fallback blueprint should still be produced and persisted
        assert "blueprint_id" in result
        assert result["page_count"] >= 1
        assert result["widget_count"] >= 1


# ---------------------------------------------------------------------------
# Test Generator Tests
# ---------------------------------------------------------------------------


class TestTestGenerator:
    """Tests for spec2sphere.pipeline.test_generator."""

    @pytest.mark.asyncio
    async def test_generate_test_spec(self):
        """generate_test_spec creates test_specs record with DSP test cases."""
        ctx = make_ctx()
        spec_id = str(uuid.uuid4())

        tech_spec_row = _make_tech_spec_row(
            spec_id=spec_id,
            project_id=ctx.project_id,
            objects=["02_RV_SALES"],
        )
        obj_row = _make_tech_obj_row(name="02_RV_SALES", platform="dsp", layer="harmonized")

        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=tech_spec_row)
        conn.fetch = AsyncMock(return_value=[obj_row])

        dsp_tests_llm = {
            "structural": [{"title": "Object accessible", "query": 'SELECT 1 FROM "02_RV_SALES"'}],
            "volume": [{"title": "Row count", "query": 'SELECT COUNT(*) FROM "02_RV_SALES"'}],
            "aggregate": [
                {
                    "title": "Revenue by period",
                    "query": 'SELECT PERIOD, SUM(NETWR) FROM "02_RV_SALES" GROUP BY PERIOD',
                    "cut_dimension": "PERIOD",
                }
            ],
            "edge_case": [
                {
                    "title": "Null handling",
                    "scenario": "Empty period",
                    "query": 'SELECT * FROM "02_RV_SALES" WHERE NETWR IS NULL',
                }
            ],
            "sample_trace": [
                {
                    "title": "VBAP trace",
                    "description": "Trace from VBAP",
                    "source_query": 'SELECT * FROM "01_LT_VBAP" LIMIT 10',
                }
            ],
        }

        with (
            patch(
                "spec2sphere.pipeline.test_generator._get_conn",
                new_callable=AsyncMock,
                return_value=conn,
            ),
            patch(
                "spec2sphere.pipeline.test_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=dsp_tests_llm,
            ),
        ):
            from spec2sphere.pipeline.test_generator import generate_test_spec

            result = await generate_test_spec(
                tech_spec_id=spec_id,
                ctx=ctx,
                llm=make_mock_llm(),
            )

        assert "test_spec_id" in result
        assert result["dsp_tests"] > 0
        assert result["mode"] == "preservation"
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_preservation_vs_improvement_mode(self):
        """test_mode is stored correctly in the result for both modes."""
        ctx = make_ctx()
        spec_id = str(uuid.uuid4())

        tech_spec_row = _make_tech_spec_row(spec_id=spec_id, project_id=ctx.project_id)

        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=tech_spec_row)
        conn.fetch = AsyncMock(return_value=[])

        minimal_dsp_tests = {
            "structural": [],
            "volume": [],
            "aggregate": [],
            "edge_case": [],
            "sample_trace": [],
        }

        with (
            patch(
                "spec2sphere.pipeline.test_generator._get_conn",
                new_callable=AsyncMock,
                return_value=conn,
            ),
            patch(
                "spec2sphere.pipeline.test_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=minimal_dsp_tests,
            ),
        ):
            from spec2sphere.pipeline.test_generator import generate_test_spec

            result_preservation = await generate_test_spec(
                tech_spec_id=spec_id, ctx=ctx, llm=make_mock_llm(), test_mode="preservation"
            )
            result_improvement = await generate_test_spec(
                tech_spec_id=spec_id, ctx=ctx, llm=make_mock_llm(), test_mode="improvement"
            )

        assert result_preservation["mode"] == "preservation"
        assert result_improvement["mode"] == "improvement"

    def test_dev_copy_commands(self):
        """generate_dev_copy_commands produces CREATE TABLE ... AS SELECT * FROM for DSP objects."""
        from spec2sphere.pipeline.test_generator import generate_dev_copy_commands

        objects = [
            {"name": "02_RV_SALES", "platform": "dsp"},
            {"name": "MY_STORY", "platform": "sac"},
            {"name": "03_FV_FACT", "platform": "dsp"},
        ]

        commands = generate_dev_copy_commands(objects)

        # Only DSP objects should be included
        names = [c["object_name"] for c in commands]
        assert "02_RV_SALES" in names
        assert "03_FV_FACT" in names
        assert "MY_STORY" not in names

        # SQL format must be CREATE TABLE "NAME_DEV" AS SELECT * FROM "NAME"
        for cmd in commands:
            assert cmd["sql"].startswith("CREATE TABLE")
            assert "_DEV" in cmd["sql"]
            assert "SELECT * FROM" in cmd["sql"]

    def test_golden_queries_aggregate_prioritized(self):
        """build_golden_queries prioritizes aggregate tests over volume tests."""
        from spec2sphere.pipeline.test_generator import build_golden_queries

        test_cases = [
            {
                "category": "volume",
                "title": "Row count check",
                "query": 'SELECT COUNT(*) FROM "02_RV_SALES"',
            },
            {
                "category": "aggregate",
                "title": "Revenue by period",
                "query": 'SELECT PERIOD, SUM(NETWR) FROM "02_RV_SALES" GROUP BY PERIOD',
                "cut_dimension": "PERIOD",
            },
        ]

        golden = build_golden_queries(objects=[], test_cases=test_cases)

        assert len(golden) >= 1
        # Aggregate should appear first
        categories = [q["category"] for q in golden]
        if "aggregate" in categories and "volume" in categories:
            assert categories.index("aggregate") < categories.index("volume")

    def test_tolerance_exact_pass(self):
        """check_tolerance exact: identical values -> passed=True."""
        from spec2sphere.pipeline.test_generator import check_tolerance

        result = check_tolerance(100, 100, {"type": "exact"})
        assert result["passed"] is True
        assert result["delta"] == 0.0

    def test_tolerance_exact_fail(self):
        """check_tolerance exact: different values -> passed=False."""
        from spec2sphere.pipeline.test_generator import check_tolerance

        result = check_tolerance(100, 101, {"type": "exact"})
        assert result["passed"] is False
        assert result["delta"] == 1.0

    def test_tolerance_absolute_pass(self):
        """check_tolerance absolute: delta=2, threshold=5 -> passed=True."""
        from spec2sphere.pipeline.test_generator import check_tolerance

        result = check_tolerance(100, 102, {"type": "absolute", "value": 5})
        assert result["passed"] is True

    def test_tolerance_absolute_fail(self):
        """check_tolerance absolute: delta=10, threshold=5 -> passed=False."""
        from spec2sphere.pipeline.test_generator import check_tolerance

        result = check_tolerance(100, 110, {"type": "absolute", "value": 5})
        assert result["passed"] is False

    def test_tolerance_percentage_pass(self):
        """check_tolerance percentage: delta=3%, threshold=5% -> passed=True."""
        from spec2sphere.pipeline.test_generator import check_tolerance

        result = check_tolerance(100, 103, {"type": "percentage", "value": 5})
        assert result["passed"] is True

    def test_tolerance_percentage_fail(self):
        """check_tolerance percentage: delta=10%, threshold=5% -> passed=False."""
        from spec2sphere.pipeline.test_generator import check_tolerance

        result = check_tolerance(100, 110, {"type": "percentage", "value": 5})
        assert result["passed"] is False

    def test_tolerance_expected_delta(self):
        """check_tolerance expected_delta: always passes with an explanation."""
        from spec2sphere.pipeline.test_generator import check_tolerance

        result = check_tolerance(100, 200, {"type": "expected_delta", "description": "Redesign intentional change"})
        assert result["passed"] is True
        assert "Redesign intentional change" in result["explanation"]


# ---------------------------------------------------------------------------
# SQL Validation Integration
# ---------------------------------------------------------------------------


class TestSQLValidation:
    """Integration tests for validate_dsp_sql."""

    def test_sql_validation_all_rules_pass(self):
        """Clean DSP SQL with no violations is reported as valid."""
        from spec2sphere.migration.sql_validator import validate_dsp_sql

        clean_sql = (
            'SELECT "VKORG", "KUNNR", SUM("NETWR") AS TOTAL_REVENUE '
            'FROM "01_LT_VBAP" '
            "WHERE \"DATAB\" <= '20261231' "
            'GROUP BY "VKORG", "KUNNR"'
        )

        result = validate_dsp_sql(clean_sql)

        assert result.is_valid is True
        assert result.error_count == 0

    def test_sql_validation_cte_detected(self):
        """SQL with a WITH/CTE clause is detected and reported as invalid."""
        from spec2sphere.migration.sql_validator import validate_dsp_sql

        cte_sql = (
            "WITH revenue_cte AS (SELECT VKORG, SUM(NETWR) AS total FROM VBAP GROUP BY VKORG) SELECT * FROM revenue_cte"
        )

        result = validate_dsp_sql(cte_sql)

        assert result.is_valid is False
        assert result.error_count > 0


# ---------------------------------------------------------------------------
# Approval Checklist Tests
# ---------------------------------------------------------------------------


class TestApprovalChecklists:
    """Tests for approval checklist content in governance/approvals.py."""

    def test_tech_spec_approval_checklist(self):
        """tech_spec checklist contains the mandatory review items."""
        from spec2sphere.governance.approvals import CHECKLISTS

        items = CHECKLISTS.get("tech_spec", [])
        assert len(items) > 0

        keys = {item["key"] for item in items}
        assert "all_views_specified" in keys
        assert "dependencies_resolved" in keys
        assert "sql_validated" in keys
        assert "naming_compliant" in keys

        # Every item must declare required flag
        for item in items:
            assert "required" in item
            assert "label" in item

    def test_sac_blueprint_approval_checklist(self):
        """sac_blueprint checklist contains the mandatory review items."""
        from spec2sphere.governance.approvals import CHECKLISTS

        items = CHECKLISTS.get("sac_blueprint", [])
        assert len(items) > 0

        keys = {item["key"] for item in items}
        assert "pages_complete" in keys
        assert "artifact_type_justified" in keys
        assert "interactions_defined" in keys
        assert "design_tokens_applied" in keys

        # Every item must declare required flag
        for item in items:
            assert "required" in item
            assert "label" in item
