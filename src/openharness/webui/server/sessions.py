"""Manage live WebUI sessions (one per browser tab)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from openharness.ui.backend_host import BackendHostConfig
from openharness.webui.server.bridge import WebSocketBackendHost
from openharness.webui.server.config import WebUIConfig

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

log = logging.getLogger(__name__)


@dataclass
class SessionEntry:
    id: str
    host: WebSocketBackendHost
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.time)
    resumed_from: str | None = None
    project_id: str | None = None


class SessionManager:
    """Lightweight registry of active WebSocket sessions."""

    def __init__(self, config: WebUIConfig, app: "FastAPI | None" = None) -> None:
        self._config = config
        self._sessions: dict[str, SessionEntry] = {}
        self.app = app

    def create_session(
        self,
        *,
        restore_messages: list[dict] | None = None,
        restore_tool_metadata: dict[str, object] | None = None,
        resumed_from: str | None = None,
        cwd: str | None = None,
        project_id: str | None = None,
    ) -> SessionEntry:
        session_id = uuid4().hex[:12]
        host_config = BackendHostConfig(
            model=self._config.model,
            base_url=self._config.base_url,
            system_prompt=self._config.system_prompt,
            api_key=self._config.api_key,
            api_format=self._config.api_format,
            cwd=cwd or self._config.cwd,
            permission_mode=self._config.permission_mode,
            enforce_max_turns=False,
            restore_messages=list(restore_messages) if restore_messages else None,
            restore_tool_metadata=dict(restore_tool_metadata) if restore_tool_metadata else None,
        )
        host = WebSocketBackendHost(host_config)
        entry = SessionEntry(id=session_id, host=host, resumed_from=resumed_from, project_id=project_id)
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
                "resumed_from": entry.resumed_from,
            }
            for entry in self._sessions.values()
        ]

    def entries(self) -> list["SessionEntry"]:
        """Return all session entries (used by /modes to find active session state)."""
        return list(self._sessions.values())

    def update_cwd(self, cwd: str) -> None:
        """Update cwd for all active sessions and the shared config.

        Called when switching projects to ensure existing sessions use the new path.
        """
        self._config.cwd = cwd
        for entry in self._sessions.values():
            if entry.host._bundle is not None:
                entry.host._bundle.cwd = cwd

    def update_provider_defaults(
        self,
        *,
        model: str | None,
        api_format: str | None,
        base_url: str | None,
    ) -> None:
        """Update default provider fields on the shared :class:`WebUIConfig`.

        New sessions created via :meth:`create_session` will pick up these
        values when building their :class:`BackendHostConfig`. Existing live
        sessions keep their current config until the next reconnect.
        """
        self._config.model = model
        self._config.api_format = api_format
        self._config.base_url = base_url

    async def remove(self, session_id: str) -> None:
        entry = self._sessions.pop(session_id, None)
        if entry and entry.task and not entry.task.done():
            entry.task.cancel()
            try:
                await entry.task
            except (asyncio.CancelledError, Exception):
                pass
