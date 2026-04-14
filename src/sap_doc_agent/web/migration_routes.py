"""API and UI routes for the Migration Accelerator."""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# --- Request/response models ---


class CreateProjectRequest(BaseModel):
    name: str
    scan_id: str
    description: str = ""
    source_system: str = ""
    brs_folder: str = ""


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    CLARIFY = "clarify"


class ReviewRequest(BaseModel):
    decision: ReviewDecision
    notes: str = ""
    reviewer: str = ""


# --- API Router ---


def create_migration_api_router(output_dir: Path) -> APIRouter:
    """Create the migration API router."""
    router = APIRouter(prefix="/api/migration", tags=["migration"])

    # --- Projects ---

    @router.get("/projects")
    async def list_projects():
        try:
            from sap_doc_agent.migration import db as migration_db

            projects = await migration_db.list_projects()
            return _serialize_rows(projects)
        except Exception as e:
            logger.warning("DB unavailable, returning empty: %s", e)
            return []

    @router.post("/projects")
    async def create_project(req: CreateProjectRequest):
        from sap_doc_agent.migration import db as migration_db

        project_id = await migration_db.create_project(
            name=req.name,
            scan_id=req.scan_id,
            description=req.description,
            source_system=req.source_system,
            brs_folder=req.brs_folder,
        )
        return {"id": project_id, "status": "created"}

    @router.get("/projects/{project_id}")
    async def get_project(project_id: str):
        from sap_doc_agent.migration import db as migration_db

        project = await migration_db.get_project(project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        return _serialize_row(project)

    @router.delete("/projects/{project_id}")
    async def delete_project(project_id: str):
        from sap_doc_agent.migration import db as migration_db

        await migration_db.delete_project(project_id)
        return {"status": "deleted"}

    @router.post("/projects/{project_id}/status")
    async def update_status(project_id: str, status: str):
        from sap_doc_agent.migration import db as migration_db

        await migration_db.update_project_status(project_id, status)
        return {"status": status}

    # --- Interpretation ---

    @router.post("/projects/{project_id}/interpret")
    async def trigger_interpret(project_id: str):
        """Trigger interpretation of all chains for a project."""
        from sap_doc_agent.migration import db as migration_db

        project = await migration_db.get_project(project_id)
        if not project:
            raise HTTPException(404, "Project not found")

        scan_id = project["scan_id"]
        chains_dir = output_dir / "chains"
        if not chains_dir.exists():
            raise HTTPException(400, "No chains found — run chain builder first")

        chain_files = sorted(chains_dir.glob("*.json"))
        # Filter out non-chain files (intent, classified, etc.)
        chain_files = [f for f in chain_files if not any(s in f.stem for s in ["_intent", "_classified", "_brs_recon"])]

        dispatched = []
        for chain_file in chain_files:
            try:
                from sap_doc_agent.tasks.migration_tasks import interpret_chain_task

                interpret_chain_task.apply_async(
                    kwargs={
                        "chain_json_path": str(chain_file),
                        "project_id": project_id,
                    }
                )
                dispatched.append(chain_file.stem)
            except Exception as e:
                logger.warning("Failed to dispatch interpret for %s: %s", chain_file.stem, e)
                dispatched.append(chain_file.stem)

        await migration_db.update_project_status(project_id, "analyzing")
        return {"status": "interpreting", "chains_dispatched": len(dispatched), "chain_ids": dispatched}

    @router.get("/projects/{project_id}/intent-cards")
    async def list_intent_cards(project_id: str):
        try:
            from sap_doc_agent.migration import db as migration_db

            cards = await migration_db.list_intent_cards(project_id)
            return _serialize_rows(cards)
        except Exception:
            # Fallback: read from file system
            return _read_intent_files(output_dir)

    @router.post("/intent-cards/{card_id}/review")
    async def review_intent_card(card_id: str, req: ReviewRequest):
        from sap_doc_agent.migration import db as migration_db

        await migration_db.review_intent_card(card_id, req.decision, req.reviewer, req.notes)
        return {"status": req.decision}

    # --- Classification ---

    @router.post("/projects/{project_id}/classify")
    async def trigger_classify(project_id: str):
        """Trigger classification of all interpreted chains."""
        chains_dir = output_dir / "chains"
        if not chains_dir.exists():
            raise HTTPException(400, "No chains found")

        dispatched = []
        for intent_file in sorted(chains_dir.glob("*_intent.json")):
            chain_id = intent_file.stem.replace("_intent", "")
            chain_file = chains_dir / f"{chain_id}.json"
            if not chain_file.exists():
                continue
            try:
                from sap_doc_agent.tasks.migration_tasks import classify_chain_task

                classify_chain_task.apply_async(
                    kwargs={
                        "chain_json_path": str(chain_file),
                        "intent_json_path": str(intent_file),
                        "project_id": project_id,
                    }
                )
                dispatched.append(chain_id)
            except Exception as e:
                logger.warning("Failed to dispatch classify for %s: %s", chain_id, e)
                dispatched.append(chain_id)

        return {"status": "classifying", "chains_dispatched": len(dispatched)}

    @router.get("/projects/{project_id}/classifications")
    async def list_classifications(project_id: str):
        try:
            from sap_doc_agent.migration import db as migration_db

            classifications = await migration_db.list_classifications(project_id)
            return _serialize_rows(classifications)
        except Exception:
            return _read_classification_files(output_dir)

    @router.post("/classifications/{classification_id}/review")
    async def review_classification(classification_id: str, req: ReviewRequest):
        from sap_doc_agent.migration import db as migration_db

        await migration_db.review_classification(classification_id, req.decision, req.reviewer, req.notes)
        return {"status": req.decision}

    # --- Target Architecture ---

    @router.post("/projects/{project_id}/design")
    async def trigger_design(project_id: str):
        """Trigger target architecture design for classified chains."""
        chains_dir = output_dir / "chains"
        if not chains_dir.exists():
            raise HTTPException(400, "No chains found")

        dispatched = []
        for classified_file in sorted(chains_dir.glob("*_classified.json")):
            chain_id = classified_file.stem.replace("_classified", "")
            chain_file = chains_dir / f"{chain_id}.json"
            if not chain_file.exists():
                continue
            try:
                from sap_doc_agent.tasks.migration_tasks import design_target_task

                design_target_task.apply_async(
                    kwargs={
                        "chain_json_path": str(chain_file),
                        "classified_json_path": str(classified_file),
                        "project_id": project_id,
                    }
                )
                dispatched.append(chain_id)
            except Exception as e:
                logger.warning("Failed to dispatch design for %s: %s", chain_id, e)
                dispatched.append(chain_id)

        return {"status": "designing", "chains_dispatched": len(dispatched), "chain_ids": dispatched}

    @router.get("/projects/{project_id}/target-views")
    async def list_target_views(project_id: str):
        try:
            from sap_doc_agent.migration import db as migration_db

            views = await migration_db.list_target_views(project_id)
            return _serialize_rows(views)
        except Exception:
            return _read_target_files(output_dir)

    # --- Code Generation ---

    @router.post("/projects/{project_id}/generate")
    async def trigger_generate(project_id: str):
        """Trigger SQL code generation for designed views."""
        chains_dir = output_dir / "chains"
        if not chains_dir.exists():
            raise HTTPException(400, "No chains found")

        dispatched = []
        for target_file in sorted(chains_dir.glob("*_target.json")):
            chain_id = target_file.stem.replace("_target", "")
            try:
                from sap_doc_agent.tasks.migration_tasks import generate_sql_task

                generate_sql_task.apply_async(
                    kwargs={
                        "chain_id": chain_id,
                        "target_json_path": str(target_file),
                        "project_id": project_id,
                    }
                )
                dispatched.append(chain_id)
            except Exception as e:
                logger.warning("Failed to dispatch generate for %s: %s", chain_id, e)
                dispatched.append(chain_id)

        return {"status": "generating", "chains_dispatched": len(dispatched), "chain_ids": dispatched}

    @router.get("/projects/{project_id}/generated-sql")
    async def list_generated_sql(project_id: str):
        return _read_generated_sql_files(output_dir)

    # --- SQL Validation ---

    @router.post("/validate-sql")
    async def validate_sql(body: dict):
        from sap_doc_agent.migration.sql_validator import validate_dsp_sql

        sql = body.get("sql", "")
        result = validate_dsp_sql(sql)
        return {
            "is_valid": result.is_valid,
            "error_count": result.error_count,
            "warning_count": result.warning_count,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "message": v.message,
                    "severity": v.severity,
                    "line": v.line,
                    "suggestion": v.suggestion,
                }
                for v in result.violations
            ],
        }

    # --- Report ---

    @router.get("/projects/{project_id}/report")
    async def get_report(project_id: str):
        """Generate and return the migration assessment report as HTML."""
        from sap_doc_agent.migration.diagram import generate_chain_diagram
        from sap_doc_agent.migration.effort import estimate_chain_effort
        from sap_doc_agent.migration.models import ClassifiedChain, TargetArchitecture, ViewSpec
        from sap_doc_agent.migration.report import ReportData, generate_report_html
        from sap_doc_agent.scanner.models import DataFlowChain

        # Load all chain data from files
        chains_dir = output_dir / "chains"
        chains: list[tuple[ClassifiedChain, DataFlowChain]] = []
        all_views: list[ViewSpec] = []

        if chains_dir.exists():
            for chain_file in sorted(chains_dir.glob("*.json")):
                if any(s in chain_file.stem for s in ["_intent", "_classified", "_brs_recon", "_target", "_sql"]):
                    continue
                try:
                    chain = DataFlowChain.model_validate_json(chain_file.read_text())
                    classified_file = chains_dir / f"{chain.chain_id}_classified.json"
                    if classified_file.exists():
                        classified = ClassifiedChain.model_validate_json(classified_file.read_text())
                    else:
                        from sap_doc_agent.migration.models import IntentCard, MigrationClassification

                        intent_file = chains_dir / f"{chain.chain_id}_intent.json"
                        if intent_file.exists():
                            intent = IntentCard.model_validate_json(intent_file.read_text())
                        else:
                            intent = IntentCard(chain_id=chain.chain_id)
                        classified = ClassifiedChain(
                            chain_id=chain.chain_id,
                            intent_card=intent,
                            classification=MigrationClassification.CLARIFY,
                        )
                    chains.append((classified, chain))
                except Exception as e:
                    logger.warning("Failed to load chain %s: %s", chain_file.stem, e)

            # Load target views
            for target_file in sorted(chains_dir.glob("*_target.json")):
                try:
                    data = json.loads(target_file.read_text())
                    if isinstance(data, list):
                        all_views.extend(ViewSpec.model_validate(v) for v in data)
                    else:
                        all_views.append(ViewSpec.model_validate(data))
                except Exception:
                    pass

        # Build effort estimates
        efforts = [estimate_chain_effort(c, ch) for c, ch in chains]

        # Build diagrams
        views_by_chain: dict[str, list[ViewSpec]] = {}
        for v in all_views:
            for sc in v.source_chains:
                views_by_chain.setdefault(sc, []).append(v)

        diagrams = {}
        for classified, chain in chains:
            chain_views = views_by_chain.get(classified.chain_id, [])
            diagrams[classified.chain_id] = generate_chain_diagram(classified, chain, chain_views)

        # Build generated SQL map
        generated_sql: dict[str, str] = {}
        if chains_dir.exists():
            for sql_file in sorted(chains_dir.glob("*_sql.json")):
                try:
                    sql_data = json.loads(sql_file.read_text())
                    if isinstance(sql_data, list):
                        for item in sql_data:
                            if isinstance(item, dict) and "technical_name" in item:
                                generated_sql[item["technical_name"]] = item.get("sql", "")
                except Exception:
                    pass

        # Get project name
        project_name = project_id
        try:
            from sap_doc_agent.migration import db as migration_db

            project = await migration_db.get_project(project_id)
            if project:
                project_name = project.get("name", project_id)
        except Exception:
            pass

        architecture = TargetArchitecture(project_name=project_name, views=all_views) if all_views else None

        report_data = ReportData(
            project_name=project_name,
            chains=chains,
            architecture=architecture,
            efforts=efforts,
            diagrams=diagrams,
            generated_sql=generated_sql,
        )

        from fastapi.responses import HTMLResponse

        return HTMLResponse(content=generate_report_html(report_data))

    return router


# --- UI Router ---


def create_migration_ui_router(output_dir: Path) -> APIRouter:
    """Create the migration UI router."""
    from fastapi.templating import Jinja2Templates

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))
    router = APIRouter(prefix="/ui/migration")

    def _render(request: Request, template: str, ctx: dict) -> HTMLResponse:
        ctx["request"] = request
        return templates.TemplateResponse(request, template, ctx)

    @router.get("/projects", response_class=HTMLResponse)
    async def projects_page(request: Request):
        projects = []
        try:
            from sap_doc_agent.migration import db as migration_db

            projects = await migration_db.list_projects()
            projects = _serialize_rows(projects)
        except Exception:
            pass
        return _render(
            request,
            "partials/migration_projects.html",
            {"active_page": "migration", "projects": projects},
        )

    @router.get("/intent", response_class=HTMLResponse)
    async def intent_page(request: Request):
        project_id = request.query_params.get("project_id", "")
        cards = []
        if project_id:
            try:
                from sap_doc_agent.migration import db as migration_db

                cards = await migration_db.list_intent_cards(project_id)
                cards = _serialize_rows(cards)
            except Exception:
                cards = _read_intent_files(output_dir)
        return _render(
            request,
            "partials/migration_intent.html",
            {"active_page": "migration", "cards": cards, "project_id": project_id},
        )

    @router.get("/classify", response_class=HTMLResponse)
    async def classify_page(request: Request):
        project_id = request.query_params.get("project_id", "")
        classifications = []
        if project_id:
            try:
                from sap_doc_agent.migration import db as migration_db

                classifications = await migration_db.list_classifications(project_id)
                classifications = _serialize_rows(classifications)
            except Exception:
                classifications = _read_classification_files(output_dir)
        return _render(
            request,
            "partials/migration_classify.html",
            {
                "active_page": "migration",
                "classifications": classifications,
                "project_id": project_id,
            },
        )

    @router.get("/design", response_class=HTMLResponse)
    async def design_page(request: Request):
        project_id = request.query_params.get("project_id", "")
        views = _read_target_files(output_dir) if project_id else []
        return _render(
            request,
            "partials/migration_design.html",
            {
                "active_page": "migration",
                "views": views,
                "project_id": project_id,
            },
        )

    @router.get("/generate", response_class=HTMLResponse)
    async def generate_page(request: Request):
        project_id = request.query_params.get("project_id", "")
        sql_results = _read_generated_sql_files(output_dir) if project_id else []
        return _render(
            request,
            "partials/migration_generate.html",
            {
                "active_page": "migration",
                "sql_results": sql_results,
                "project_id": project_id,
            },
        )

    @router.get("/report", response_class=HTMLResponse)
    async def report_page(request: Request):
        project_id = request.query_params.get("project_id", "")
        return _render(
            request,
            "partials/migration_report_page.html",
            {
                "active_page": "migration",
                "project_id": project_id,
            },
        )

    return router


# --- Helpers ---


def _serialize_row(row: dict) -> dict:
    """Serialize a DB row for JSON response (handle UUID, datetime)."""
    result = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif hasattr(v, "hex"):  # UUID
            result[k] = str(v)
        else:
            result[k] = v
    return result


def _serialize_rows(rows: list[dict]) -> list[dict]:
    return [_serialize_row(r) for r in rows]


def _read_intent_files(output_dir: Path) -> list[dict]:
    """Fallback: read intent card JSON files from output dir."""
    chains_dir = output_dir / "chains"
    if not chains_dir.exists():
        return []
    cards = []
    for f in sorted(chains_dir.glob("*_intent.json")):
        try:
            cards.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return cards


def _read_classification_files(output_dir: Path) -> list[dict]:
    """Fallback: read classification JSON files."""
    chains_dir = output_dir / "chains"
    if not chains_dir.exists():
        return []
    classifications = []
    for f in sorted(chains_dir.glob("*_classified.json")):
        try:
            classifications.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return classifications


def _read_target_files(output_dir: Path) -> list[dict]:
    """Fallback: read target view JSON files."""
    chains_dir = output_dir / "chains"
    if not chains_dir.exists():
        return []
    views = []
    for f in sorted(chains_dir.glob("*_target.json")):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, list):
                views.extend(data)
            else:
                views.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return views


def _read_generated_sql_files(output_dir: Path) -> list[dict]:
    """Fallback: read generated SQL JSON files."""
    chains_dir = output_dir / "chains"
    if not chains_dir.exists():
        return []
    results = []
    for f in sorted(chains_dir.glob("*_sql.json")):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return results
