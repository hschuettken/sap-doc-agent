"""File drop via inotify — Beat poll retired; watchdog fires on events.

These tests cover the plumbing we changed in Task 12:
1. The ``file-drop-poll`` Beat entry is no longer scheduled by default.
2. The watchdog handler emits ``file_dropped`` NOTIFY when a file lands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock



def test_file_drop_poll_not_scheduled_by_default(monkeypatch) -> None:
    """Default env (no FILE_DROP_POLL_ENABLED) should leave the beat entry out."""
    monkeypatch.delenv("FILE_DROP_POLL_ENABLED", raising=False)
    monkeypatch.delenv("FILE_DROP_ENABLED", raising=False)
    import importlib
    import spec2sphere.tasks.schedules as sched

    importlib.reload(sched)
    assert "file-drop-poll" not in sched.BEAT_SCHEDULE


def test_file_drop_poll_re_enabled_via_env(monkeypatch) -> None:
    """FILE_DROP_POLL_ENABLED=true re-adds the 30-min recovery poll."""
    monkeypatch.setenv("FILE_DROP_POLL_ENABLED", "true")
    import importlib
    import spec2sphere.tasks.schedules as sched

    importlib.reload(sched)
    assert "file-drop-poll" in sched.BEAT_SCHEDULE


def test_watchdog_handler_emits_notify_on_file_event(monkeypatch) -> None:
    """Dropping a file → watchdog → NOTIFY(file_dropped) + process_file()."""
    from spec2sphere.scanner.file_drop import _DropHandler

    # Avoid needing a real watchdog install for the type check
    class _FakeCreated:
        def __init__(self, path: str) -> None:
            self.src_path = path

    # Patch watchdog event imports inside the dispatch() function
    import types

    fake_wd_events = types.ModuleType("watchdog.events")
    fake_wd_events.FileCreatedEvent = _FakeCreated  # type: ignore[attr-defined]
    fake_wd_events.FileModifiedEvent = _FakeCreated  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "watchdog.events", fake_wd_events)

    captured: list = []

    async def _fake_emit(channel, payload):
        captured.append((channel, payload))

    monkeypatch.setattr("spec2sphere.dsp_ai.events.emit", _fake_emit)

    watcher = MagicMock()
    # process_file is called synchronously by dispatch — stub it
    watcher.process_file = MagicMock(return_value=True)

    handler = _DropHandler(watcher)

    # Create a real temp file so the `path.is_file()` check passes
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b"x: 1\n")
        tmp_path = f.name

    try:
        handler.dispatch(_FakeCreated(tmp_path))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # process_file called synchronously inside the thread
    watcher.process_file.assert_called_once()
    # NOTIFY was dispatched via asyncio.run (sync context); captured list filled
    assert captured, "Expected NOTIFY emit to have been called"
    assert captured[0][0] == "file_dropped"
    assert captured[0][1]["path"] == tmp_path
