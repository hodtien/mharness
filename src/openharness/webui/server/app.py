"""FastAPI application factory for the OpenHarness Web UI.

The intent of this module is intentionally narrow: build a :class:`FastAPI`
instance, attach the shared :class:`~openharness.webui.server.state.WebUIState`,
and mount the routers. All endpoint logic lives in
``openharness/webui/server/routes/`` so each surface (health, sessions, tasks,
cron) stays small and independently testable.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from openharness.webui.server.routes import cron as cron_routes
from openharness.webui.server.routes import health as health_routes
from openharness.webui.server.routes import sessions as sessions_routes
from openharness.webui.server.routes import tasks as tasks_routes
from openharness.webui.server.state import WebUIState, generate_token


def create_app(
    *,
    token: str | None = None,
    cwd: str | Path | None = None,
    model: str | None = None,
    api_format: str | None = None,
    permission_mode: str | None = None,
    extra_meta: dict[str, object] | None = None,
) -> FastAPI:
    """Build the Web UI FastAPI app.

    Parameters mirror the ``oh webui`` CLI flags. The created state object is
    attached to ``app.state.webui`` so request handlers can read it via the
    ``get_state`` dependency.
    """

    app = FastAPI(title="OpenHarness Web UI", version="0.1.0")

    app.state.webui = WebUIState(
        token=token or generate_token(),
        cwd=Path(cwd).expanduser().resolve() if cwd else Path.cwd(),
        model=model,
        api_format=api_format,
        permission_mode=permission_mode,
        extra_meta=dict(extra_meta or {}),
    )

    app.include_router(health_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(tasks_routes.router)
    app.include_router(cron_routes.router)

    return app


__all__ = ["create_app"]
