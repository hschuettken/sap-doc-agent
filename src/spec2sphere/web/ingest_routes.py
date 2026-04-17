"""
File-drop ingest API routes.

Provides ``POST /api/ingest/upload`` for accepting single-file uploads that
behave identically to a filesystem drop — the file is written to the drop
directory and a Celery task is queued to process it.

The router is only registered when ``FILE_DROP_ENABLED=true``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])

_SUPPORTED_EXTENSIONS = {".abap", ".ddls", ".sql", ".zip"}


@router.post("/api/ingest/upload", summary="Upload a file for file-drop ingestion")
async def upload_file(file: UploadFile) -> JSONResponse:
    """Accept a single file upload and queue it for processing.

    Only enabled when ``FILE_DROP_ENABLED=true``.  Mimics the behaviour of
    dropping a file on the watched directory:

    1. Writes the uploaded file to ``FILE_DROP_PATH``.
    2. Queues ``process_dropped_file`` Celery task.
    3. Returns ``202 Accepted`` with the queued path.

    Supported file types: ``.abap``, ``.ddls``, ``.sql``, ``.zip``
    """
    if os.environ.get("FILE_DROP_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="File drop ingestion is not enabled")

    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type {suffix!r}. Supported: {sorted(_SUPPORTED_EXTENSIONS)}",
        )

    drop_path = Path(os.environ.get("FILE_DROP_PATH", "/var/spec2sphere/drop"))
    drop_path.mkdir(parents=True, exist_ok=True)

    dest = drop_path / filename
    # Avoid clobbering existing files by appending a counter
    if dest.exists():
        base = dest.stem
        counter = 1
        while dest.exists():
            dest = drop_path / f"{base}_{counter}{suffix}"
            counter += 1

    content = await file.read()
    dest.write_bytes(content)
    logger.info("Uploaded file written to drop dir: %s (%d bytes)", dest, len(content))

    # Queue Celery task (best-effort — if Celery is unavailable, file still lands in drop dir)
    task_id: str | None = None
    try:
        from spec2sphere.tasks.file_drop_tasks import process_dropped_file  # noqa: PLC0415

        result = process_dropped_file.delay(str(dest))
        task_id = result.id
    except Exception as exc:
        logger.warning("Failed to queue process_dropped_file task: %s — file will be picked up by poll", exc)

    return JSONResponse(
        status_code=202,
        content={
            "status": "queued",
            "path": str(dest),
            "filename": dest.name,
            "task_id": task_id,
            "message": "File queued for processing. Track status via /scan/status.",
        },
    )
