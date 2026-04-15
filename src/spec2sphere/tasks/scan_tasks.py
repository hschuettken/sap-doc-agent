from spec2sphere.tasks.celery_app import celery_app
import logging

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="scan")
def run_scan(self, scanner_type: str, config_path: str, run_id: str):
    logger.info("run_scan: type=%s run_id=%s", scanner_type, run_id)
    return {"run_id": run_id, "status": "completed", "scanner_type": scanner_type}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="scan")
def run_abap_scan(self, system_name: str, config_path: str, run_id: str):
    logger.info("run_abap_scan: system=%s run_id=%s", system_name, run_id)
    return {"run_id": run_id, "status": "completed", "system_name": system_name}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="scan")
def run_dsp_api_scan(self, system_name: str, config_path: str, run_id: str):
    return {"run_id": run_id, "status": "completed", "system_name": system_name}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="chrome")
def run_cdp_scan(self, system_name: str, config_path: str, run_id: str):
    return {"run_id": run_id, "status": "completed", "system_name": system_name}
