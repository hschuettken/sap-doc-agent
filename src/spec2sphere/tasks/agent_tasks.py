from spec2sphere.tasks.celery_app import celery_app
import logging

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="llm")
def run_doc_review(self, object_id: str, config_path: str):
    return {"object_id": object_id, "status": "completed"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="llm")
def run_qa_check(self, object_id: str, config_path: str):
    return {"object_id": object_id, "status": "completed"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="llm")
def run_pdf_ingest(self, file_path: str, config_path: str):
    return {"file_path": file_path, "status": "completed"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="llm")
def run_report_generator(self, scope: str, config_path: str):
    return {"scope": scope, "status": "completed"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="llm")
def run_brs_traceability(self, brs_id: str, config_path: str):
    return {"brs_id": brs_id, "status": "completed"}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="llm")
def process_standard_upload(self, standard_id: str, config_path: str):
    import asyncio

    async def _run():
        from spec2sphere.standards import db as standards_db
        from spec2sphere.standards.extractor import extract_text
        from spec2sphere.standards.rule_extractor import extract_rules
        from spec2sphere.llm.noop import NoopLLMProvider

        try:
            file_row = await standards_db.get_standard_file(standard_id)
            if not file_row:
                return {"error": "File not found"}
            raw_text = extract_text(bytes(file_row["file_data"]), file_row["content_type"])
            rules = await extract_rules(raw_text, NoopLLMProvider())
            await standards_db.update_standard_rules(standard_id, rules, raw_text, "ready")
            return {"standard_id": standard_id, "status": "ready"}
        except Exception as e:
            await standards_db.update_standard_rules(standard_id, {}, "", "error", str(e))
            return {"error": str(e)}

    return asyncio.run(_run())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="llm")
def process_knowledge_upload(
    self, file_data_b64: str = None, filename: str = "", knowledge_id: str = None, config_path: str = ""
):
    return {"status": "completed", "filename": filename}
