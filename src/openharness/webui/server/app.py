"""FastAPI application factory for the OpenHarness Web UI.

The intent of this module is intentionally narrow: build a :class:`FastAPI`
instance, attach the shared :class:`~openharness.webui.server.state.WebUIState`,
mount the API routers, and serve the bundled SPA. All endpoint logic lives in
``openharness/webui/server/routes/`` so each surface (health, sessions, tasks,
cron) stays small and independently testable.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from openharness.webui.server.config import WebUIConfig
from openharness.webui.server.routes import cron as cron_routes
from openharness.webui.server.routes import health as health_routes
from openharness.webui.server.routes import history as history_routes
from openharness.webui.server.routes import modes as modes_routes
from openharness.webui.server.routes import sessions as sessions_routes
from openharness.webui.server.routes import tasks as tasks_routes
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import WebUIState, generate_token


def _resolve_spa_dir() -> Path | None:
    """Return the directory containing the built SPA, or ``None`` if absent.

    Two layouts are supported:

    1. Source checkout: ``frontend/webui/dist`` (relative to the repo root).
    2. Installed wheel: ``openharness/_webui_frontend`` (forced-include from
       ``pyproject.toml``).
    """

    # Wheel layout — package data shipped beside the python sources.
    pkg_dir = Path(__file__).resolve().parent.parent.parent / "_webui_frontend"
    if (pkg_dir / "index.html").is_file():
        return pkg_dir

    # Source checkout layout — climb until we find ``frontend/webui/dist``.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "frontend" / "webui" / "dist"
        if (candidate / "index.html").is_file():
            return candidate

    return None


def _mount_spa(app: FastAPI, spa_dir: Path) -> None:
    """Serve the SPA bundle and add a non-API fallback to ``index.html``.

    The SPA uses client-side routing (react-router-dom ``BrowserRouter``), so
    deep links like ``/chat`` must return ``index.html`` instead of a 404.
    The fallback intentionally skips ``/api`` and ``/ws`` so backend errors
    surface correctly instead of being masked by an HTML response.
    """

    index_html = spa_dir / "index.html"

    # Serve hashed bundles, css, fonts, etc.
    assets_dir = spa_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="webui-assets")

    @app.get("/", include_in_schema=False)
    async def _root() -> FileResponse:
        return FileResponse(index_html)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        # Never shadow API or WebSocket routes.
        if full_path.startswith(("api/", "ws/")) or full_path in {"api", "ws"}:
            raise HTTPException(status_code=404)

        # Serve real files (favicon.svg, robots.txt, etc.) verbatim.
        candidate = (spa_dir / full_path).resolve()
        try:
            candidate.relative_to(spa_dir)
        except ValueError:
            # Path traversal — refuse.
            raise HTTPException(status_code=404) from None
        if candidate.is_file():
            return FileResponse(candidate)

        # Anything else is an SPA route — let the client router handle it.
        return FileResponse(index_html)


def create_app(
    *,
    token: str | None = None,
    cwd: str | Path | None = None,
    model: str | None = None,
    api_format: str | None = None,
    permission_mode: str | None = None,
    extra_meta: dict[str, object] | None = None,
    spa_dir: str | Path | None = None,
) -> FastAPI:
    """Build the Web UI FastAPI app.

    Parameters mirror the ``oh webui`` CLI flags. The created state object is
    attached to ``app.state.webui`` so request handlers can read it via the
    ``get_state`` dependency.

    If a built SPA bundle is available (either inside the installed wheel at
    ``openharness/_webui_frontend`` or at ``frontend/webui/dist`` in a source
    checkout), it is mounted at ``/`` with an SPA fallback so that deep links
    like ``/chat`` survive a hard reload. Pass ``spa_dir`` to override the
    auto-detected location, or ``spa_dir=False``-equivalent (an empty string)
    to skip mounting entirely (useful in tests).
    """

    app = FastAPI(title="OpenHarness Web UI", version="0.1.0")

    resolved_token = token or generate_token()
    resolved_cwd = Path(cwd).expanduser().resolve() if cwd else Path.cwd()
    app.state.webui = WebUIState(
        token=resolved_token,
        cwd=resolved_cwd,
        model=model,
        api_format=api_format,
        permission_mode=permission_mode,
        extra_meta=dict(extra_meta or {}),
    )
    app.state.webui_session_manager = SessionManager(
        WebUIConfig(
            token=resolved_token,
            cwd=str(resolved_cwd),
            model=model,
            api_format=api_format,
            permission_mode=permission_mode,
        )
    )

    app.include_router(health_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(tasks_routes.router)
    app.include_router(cron_routes.router)
    app.include_router(history_routes.router)
    app.include_router(modes_routes.router)

    resolved_spa: Path | None
    if spa_dir is None:
        resolved_spa = _resolve_spa_dir()
    elif spa_dir == "":
        resolved_spa = None
    else:
        candidate = Path(spa_dir).expanduser().resolve()
        resolved_spa = candidate if (candidate / "index.html").is_file() else None

    if resolved_spa is not None:
        _mount_spa(app, resolved_spa)

    return app


__all__ = ["create_app"]
