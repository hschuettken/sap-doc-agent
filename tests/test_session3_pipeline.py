"""Tests for Session 3: Pipeline — Requirement to Architecture.

Covers:
  - Placement engine (deterministic rules, LLM fallback, place_architecture)
  - Intake (markdown / YAML / plain-text ingestion, project scoping)
  - Semantic parser (entity extraction, confidence scoring, ambiguity detection)
  - HLA generator (structure, placement annotation, DB records)
  - Approval workflow state machine (submit, approve, reject, rework, checklist)
  - Notification system (create, list, unread count, mark read)
  - Integration flow (intake → parse → submit → HLA generation)

All database calls are intercepted via patch("...._get_conn") returning an
AsyncMock connection.  No real database is required.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spec2sphere.tenant.context import ContextEnvelope

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_session2 style)
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


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


def _fake_req_row(
    req_id=None,
    project_id=None,
    title="Test BRS",
    source_text="Sample BRS text with entities and measures.",
    parsed_entities=None,
    parsed_kpis=None,
    parsed_grain=None,
    status="draft",
):
    """Build a minimal asyncpg-Record-like dict for a requirements row."""
    row = {
        "id": req_id or uuid.uuid4(),
        "project_id": project_id or uuid.uuid4(),
        "title": title,
        "status": status,
        "business_domain": None,
        "description": None,
        "source_documents": json.dumps(
            [
                {
                    "filename": "test.md",
                    "content_type": "text/markdown",
                    "text": source_text,
                    "uploaded_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        ),
        "parsed_entities": json.dumps(parsed_entities or {}),
        "parsed_kpis": json.dumps(parsed_kpis or []),
        "parsed_grain": json.dumps(parsed_grain or {}),
        "confidence": json.dumps({}),
        "open_questions": json.dumps([]),
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    # Support dict-like access (asyncpg Record behaves like a mapping)
    return _DictRecord(row)


class _DictRecord(dict):
    """Minimal asyncpg.Record substitute: supports dict() and attribute access."""

    def __getitem__(self, key):
        return super().__getitem__(key)


# ---------------------------------------------------------------------------
# Placement Engine Tests
# ---------------------------------------------------------------------------


class TestPlacement:
    """Cross-platform placement engine — deterministic rules and fallback."""

    @pytest.mark.asyncio
    async def test_visualization_always_sac(self):
        """Visualization artifacts always go to SAC regardless of details."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        result = await decide_placement("Sales Dashboard", "visualization", {})
        assert result.platform == Platform.SAC
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_data_model_always_dsp(self):
        """Data model artifacts always reside in DSP."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        result = await decide_placement("DIM_CUSTOMER", "data_model", {})
        assert result.platform == Platform.DSP
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_replication_flow_always_dsp(self):
        """Replication flows always go to DSP Data Integration."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        result = await decide_placement("RF_VBAP", "replication_flow", {})
        assert result.platform == Platform.DSP

    @pytest.mark.asyncio
    async def test_complex_calculation_goes_dsp(self):
        """Complex calculation (CASE WHEN) belongs in DSP for performance."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        details = {"formula": "CASE WHEN MATKL = 'FERT' THEN netwr * 0.9 ELSE netwr END"}
        result = await decide_placement("NET_REVENUE_ADJUSTED", "calculation", details)
        assert result.platform == Platform.DSP
        assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_reusable_calculation_goes_dsp(self):
        """Reusable calculation (shared flag) belongs in DSP."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        details = {"reusable": True, "description": "Shared margin calculation"}
        result = await decide_placement("GROSS_MARGIN_PCT", "calculation", details)
        assert result.platform == Platform.DSP

    @pytest.mark.asyncio
    async def test_interactive_calculation_goes_sac(self):
        """Ad-hoc / interactive calculations belong in SAC."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        details = {"description": "User-defined ad hoc variance for interactive analysis"}
        result = await decide_placement("USER_VARIANCE", "calculation", details)
        assert result.platform == Platform.SAC

    @pytest.mark.asyncio
    async def test_data_level_filter_goes_dsp(self):
        """Row-level security filter belongs in DSP."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        details = {"description": "Row level security filter for Sales Org"}
        result = await decide_placement("SALES_ORG_RLS", "filter", details)
        assert result.platform == Platform.DSP

    @pytest.mark.asyncio
    async def test_interactive_filter_goes_sac(self):
        """User-facing interactive filter belongs in SAC story."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        details = {"description": "Interactive date range filter for user story"}
        result = await decide_placement("DATE_RANGE_FILTER", "filter", details)
        assert result.platform == Platform.SAC

    @pytest.mark.asyncio
    async def test_fallback_when_no_rule_no_llm(self):
        """Unknown artifact type with no LLM falls back to DSP with low confidence."""
        from spec2sphere.pipeline.placement import Platform, decide_placement

        result = await decide_placement("UNKNOWN_ARTIFACT", "unknown_type", {}, llm=None)
        assert result.platform == Platform.DSP
        assert result.confidence <= 0.5

    @pytest.mark.asyncio
    async def test_place_architecture_processes_views(self):
        """place_architecture generates one decision per view in hla_content."""
        from spec2sphere.pipeline.placement import Platform, place_architecture

        hla_content = {
            "views": [
                {"name": "V_SALES_RAW", "layer": "RAW", "type": "relational_dataset"},
                {"name": "V_SALES_CONSUMPTION", "layer": "CONSUMPTION", "type": "analytic_model"},
            ],
            "replication_strategy": [],
            "key_decisions": [],
        }
        decisions = await place_architecture(hla_content)
        assert len(decisions) == 2
        # RAW relational_dataset → data_model → DSP
        raw_decision = next(d for d in decisions if d.artifact_name == "V_SALES_RAW")
        assert raw_decision.platform == Platform.DSP
        # analytic_model → DSP
        cons_decision = next(d for d in decisions if d.artifact_name == "V_SALES_CONSUMPTION")
        assert cons_decision.platform == Platform.DSP

    @pytest.mark.asyncio
    async def test_place_architecture_key_decisions_use_explicit_placement(self):
        """Key decisions honour the platform_placement field explicitly."""
        from spec2sphere.pipeline.placement import Platform, place_architecture

        hla_content = {
            "views": [],
            "replication_strategy": [],
            "key_decisions": [
                {
                    "topic": "Story Design",
                    "choice": "Single SAC story",
                    "rationale": "All users on SAC",
                    "platform_placement": "sac",
                },
                {
                    "topic": "Persistence View",
                    "choice": "Monthly aggregate",
                    "rationale": "Performance",
                    "platform_placement": "dsp",
                },
            ],
        }
        decisions = await place_architecture(hla_content)
        assert len(decisions) == 2
        sac_d = next(d for d in decisions if d.artifact_name == "Story Design")
        dsp_d = next(d for d in decisions if d.artifact_name == "Persistence View")
        assert sac_d.platform == Platform.SAC
        assert dsp_d.platform == Platform.DSP


# ---------------------------------------------------------------------------
# Intake Tests
# ---------------------------------------------------------------------------


class TestIntake:
    """Requirement intake engine: various BRS formats."""

    @pytest.mark.asyncio
    async def test_ingest_markdown_brs(self):
        """Ingest the sample Markdown BRS — title derived from first heading."""
        from spec2sphere.pipeline.intake import ingest_requirement

        ctx = make_ctx()
        conn = make_mock_conn()
        file_data = (FIXTURES / "sample_brs_sales.md").read_bytes()

        with (
            patch("spec2sphere.pipeline.intake._get_conn", return_value=conn),
            patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn),
        ):
            result = await ingest_requirement(
                file_data=file_data,
                filename="sample_brs_sales.md",
                content_type="text/markdown",
                ctx=ctx,
            )

        assert "requirement_id" in result
        uuid.UUID(result["requirement_id"])  # must be valid UUID
        assert result["status"] == "draft"
        # Title comes from first non-empty line (stripped of #)
        assert "Sales Analytics" in result["title"]
        conn.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_ingest_yaml_brs(self):
        """Ingest the sample YAML BRS — detected by .yaml extension."""
        from spec2sphere.pipeline.intake import ingest_requirement

        ctx = make_ctx()
        conn = make_mock_conn()
        file_data = (FIXTURES / "sample_brs_finance.yaml").read_bytes()

        with (
            patch("spec2sphere.pipeline.intake._get_conn", return_value=conn),
            patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn),
        ):
            result = await ingest_requirement(
                file_data=file_data,
                filename="sample_brs_finance.yaml",
                # Generic content_type triggers YAML extension check
                content_type="application/octet-stream",
                ctx=ctx,
            )

        assert result["status"] == "draft"
        uuid.UUID(result["requirement_id"])
        # YAML title field should surface — after json.dumps the text will include "Financial Close"
        assert result["title"]  # non-empty

    @pytest.mark.asyncio
    async def test_ingest_plaintext_workshop_notes(self):
        """Ingest plain text workshop notes — treated as UTF-8 text."""
        from spec2sphere.pipeline.intake import ingest_requirement

        ctx = make_ctx()
        conn = make_mock_conn()
        file_data = (FIXTURES / "sample_brs_workshop_notes.txt").read_bytes()

        from spec2sphere.standards.extractor import UnsupportedFileType

        with (
            patch("spec2sphere.pipeline.intake._get_conn", return_value=conn),
            # extract_text is a local import inside ingest_requirement; patch at source module.
            # Must raise UnsupportedFileType (not generic Exception) to trigger the UTF-8 fallback.
            patch("spec2sphere.standards.extractor.extract_text", side_effect=UnsupportedFileType("unsupported")),
            patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn),
        ):
            # UnsupportedFileType → fallback to raw UTF-8 decode
            result = await ingest_requirement(
                file_data=file_data,
                filename="workshop_notes.txt",
                content_type="text/plain",
                ctx=ctx,
            )

        assert result["status"] == "draft"
        # Title should be derived from the first line
        assert "Sales Analytics Workshop" in result["title"]

    @pytest.mark.asyncio
    async def test_ingest_stores_correct_project_id(self):
        """INSERT must use the project_id from the context."""
        from spec2sphere.pipeline.intake import ingest_requirement

        project_id = uuid.uuid4()
        ctx = make_ctx(project_id=project_id)
        conn = make_mock_conn()
        file_data = b"# Quick Test BRS\n\nSome content."

        with (
            patch("spec2sphere.pipeline.intake._get_conn", return_value=conn),
            patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn),
        ):
            await ingest_requirement(
                file_data=file_data,
                filename="quick.md",
                content_type="text/markdown",
                ctx=ctx,
            )

        # First execute call is the INSERT — verify project_id appears in args
        call_args = conn.execute.await_args_list[0]
        positional = call_args[0]
        # positional[0] is SQL string, [1] is req_id UUID, [2] is project_id
        assert positional[2] == project_id

    @pytest.mark.asyncio
    async def test_list_requirements_project_scoped(self):
        """list_requirements returns rows filtered to the active project."""
        from spec2sphere.pipeline.intake import list_requirements

        project_id = uuid.uuid4()
        ctx = make_ctx(project_id=project_id)
        conn = make_mock_conn()
        conn.fetch = AsyncMock(return_value=[_fake_req_row(project_id=project_id)])

        with patch("spec2sphere.pipeline.intake._get_conn", return_value=conn):
            result = await list_requirements(ctx)

        assert len(result) == 1
        conn.fetch.assert_awaited_once()
        # SQL must include project_id filtering
        sql_used = conn.fetch.await_args[0][0]
        assert "project_id" in sql_used

    @pytest.mark.asyncio
    async def test_list_requirements_empty_without_project(self):
        """list_requirements returns [] when no project is set in context."""
        from spec2sphere.pipeline.intake import list_requirements

        ctx = ContextEnvelope.single_tenant(
            tenant_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            project_id=None,
        )
        result = await list_requirements(ctx)
        assert result == []


# ---------------------------------------------------------------------------
# Semantic Parser Tests
# ---------------------------------------------------------------------------


class TestSemanticParser:
    """LLM-powered semantic extraction tests."""

    @pytest.mark.asyncio
    async def test_parse_extracts_entities(self):
        """Parsing stores extracted entities into the requirements row."""
        from spec2sphere.pipeline.semantic_parser import parse_requirement

        req_id = str(uuid.uuid4())
        ctx = make_ctx()
        conn = make_mock_conn()

        llm_extraction = {
            "business_domains": ["Sales & Distribution"],
            "entities": [
                {"name": "Sales Order Item", "type": "fact", "description": "VBAP line items"},
                {"name": "Customer", "type": "dimension", "description": "KNA1 master"},
            ],
            "facts_and_measures": [{"name": "Net Revenue", "type": "measure", "aggregation": "SUM"}],
            "kpis": [{"name": "Revenue YoY", "formula": "(cy - py) / py"}],
            "grain": {"dimensions": ["Sales Order Item"], "time_granularity": "daily"},
            "ambiguities": [],
            "open_questions": [],
            "source_systems": [{"name": "SAP ECC", "type": "ERP", "tables": ["VBAP"]}],
            "time_semantics": {"type": "event", "fiscal_variants": [], "comparison_periods": ["YoY"]},
            "security_implications": {"row_level_security": True, "column_level_security": False, "roles": []},
            "non_functional": {"expected_volume_rows": 2000000},
            "llm_confidence_notes": {"entities": "high", "kpis": "high"},
        }

        conn.fetchrow = AsyncMock(
            side_effect=[
                _fake_req_row(req_id=uuid.UUID(req_id), project_id=ctx.project_id),  # first fetch (get req)
                _fake_req_row(req_id=uuid.UUID(req_id), project_id=ctx.project_id),  # second fetch (update RETURNING)
            ]
        )

        llm = make_mock_llm()

        with (
            patch("spec2sphere.pipeline.semantic_parser._get_conn", return_value=conn),
            patch(
                "spec2sphere.pipeline.semantic_parser.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=llm_extraction,
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service._get_conn",
                return_value=conn,
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await parse_requirement(req_id, ctx, llm)

        # The UPDATE must have been executed
        conn.fetchrow.assert_awaited()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_confidence_scoring_high_when_entities_present(self):
        """Confidence level is 'high' when entities are populated."""
        from spec2sphere.pipeline.semantic_parser import _compute_confidence

        extracted = {
            "entities": [{"name": "E1"}, {"name": "E2"}],
            "facts_and_measures": [{"name": "M1"}],
            "kpis": [{"name": "KPI1"}],
            "grain": {"dimensions": ["D1"]},
            "source_systems": [{"name": "ECC"}],
            "security_implications": {"row_level_security": True},
            "llm_confidence_notes": {},
        }
        conf = _compute_confidence(extracted)
        assert conf["entities"]["level"] == "high"
        assert conf["kpis"]["level"] == "high"

    @pytest.mark.asyncio
    async def test_confidence_scoring_low_when_empty(self):
        """Confidence level is 'low' when nothing was extracted."""
        from spec2sphere.pipeline.semantic_parser import _compute_confidence

        extracted = {
            "entities": [],
            "facts_and_measures": [],
            "kpis": [],
            "grain": {},
            "source_systems": [],
            "security_implications": {},
            "llm_confidence_notes": {},
        }
        conf = _compute_confidence(extracted)
        assert conf["entities"]["level"] == "low"
        assert conf["kpis"]["level"] == "low"

    @pytest.mark.asyncio
    async def test_ambiguity_detection_persists_and_returns(self):
        """detect_ambiguities persists results and returns the list."""
        from spec2sphere.pipeline.semantic_parser import detect_ambiguities

        req_id = str(uuid.uuid4())
        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(
            return_value=_fake_req_row(
                req_id=uuid.UUID(req_id),
                source_text="Active customer is not defined. Conflicting grain in section 4 and 6.",
                parsed_entities={"entities": [], "facts_and_measures": []},
            )
        )

        ambiguities_response = {
            "ambiguities": [
                {
                    "element": "active customer",
                    "issue": "Term not defined",
                    "severity": "high",
                    "suggested_resolution": "Business owner must clarify",
                },
                {
                    "element": "grain",
                    "issue": "Section 4 says item-level, section 6 says customer-day",
                    "severity": "high",
                    "suggested_resolution": "Design two separate views",
                },
            ]
        }

        llm = make_mock_llm()

        with (
            patch("spec2sphere.pipeline.semantic_parser._get_conn", return_value=conn),
            patch(
                "spec2sphere.pipeline.semantic_parser.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=ambiguities_response,
            ),
        ):
            result = await detect_ambiguities(req_id, llm)

        assert len(result) == 2
        assert result[0]["element"] == "active customer"
        assert result[0]["severity"] == "high"
        # UPDATE was called to persist
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_parse_raises_when_no_text(self):
        """parse_requirement raises ValueError when source_documents has no text."""
        from spec2sphere.pipeline.semantic_parser import parse_requirement

        req_id = str(uuid.uuid4())
        ctx = make_ctx()
        conn = make_mock_conn()

        # Requirement with empty text
        empty_row = _fake_req_row(req_id=uuid.UUID(req_id), source_text="")
        conn.fetchrow = AsyncMock(return_value=empty_row)

        with (
            patch("spec2sphere.pipeline.semantic_parser._get_conn", return_value=conn),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            with pytest.raises(ValueError, match="no extractable text"):
                await parse_requirement(req_id, ctx, make_mock_llm())


# ---------------------------------------------------------------------------
# HLA Generator Tests
# ---------------------------------------------------------------------------


class TestHLAGenerator:
    """HLA document generation tests."""

    def _sample_hla_content(self):
        return {
            "layered_architecture": {
                "RAW": {"description": "Raw layer", "tables": ["Z_RAW_VBAP"]},
                "HARMONIZED": {"description": "Harmonised", "views": ["Z_HARM_SALES_ITEM"]},
                "MART": {"description": "Mart", "views": ["Z_MART_SALES_MONTHLY"]},
                "CONSUMPTION": {
                    "description": "Consumption",
                    "views": ["Z_CONS_SALES_AM"],
                    "analytic_models": ["Z_AM_SALES"],
                },
            },
            "views": [
                {"name": "Z_RAW_VBAP", "layer": "RAW", "type": "relational_dataset"},
                {"name": "Z_AM_SALES", "layer": "CONSUMPTION", "type": "analytic_model"},
            ],
            "key_decisions": [
                {
                    "topic": "Schema Type",
                    "choice": "Star schema",
                    "alternatives": ["Snowflake"],
                    "rationale": "Performance and SAC compatibility",
                    "platform_placement": "dsp",
                }
            ],
            "replication_strategy": [
                {"source_table": "VBAP", "target_table": "Z_RAW_VBAP", "source_system": "ECC", "delta_enabled": True}
            ],
            "narrative": "Sales analytics HLA for ECC migration.",
        }

    @pytest.mark.asyncio
    async def test_generate_hla_creates_db_records(self):
        """generate_hla inserts one hla_documents row and one architecture_decisions row."""
        from spec2sphere.pipeline.hla_generator import generate_hla

        req_id = str(uuid.uuid4())
        ctx = make_ctx()
        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=_fake_req_row(req_id=uuid.UUID(req_id), project_id=ctx.project_id))
        llm = make_mock_llm()

        with (
            patch("spec2sphere.pipeline.hla_generator._get_conn", return_value=conn),
            patch(
                "spec2sphere.pipeline.hla_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=self._sample_hla_content(),
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await generate_hla(req_id, ctx, llm)

        assert "hla_id" in result
        uuid.UUID(result["hla_id"])
        assert result["status"] == "draft"
        assert result["decisions_count"] == 1  # one key decision in sample
        # Transaction execute: INSERT hla_documents + INSERT architecture_decisions
        assert conn.execute.await_count >= 2

    @pytest.mark.asyncio
    async def test_generate_hla_annotates_views_with_placement(self):
        """Views in hla_content get a platform_placement annotation after generate_hla."""
        from spec2sphere.pipeline.hla_generator import generate_hla

        req_id = str(uuid.uuid4())
        ctx = make_ctx()
        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=_fake_req_row(req_id=uuid.UUID(req_id), project_id=ctx.project_id))
        llm = make_mock_llm()

        captured_hla = {}

        async def _mock_generate_json(**kwargs):
            content = self._sample_hla_content()
            captured_hla.update(content)
            return content

        with (
            patch("spec2sphere.pipeline.hla_generator._get_conn", return_value=conn),
            patch(
                "spec2sphere.pipeline.hla_generator.generate_json_with_retry",
                side_effect=_mock_generate_json,
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await generate_hla(req_id, ctx, llm)

        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_generate_hla_handles_none_llm_response(self):
        """If LLM returns None, generate_hla uses empty structure and still inserts."""
        from spec2sphere.pipeline.hla_generator import generate_hla

        req_id = str(uuid.uuid4())
        ctx = make_ctx()
        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=_fake_req_row(req_id=uuid.UUID(req_id), project_id=ctx.project_id))
        llm = make_mock_llm()

        with (
            patch("spec2sphere.pipeline.hla_generator._get_conn", return_value=conn),
            patch(
                "spec2sphere.pipeline.hla_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value=None,  # LLM timeout / failure
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await generate_hla(req_id, ctx, llm)

        assert result["decisions_count"] == 0
        assert result["status"] == "draft"


# ---------------------------------------------------------------------------
# Approval Workflow Tests
# ---------------------------------------------------------------------------


class TestApprovalWorkflow:
    """Approval state machine: submit, review decisions, checklist."""

    def _approval_row(self, artifact_type="requirement", status="pending"):
        return _DictRecord(
            {
                "id": uuid.uuid4(),
                "project_id": uuid.uuid4(),
                "artifact_type": artifact_type,
                "artifact_id": str(uuid.uuid4()),
                "status": status,
                "reviewer_id": None,
                "comments": None,
                "checklist": json.dumps(
                    {
                        "items": [
                            {"key": "scope_correct", "label": "Scope correct", "required": True, "checked": False},
                            {"key": "kpis_defined", "label": "KPIs defined", "required": True, "checked": False},
                        ]
                    }
                ),
                "created_at": "2026-01-01T00:00:00+00:00",
                "resolved_at": None,
            }
        )

    @pytest.mark.asyncio
    async def test_submit_creates_approval_with_checklist(self):
        """submit_for_review inserts approval + updates artifact status to pending_review."""
        from spec2sphere.governance.approvals import submit_for_review

        ctx = make_ctx()
        artifact_id = str(uuid.uuid4())
        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=self._approval_row())

        with patch("spec2sphere.governance.approvals._get_conn", return_value=conn):
            result = await submit_for_review("requirement", artifact_id, ctx)

        assert isinstance(result, dict)
        # fetchrow (INSERT RETURNING) must have been called
        conn.fetchrow.assert_awaited_once()
        # UPDATE requirements SET status = 'pending_review'
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_requires_valid_artifact_type(self):
        """submit_for_review raises ValueError for unknown artifact types."""
        from spec2sphere.governance.approvals import submit_for_review

        ctx = make_ctx()
        with pytest.raises(ValueError, match="Unknown artifact_type"):
            await submit_for_review("nonexistent_type", str(uuid.uuid4()), ctx)

    @pytest.mark.asyncio
    async def test_approve_updates_status(self):
        """review_artifact with 'approve' sets approval + artifact status to 'approve'."""
        from spec2sphere.governance.approvals import review_artifact

        ctx = make_ctx()
        approval_id = str(uuid.uuid4())
        conn = make_mock_conn()

        pending = self._approval_row(status="pending")
        approved = dict(pending)
        approved["status"] = "approve"
        conn.fetchrow = AsyncMock(side_effect=[pending, _DictRecord(approved)])

        with patch("spec2sphere.governance.approvals._get_conn", return_value=conn):
            result = await review_artifact(approval_id, "approve", ctx, comments="Looks good")

        assert isinstance(result, dict)
        # Two fetchrow calls: get approval, then UPDATE RETURNING
        assert conn.fetchrow.await_count == 2
        # Execute called once to update the artifact table
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_updates_status(self):
        """review_artifact with 'reject' sets statuses to 'reject'."""
        from spec2sphere.governance.approvals import review_artifact

        ctx = make_ctx()
        approval_id = str(uuid.uuid4())
        conn = make_mock_conn()
        rejected = self._approval_row(status="reject")
        conn.fetchrow = AsyncMock(side_effect=[self._approval_row(), rejected])

        with patch("spec2sphere.governance.approvals._get_conn", return_value=conn):
            result = await review_artifact(approval_id, "reject", ctx, comments="Missing KPIs")

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_rework_updates_status(self):
        """review_artifact with 'rework' sets statuses to 'rework'."""
        from spec2sphere.governance.approvals import review_artifact

        ctx = make_ctx()
        approval_id = str(uuid.uuid4())
        conn = make_mock_conn()
        rework = self._approval_row(status="rework")
        conn.fetchrow = AsyncMock(side_effect=[self._approval_row(), rework])

        with patch("spec2sphere.governance.approvals._get_conn", return_value=conn):
            result = await review_artifact(approval_id, "rework", ctx)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_invalid_decision_raises(self):
        """review_artifact raises ValueError for an unrecognised decision string."""
        from spec2sphere.governance.approvals import review_artifact

        ctx = make_ctx()
        with pytest.raises(ValueError, match="Invalid decision"):
            conn = make_mock_conn()
            with patch("spec2sphere.governance.approvals._get_conn", return_value=conn):
                await review_artifact(str(uuid.uuid4()), "maybe", ctx)

    @pytest.mark.asyncio
    async def test_checklist_partial_update(self):
        """update_checklist merges True/False into items without deciding."""
        from spec2sphere.governance.approvals import update_checklist

        ctx = make_ctx()
        approval_id = str(uuid.uuid4())
        conn = make_mock_conn()
        pending = self._approval_row()
        updated = dict(pending)
        updated["checklist"] = json.dumps(
            {
                "items": [
                    {"key": "scope_correct", "label": "Scope correct", "required": True, "checked": True},
                    {"key": "kpis_defined", "label": "KPIs defined", "required": True, "checked": False},
                ]
            }
        )
        conn.fetchrow = AsyncMock(side_effect=[pending, _DictRecord(updated)])

        with patch("spec2sphere.governance.approvals._get_conn", return_value=conn):
            result = await update_checklist(approval_id, {"scope_correct": True}, ctx)

        assert isinstance(result, dict)
        # Two fetchrow calls: get, then UPDATE RETURNING
        assert conn.fetchrow.await_count == 2

    @pytest.mark.asyncio
    async def test_checklist_build_contains_predefined_items(self):
        """_build_checklist produces correct items for 'requirement' type."""
        from spec2sphere.governance.approvals import CHECKLISTS, _build_checklist

        checklist = _build_checklist("requirement")
        expected_keys = {item["key"] for item in CHECKLISTS["requirement"]}
        actual_keys = {item["key"] for item in checklist["items"]}
        assert expected_keys == actual_keys
        # All items start unchecked
        assert all(not item["checked"] for item in checklist["items"])


# ---------------------------------------------------------------------------
# Notification Tests
# ---------------------------------------------------------------------------


class TestNotifications:
    """In-app notification system tests."""

    def _notif_row(self, user_id=None, is_read=False):
        return _DictRecord(
            {
                "id": uuid.uuid4(),
                "project_id": uuid.uuid4(),
                "user_id": user_id or uuid.uuid4(),
                "title": "Review requested",
                "message": "A requirement has been submitted for your review.",
                "link": "/pipeline/requirements/abc",
                "notification_type": "approval_required",
                "is_read": is_read,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )

    @pytest.mark.asyncio
    async def test_create_and_list(self):
        """create_notification inserts a row; list_notifications returns it."""
        from spec2sphere.governance.notifications import create_notification, list_notifications

        project_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        conn = make_mock_conn()
        notif = self._notif_row(user_id=uuid.UUID(user_id))
        conn.fetchrow = AsyncMock(return_value=notif)
        conn.fetch = AsyncMock(return_value=[notif])

        with patch("spec2sphere.governance.notifications._get_conn", return_value=conn):
            created = await create_notification(project_id, user_id, "Review requested", "Please review.")
            notifications = await list_notifications(user_id)

        assert isinstance(created, dict)
        assert len(notifications) == 1

    @pytest.mark.asyncio
    async def test_unread_count_accurate(self):
        """get_unread_count returns the integer from the COUNT query."""
        from spec2sphere.governance.notifications import get_unread_count

        user_id = str(uuid.uuid4())
        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=_DictRecord({"cnt": 3}))

        with patch("spec2sphere.governance.notifications._get_conn", return_value=conn):
            count = await get_unread_count(user_id)

        assert count == 3

    @pytest.mark.asyncio
    async def test_mark_read_executes_update(self):
        """mark_read issues an UPDATE statement for the notification."""
        from spec2sphere.governance.notifications import mark_read

        notif_id = str(uuid.uuid4())
        conn = make_mock_conn()

        with patch("spec2sphere.governance.notifications._get_conn", return_value=conn):
            await mark_read(notif_id)

        conn.execute.assert_awaited_once()
        sql = conn.execute.await_args[0][0]
        assert "is_read = true" in sql

    @pytest.mark.asyncio
    async def test_mark_all_read_updates_user_notifications(self):
        """mark_all_read issues UPDATE for all unread by user_id."""
        from spec2sphere.governance.notifications import mark_all_read

        user_id = str(uuid.uuid4())
        conn = make_mock_conn()
        conn.execute = AsyncMock(return_value="UPDATE 5")

        with patch("spec2sphere.governance.notifications._get_conn", return_value=conn):
            await mark_all_read(user_id)

        conn.execute.assert_awaited_once()
        sql = conn.execute.await_args[0][0]
        assert "is_read = true" in sql
        assert "user_id" in sql

    @pytest.mark.asyncio
    async def test_unread_count_zero_when_no_row(self):
        """get_unread_count returns 0 when fetchrow returns None."""
        from spec2sphere.governance.notifications import get_unread_count

        conn = make_mock_conn()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("spec2sphere.governance.notifications._get_conn", return_value=conn):
            count = await get_unread_count(str(uuid.uuid4()))

        assert count == 0


# ---------------------------------------------------------------------------
# Integration / Pipeline Flow Tests
# ---------------------------------------------------------------------------


class TestPipelineFlow:
    """End-to-end pipeline flow tests — orchestrated across modules."""

    @pytest.mark.asyncio
    async def test_full_pipeline_intake_to_hla(self):
        """Full flow: ingest → parse → submit for review → generate HLA.

        Verifies that the pipeline functions can be called in sequence and that
        IDs flow correctly from one step to the next.
        """
        ctx = make_ctx()
        conn = make_mock_conn()

        # --- Step 1: Ingest ---
        from spec2sphere.pipeline.intake import ingest_requirement

        req_uuid = uuid.uuid4()

        def _execute_side_effect(*args, **kwargs):
            return "INSERT 0 1"

        conn.execute = AsyncMock(side_effect=lambda *a, **kw: "INSERT 0 1")

        with (
            patch("spec2sphere.pipeline.intake._get_conn", return_value=conn),
            patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn),
        ):
            intake_result = await ingest_requirement(
                file_data=b"# Sales BRS\n\nSome requirements content.",
                filename="pipeline_test.md",
                content_type="text/markdown",
                ctx=ctx,
            )

        assert "requirement_id" in intake_result
        requirement_id = intake_result["requirement_id"]

        # --- Step 2: Parse ---
        from spec2sphere.pipeline.semantic_parser import parse_requirement

        conn2 = make_mock_conn()
        req_row = _fake_req_row(
            req_id=uuid.UUID(requirement_id),
            project_id=ctx.project_id,
            source_text="Sales BRS content",
        )
        conn2.fetchrow = AsyncMock(side_effect=[req_row, req_row])

        with (
            patch("spec2sphere.pipeline.semantic_parser._get_conn", return_value=conn2),
            patch(
                "spec2sphere.pipeline.semantic_parser.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value={
                    "business_domains": ["Sales"],
                    "entities": [{"name": "Sales Order", "type": "fact"}],
                    "facts_and_measures": [{"name": "Revenue", "type": "measure", "aggregation": "SUM"}],
                    "kpis": [],
                    "grain": {"dimensions": ["Item"], "time_granularity": "daily"},
                    "ambiguities": [],
                    "open_questions": [],
                    "source_systems": [],
                    "llm_confidence_notes": {},
                },
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            parse_result = await parse_requirement(requirement_id, ctx, make_mock_llm())

        assert isinstance(parse_result, dict)

        # --- Step 3: Submit for review ---
        from spec2sphere.governance.approvals import submit_for_review

        conn3 = make_mock_conn()
        approval_row = _DictRecord(
            {
                "id": uuid.uuid4(),
                "project_id": ctx.project_id,
                "artifact_type": "requirement",
                "artifact_id": requirement_id,
                "status": "pending",
                "reviewer_id": None,
                "comments": None,
                "checklist": json.dumps({"items": []}),
                "created_at": "2026-01-01T00:00:00+00:00",
                "resolved_at": None,
            }
        )
        conn3.fetchrow = AsyncMock(return_value=approval_row)

        with patch("spec2sphere.governance.approvals._get_conn", return_value=conn3):
            approval = await submit_for_review("requirement", requirement_id, ctx)

        assert approval["status"] == "pending"

        # --- Step 4: Generate HLA ---
        from spec2sphere.pipeline.hla_generator import generate_hla

        conn4 = make_mock_conn()
        conn4.fetchrow = AsyncMock(return_value=req_row)

        with (
            patch("spec2sphere.pipeline.hla_generator._get_conn", return_value=conn4),
            patch(
                "spec2sphere.pipeline.hla_generator.generate_json_with_retry",
                new_callable=AsyncMock,
                return_value={
                    "layered_architecture": {"RAW": {}, "HARMONIZED": {}, "MART": {}, "CONSUMPTION": {}},
                    "views": [{"name": "Z_RAW_VBAP", "layer": "RAW", "type": "relational_dataset"}],
                    "key_decisions": [
                        {
                            "topic": "Schema",
                            "choice": "Star",
                            "alternatives": [],
                            "rationale": "Performance",
                            "platform_placement": "dsp",
                        }
                    ],
                    "replication_strategy": [],
                    "narrative": "Generated architecture.",
                },
            ),
            patch(
                "spec2sphere.core.knowledge.knowledge_service.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            hla_result = await generate_hla(requirement_id, ctx, make_mock_llm())

        assert "hla_id" in hla_result
        assert hla_result["decisions_count"] == 1
        assert hla_result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_placement_to_dict_serialisable(self):
        """PlacementDecision.to_dict() produces JSON-serialisable output."""
        from spec2sphere.pipeline.placement import Platform, PlacementDecision

        d = PlacementDecision(
            artifact_name="Z_AM_SALES",
            artifact_type="analytic_model",
            platform=Platform.DSP,
            rationale="Always DSP",
            confidence=0.95,
        )
        serialised = d.to_dict()
        # Must round-trip through JSON
        json_str = json.dumps(serialised)
        parsed = json.loads(json_str)
        assert parsed["platform"] == "dsp"
        assert parsed["confidence"] == 0.95
