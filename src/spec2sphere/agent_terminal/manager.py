"""Agent session manager.

Manages tmux sessions for AI agent tasks, tracks status, and provides output
capture. Sessions are stored in-memory with optional JSON persistence.
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SESSIONS_FILE = Path("/app/output/agent_sessions.json")
_TMUX_PREFIX = "s2s-agent-"


def _run_tmux(*args: str, timeout: int = 5) -> subprocess.CompletedProcess:
    """Run a tmux command with a short timeout. Returns CompletedProcess."""
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _tmux_available() -> bool:
    """Check if tmux is available on the system."""
    try:
        result = subprocess.run(
            ["tmux", "-V"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@dataclass
class AgentSession:
    """Represents a single agent task session backed by a tmux pane."""

    id: str
    name: str
    description: str
    command: str
    tmux_session_name: str
    status: str = "running"  # running | completed | failed
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "command": self.command,
            "tmux_session_name": self.tmux_session_name,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentSession":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d.get("description", ""),
            command=d.get("command", ""),
            tmux_session_name=d["tmux_session_name"],
            status=d.get("status", "running"),
            created_at=d.get("created_at", datetime.utcnow().isoformat()),
            completed_at=d.get("completed_at"),
        )


class AgentSessionManager:
    """Singleton that manages agent tmux sessions.

    If tmux is not available (e.g., minimal container) the manager degrades
    gracefully: sessions are created in-memory as 'failed' with a clear error
    message, no crash.
    """

    _instance: Optional["AgentSessionManager"] = None

    def __new__(cls) -> "AgentSessionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: dict[str, AgentSession] = {}
            cls._instance._tmux_ok: Optional[bool] = None
            cls._instance._load_persisted()
        return cls._instance

    # ── tmux availability ──────────────────────────────────────────────────

    def _check_tmux(self) -> bool:
        if self._tmux_ok is None:
            self._tmux_ok = _tmux_available()
            if not self._tmux_ok:
                logger.warning("tmux not found — agent terminal sessions will not execute commands")
        return self._tmux_ok

    # ── persistence ────────────────────────────────────────────────────────

    def _load_persisted(self) -> None:
        """Load sessions from JSON file on startup (best-effort)."""
        try:
            if _SESSIONS_FILE.exists():
                raw = json.loads(_SESSIONS_FILE.read_text())
                for d in raw:
                    s = AgentSession.from_dict(d)
                    self._sessions[s.id] = s
                logger.info("Loaded %d persisted agent sessions", len(self._sessions))
        except Exception as exc:
            logger.warning("Could not load persisted agent sessions: %s", exc)

    def _persist(self) -> None:
        """Persist sessions to JSON file (best-effort)."""
        try:
            _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = [s.to_dict() for s in self._sessions.values()]
            _SESSIONS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.debug("Could not persist agent sessions: %s", exc)

    # ── public API ─────────────────────────────────────────────────────────

    def create_session(self, name: str, description: str, command: str) -> AgentSession:
        """Create a new tmux session and run the command in it.

        Returns the AgentSession immediately (status='running').
        If tmux is not available the session is stored with status='failed'.
        """
        session_id = str(uuid.uuid4())
        tmux_name = f"{_TMUX_PREFIX}{session_id[:8]}"

        session = AgentSession(
            id=session_id,
            name=name,
            description=description,
            command=command,
            tmux_session_name=tmux_name,
        )

        if not self._check_tmux():
            session.status = "failed"
            session.completed_at = datetime.utcnow().isoformat()
            self._sessions[session_id] = session
            self._persist()
            logger.warning("tmux unavailable — session %s created as failed", session_id)
            return session

        try:
            # Create a new detached tmux session with the command.
            # The command is wrapped so the pane stays open after completion,
            # allowing output capture even after the process exits.
            wrapped = f"{command}; echo '--- session ended (exit $?) ---'"
            result = _run_tmux(
                "new-session",
                "-d",  # detached
                "-s",
                tmux_name,  # session name
                "-x",
                "220",  # wide enough for most output
                "-y",
                "50",
                wrapped,
            )
            if result.returncode != 0:
                logger.warning("tmux new-session failed for %s: %s", tmux_name, result.stderr.strip())
                session.status = "failed"
                session.completed_at = datetime.utcnow().isoformat()
            else:
                logger.info("Started agent session %s (tmux: %s)", session_id, tmux_name)
        except subprocess.TimeoutExpired:
            logger.warning("Timeout creating tmux session %s", tmux_name)
            session.status = "failed"
            session.completed_at = datetime.utcnow().isoformat()
        except Exception as exc:
            logger.error("Error creating tmux session %s: %s", tmux_name, exc)
            session.status = "failed"
            session.completed_at = datetime.utcnow().isoformat()

        self._sessions[session_id] = session
        self._persist()
        return session

    def list_sessions(self) -> list[AgentSession]:
        """Return all sessions, refreshing status for running ones."""
        for session in list(self._sessions.values()):
            if session.status == "running":
                self._refresh_status(session)
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Get a session by ID, refreshing its status if running."""
        session = self._sessions.get(session_id)
        if session and session.status == "running":
            self._refresh_status(session)
        return session

    def kill_session(self, session_id: str) -> bool:
        """Kill the tmux session and mark as completed. Returns True on success."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        if self._check_tmux() and session.status == "running":
            try:
                _run_tmux("kill-session", "-t", session.tmux_session_name)
            except Exception as exc:
                logger.warning("Error killing tmux session %s: %s", session.tmux_session_name, exc)

        session.status = "completed"
        session.completed_at = datetime.utcnow().isoformat()
        self._persist()
        return True

    def read_output(self, session_id: str, lines: int = 100) -> str:
        """Read the last N lines of output from the tmux pane.

        Returns an empty string if the session doesn't exist or tmux is unavailable.
        """
        session = self._sessions.get(session_id)
        if not session:
            return ""
        if not self._check_tmux():
            return "(tmux not available)"

        try:
            result = _run_tmux(
                "capture-pane",
                "-t",
                session.tmux_session_name,
                "-p",  # print to stdout
                "-S",
                f"-{lines}",  # start N lines back
            )
            if result.returncode != 0:
                return f"(session not found or ended)\n{result.stderr.strip()}"
            return result.stdout
        except subprocess.TimeoutExpired:
            return "(timeout reading tmux output)"
        except Exception as exc:
            logger.debug("read_output error for %s: %s", session_id, exc)
            return f"(error: {exc})"

    def is_session_alive(self, session_id: str) -> bool:
        """Return True if the tmux session still exists."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        if not self._check_tmux():
            return False

        try:
            result = _run_tmux("has-session", "-t", session.tmux_session_name)
            return result.returncode == 0
        except Exception:
            return False

    # ── internal ───────────────────────────────────────────────────────────

    def _refresh_status(self, session: AgentSession) -> None:
        """Update session status based on whether tmux session still exists."""
        if not self.is_session_alive(session.id):
            session.status = "completed"
            if not session.completed_at:
                session.completed_at = datetime.utcnow().isoformat()
            self._persist()


# Module-level singleton accessor
def get_manager() -> AgentSessionManager:
    """Return the global AgentSessionManager instance."""
    return AgentSessionManager()
