"""WebSocket transport route for live Web UI sessions.

The browser connects to ``/api/ws/{session_id}`` after creating a session
via ``POST /api/sessions``. Without this route, every connection ends with
close code 1006 ("abnormal closure") and the SPA shows an error banner.

The handler validates the token from the ``oh_token`` cookie, looks up the
:class:`SessionEntry` registered by ``SessionManager``, and pumps frames
between the browser and the per-session :class:`WebSocketBackendHost`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from openharness.webui.server.auth import check_ws_token
from openharness.webui.server.config import WebUIConfig
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import WebUIState

log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/api/ws/{session_id}")
async def websocket_session(ws: WebSocket, session_id: str) -> None:
    """Attach a browser WebSocket to an existing Web UI session."""
    state: WebUIState | None = getattr(ws.app.state, "webui", None)
    manager: SessionManager | None = getattr(ws.app.state, "webui_session_manager", None)
    if state is None or manager is None:  # pragma: no cover - app misconfiguration
        await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    auth_config = WebUIConfig(token=state.token)
    if not check_ws_token(ws, auth_config):
        # 1008 = policy violation — the SPA surfaces this as "Authentication failed".
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    entry = manager.get(session_id)
    if entry is None:
        # Treat unknown session as a policy violation so the SPA does not retry
        # endlessly against a session that no longer exists.
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()
    host = entry.host
    host.attach_websocket(ws)
    if entry.task is None or entry.task.done():
        entry.task = asyncio.create_task(host.run())

    try:
        while True:
            message = await ws.receive_text()
            await host.push_inbound(message.encode("utf-8") + b"\n")
    except WebSocketDisconnect:
        await host.signal_disconnect()
    except Exception as exc:  # pragma: no cover - defensive transport handling
        log.debug("websocket session failed: %s", exc)
        await host.signal_disconnect()
        with contextlib.suppress(Exception):
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
    finally:
        # Wait for the dispatch loop to wind down so subsequent reconnects
        # observe a clean state.
        if entry.task is not None and not entry.task.done():
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(entry.task, timeout=2.0)
