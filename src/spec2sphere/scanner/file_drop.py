"""
File Drop watcher for offline / air-gapped SAP export ingestion.

Watches a directory for dropped files (ABAP source, CDS view, DDL SQL,
ZIP bundles) and dispatches each to the appropriate parser, producing
a ``ScanResult`` that feeds directly into the existing scan pipeline.

Directory layout managed by this module:

    <drop_root>/               # watched for new files
    <drop_root>/processed/<ts>/  # on success
    <drop_root>/errors/        # on failure

Enable with env var ``FILE_DROP_ENABLED=true``.
Configure path with ``FILE_DROP_PATH`` (default: ``/var/spec2sphere/drop``).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from spec2sphere.scanner.models import (
    ObjectType,
    ScanResult,
    ScannedObject,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File-type classification
# ---------------------------------------------------------------------------

_EXT_MAP: dict[str, str] = {
    ".abap": "abap",
    ".ddls": "cds",
    ".sql": "sql",
    ".zip": "zip",
}


def classify_file(path: Path) -> str:
    """Return a file-type label for *path*, or ``'unknown'``.

    Classification order:
    1. Extension mapping (``.abap`` / ``.ddls`` / ``.sql`` / ``.zip``)
    2. Content sniffing (first 256 bytes) for ambiguous ``.txt`` files
    """
    ext = path.suffix.lower()
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]
    # Content sniff for plain-text variants
    try:
        snippet = path.read_bytes()[:256].decode("utf-8", errors="replace").upper()
        if "DEFINE ROOT VIEW" in snippet or "DEFINE VIEW" in snippet:
            return "cds"
        if re.search(r"\bCLASS\b|\bMETHOD\b|\bFUNCTION\b|\bREPORT\b", snippet):
            return "abap"
        if re.search(r"\bSELECT\b|\bCREATE\b|\bINSERT\b", snippet):
            return "sql"
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Parsers — convert dropped files into ScanResult
# ---------------------------------------------------------------------------


def _parse_abap(path: Path) -> ScanResult:
    """Parse a raw ABAP source file."""
    source_code = path.read_text(encoding="utf-8", errors="replace")

    # Infer object type from first keyword
    upper = source_code.upper().lstrip()
    if upper.startswith("CLASS"):
        obj_type = ObjectType.CLASS
    elif upper.startswith("FUNCTION"):
        obj_type = ObjectType.FM
    elif upper.startswith("REPORT"):
        obj_type = ObjectType.OTHER
    else:
        obj_type = ObjectType.OTHER

    obj = ScannedObject(
        object_id=path.stem,
        object_type=obj_type,
        name=path.stem,
        source_code=source_code,
        source_system="file_drop",
        metadata={"file_drop_path": str(path), "original_filename": path.name},
    )
    obj.compute_hash()
    return ScanResult(source_system="file_drop", objects=[obj])


def _parse_cds(path: Path) -> ScanResult:
    """Parse a CDS view definition (.ddls)."""
    source_code = path.read_text(encoding="utf-8", errors="replace")

    # Extract view name from DEFINE [ROOT] VIEW <name>
    match = re.search(r"DEFINE\s+(?:ROOT\s+)?VIEW\s+(\w+)", source_code, re.IGNORECASE)
    name = match.group(1) if match else path.stem

    obj = ScannedObject(
        object_id=name,
        object_type=ObjectType.VIEW,
        name=name,
        source_code=source_code,
        source_system="file_drop",
        metadata={"file_drop_path": str(path), "original_filename": path.name},
    )
    obj.compute_hash()
    return ScanResult(source_system="file_drop", objects=[obj])


def _parse_sql(path: Path) -> ScanResult:
    """Parse a DDL SQL file."""
    source_code = path.read_text(encoding="utf-8", errors="replace")

    # Extract table/view name from CREATE TABLE/VIEW <name>
    match = re.search(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+(\w+)", source_code, re.IGNORECASE)
    name = match.group(1) if match else path.stem

    # Distinguish table vs view
    if re.search(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW", source_code, re.IGNORECASE):
        obj_type = ObjectType.VIEW
    else:
        obj_type = ObjectType.TABLE

    obj = ScannedObject(
        object_id=name,
        object_type=obj_type,
        name=name,
        source_code=source_code,
        source_system="file_drop",
        metadata={"file_drop_path": str(path), "original_filename": path.name},
    )
    obj.compute_hash()
    return ScanResult(source_system="file_drop", objects=[obj])


def _parse_zip(path: Path, tmp_dir: Path) -> list[ScanResult]:
    """Extract a ZIP archive and parse each supported member."""
    results: list[ScanResult] = []
    extract_dir = tmp_dir / path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        zf.extractall(extract_dir)
    for member in extract_dir.rglob("*"):
        if member.is_file():
            file_type = classify_file(member)
            try:
                result = parse_file(member, file_type, tmp_dir)
                if result:
                    results.extend(result)
            except Exception as exc:
                logger.warning("ZIP member %s failed to parse: %s", member, exc)
    return results


def parse_file(path: Path, file_type: str, tmp_dir: Path | None = None) -> list[ScanResult]:
    """Parse *path* according to *file_type*; return list of ScanResult."""
    if file_type == "abap":
        return [_parse_abap(path)]
    if file_type == "cds":
        return [_parse_cds(path)]
    if file_type == "sql":
        return [_parse_sql(path)]
    if file_type == "zip":
        if tmp_dir is None:
            tmp_dir = path.parent / "_tmp"
            tmp_dir.mkdir(exist_ok=True)
        return _parse_zip(path, tmp_dir)
    raise ValueError(f"Unsupported file type: {file_type!r}")


# ---------------------------------------------------------------------------
# Directory management helpers
# ---------------------------------------------------------------------------


def _move_to_processed(path: Path, drop_root: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dir = drop_root / "processed" / ts
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), dest)
    return dest


def _move_to_errors(path: Path, drop_root: Path) -> Path:
    errors_dir = drop_root / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)
    dest = errors_dir / path.name
    shutil.move(str(path), dest)
    return dest


# ---------------------------------------------------------------------------
# FileDropWatcher
# ---------------------------------------------------------------------------


class FileDropWatcher:
    """Watches ``drop_root`` for new files and dispatches them to *on_result*.

    ``on_result`` receives a list of ``ScanResult`` objects produced from the
    dropped file.  The caller is responsible for feeding them into the pipeline
    (e.g. write output, trigger Celery chain).

    Usage::

        def handle(results, source_path):
            ...

        watcher = FileDropWatcher(Path("/var/spec2sphere/drop"), handle)
        watcher.start()   # non-blocking; spawns watchdog observer thread
        ...
        watcher.stop()

    When ``watchdog`` is not installed, :meth:`start` is a no-op and callers
    should rely on :meth:`poll` (used by the Celery beat task).
    """

    def __init__(
        self,
        drop_root: Path,
        on_result: Callable[[list[ScanResult], Path], None] | None = None,
    ) -> None:
        self.drop_root = Path(drop_root)
        self.on_result = on_result
        self._observer = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the watchdog observer (background thread). No-op if watchdog is absent."""
        try:
            from watchdog.events import FileSystemEventHandler  # noqa: PLC0415
            from watchdog.observers import Observer  # noqa: PLC0415
        except ImportError:
            logger.warning(
                "watchdog not installed — FileDropWatcher will not use inotify. "
                "Falling back to poll_drop_directory Celery beat task."
            )
            return

        self.drop_root.mkdir(parents=True, exist_ok=True)

        handler = _DropHandler(self)
        observer = Observer()
        observer.schedule(handler, str(self.drop_root), recursive=False)
        observer.start()
        self._observer = observer
        logger.info("FileDropWatcher started on %s", self.drop_root)

    def stop(self) -> None:
        """Stop the watchdog observer if running."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("FileDropWatcher stopped")

    def process_file(self, path: Path) -> bool:
        """Parse *path*, call on_result, and move to processed/errors.

        Returns ``True`` on success, ``False`` on failure.
        """
        file_type = classify_file(path)
        if file_type == "unknown":
            logger.warning("Skipping unrecognised file: %s", path)
            return False

        logger.info("Processing dropped file: %s (type=%s)", path, file_type)
        try:
            results = parse_file(path, file_type)
            if self.on_result and results:
                self.on_result(results, path)
            _move_to_processed(path, self.drop_root)
            logger.info("Processed %s → %d ScanResult(s)", path.name, len(results))
            return True
        except Exception as exc:
            logger.error("Failed to process %s: %s", path, exc, exc_info=True)
            _move_to_errors(path, self.drop_root)
            return False

    def poll(self) -> int:
        """Scan the drop root for unprocessed files and process them all.

        Returns the number of files processed.
        """
        self.drop_root.mkdir(parents=True, exist_ok=True)
        processed = 0
        for entry in sorted(self.drop_root.iterdir()):
            if entry.is_file() and entry.name not in (".", ".."):
                if self.process_file(entry):
                    processed += 1
        return processed


# ---------------------------------------------------------------------------
# Watchdog event handler (internal)
# ---------------------------------------------------------------------------


class _DropHandler:
    """Watchdog event handler that delegates to FileDropWatcher.process_file."""

    def __init__(self, watcher: FileDropWatcher) -> None:
        self._watcher = watcher

    # watchdog calls dispatch() → on_created / on_modified
    def dispatch(self, event) -> None:  # type: ignore[override]
        from watchdog.events import FileCreatedEvent, FileModifiedEvent  # noqa: PLC0415

        if isinstance(event, (FileCreatedEvent, FileModifiedEvent)):
            path = Path(event.src_path)
            if path.is_file():
                # Publish a NOTIFY for downstream subscribers (e.g. a future
                # Celery file-drop consumer) in addition to processing inline.
                try:
                    import asyncio

                    from spec2sphere.dsp_ai.events import emit

                    async def _pub() -> None:
                        await emit("file_dropped", {"path": str(path)})

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(_pub())
                    except RuntimeError:
                        asyncio.run(_pub())
                except Exception:
                    pass  # best-effort; processing still happens below
                self._watcher.process_file(path)

    # Satisfy watchdog's EventHandler interface (unused but required)
    def on_any_event(self, event) -> None:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Module-level singleton accessed by Celery tasks
# ---------------------------------------------------------------------------

_watcher: FileDropWatcher | None = None


def get_watcher() -> FileDropWatcher:
    """Return the module-level FileDropWatcher singleton, creating it if needed."""
    global _watcher  # noqa: PLW0603
    if _watcher is None:
        drop_path = Path(os.environ.get("FILE_DROP_PATH", "/var/spec2sphere/drop"))
        _watcher = FileDropWatcher(drop_root=drop_path, on_result=_default_on_result)
    return _watcher


def _default_on_result(results: list[ScanResult], source_path: Path) -> None:
    """Default handler: write scan output to the configured output directory."""
    try:
        output_dir = Path(os.environ.get("OUTPUT_DIR", "output")) / "file_drop"
        from spec2sphere.scanner.output import write_scan_output  # noqa: PLC0415

        for result in results:
            write_scan_output(result, output_dir)
    except Exception as exc:
        logger.error("Failed to write scan output for %s: %s", source_path, exc)
