"""Tests for the File Drop ingestion module.

Covers:
- classify_file (extension + content sniff)
- parse_file for each supported type (ABAP, CDS, SQL, ZIP)
- FileDropWatcher.process_file: success path → processed dir, failure path → errors dir
- FileDropWatcher.poll: processes all files in drop root
- Celery tasks (unit): process_dropped_file, poll_drop_directory
- API upload endpoint: enabled / disabled / unsupported extension
"""

from __future__ import annotations

import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# classify_file
# ---------------------------------------------------------------------------


class TestClassifyFile:
    def test_abap_extension(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "ZCL_MY_CLASS.abap"
        f.write_text("CLASS zcl_my_class DEFINITION.\nENDCLASS.")
        assert classify_file(f) == "abap"

    def test_ddls_extension(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "ZV_MY_VIEW.ddls"
        f.write_text("DEFINE VIEW ZV_MY_VIEW AS SELECT FROM ztable { * };")
        assert classify_file(f) == "cds"

    def test_sql_extension(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "create_table.sql"
        f.write_text("CREATE TABLE my_table (id INT);")
        assert classify_file(f) == "sql"

    def test_zip_extension(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "export.zip"
        f.write_bytes(b"PK\x03\x04")  # minimal ZIP magic
        assert classify_file(f) == "zip"

    def test_unknown_extension(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "notes.txt"
        f.write_text("just some text")
        assert classify_file(f) == "unknown"

    def test_content_sniff_cds(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "view.txt"
        f.write_text("DEFINE ROOT VIEW ZV_FOO AS SELECT FROM ztbl { * };")
        assert classify_file(f) == "cds"

    def test_content_sniff_abap(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "prog.txt"
        f.write_text("REPORT z_my_report.\nWRITE: 'hello'.")
        assert classify_file(f) == "abap"

    def test_content_sniff_sql(self, tmp_path):
        from spec2sphere.scanner.file_drop import classify_file

        f = tmp_path / "ddl.txt"
        f.write_text("SELECT id FROM orders WHERE id = 1;")
        assert classify_file(f) == "sql"


# ---------------------------------------------------------------------------
# parse_file — ABAP
# ---------------------------------------------------------------------------


class TestParseAbap:
    def test_basic(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file
        from spec2sphere.scanner.models import ObjectType

        f = tmp_path / "ZCL_DEMO.abap"
        f.write_text("CLASS zcl_demo DEFINITION PUBLIC FINAL.\nENDCLASS.")
        results = parse_file(f, "abap")
        assert len(results) == 1
        assert len(results[0].objects) == 1
        obj = results[0].objects[0]
        assert obj.object_id == "ZCL_DEMO"
        assert obj.object_type == ObjectType.CLASS
        assert obj.source_system == "file_drop"
        assert obj.content_hash is not None

    def test_function_module(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file
        from spec2sphere.scanner.models import ObjectType

        f = tmp_path / "Z_MY_FM.abap"
        f.write_text("FUNCTION z_my_fm.\n*\nENDFUNCTION.")
        results = parse_file(f, "abap")
        assert results[0].objects[0].object_type == ObjectType.FM


# ---------------------------------------------------------------------------
# parse_file — CDS
# ---------------------------------------------------------------------------


class TestParseCds:
    def test_basic(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file
        from spec2sphere.scanner.models import ObjectType

        f = tmp_path / "ZV_SALES.ddls"
        f.write_text("DEFINE ROOT VIEW ZV_SALES AS SELECT FROM ztable { ztable.id };\n")
        results = parse_file(f, "cds")
        assert len(results) == 1
        obj = results[0].objects[0]
        assert obj.object_id == "ZV_SALES"
        assert obj.name == "ZV_SALES"
        assert obj.object_type == ObjectType.VIEW

    def test_name_fallback_to_stem(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file

        f = tmp_path / "MY_CDS.ddls"
        f.write_text("-- some comment\n")  # no DEFINE VIEW line
        results = parse_file(f, "cds")
        assert results[0].objects[0].object_id == "MY_CDS"


# ---------------------------------------------------------------------------
# parse_file — SQL
# ---------------------------------------------------------------------------


class TestParseSql:
    def test_table(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file
        from spec2sphere.scanner.models import ObjectType

        f = tmp_path / "orders.sql"
        f.write_text("CREATE TABLE orders (id INT PRIMARY KEY);")
        results = parse_file(f, "sql")
        obj = results[0].objects[0]
        assert obj.object_type == ObjectType.TABLE
        assert obj.object_id == "orders"

    def test_view(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file
        from spec2sphere.scanner.models import ObjectType

        f = tmp_path / "v_orders.sql"
        f.write_text("CREATE OR REPLACE VIEW v_orders AS SELECT * FROM orders;")
        results = parse_file(f, "sql")
        assert results[0].objects[0].object_type == ObjectType.VIEW


# ---------------------------------------------------------------------------
# parse_file — ZIP
# ---------------------------------------------------------------------------


class TestParseZip:
    def test_zip_with_abap(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file

        # Build a real ZIP containing one ABAP file
        abap_content = "CLASS zcl_in_zip DEFINITION.\nENDCLASS."
        zip_path = tmp_path / "bundle.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("ZCL_IN_ZIP.abap", abap_content)

        results = parse_file(zip_path, "zip", tmp_dir=tmp_path)
        assert len(results) >= 1
        obj_ids = [r.objects[0].object_id for r in results if r.objects]
        assert "ZCL_IN_ZIP" in obj_ids

    def test_zip_skips_unknown_members(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file

        zip_path = tmp_path / "mixed.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "just text")  # no recognisable content
            zf.writestr("ZV_FOO.ddls", "DEFINE VIEW ZV_FOO AS SELECT FROM t { * };")

        results = parse_file(zip_path, "zip", tmp_dir=tmp_path)
        # At least the ddls should be parsed; txt with unknown content may return 0
        view_results = [r for r in results if r.objects and r.objects[0].object_id == "ZV_FOO"]
        assert len(view_results) == 1

    def test_unsupported_type_raises(self, tmp_path):
        from spec2sphere.scanner.file_drop import parse_file

        f = tmp_path / "file.bin"
        f.write_bytes(b"\x00\x01\x02")
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_file(f, "binary")


# ---------------------------------------------------------------------------
# FileDropWatcher — process_file
# ---------------------------------------------------------------------------


class TestFileDropWatcherProcessFile:
    def test_success_moves_to_processed(self, tmp_path):
        from spec2sphere.scanner.file_drop import FileDropWatcher

        drop_root = tmp_path / "drop"
        drop_root.mkdir()
        f = drop_root / "ZCL_OK.abap"
        f.write_text("CLASS zcl_ok DEFINITION.\nENDCLASS.")

        received: list = []
        watcher = FileDropWatcher(drop_root, on_result=lambda results, path: received.extend(results))

        result = watcher.process_file(f)

        assert result is True
        # Original file must be gone
        assert not f.exists()
        # Must land in processed/<ts>/
        processed_files = list((drop_root / "processed").rglob("ZCL_OK.abap"))
        assert len(processed_files) == 1
        # on_result was called
        assert len(received) >= 1

    def test_failure_moves_to_errors(self, tmp_path):
        from spec2sphere.scanner.file_drop import FileDropWatcher

        drop_root = tmp_path / "drop"
        drop_root.mkdir()
        f = drop_root / "bad.abap"
        f.write_text("REPORT bad.")

        def boom(results, path):
            raise RuntimeError("pipeline exploded")

        watcher = FileDropWatcher(drop_root, on_result=boom)

        result = watcher.process_file(f)

        assert result is False
        assert not f.exists()
        assert (drop_root / "errors" / "bad.abap").exists()

    def test_unknown_file_type_returns_false(self, tmp_path):
        from spec2sphere.scanner.file_drop import FileDropWatcher

        drop_root = tmp_path / "drop"
        drop_root.mkdir()
        f = drop_root / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")

        watcher = FileDropWatcher(drop_root)
        result = watcher.process_file(f)
        assert result is False

    def test_on_result_called_with_parsed_objects(self, tmp_path):
        from spec2sphere.scanner.file_drop import FileDropWatcher

        drop_root = tmp_path / "drop"
        drop_root.mkdir()
        f = drop_root / "ZV_TEST.ddls"
        f.write_text("DEFINE VIEW ZV_TEST AS SELECT FROM ztbl { * };")

        captured = MagicMock()
        watcher = FileDropWatcher(drop_root, on_result=captured)
        watcher.process_file(f)

        captured.assert_called_once()
        scan_results, source_path = captured.call_args[0]
        assert len(scan_results) >= 1
        assert scan_results[0].objects[0].object_id == "ZV_TEST"


# ---------------------------------------------------------------------------
# FileDropWatcher — poll
# ---------------------------------------------------------------------------


class TestFileDropWatcherPoll:
    def test_poll_processes_all_files(self, tmp_path):
        from spec2sphere.scanner.file_drop import FileDropWatcher

        drop_root = tmp_path / "drop"
        drop_root.mkdir()
        (drop_root / "A.abap").write_text("REPORT a.")
        (drop_root / "B.abap").write_text("REPORT b.")
        (drop_root / "C.ddls").write_text("DEFINE VIEW ZV_C AS SELECT FROM t { * };")

        processed_names: list[str] = []

        def capture(results, path):
            processed_names.append(path.name)

        watcher = FileDropWatcher(drop_root, on_result=capture)
        count = watcher.poll()

        assert count == 3
        assert set(processed_names) == {"A.abap", "B.abap", "C.ddls"}

    def test_poll_creates_drop_root_if_missing(self, tmp_path):
        from spec2sphere.scanner.file_drop import FileDropWatcher

        drop_root = tmp_path / "nonexistent_drop"
        assert not drop_root.exists()

        watcher = FileDropWatcher(drop_root)
        count = watcher.poll()

        assert count == 0
        assert drop_root.exists()

    def test_poll_skips_subdirectories(self, tmp_path):
        from spec2sphere.scanner.file_drop import FileDropWatcher

        drop_root = tmp_path / "drop"
        drop_root.mkdir()
        # Add a file and a subdirectory
        (drop_root / "Z.abap").write_text("REPORT z.")
        (drop_root / "processed").mkdir()

        watcher = FileDropWatcher(drop_root)
        count = watcher.poll()

        assert count == 1  # only the file, not the directory


# ---------------------------------------------------------------------------
# Celery tasks (unit — mock watcher)
# ---------------------------------------------------------------------------


class TestFiledropTasks:
    def test_process_dropped_file_disabled(self, tmp_path):
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "false"}):
            from spec2sphere.tasks.file_drop_tasks import process_dropped_file

            result = process_dropped_file(str(tmp_path / "fake.abap"))
            assert result["status"] == "disabled"

    def test_process_dropped_file_not_found(self, tmp_path):
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "true"}):
            # Re-import to pick up env change
            import importlib

            import spec2sphere.tasks.file_drop_tasks as m

            importlib.reload(m)

            result = m.process_dropped_file(str(tmp_path / "missing.abap"))
            assert result["status"] == "not_found"

    def test_process_dropped_file_success(self, tmp_path):
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "true", "FILE_DROP_PATH": str(tmp_path / "drop")}):
            f = tmp_path / "ZCL_TASK.abap"
            f.write_text("CLASS zcl_task DEFINITION.\nENDCLASS.")

            from spec2sphere.tasks import file_drop_tasks as m

            with patch.object(m, "get_watcher") as mock_gw:
                mock_watcher = MagicMock()
                mock_watcher.process_file.return_value = True
                mock_gw.return_value = mock_watcher

                result = m.process_dropped_file(str(f))

            assert result["status"] == "ok"
            mock_watcher.process_file.assert_called_once_with(f)

    def test_poll_drop_directory_disabled(self):
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "false"}):
            from spec2sphere.tasks.file_drop_tasks import poll_drop_directory

            result = poll_drop_directory()
            assert result["status"] == "disabled"

    def test_poll_drop_directory_enabled(self, tmp_path):
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "true", "FILE_DROP_PATH": str(tmp_path / "drop")}):
            from spec2sphere.tasks import file_drop_tasks as m

            with patch.object(m, "get_watcher") as mock_gw:
                mock_watcher = MagicMock()
                mock_watcher.poll.return_value = 3
                mock_gw.return_value = mock_watcher

                result = m.poll_drop_directory()

            assert result["status"] == "ok"
            assert result["processed"] == 3


# ---------------------------------------------------------------------------
# API upload endpoint
# ---------------------------------------------------------------------------


def _build_test_app():
    """Build a minimal FastAPI app with the ingest router mounted."""
    from fastapi import FastAPI

    from spec2sphere.web.ingest_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


class TestIngestUploadEndpoint:
    def test_disabled_returns_404(self, tmp_path):
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "false"}):
            app = _build_test_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/ingest/upload",
                files={"file": ("test.abap", b"REPORT x.", "text/plain")},
            )
            assert resp.status_code == 404

    def test_unsupported_extension_returns_422(self, tmp_path):
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "true", "FILE_DROP_PATH": str(tmp_path)}):
            app = _build_test_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/ingest/upload",
                files={"file": ("image.png", b"\x89PNG", "image/png")},
            )
            assert resp.status_code == 422

    def test_abap_upload_accepted(self, tmp_path):
        drop_dir = tmp_path / "drop"
        drop_dir.mkdir()
        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "true", "FILE_DROP_PATH": str(drop_dir)}):
            # The task is imported inside the endpoint function, patch at its real location
            with patch("spec2sphere.tasks.file_drop_tasks.process_dropped_file") as mock_task:
                mock_task.delay.return_value = MagicMock(id="task-abc-123")
                app = _build_test_app()
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/ingest/upload",
                    files={"file": ("ZCL_UPLOAD.abap", b"CLASS zcl_upload DEFINITION.\nENDCLASS.", "text/plain")},
                )
            assert resp.status_code == 202
            body = resp.json()
            assert body["status"] == "queued"
            assert body["filename"] == "ZCL_UPLOAD.abap"
            assert "path" in body
            # File must be written to drop dir
            assert (drop_dir / "ZCL_UPLOAD.abap").exists()

    def test_zip_upload_accepted(self, tmp_path):
        import io

        drop_dir = tmp_path / "drop"
        drop_dir.mkdir()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ZCL_INNER.abap", "CLASS zcl_inner DEFINITION.\nENDCLASS.")
        zip_bytes = buf.getvalue()

        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "true", "FILE_DROP_PATH": str(drop_dir)}):
            with patch("spec2sphere.tasks.file_drop_tasks.process_dropped_file") as mock_task:
                mock_task.delay.return_value = MagicMock(id="task-zip-999")
                app = _build_test_app()
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/ingest/upload",
                    files={"file": ("bundle.zip", zip_bytes, "application/zip")},
                )
            assert resp.status_code == 202
            assert resp.json()["filename"] == "bundle.zip"

    def test_duplicate_filename_gets_counter_suffix(self, tmp_path):
        drop_dir = tmp_path / "drop"
        drop_dir.mkdir()
        # Pre-create the target file to trigger counter logic
        (drop_dir / "ZCL_DUP.abap").write_text("existing")

        with patch.dict("os.environ", {"FILE_DROP_ENABLED": "true", "FILE_DROP_PATH": str(drop_dir)}):
            with patch("spec2sphere.tasks.file_drop_tasks.process_dropped_file") as mock_task:
                mock_task.delay.return_value = MagicMock(id="task-dup")
                app = _build_test_app()
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/ingest/upload",
                    files={"file": ("ZCL_DUP.abap", b"CLASS zcl_dup DEFINITION.\nENDCLASS.", "text/plain")},
                )
            assert resp.status_code == 202
            body = resp.json()
            # Filename should have been renamed to avoid clobbering
            assert body["filename"] != "ZCL_DUP.abap"
            assert "ZCL_DUP" in body["filename"]
