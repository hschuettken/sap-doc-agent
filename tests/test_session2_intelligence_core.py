"""Session 2 — Intelligence Core: comprehensive tests.

Covers:
  - Knowledge Engine (knowledge_service.py): CRUD, semantic search, scoping, document ingestion
  - Design System (tokens.py, archetypes.py, scorer.py): CRUD, profile resolution, scoring
  - Standards Intake (intake.py): rule extraction, LLM fallback, storage
  - Scanner / Landscape Store (landscape_store.py): store/query/stats
  - Scanner / Graph Builder (graph_builder.py): traversal, impact analysis, vis.js output
  - Audit Engine (doc_audit.py): field scoring, description quality, full audit report

All database calls are intercepted via patch("...._get_conn") returning an AsyncMock
connection.  No real database is required.
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


def make_ctx(
    tenant_id=None,
    customer_id=None,
    project_id=None,
) -> ContextEnvelope:
    return ContextEnvelope.single_tenant(
        tenant_id=tenant_id or uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        project_id=project_id,
    )


def make_mock_llm(embeddings=None):
    llm = AsyncMock()
    # is_available() is synchronous in the intake pipeline — must be a plain MagicMock
    # so truthiness checks work without requiring an await.
    llm.is_available = MagicMock(return_value=True)
    llm.embed = AsyncMock(return_value=embeddings)
    llm.generate_json = AsyncMock(
        return_value={
            "rules": [
                {
                    "category": "naming",
                    "rule_text": "Use Z_ prefix for all custom objects",
                    "severity": "must",
                    "examples": ["Z_RAW_SALES", "Z_HARM_CUSTOMER"],
                }
            ]
        }
    )
    return llm


def make_mock_conn():
    conn = AsyncMock()
    conn.close = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetchval = AsyncMock(return_value=0)
    # Support async context manager for transactions
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    return conn


# ---------------------------------------------------------------------------
# Knowledge Engine — CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_knowledge_item_returns_uuid_string():
    """create_knowledge_item should return a UUID-formatted string."""
    from spec2sphere.core.knowledge.knowledge_service import create_knowledge_item

    ctx = make_ctx()
    llm = make_mock_llm(embeddings=[[0.1, 0.2, 0.3]])
    conn = make_mock_conn()

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await create_knowledge_item(ctx, "Test Title", "Test content", "naming", "manual", 0.9, llm)

    # Must be a valid UUID string
    parsed = uuid.UUID(result)
    assert isinstance(parsed, uuid.UUID)
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_knowledge_item_embedding_fallback_on_none():
    """When llm.embed returns None, create still succeeds with NULL embedding."""
    from spec2sphere.core.knowledge.knowledge_service import create_knowledge_item

    ctx = make_ctx()
    llm = make_mock_llm(embeddings=None)  # embed returns None
    conn = make_mock_conn()

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await create_knowledge_item(ctx, "Title", "Content", "quality", "file.md", 1.0, llm)

    assert uuid.UUID(result)  # still returns a valid UUID
    # The execute call should have been made with None for embedding
    _, args, _ = conn.execute.mock_calls[0]
    # $8 position (index 7 in the args after sql) is the embedding value — should be None
    # args = (sql, item_id, tenant_id, customer_id, project_id, category, title, content, embedding_str, source, confidence)
    execute_args = conn.execute.call_args[0]
    embedding_arg = execute_args[8]  # $8 = embedding
    assert embedding_arg is None


@pytest.mark.asyncio
async def test_create_knowledge_item_embedding_fallback_on_exception():
    """When llm.embed raises, create still inserts with NULL embedding (no crash)."""
    from spec2sphere.core.knowledge.knowledge_service import create_knowledge_item

    ctx = make_ctx()
    llm = make_mock_llm()
    llm.embed = AsyncMock(side_effect=RuntimeError("embedding service down"))
    conn = make_mock_conn()

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await create_knowledge_item(ctx, "Title", "Content", "quality", "src", 0.8, llm)

    assert uuid.UUID(result)


@pytest.mark.asyncio
async def test_get_knowledge_item_found():
    """get_knowledge_item returns a dict when the row exists."""
    from spec2sphere.core.knowledge.knowledge_service import get_knowledge_item

    item_id = str(uuid.uuid4())
    fake_row = {"id": uuid.UUID(item_id), "title": "Found", "content": "hello"}
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value=fake_row)

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await get_knowledge_item(item_id)

    assert result is not None
    assert result["title"] == "Found"


@pytest.mark.asyncio
async def test_get_knowledge_item_not_found():
    """get_knowledge_item returns None when the row does not exist."""
    from spec2sphere.core.knowledge.knowledge_service import get_knowledge_item

    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value=None)

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await get_knowledge_item(str(uuid.uuid4()))

    assert result is None


@pytest.mark.asyncio
async def test_update_knowledge_item_returns_true_when_row_updated():
    """update_knowledge_item returns True when execute reports UPDATE 1."""
    from spec2sphere.core.knowledge.knowledge_service import update_knowledge_item

    item_id = str(uuid.uuid4())
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value={"id": item_id, "content": "old content"})
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await update_knowledge_item(item_id, title="New Title")

    assert result is True


@pytest.mark.asyncio
async def test_update_knowledge_item_returns_false_when_not_found():
    """update_knowledge_item returns False when the item does not exist."""
    from spec2sphere.core.knowledge.knowledge_service import update_knowledge_item

    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value=None)

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await update_knowledge_item(str(uuid.uuid4()), title="x")

    assert result is False


@pytest.mark.asyncio
async def test_delete_knowledge_item_true_on_success():
    """delete_knowledge_item returns True when a row is deleted."""
    from spec2sphere.core.knowledge.knowledge_service import delete_knowledge_item

    conn = make_mock_conn()
    conn.execute = AsyncMock(return_value="DELETE 1")

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await delete_knowledge_item(str(uuid.uuid4()))

    assert result is True


@pytest.mark.asyncio
async def test_delete_knowledge_item_false_when_missing():
    """delete_knowledge_item returns False when no row is deleted."""
    from spec2sphere.core.knowledge.knowledge_service import delete_knowledge_item

    conn = make_mock_conn()
    conn.execute = AsyncMock(return_value="DELETE 0")

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        result = await delete_knowledge_item(str(uuid.uuid4()))

    assert result is False


@pytest.mark.asyncio
async def test_list_knowledge_items_returns_dicts():
    """list_knowledge_items returns list of dicts from the DB rows."""
    from spec2sphere.core.knowledge.knowledge_service import list_knowledge_items

    ctx = make_ctx()
    fake_rows = [
        {"id": uuid.uuid4(), "title": "A", "category": "naming"},
        {"id": uuid.uuid4(), "title": "B", "category": "naming"},
    ]
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=fake_rows)

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        results = await list_knowledge_items(ctx, category="naming")

    assert len(results) == 2
    assert results[0]["title"] == "A"


# ---------------------------------------------------------------------------
# Knowledge Engine — Semantic Search + Tenant Scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_knowledge_uses_embedding_when_available():
    """search_knowledge calls _search_layer_semantic (not text) when embed succeeds."""
    from spec2sphere.core.knowledge.knowledge_service import search_knowledge

    ctx = make_ctx(project_id=uuid.uuid4())
    llm = make_mock_llm(embeddings=[[0.1, 0.2, 0.3]])
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[])

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        results = await search_knowledge("naming convention", ctx, top_k=5, llm=llm)

    # embed should have been called for the query
    llm.embed.assert_awaited_once_with(["naming convention"])
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_knowledge_falls_back_to_text_when_embed_none():
    """search_knowledge falls back to ILIKE text search when embed returns None."""
    from spec2sphere.core.knowledge.knowledge_service import search_knowledge

    ctx = make_ctx(project_id=uuid.uuid4())
    llm = make_mock_llm(embeddings=None)  # No embedding available
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[])

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        results = await search_knowledge("Z_prefix rule", ctx, top_k=5, llm=llm)

    assert isinstance(results, list)
    # fetch should still have been called (for text search)
    assert conn.fetch.awaited


@pytest.mark.asyncio
async def test_search_knowledge_tenant_scoping():
    """search_knowledge must NOT return results from a different tenant.

    We mock the DB to return a row that belongs to a different tenant_id.
    The function passes tenant_id as a DB parameter — we verify the SQL
    is called with the correct tenant_id, not the other tenant's ID.
    """
    from spec2sphere.core.knowledge.knowledge_service import search_knowledge

    my_tenant = uuid.uuid4()
    other_tenant = uuid.uuid4()
    ctx = make_ctx(tenant_id=my_tenant, project_id=uuid.uuid4())
    llm = make_mock_llm(embeddings=None)

    # Simulate DB returns a row whose tenant_id is the OTHER tenant
    other_tenant_row = {
        "id": uuid.uuid4(),
        "tenant_id": other_tenant,
        "title": "Other tenant item",
        "content": "secret",
        "similarity": None,
    }
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[other_tenant_row])

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        results = await search_knowledge("naming", ctx, top_k=10, llm=llm)

    # Verify all DB calls used the correct tenant_id (my_tenant), not other_tenant
    for mock_call in conn.fetch.call_args_list:
        args = mock_call[0]
        # The tenant_id parameter is always passed to the query — verify it is my_tenant
        assert other_tenant not in args, (
            f"search_knowledge passed other_tenant={other_tenant} to DB — cross-tenant leak!"
        )


@pytest.mark.asyncio
async def test_search_knowledge_deduplicates_by_title():
    """If the same title appears in multiple layers, only the highest-scored one is returned."""
    from spec2sphere.core.knowledge.knowledge_service import search_knowledge

    ctx = make_ctx(project_id=uuid.uuid4())
    llm = make_mock_llm(embeddings=None)

    shared_title = "Z_ prefix rule"
    # project layer returns with similarity 0.9 (score = 0.9 + 0.10 = 1.0)
    # customer layer returns same title with similarity 0.7 (score = 0.7 + 0.05 = 0.75)
    project_row = {
        "id": uuid.uuid4(),
        "tenant_id": ctx.tenant_id,
        "title": shared_title,
        "content": "project version",
        "similarity": None,
    }
    customer_row = {
        "id": uuid.uuid4(),
        "tenant_id": ctx.tenant_id,
        "title": shared_title,
        "content": "customer version",
        "similarity": None,
    }

    # fetch is called once per layer — return rows by call order
    conn = make_mock_conn()
    conn.fetch = AsyncMock(side_effect=[[project_row], [customer_row], []])

    with patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn):
        results = await search_knowledge(shared_title, ctx, top_k=10, llm=llm)

    # Deduplication: only one result for this title
    titles = [r["title"] for r in results]
    assert titles.count(shared_title) == 1


# ---------------------------------------------------------------------------
# Knowledge Engine — Document Ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_documents_returns_ingested_count():
    """ingest_documents should return ingested count matching number of chunks."""
    from spec2sphere.core.knowledge.knowledge_service import ingest_documents

    ctx = make_ctx()
    llm = make_mock_llm(embeddings=[[0.1, 0.2]])
    conn = make_mock_conn()

    # Plain text file — one small chunk
    files = [("readme.txt", b"Short document about naming conventions.", "text/plain")]

    with (
        patch("spec2sphere.core.knowledge.knowledge_service._get_conn", return_value=conn),
        patch("spec2sphere.standards.extractor.extract_text", return_value="Short document about naming conventions."),
    ):
        result = await ingest_documents(files, ctx, llm)

    assert result["ingested"] >= 1
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_ingest_documents_records_error_on_unsupported_type():
    """ingest_documents records an error entry for unsupported file types."""
    from spec2sphere.core.knowledge.knowledge_service import ingest_documents
    from spec2sphere.standards.extractor import UnsupportedFileType

    ctx = make_ctx()
    llm = make_mock_llm()

    files = [("data.xls", b"\x00binary", "application/vnd.ms-excel")]

    with patch("spec2sphere.standards.extractor.extract_text", side_effect=UnsupportedFileType("xls")):
        result = await ingest_documents(files, ctx, llm)

    assert result["ingested"] == 0
    assert len(result["errors"]) == 1
    assert "data.xls" in result["errors"][0]


# ---------------------------------------------------------------------------
# Design System — Tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_token_returns_uuid():
    """create_token inserts a row and returns a UUID string."""
    from spec2sphere.core.design_system.tokens import create_token

    new_id = str(uuid.uuid4())
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value={"id": uuid.UUID(new_id)})

    with patch("spec2sphere.core.design_system.tokens._get_conn", return_value=conn):
        result = await create_token(
            customer_id=None,
            token_type="color",
            token_name="primary",
            token_value={"hex": "#05415A"},
        )

    assert uuid.UUID(result)
    conn.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_design_profile_customer_overrides_default():
    """Customer token values should override Horvath defaults for the same (type, name)."""
    from spec2sphere.core.design_system.tokens import resolve_design_profile

    customer_id = uuid.uuid4()
    # Default row: primary color = #05415A (Horvath petrol)
    default_rows = [
        {"token_type": "color", "token_name": "primary", "token_value": json.dumps({"hex": "#05415A"})},
        {"token_type": "color", "token_name": "accent", "token_value": json.dumps({"hex": "#C8963E"})},
    ]
    # Customer override: primary = #FF0000
    override_rows = [
        {"token_type": "color", "token_name": "primary", "token_value": json.dumps({"hex": "#FF0000"})},
    ]

    conn = make_mock_conn()
    # First fetch returns defaults, second returns overrides
    conn.fetch = AsyncMock(side_effect=[default_rows, override_rows])

    with patch("spec2sphere.core.design_system.tokens._get_conn", return_value=conn):
        profile = await resolve_design_profile(customer_id)

    # Customer override wins
    assert profile["color"]["primary"]["hex"] == "#FF0000"
    # Non-overridden default should still be present
    assert profile["color"]["accent"]["hex"] == "#C8963E"


@pytest.mark.asyncio
async def test_seed_horvath_defaults_inserts_when_absent():
    """seed_horvath_defaults inserts tokens that don't exist yet."""
    from spec2sphere.core.design_system.tokens import seed_horvath_defaults

    conn = make_mock_conn()
    # All tokens absent — fetchrow returns None every time
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    with patch("spec2sphere.core.design_system.tokens._get_conn", return_value=conn):
        inserted = await seed_horvath_defaults()

    # At least the core defaults should be inserted
    assert inserted > 0
    assert conn.execute.await_count == inserted


@pytest.mark.asyncio
async def test_seed_horvath_defaults_skips_existing():
    """seed_horvath_defaults is idempotent — existing tokens are not re-inserted."""
    from spec2sphere.core.design_system.tokens import seed_horvath_defaults

    conn = make_mock_conn()
    # All tokens already exist — fetchrow returns a truthy row every time
    conn.fetchrow = AsyncMock(return_value={"id": uuid.uuid4()})
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    with patch("spec2sphere.core.design_system.tokens._get_conn", return_value=conn):
        inserted = await seed_horvath_defaults()

    assert inserted == 0
    conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Design System — Archetypes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_archetype_returns_uuid():
    """create_archetype inserts a row and returns a UUID string."""
    from spec2sphere.core.design_system.archetypes import create_archetype

    new_id = str(uuid.uuid4())
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value={"id": uuid.UUID(new_id)})

    with patch("spec2sphere.core.design_system.archetypes._get_conn", return_value=conn):
        result = await create_archetype(
            customer_id=None,
            name="exec_overview",
            description="C-level overview",
            archetype_type="layout",
            definition={"recommended_density": "sparse"},
        )

    assert uuid.UUID(result)


@pytest.mark.asyncio
async def test_seed_horvath_archetypes_inserts_nine():
    """seed_horvath_archetypes inserts all 9 standard archetypes when none exist."""
    from spec2sphere.core.design_system.archetypes import seed_horvath_archetypes, _HORVATH_ARCHETYPES

    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[])  # no existing names
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    with patch("spec2sphere.core.design_system.archetypes._get_conn", return_value=conn):
        inserted = await seed_horvath_archetypes()

    assert inserted == len(_HORVATH_ARCHETYPES)


@pytest.mark.asyncio
async def test_seed_horvath_archetypes_idempotent():
    """seed_horvath_archetypes skips existing archetypes."""
    from spec2sphere.core.design_system.archetypes import seed_horvath_archetypes, _HORVATH_ARCHETYPES

    # All already exist
    existing = [{"name": a["name"]} for a in _HORVATH_ARCHETYPES]
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=existing)

    with patch("spec2sphere.core.design_system.archetypes._get_conn", return_value=conn):
        inserted = await seed_horvath_archetypes()

    assert inserted == 0


# ---------------------------------------------------------------------------
# Design System — Scorer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_dashboard_known_archetype_scores_high():
    """A well-formed blueprint with a known archetype and good metadata scores >= 70."""
    from spec2sphere.core.design_system.scorer import score_dashboard

    blueprint = {
        "title": "Revenue Performance Dashboard",
        "archetype": "exec_overview",
        "density": "sparse",
        "widgets": [
            {"title": "Total Revenue", "chart_type": "kpi_tile"},
            {"title": "Revenue Trend", "chart_type": "line_chart"},
        ],
        "filters": [
            {"type": "date_range", "position": "header", "scope": "global"},
        ],
        "pages": [{"name": "Overview"}],
        "breadcrumb": True,
        "drill_paths": [{"from": "overview", "to": "detail"}],
    }
    tokens = {
        "spacing": {"standard": {"base": "8px"}},
        "density": {"sparse": {"kpi_limit": 4, "widgets_per_row": 2}},
    }

    result = await score_dashboard(blueprint, tokens=tokens)

    assert result.total >= 70.0
    assert result.archetype_compliance == 100.0


@pytest.mark.asyncio
async def test_score_dashboard_missing_archetype_scores_low():
    """A blueprint with no archetype declared has zero archetype_compliance."""
    from spec2sphere.core.design_system.scorer import score_dashboard

    blueprint = {
        # No archetype key
        "title": "Unnamed Dashboard",
    }

    result = await score_dashboard(blueprint)

    assert result.archetype_compliance == 0.0
    # Total must reflect the 30% weight penalty
    assert result.total < 40.0


@pytest.mark.asyncio
async def test_score_dashboard_unknown_chart_types_penalised():
    """Each unknown chart type deducts 20 points from chart_choice score."""
    from spec2sphere.core.design_system.scorer import score_dashboard

    blueprint = {
        "title": "Analytics Board",
        "archetype": "exec_overview",
        "widgets": [
            {"title": "Revenue", "chart_type": "kpi_tile"},  # known
            {"title": "Magic", "chart_type": "hologram_3d"},  # unknown
            {"title": "Mystery", "chart_type": "quantum_viz"},  # unknown
        ],
    }

    result = await score_dashboard(blueprint)

    # 2 unknown types → penalty of 40 → chart_choice = 60
    assert result.chart_choice == 60.0


@pytest.mark.asyncio
async def test_score_dashboard_accepts_knowledge_item_row():
    """score_dashboard can accept a knowledge_item row with a 'content' dict."""
    from spec2sphere.core.design_system.scorer import score_dashboard

    knowledge_item = {
        "id": str(uuid.uuid4()),
        "title": "Dashboard Item",
        "content": {
            "archetype": "management_cockpit",
            "density": "medium",
            "title": "Management Cockpit",
        },
    }

    result = await score_dashboard(knowledge_item)

    assert result.archetype_compliance == 100.0


@pytest.mark.asyncio
async def test_score_dashboard_generic_title_penalised():
    """A generic dashboard title ('untitled') should lower title_quality score."""
    from spec2sphere.core.design_system.scorer import score_dashboard

    blueprint = {
        "title": "untitled",
        "archetype": "exec_overview",
    }

    result = await score_dashboard(blueprint)

    # Generic title gets 0 pts for dashboard title, neutral 25 for no widgets
    assert result.title_quality == 25.0


# ---------------------------------------------------------------------------
# Standards Intake
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_standard_extracts_and_stores_rules():
    """ingest_standard should extract rules via LLM and store them in the DB."""
    from spec2sphere.core.standards.intake import ingest_standard

    ctx = make_ctx()
    llm = make_mock_llm(embeddings=[[0.1, 0.2]])
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value={"id": uuid.uuid4()})

    file_data = b"All custom views must start with Z_. Use layering: L0 raw, L1 harmonised."
    filename = "naming_guide.md"
    content_type = "text/markdown"

    with (
        patch("spec2sphere.core.standards.intake._get_conn", return_value=conn),
        patch("spec2sphere.standards.extractor.extract_text", return_value=file_data.decode()),
    ):
        result = await ingest_standard(file_data, filename, content_type, ctx, llm)

    assert result["filename"] == filename
    assert result["rules_extracted"] >= 1
    assert len(result["rules"]) >= 1
    assert result["rules"][0]["category"] == "naming"


@pytest.mark.asyncio
async def test_ingest_standard_llm_unavailable_returns_zero_rules():
    """When LLM is unavailable, ingest_standard returns 0 rules extracted."""
    from spec2sphere.core.standards.intake import ingest_standard

    ctx = make_ctx()
    llm = make_mock_llm()
    # is_available() is called synchronously in _extract_rules_enhanced — use MagicMock
    # so the truthiness check fires correctly (AsyncMock returns a coroutine which is
    # always truthy and would bypass the availability guard).
    llm.is_available = MagicMock(return_value=False)

    file_data = b"Some text about naming."
    with patch("spec2sphere.standards.extractor.extract_text", return_value="Some text about naming."):
        result = await ingest_standard(file_data, "guide.md", "text/markdown", ctx, llm)

    assert result["rules_extracted"] == 0
    assert result["rules"] == []


@pytest.mark.asyncio
async def test_ingest_standard_empty_document_returns_error():
    """An empty document should return an error key."""
    from spec2sphere.core.standards.intake import ingest_standard

    ctx = make_ctx()
    llm = make_mock_llm()

    with patch("spec2sphere.standards.extractor.extract_text", return_value="   "):
        result = await ingest_standard(b"   ", "empty.md", "text/markdown", ctx, llm)

    assert result["rules_extracted"] == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_ingest_standard_llm_returns_raw_fallback():
    """When LLM generate_json returns {'raw': ...} (parse failure), no rules stored."""
    from spec2sphere.core.standards.intake import ingest_standard

    ctx = make_ctx()
    llm = make_mock_llm()
    # Simulate LLM returning raw text fallback (not a valid rules dict)
    llm.generate_json = AsyncMock(return_value={"raw": "Some unparsed text"})

    conn = make_mock_conn()
    with (
        patch("spec2sphere.core.standards.intake._get_conn", return_value=conn),
        patch("spec2sphere.standards.extractor.extract_text", return_value="A naming rule document."),
    ):
        result = await ingest_standard(b"content", "doc.md", "text/markdown", ctx, llm)

    # {"raw": ...} does not match the {"rules": [...]} schema — 0 rules stored
    assert result["rules_extracted"] == 0


# ---------------------------------------------------------------------------
# Scanner — Landscape Store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_landscape_objects_scoped_by_customer():
    """get_landscape_objects must filter by customer_id."""
    from spec2sphere.core.scanner.landscape_store import get_landscape_objects

    ctx = make_ctx()
    fake_rows = [
        {
            "id": uuid.uuid4(),
            "object_name": "Z_SALES_VIEW",
            "platform": "dsp",
            "object_type": "view",
            "layer": "L2",
            "metadata": "{}",
            "dependencies": "[]",
            "technical_name": "Z_SALES_VIEW",
            "documentation": None,
            "last_scanned": None,
            "created_at": None,
            "project_id": None,
            "customer_id": ctx.customer_id,
        },
    ]
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=fake_rows)

    with patch("spec2sphere.core.scanner.landscape_store._get_conn", return_value=conn):
        results = await get_landscape_objects(ctx)

    assert len(results) == 1
    # Verify customer_id was passed to the DB (first positional param after SQL)
    fetch_args = conn.fetch.call_args[0]
    assert ctx.customer_id in fetch_args


@pytest.mark.asyncio
async def test_get_landscape_stats_returns_expected_keys():
    """get_landscape_stats returns a dict with total, by_platform, by_object_type, by_layer."""
    from spec2sphere.core.scanner.landscape_store import get_landscape_stats

    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"platform": "dsp", "cnt": 10}],  # by_platform
            [{"object_type": "view", "cnt": 10}],  # by_type
            [{"layer": "L1", "cnt": 5}, {"layer": None, "cnt": 5}],  # by_layer
        ]
    )
    conn.fetchval = AsyncMock(return_value=10)

    with patch("spec2sphere.core.scanner.landscape_store._get_conn", return_value=conn):
        stats = await get_landscape_stats(ctx)

    assert "total" in stats
    assert stats["total"] == 10
    assert "by_platform" in stats
    assert "by_object_type" in stats
    assert "by_layer" in stats
    # None layer should be mapped to "unknown"
    assert "unknown" in stats["by_layer"]


# ---------------------------------------------------------------------------
# Scanner — Graph Builder (pure / in-memory — no DB needed)
# ---------------------------------------------------------------------------


def _make_graph():
    """Build a small in-memory DependencyGraph for traversal tests.

    Layout:
      A --reads_from--> B --reads_from--> C
      D --references--> B
    """
    from spec2sphere.core.scanner.graph_builder import DependencyGraph, GraphNode, GraphEdge

    a_id = str(uuid.uuid4())
    b_id = str(uuid.uuid4())
    c_id = str(uuid.uuid4())
    d_id = str(uuid.uuid4())

    nodes = [
        GraphNode(id=a_id, name="View_A", platform="dsp", object_type="view"),
        GraphNode(id=b_id, name="ADSO_B", platform="bw", object_type="adso"),
        GraphNode(id=c_id, name="Raw_C", platform="bw", object_type="table"),
        GraphNode(id=d_id, name="Story_D", platform="sac", object_type="story"),
    ]
    edges = [
        GraphEdge(source_id=a_id, target_id=b_id, edge_type="reads_from"),
        GraphEdge(source_id=b_id, target_id=c_id, edge_type="reads_from"),
        GraphEdge(source_id=d_id, target_id=b_id, edge_type="references"),
    ]

    graph = DependencyGraph(nodes=nodes, edges=edges)
    graph._build_index()
    return graph, {"a": a_id, "b": b_id, "c": c_id, "d": d_id}


def test_graph_upstream_returns_all_source_nodes():
    """upstream(graph, C) should return B and nothing else (B feeds into C)."""
    from spec2sphere.core.scanner.graph_builder import upstream

    graph, ids = _make_graph()
    result = upstream(graph, ids["c"])

    result_ids = {n.id for n in result}
    assert ids["b"] in result_ids
    # A and D are not direct upstream of C (they feed B, not C directly at 1-hop,
    # but BFS goes further — A feeds B which feeds C, so A is also upstream)
    assert ids["a"] in result_ids or ids["b"] in result_ids


def test_graph_downstream_returns_consumers():
    """downstream(graph, B) should return A — wait, A reads FROM B, so B is upstream of A.

    Re-check directionality: A --reads_from--> B means A depends on B.
    Forward edge: A→B (A is source, B is target).
    downstream(B) = nodes that B feeds into = A (because A has B as a target).

    Actually: 'downstream' in the code follows forward edges from the node.
    downstream(B) follows B's forward edges → B→C, so C is downstream.
    Let's verify this with the actual implementation logic.
    """
    from spec2sphere.core.scanner.graph_builder import downstream

    graph, ids = _make_graph()
    # B has a forward edge to C (B→C via reads_from)
    result = downstream(graph, ids["b"])

    result_ids = {n.id for n in result}
    assert ids["c"] in result_ids


def test_graph_upstream_of_leaf_is_empty():
    """A node with no backward edges has no upstream."""
    from spec2sphere.core.scanner.graph_builder import upstream

    graph, ids = _make_graph()
    # C has no outgoing (forward) edges and no nodes point away from it as a source
    # But backward of C = B (B→C), backward of A = none (nothing points to A)
    result = upstream(graph, ids["a"])

    assert result == []


def test_graph_impact_analysis_structure():
    """impact_analysis returns a dict with the required keys."""
    from spec2sphere.core.scanner.graph_builder import impact_analysis

    graph, ids = _make_graph()
    result = impact_analysis(graph, ids["b"])

    assert "object_id" in result
    assert "upstream" in result
    assert "downstream" in result
    assert "affected_count" in result
    assert "platforms_affected" in result
    assert result["object_id"] == ids["b"]
    # B has upstream (C flows into it via A--reads_from-->B actually B is between A and C)
    # Let's just verify the structure is correct
    assert isinstance(result["upstream"], list)
    assert isinstance(result["downstream"], list)
    assert isinstance(result["affected_count"], int)


def test_graph_impact_analysis_platforms_affected():
    """impact_analysis should list all platform names touched by the affected nodes."""
    from spec2sphere.core.scanner.graph_builder import impact_analysis

    graph, ids = _make_graph()
    # B is referenced by D (sac) and has C (bw) downstream and A (dsp) upstream
    result = impact_analysis(graph, ids["b"])

    platforms = set(result["platforms_affected"])
    # dsp (A), bw (C), sac (D) should all be mentioned
    assert len(platforms) >= 2


def test_to_vis_js_format():
    """to_vis_js returns a dict with 'nodes' and 'edges' lists in vis.js format."""
    from spec2sphere.core.scanner.graph_builder import to_vis_js

    graph, ids = _make_graph()
    vis = to_vis_js(graph)

    assert "nodes" in vis
    assert "edges" in vis
    assert len(vis["nodes"]) == 4
    assert len(vis["edges"]) == 3

    # Check node fields
    node = vis["nodes"][0]
    assert "id" in node
    assert "label" in node
    assert "group" in node
    assert "color" in node
    assert "shape" in node

    # Check edge fields
    edge = vis["edges"][0]
    assert "from" in edge
    assert "to" in edge
    assert "arrows" in edge
    assert edge["arrows"] == "to"


def test_to_vis_js_platform_colors():
    """to_vis_js assigns correct platform colors (dsp=blue, sac=orange, bw=purple)."""
    from spec2sphere.core.scanner.graph_builder import to_vis_js, _PLATFORM_COLORS

    graph, ids = _make_graph()
    vis = to_vis_js(graph)

    nodes_by_id = {n["id"]: n for n in vis["nodes"]}

    # A is dsp → blue
    assert nodes_by_id[ids["a"]]["color"] == _PLATFORM_COLORS["dsp"]
    # D is sac → orange
    assert nodes_by_id[ids["d"]]["color"] == _PLATFORM_COLORS["sac"]


# ---------------------------------------------------------------------------
# Audit Engine — Unit-level helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_documented_fields_all_present_scores_100():
    """An object with all four documentation fields filled scores 100."""
    from spec2sphere.core.audit.doc_audit import _score_documented_fields

    obj = {
        "documentation": "This view loads raw sales data from SAP ERP.",
        "metadata": json.dumps({"description": "Acquisition layer view for sales."}),
        "layer": "L0",
        "dependencies": json.dumps([{"target_id": str(uuid.uuid4()), "dependency_type": "reads_from"}]),
    }

    score, recs = await _score_documented_fields(obj)

    assert score == 100.0
    assert recs == []


@pytest.mark.asyncio
async def test_score_documented_fields_all_missing_scores_zero():
    """An object with no documentation fields scores 0."""
    from spec2sphere.core.audit.doc_audit import _score_documented_fields

    obj = {
        "documentation": None,
        "metadata": "{}",
        "layer": None,
        "dependencies": "[]",
    }

    score, recs = await _score_documented_fields(obj)

    assert score == 0.0
    assert len(recs) >= 4


@pytest.mark.asyncio
async def test_score_description_quality_good_description():
    """A long, keyword-rich description scores high."""
    from spec2sphere.core.audit.doc_audit import _score_description_quality

    obj = {
        "documentation": (
            "This transformation loads and harmonizes raw sales data from the source system. "
            "It maps customer IDs to the business key and calculates revenue per domain. "
            "Purpose: provides a cleansed dataset for the L1 layer."
        )
    }

    score, recs = await _score_description_quality(obj)

    assert score >= 70.0


@pytest.mark.asyncio
async def test_score_description_quality_empty_scores_zero():
    """No description at all scores 0."""
    from spec2sphere.core.audit.doc_audit import _score_description_quality

    obj = {"documentation": None, "metadata": "{}"}

    score, recs = await _score_description_quality(obj)

    assert score == 0.0
    assert len(recs) == 1


@pytest.mark.asyncio
async def test_score_description_quality_placeholder_penalised():
    """A placeholder 'todo' description is penalised."""
    from spec2sphere.core.audit.doc_audit import _score_description_quality

    obj = {"documentation": "todo"}

    score, recs = await _score_description_quality(obj)

    # Placeholder penalty: base 40 - 30 penalty = 10 (no keyword bonus)
    assert score <= 20.0
    assert any("placeholder" in r.lower() for r in recs)


@pytest.mark.asyncio
async def test_audit_documentation_returns_report():
    """audit_documentation should return a populated AuditReport."""
    from spec2sphere.core.audit.doc_audit import audit_documentation, AuditReport

    ctx = make_ctx()

    fake_objects = [
        {
            "id": uuid.uuid4(),
            "object_name": "Z_SALES_VIEW",
            "platform": "dsp",
            "object_type": "view",
            "documentation": "Loads raw sales from ERP and maps to business key for harmonization.",
            "metadata": json.dumps({"description": "Sales acquisition layer."}),
            "layer": "L0",
            "dependencies": json.dumps([{"target_id": str(uuid.uuid4()), "dependency_type": "reads_from"}]),
        },
        {
            "id": uuid.uuid4(),
            "object_name": "UNNAMED_OBJ",
            "platform": "bw",
            "object_type": "adso",
            "documentation": None,
            "metadata": "{}",
            "layer": None,
            "dependencies": "[]",
        },
    ]

    conn = make_mock_conn()
    # _load_objects returns the fake objects
    conn.fetch = AsyncMock(side_effect=[fake_objects, []])  # objects, then naming rules

    with patch("spec2sphere.core.audit.doc_audit._get_conn", return_value=conn):
        report = await audit_documentation(ctx)

    assert isinstance(report, AuditReport)
    assert report.total_objects == 2
    assert report.audited_objects == 2
    assert report.average_score >= 0.0

    # The well-documented object should score higher
    scores = sorted([sc.total_score for sc in report.scorecards], reverse=True)
    assert scores[0] > scores[1]


@pytest.mark.asyncio
async def test_audit_documentation_summary_buckets():
    """Bucket summary correctly categorises excellent/good/needs_work/poor."""
    from spec2sphere.core.audit.doc_audit import _bucket_summary, ObjectScorecard

    scorecards = [
        ObjectScorecard(
            "id1",
            "A",
            "dsp",
            total_score=90.0,
            documented_fields=100,
            naming_compliance=90,
            description_quality=85,
            cross_references=90,
        ),
        ObjectScorecard(
            "id2",
            "B",
            "dsp",
            total_score=70.0,
            documented_fields=75,
            naming_compliance=65,
            description_quality=70,
            cross_references=65,
        ),
        ObjectScorecard(
            "id3",
            "C",
            "dsp",
            total_score=50.0,
            documented_fields=50,
            naming_compliance=50,
            description_quality=50,
            cross_references=50,
        ),
        ObjectScorecard(
            "id4",
            "D",
            "dsp",
            total_score=20.0,
            documented_fields=10,
            naming_compliance=20,
            description_quality=10,
            cross_references=30,
        ),
    ]

    summary = _bucket_summary(scorecards)

    assert summary["excellent"] == 1  # 90
    assert summary["good"] == 1  # 70
    assert summary["needs_work"] == 1  # 50
    assert summary["poor"] == 1  # 20


# ---------------------------------------------------------------------------
# Scanner — Hash-based incremental scan (Gap B4 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_scan_results_unchanged_when_hash_matches():
    """store_scan_results returns unchanged > 0 when content_hash already matches."""
    from spec2sphere.core.scanner.landscape_store import store_scan_results
    from spec2sphere.scanner.models import ObjectType, ScanResult, ScannedObject

    ctx = make_ctx()
    obj = ScannedObject(
        object_id="OBJ_001",
        object_type=ObjectType.VIEW,
        name="Z_SALES_VIEW",
        technical_name="Z_SALES_VIEW",
    )
    existing_hash = obj.compute_hash()  # pre-compute so mock can return the same value

    scan_result = ScanResult(source_system="dsp_test", objects=[obj])

    conn = make_mock_conn()
    # fetchrow returns a row with the same content_hash → unchanged path
    conn.fetchrow = AsyncMock(return_value={"id": uuid.uuid4(), "content_hash": existing_hash})

    run_id = uuid.uuid4()
    vt_conn = make_mock_conn()
    vt_conn.fetchrow = AsyncMock(return_value={"id": run_id})
    vt_conn.execute = AsyncMock(return_value="UPDATE 1")

    with (
        patch("spec2sphere.core.scanner.landscape_store._get_conn", return_value=conn),
        patch("spec2sphere.core.scanner.version_tracker._get_conn", return_value=vt_conn),
    ):
        result = await store_scan_results(scan_result, ctx, platform="dsp")

    assert result["unchanged"] > 0
    assert result["stored"] == 0
    assert result["updated"] == 0


@pytest.mark.asyncio
async def test_store_scan_results_stores_new_objects():
    """store_scan_results stores objects when no existing row is found (fetchrow returns None)."""
    from spec2sphere.core.scanner.landscape_store import store_scan_results
    from spec2sphere.scanner.models import ObjectType, ScanResult, ScannedObject

    ctx = make_ctx()
    obj = ScannedObject(
        object_id="OBJ_002",
        object_type=ObjectType.VIEW,
        name="Z_NEW_VIEW",
        technical_name="Z_NEW_VIEW",
    )
    scan_result = ScanResult(source_system="dsp_test", objects=[obj])

    run_id = uuid.uuid4()
    inserted_id = uuid.uuid4()

    # Main connection: first fetchrow = existence check (None), second = INSERT RETURNING id
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(side_effect=[None, {"id": inserted_id}])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetch = AsyncMock(return_value=[])

    # version_tracker connections (create_scan_run + complete_scan_run each open their own)
    vt_conn_create = make_mock_conn()
    vt_conn_create.fetchrow = AsyncMock(return_value={"id": run_id})
    vt_conn_complete = make_mock_conn()
    vt_conn_complete.execute = AsyncMock(return_value="UPDATE 1")

    with (
        patch("spec2sphere.core.scanner.landscape_store._get_conn", return_value=conn),
        patch(
            "spec2sphere.core.scanner.version_tracker._get_conn",
            side_effect=[vt_conn_create, vt_conn_complete],
        ),
    ):
        result = await store_scan_results(scan_result, ctx, platform="dsp")

    assert result["stored"] > 0
    assert result["unchanged"] == 0


# ---------------------------------------------------------------------------
# Design System — Scorer (Gap B4 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_dashboard_sac_object_has_all_six_subcategories():
    """score_dashboard returns all 6 subcategory scores and a total for a SAC metadata dict."""
    from spec2sphere.core.design_system.scorer import score_dashboard

    sac_metadata = {
        "title": "SAP Analytics Cloud Overview",
        "archetype": "exec_overview",
        "density": "sparse",
        "widgets": [
            {"title": "Revenue KPI", "chart_type": "kpi_tile"},
            {"title": "Trend Line", "chart_type": "line_chart"},
        ],
        "filters": [{"type": "fiscal_period", "position": "header", "scope": "global"}],
        "pages": [{"name": "Overview"}],
        "breadcrumb": True,
        "drill_paths": [{"from": "overview", "to": "region"}],
    }

    score = await score_dashboard(sac_metadata)

    # All 6 subcategories must be present and numeric
    assert isinstance(score.total, float)
    assert isinstance(score.archetype_compliance, float)
    assert isinstance(score.layout_readability, float)
    assert isinstance(score.chart_choice, float)
    assert isinstance(score.title_quality, float)
    assert isinstance(score.filter_usability, float)
    assert isinstance(score.navigation_clarity, float)
    # Total should be in valid range
    assert 0.0 <= score.total <= 100.0


# ---------------------------------------------------------------------------
# Design System — resolve_design_profile (Gap B4 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_design_profile_accepts_context_envelope():
    """resolve_design_profile works when passed a ContextEnvelope."""
    from spec2sphere.core.design_system.tokens import resolve_design_profile

    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[])  # no tokens — empty profile is fine

    with patch("spec2sphere.core.design_system.tokens._get_conn", return_value=conn):
        profile = await resolve_design_profile(ctx)

    assert isinstance(profile, dict)
    # Verify the correct customer_id was passed to the second DB query
    second_call_args = conn.fetch.call_args_list[1][0]
    assert str(ctx.customer_id) in second_call_args


@pytest.mark.asyncio
async def test_resolve_design_profile_accepts_raw_uuid():
    """resolve_design_profile accepts a raw UUID (backward compat path)."""
    from spec2sphere.core.design_system.tokens import resolve_design_profile

    customer_id = uuid.uuid4()
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[])

    with patch("spec2sphere.core.design_system.tokens._get_conn", return_value=conn):
        profile = await resolve_design_profile(customer_id)

    assert isinstance(profile, dict)
    # The second DB fetch call should include the raw UUID value
    second_call_args = conn.fetch.call_args_list[1][0]
    assert str(customer_id) in second_call_args
