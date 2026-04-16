"""Tests for the agent terminal module.

Covers:
- terminal_routes.py HTTP endpoints
- manager.py AgentSessionManager unit behaviour
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from spec2sphere.web.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_manager_singleton():
    """Reset the AgentSessionManager singleton before every test.

    The manager is a module-level singleton.  Without a reset, a session
    created in one test leaks into the next.
    """
    from spec2sphere.agent_terminal import manager as mgr_mod

    mgr_mod.AgentSessionManager._instance = None
    yield
    mgr_mod.AgentSessionManager._instance = None


@pytest.fixture
def output_dir(tmp_path):
    """Minimal output directory with graph.json so create_app is happy."""
    graph = {
        "nodes": [
            {"id": "SPACE.OBJ1", "name": "OBJ1", "type": "view", "layer": "harmonized", "source_system": "DSP"},
        ],
        "edges": [],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    obj_dir = tmp_path / "objects" / "view"
    obj_dir.mkdir(parents=True)
    (obj_dir / "SPACE.OBJ1.md").write_text("---\nobject_id: SPACE.OBJ1\nname: OBJ1\n---\n# OBJ1\nA test view.")
    (tmp_path / "reports").mkdir()
    return tmp_path


@pytest.fixture
def authed_client(output_dir):
    """TestClient authenticated via the session-cookie login flow."""
    from spec2sphere.web.auth import hash_password

    pw_hash = hash_password("testpass")
    os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = pw_hash
    os.environ["SAP_DOC_AGENT_SECRET_KEY"] = "test-secret"
    app = create_app(output_dir=str(output_dir))
    c = TestClient(app, follow_redirects=True)
    c.post("/ui/login", data={"password": "testpass"}, follow_redirects=False)
    return c


@pytest.fixture
def client(output_dir):
    """Unauthenticated TestClient (sufficient for /api/* routes)."""
    app = create_app(output_dir=str(output_dir))
    return TestClient(app)


# ---------------------------------------------------------------------------
# HTTP route tests
# ---------------------------------------------------------------------------


def test_terminal_page_renders(authed_client):
    """GET /ui/agent-terminal returns 200 with expected page content."""
    resp = authed_client.get("/ui/agent-terminal")
    assert resp.status_code == 200
    assert "Agent Sessions" in resp.text


def test_list_sessions_empty(client):
    """GET /api/agent-terminal/sessions returns 200 with an empty list initially."""
    resp = client.get("/api/agent-terminal/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_create_session(client):
    """POST /api/agent-terminal/sessions creates a session.

    If tmux is available the session is 'running'; if not it is 'failed'.
    Either way we get a 201 with the expected fields.
    """
    resp = client.post(
        "/api/agent-terminal/sessions",
        json={"name": "test-session", "description": "Unit test session", "command": "echo hello"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-session"
    assert data["command"] == "echo hello"
    assert "id" in data
    assert data["status"] in ("running", "failed", "completed")


def test_create_session_missing_name(client):
    """POST /api/agent-terminal/sessions with no name returns 400."""
    resp = client.post(
        "/api/agent-terminal/sessions",
        json={"description": "oops", "command": "echo hi"},
    )
    assert resp.status_code == 400
    assert "name" in resp.json().get("error", "").lower()


def test_create_session_missing_command(client):
    """POST /api/agent-terminal/sessions with no command returns 400."""
    resp = client.post(
        "/api/agent-terminal/sessions",
        json={"name": "no-cmd"},
    )
    assert resp.status_code == 400
    assert "command" in resp.json().get("error", "").lower()


def test_get_session_not_found(client):
    """GET /api/agent-terminal/sessions/{id} with unknown id returns 404."""
    resp = client.get("/api/agent-terminal/sessions/nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.json().get("error", "").lower()


def test_delete_session_not_found(client):
    """DELETE /api/agent-terminal/sessions/{id} with unknown id returns 404."""
    resp = client.delete("/api/agent-terminal/sessions/nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.json().get("error", "").lower()


def test_session_output_not_found(client):
    """GET /api/agent-terminal/sessions/{id}/output with unknown id returns 404."""
    resp = client.get("/api/agent-terminal/sessions/nonexistent/output")
    assert resp.status_code == 404
    assert "not found" in resp.json().get("error", "").lower()


def test_list_sessions_reflects_created(client):
    """After creating a session it appears in the list."""
    client.post(
        "/api/agent-terminal/sessions",
        json={"name": "list-test", "command": "true"},
    )
    resp = client.get("/api/agent-terminal/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "list-test"


def test_get_session_returns_created(client):
    """After creating a session it can be retrieved by ID."""
    create_resp = client.post(
        "/api/agent-terminal/sessions",
        json={"name": "get-test", "command": "pwd"},
    )
    session_id = create_resp.json()["id"]

    resp = client.get(f"/api/agent-terminal/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == session_id


def test_delete_session_marks_completed(client):
    """Killing an existing session returns 200 and status 'killed'."""
    create_resp = client.post(
        "/api/agent-terminal/sessions",
        json={"name": "kill-test", "command": "sleep 60"},
    )
    session_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/agent-terminal/sessions/{session_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "killed"

    # Session should still be retrievable (just marked completed)
    get_resp = client.get(f"/api/agent-terminal/sessions/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "completed"


def test_session_output_returns_string(client):
    """GET /output for an existing session returns a string (possibly empty)."""
    create_resp = client.post(
        "/api/agent-terminal/sessions",
        json={"name": "output-test", "command": "echo hello-world"},
    )
    session_id = create_resp.json()["id"]

    resp = client.get(f"/api/agent-terminal/sessions/{session_id}/output")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    assert isinstance(data["output"], str)
    assert "lines" in data


# ---------------------------------------------------------------------------
# Unit tests for AgentSessionManager
# ---------------------------------------------------------------------------


def test_manager_check_tmux():
    """_check_tmux() returns a bool without raising."""
    from spec2sphere.agent_terminal.manager import AgentSessionManager

    manager = AgentSessionManager()
    result = manager._check_tmux()
    assert isinstance(result, bool)


def test_manager_create_without_tmux(monkeypatch):
    """When tmux is unavailable create_session returns a failed session (no crash)."""
    from spec2sphere.agent_terminal import manager as mgr_mod

    # Force tmux to be unavailable
    monkeypatch.setattr(mgr_mod, "_tmux_available", lambda: False)

    # Reset singleton so the patched _tmux_available takes effect
    mgr_mod.AgentSessionManager._instance = None

    manager = mgr_mod.AgentSessionManager()
    session = manager.create_session(name="no-tmux", description="test", command="echo hi")

    assert session.status == "failed"
    assert session.completed_at is not None
    assert session.name == "no-tmux"


def test_manager_list_empty():
    """Fresh manager returns empty list from list_sessions()."""
    from spec2sphere.agent_terminal.manager import AgentSessionManager

    manager = AgentSessionManager()
    sessions = manager.list_sessions()
    assert sessions == []


def test_manager_session_dataclass():
    """AgentSession fields have the correct types."""
    from spec2sphere.agent_terminal.manager import AgentSession

    s = AgentSession(
        id="abc-123",
        name="my-session",
        description="A description",
        command="echo test",
        tmux_session_name="s2s-agent-abc123",
        status="running",
    )
    assert isinstance(s.id, str)
    assert isinstance(s.name, str)
    assert isinstance(s.description, str)
    assert isinstance(s.command, str)
    assert isinstance(s.tmux_session_name, str)
    assert isinstance(s.status, str)
    assert isinstance(s.created_at, str)
    assert s.completed_at is None

    d = s.to_dict()
    assert d["id"] == "abc-123"
    assert d["name"] == "my-session"
    assert d["status"] == "running"
    assert d["completed_at"] is None


def test_manager_session_roundtrip():
    """AgentSession.to_dict / from_dict roundtrip preserves all fields."""
    from spec2sphere.agent_terminal.manager import AgentSession

    s = AgentSession(
        id="xyz",
        name="rt-test",
        description="roundtrip",
        command="ls",
        tmux_session_name="s2s-agent-xyz",
        status="completed",
        completed_at="2024-01-01T00:00:00",
    )
    d = s.to_dict()
    s2 = AgentSession.from_dict(d)
    assert s2.id == s.id
    assert s2.name == s.name
    assert s2.status == s.status
    assert s2.completed_at == s.completed_at
