"""
Celery tasks for File Drop ingestion.

``process_dropped_file`` — parse a single file and feed it into the pipeline.
``poll_drop_directory``  — periodic fallback in case filesystem events are missed.

Both tasks are no-ops when ``FILE_DROP_ENABLED`` is not ``true``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from spec2sphere.scanner.file_drop import get_watcher
from spec2sphere.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    return os.environ.get("FILE_DROP_ENABLED", "false").lower() == "true"


@celery_app.task(name="spec2sphere.tasks.file_drop_tasks.process_dropped_file")
def process_dropped_file(path: str) -> dict:
    """Parse a single dropped file and feed into the scan pipeline.

    Args:
        path: Absolute path string of the file to process.

    Returns:
        Dict with ``status``, ``path``, and (on success) ``objects`` count.
    """
    if not _is_enabled():
        logger.debug("FILE_DROP_ENABLED is false — skipping process_dropped_file")
        return {"status": "disabled", "path": path}

    file_path = Path(path)
    if not file_path.exists():
        logger.warning("process_dropped_file: file not found: %s", path)
        return {"status": "not_found", "path": path}


    watcher = get_watcher()
    success = watcher.process_file(file_path)
    if success:
        return {"status": "ok", "path": path}
    return {"status": "error", "path": path}


@celery_app.task(name="spec2sphere.tasks.file_drop_tasks.poll_drop_directory")
def poll_drop_directory() -> dict:
    """Scan the drop directory for unprocessed files.

    Intended as a periodic beat task (every 5 minutes) so that files are not
    permanently lost if the watchdog inotify event was missed.

    Returns:
        Dict with ``status`` and ``processed`` count.
    """
    if not _is_enabled():
        logger.debug("FILE_DROP_ENABLED is false — skipping poll_drop_directory")
        return {"status": "disabled", "processed": 0}


    watcher = get_watcher()
    count = watcher.poll()
    logger.info("poll_drop_directory: processed %d file(s)", count)
    return {"status": "ok", "processed": count}
