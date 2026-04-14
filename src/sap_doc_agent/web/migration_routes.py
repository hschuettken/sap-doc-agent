"""API and UI routes for the Migration Accelerator."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Request/response models ---


class CreateProjectRequest(BaseModel):
    name: str
    scan_id: str
    description: str = ""
    source_system: str = ""
    brs_folder: str = ""


class ReviewRequest(BaseModel):
    decision: str = Field(..., description="approve, reject, or clarify")
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
