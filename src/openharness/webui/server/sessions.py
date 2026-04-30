"""Manage live WebUI sessions (one per browser tab)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from uuid import uuid4

from openharness.ui.backend_host import BackendHostConfig
from openharness.webui.server.bridge import WebSocketBackendHost
from openharness.webui.server.config import WebUIConfig

log = logging.getLogger(__name__)


@dataclass
class SessionEntry:
    id: str
    host: WebSocketBackendHost
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.time)


class SessionManager:
    """Lightweight registry of active WebSocket sessions."""

    def __init__(self, config: WebUIConfig) -> None:
        self._config = config
        self._sessions: dict[str, SessionEntry] = {}

    def create_session(self) -> SessionEntry:
        session_id = uuid4().hex[:12]
        host_config = BackendHostConfig(
            model=self._config.model,
            base_url=self._config.base_url,
            system_prompt=self._config.system_prompt,
            api_key=self._config.api_key,
            api_format=self._config.api_format,
            cwd=self._config.cwd,
            permission_mode=self._config.permission_mode,
            enforce_max_turns=False,
        )
        host = WebSocketBackendHost(host_config)
        entry = SessionEntry(id=session_id, host=host)
        self._sessions[session_id] = entry
        return entry

    def get(self, session_id: str) -> SessionEntry | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "id": entry.id,
                "created_at": entry.created_at,
                "active": entry.task is not None and not entry.task.done(),
            }
            for entry in self._sessions.values()
        ]

    async def remove(self, session_id: str) -> None:
        entry = self._sessions.pop(session_id, None)
        if entry and entry.task and not entry.task.done():
            entry.task.cancel()
            try:
                await entry.task
            except (asyncio.CancelledError, Exception):
                pass
