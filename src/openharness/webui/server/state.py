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

from fastapi import Depends, Header, HTTPException, Query, Request, status

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from openharness.bridge.manager import BridgeSessionManager
    from openharness.tasks.manager import BackgroundTaskManager


@dataclass
class WebUIState:
    """Runtime state shared across all routers."""

    token: str
    cwd: Path
    model: str | None = None
    api_format: str | None = None
    permission_mode: str | None = None
    extra_meta: dict[str, object] = field(default_factory=dict)


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
    """Validate the bearer token in ``Authorization`` header or ``token`` query.

    The Web UI passes the token in either the ``Authorization: Bearer …``
    header (browser fetches) or in the ``?token=`` query string (initial page
    load and WebSocket handshake). Constant-time comparison avoids leaking the
    token via timing.
    """

    candidate: str | None = None
    if authorization:
        prefix = "Bearer "
        if authorization.startswith(prefix):
            candidate = authorization[len(prefix):].strip() or None
    if candidate is None:
        candidate = token_query

    if candidate is None or not secrets.compare_digest(candidate, state.token):
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
