"""WebSocket proxy that streams tmux pane output to the browser in real-time.

Polls tmux capture-pane every 200ms and sends new lines as text frames.
Also accepts input from the browser for future interactive use.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from spec2sphere.agent_terminal.manager import get_manager

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.2  # seconds between tmux capture-pane polls
_MAX_IDLE = 120  # seconds of no activity before giving up on a dead session


async def stream_terminal(websocket: WebSocket, session_id: str) -> None:
    """Stream tmux output to the WebSocket client.

    Sends text frames with the latest terminal content. Keeps an internal
    buffer of what has already been sent to avoid re-sending unchanged lines.
    Cleanly disconnects when the session ends or the client disconnects.
    """
    await websocket.accept()

    manager = get_manager()
    session = manager.get_session(session_id)

    if not session:
        await websocket.send_text(f"\r\n\x1b[31mSession '{session_id}' not found.\x1b[0m\r\n")
        await websocket.close()
        return

    await websocket.send_text(
        f"\x1b[36m=== {session.name} ===\x1b[0m\r\n"
        f"\x1b[90mCommand: {session.command}\x1b[0m\r\n"
        f"\x1b[90mStatus:  {session.status}\x1b[0m\r\n\r\n"
    )

    last_output: Optional[str] = None
    idle_ticks = 0
    max_idle_ticks = int(_MAX_IDLE / _POLL_INTERVAL)

    # We run two concurrent tasks: one reads tmux, the other drains incoming
    # WebSocket messages (so the client connection doesn't buffer up).
    receive_queue: asyncio.Queue[str] = asyncio.Queue()

    async def _receive_loop() -> None:
        """Drain incoming WebSocket frames into the queue (ignore for now)."""
        try:
            while True:
                data = await websocket.receive_text()
                await receive_queue.put(data)
        except (WebSocketDisconnect, Exception):
            pass

    receive_task = asyncio.create_task(_receive_loop())

    try:
        while True:
            await asyncio.sleep(_POLL_INTERVAL)

            # Re-fetch session to pick up status changes
            session = manager.get_session(session_id)
            if not session:
                await websocket.send_text("\r\n\x1b[31mSession disappeared.\x1b[0m\r\n")
                break

            output = manager.read_output(session_id, lines=500)

            if output == last_output:
                idle_ticks += 1
                if idle_ticks >= max_idle_ticks and session.status != "running":
                    # Session is done and no new output — disconnect
                    break
            else:
                idle_ticks = 0

                if last_output is None:
                    # First read — send everything
                    chunk = output
                else:
                    # Send only new lines appended since last read.
                    # Simple heuristic: if the new output starts with the old
                    # output, send only the tail. Otherwise send the full diff.
                    if output.startswith(last_output):
                        chunk = output[len(last_output) :]
                    else:
                        # Screen was cleared or output rolled; resend all
                        chunk = "\x1b[2J\x1b[H" + output  # clear screen + home cursor

                if chunk:
                    # Convert bare \n to \r\n for terminal emulators
                    chunk = chunk.replace("\r\n", "\n").replace("\n", "\r\n")
                    try:
                        await websocket.send_text(chunk)
                    except WebSocketDisconnect:
                        break

                last_output = output

            # If the session has finished, send a final status line and stop
            if session.status in ("completed", "failed") and idle_ticks > 2:
                colour = "\x1b[32m" if session.status == "completed" else "\x1b[31m"
                await websocket.send_text(f"\r\n{colour}--- Session {session.status} ---\x1b[0m\r\n")
                break

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for session %s", session_id)
    except Exception as exc:
        logger.warning("ws_proxy error for session %s: %s", session_id, exc)
    finally:
        receive_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
