"""Celery tasks for Migration Accelerator phases."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sap_doc_agent.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, queue="llm")
def interpret_chain_task(self, chain_json_path: str, project_id: str, config_path: str = "config.yaml") -> dict:
    """Interpret a chain into an IntentCard and store in DB.

    Reads chain JSON, runs semantic interpreter, persists to migration_intent_cards_v1.
    """
    import asyncio

    async def _run():
        from sap_doc_agent.app import SAPDocAgent
        from sap_doc_agent.migration.interpreter import interpret_chain
        from sap_doc_agent.scanner.models import DataFlowChain

        chain = DataFlowChain.model_validate_json(Path(chain_json_path).read_text())
        app = SAPDocAgent.from_config(config_path)

        intent_card = await interpret_chain(chain, app.llm)

        # Persist to DB
        try:
            from sap_doc_agent.migration import db as migration_db

            await migration_db.upsert_intent_card(project_id, chain.chain_id, intent_card.model_dump())
        except Exception as e:
            logger.warning("Failed to persist intent card to DB: %s", e)

        # Write intent card JSON alongside chain file
        intent_path = Path(chain_json_path).parent / f"{chain.chain_id}_intent.json"
        intent_path.write_text(intent_card.model_dump_json(indent=2))

        return {
            "status": "completed",
            "chain_id": chain.chain_id,
            "business_purpose": intent_card.business_purpose[:200],
            "confidence": intent_card.confidence,
            "needs_human_review": intent_card.needs_human_review,
        }

    return asyncio.run(_run())


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, queue="llm")
def reconcile_brs_task(
    self, chain_id: str, intent_json_path: str, brs_folder: str, project_id: str, config_path: str = "config.yaml"
) -> dict:
    """Reconcile a chain's IntentCard against BRS documents."""
    import asyncio

    async def _run():
        from sap_doc_agent.app import SAPDocAgent
        from sap_doc_agent.migration.brs_reconciler import reconcile_brs_folder
        from sap_doc_agent.migration.models import IntentCard

        intent_card = IntentCard.model_validate_json(Path(intent_json_path).read_text())
        app = SAPDocAgent.from_config(config_path)

        results = await reconcile_brs_folder(intent_card, Path(brs_folder), app.llm)

        # Write reconciliation results
        recon_path = Path(intent_json_path).parent / f"{chain_id}_brs_recon.json"
        recon_path.write_text(json.dumps([_serialize_recon(r) for r in results], indent=2, default=str))

        return {
            "status": "completed",
            "chain_id": chain_id,
            "brs_documents_checked": len(results),
            "total_deltas": sum(len(r.get("deltas", [])) for r in results),
        }

    return asyncio.run(_run())


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, queue="llm")
def classify_chain_task(
    self, chain_json_path: str, intent_json_path: str, project_id: str, config_path: str = "config.yaml"
) -> dict:
    """Classify a chain for migration and store in DB."""
    import asyncio

    async def _run():
        from sap_doc_agent.app import SAPDocAgent
        from sap_doc_agent.migration.classifier import ActivityData, classify_chain
        from sap_doc_agent.migration.models import IntentCard
        from sap_doc_agent.scanner.models import DataFlowChain

        chain = DataFlowChain.model_validate_json(Path(chain_json_path).read_text())
        intent_card = IntentCard.model_validate_json(Path(intent_json_path).read_text())
        app = SAPDocAgent.from_config(config_path)

        # Extract activity data from chain metadata
        activity = None
        for step in chain.steps:
            last_run = step.metadata.get("last_run")
            if last_run:
                activity = ActivityData(last_execution=last_run)
                break

        classified = await classify_chain(intent_card, chain, app.llm, activity)

        # Persist to DB
        try:
            from sap_doc_agent.migration import db as migration_db

            # Find the intent card ID in DB
            cards = await migration_db.list_intent_cards(project_id)
            card_row = next((c for c in cards if c["chain_id"] == chain.chain_id), None)
            if card_row:
                await migration_db.upsert_classification(
                    project_id, chain.chain_id, str(card_row["id"]), classified.model_dump()
                )
        except Exception as e:
            logger.warning("Failed to persist classification to DB: %s", e)

        # Write classification JSON
        class_path = Path(chain_json_path).parent / f"{chain.chain_id}_classified.json"
        class_path.write_text(classified.model_dump_json(indent=2))

        return {
            "status": "completed",
            "chain_id": chain.chain_id,
            "classification": classified.classification.value,
            "effort_category": classified.effort_category,
            "confidence": classified.confidence,
            "needs_human_review": classified.needs_human_review,
        }

    return asyncio.run(_run())


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, queue="llm")
def design_target_task(
    self, chain_json_path: str, classified_json_path: str, project_id: str, config_path: str = "config.yaml"
) -> dict:
    """Design DSP target views for a classified chain."""
    import asyncio

    async def _run():
        from sap_doc_agent.app import SAPDocAgent
        from sap_doc_agent.migration.architect import design_chain_views
        from sap_doc_agent.migration.models import ClassifiedChain
        from sap_doc_agent.scanner.models import DataFlowChain

        chain = DataFlowChain.model_validate_json(Path(chain_json_path).read_text())
        classified = ClassifiedChain.model_validate_json(Path(classified_json_path).read_text())
        app = SAPDocAgent.from_config(config_path)

        views = await design_chain_views(classified, chain, app.llm)

        # Persist to DB
        try:
            from sap_doc_agent.migration import db as migration_db

            for view in views:
                await migration_db.upsert_target_view(project_id, view.technical_name, view.model_dump())
        except Exception as e:
            logger.warning("Failed to persist target views to DB: %s", e)

        # Write target views JSON
        target_path = Path(chain_json_path).parent / f"{chain.chain_id}_target.json"
        target_path.write_text(json.dumps([v.model_dump() for v in views], indent=2, default=str))

        return {
            "status": "completed",
            "chain_id": chain.chain_id,
            "views_designed": len(views),
            "view_names": [v.technical_name for v in views],
        }

    return asyncio.run(_run())


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, queue="llm")
def generate_sql_task(
    self, chain_id: str, target_json_path: str, project_id: str, config_path: str = "config.yaml"
) -> dict:
    """Generate DSP SQL for designed target views."""
    import asyncio

    async def _run():
        from sap_doc_agent.app import SAPDocAgent
        from sap_doc_agent.migration.generator import generate_sql_for_view
        from sap_doc_agent.migration.models import ViewSpec

        target_data = json.loads(Path(target_json_path).read_text())
        views = [ViewSpec.model_validate(v) for v in target_data]
        app = SAPDocAgent.from_config(config_path)

        results = []
        for view in views:
            result = await generate_sql_for_view(view, app.llm)
            results.append(
                {
                    "technical_name": result.technical_name,
                    "space": result.space,
                    "layer": result.layer,
                    "sql": result.sql,
                    "needs_manual_edit": result.needs_manual_edit,
                    "generation_method": result.generation_method,
                    "error_count": result.validation_result.error_count if result.validation_result else 0,
                    "warning_count": result.validation_result.warning_count if result.validation_result else 0,
                }
            )

        # Write SQL results JSON
        sql_path = Path(target_json_path).parent / f"{chain_id}_sql.json"
        sql_path.write_text(json.dumps(results, indent=2))

        return {
            "status": "completed",
            "chain_id": chain_id,
            "views_generated": len(results),
            "needs_review": sum(1 for r in results if r["needs_manual_edit"]),
        }

    return asyncio.run(_run())


def _serialize_recon(result: dict) -> dict:
    """Serialize a reconciliation result for JSON output."""
    serialized = {}
    for key, value in result.items():
        if isinstance(value, list):
            serialized[key] = [v.model_dump() if hasattr(v, "model_dump") else v for v in value]
        else:
            serialized[key] = value
    return serialized
