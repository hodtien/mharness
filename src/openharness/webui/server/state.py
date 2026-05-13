"""Application state and dependencies for the Web UI server.

Centralizes the shared singletons (auth token, working directory, default
model, task manager, bridge manager) so individual routers can pull just what
they need. Keeping this in one place lets ``create_app`` wire everything in
exactly one location.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Cookie, Depends, Header, HTTPException, Query, Request, status

from openharness.webui.server.auth_store import is_access_token_valid

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from openharness.bridge.manager import BridgeSessionManager
    from openharness.tasks.manager import BackgroundTaskManager
    from openharness.services.projects import Project as ServiceProject


@dataclass
class WebUIState:
    """Runtime state shared across all routers."""

    token: str
    cwd: Path
    model: str | None = None
    api_format: str | None = None
    permission_mode: str | None = None
    extra_meta: dict[str, object] = field(default_factory=dict)
    active_project_id: str | None = None

    def switch_project(self, project: "ServiceProject") -> None:
        """Switch to the given project, updating cwd and active_project_id."""
        self.cwd = Path(project.path).resolve()
        self.active_project_id = project.id



def generate_token() -> str:
    """Return a random URL-safe token for bearer auth."""
    return secrets.token_urlsafe(32)


def get_state(request: Request) -> WebUIState:
    """Return the :class:`WebUIState` attached to the running app."""
    state = getattr(request.app.state, "webui", None)
    if state is None:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Web UI state not initialized",
        )
    return state


def require_token(
    state: WebUIState = Depends(get_state),
    authorization: str | None = Header(default=None),
    token_query: str | None = Query(default=None, alias="token"),
) -> None:
    """Validate the bearer token in ``Authorization`` header or ``token`` query."""

    candidate = _bearer_candidate(authorization) or token_query
    _require_matching_token(candidate, state.token)


def require_stream_token(
    state: WebUIState = Depends(get_state),
    authorization: str | None = Header(default=None),
    token_cookie: str | None = Cookie(default=None, alias="oh_token"),
) -> None:
    """Validate stream auth without accepting bearer tokens in the URL."""

    candidate = _bearer_candidate(authorization) or token_cookie
    _require_matching_token(candidate, state.token)


def _bearer_candidate(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip() or None
    return None


def _require_matching_token(candidate: str | None, token: str) -> None:
    if candidate is not None:
        if is_access_token_valid(candidate) or secrets.compare_digest(candidate, token):
            return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_task_manager() -> "BackgroundTaskManager":
    """Lazy import of the task manager singleton."""
    from openharness.tasks.manager import get_task_manager as _factory

    return _factory()


def get_bridge_manager() -> "BridgeSessionManager":
    """Lazy import of the bridge manager singleton."""
    from openharness.bridge.manager import get_bridge_manager as _factory

    return _factory()


def get_session_manager(request: Request):
    """Return the per-app :class:`SessionManager` attached by ``create_app``."""
    manager = getattr(request.app.state, "webui_session_manager", None)
    if manager is None:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Web UI session manager not initialized",
        )
    return manager
