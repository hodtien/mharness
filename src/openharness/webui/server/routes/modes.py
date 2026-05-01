"""Current mode endpoint for the Web UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from openharness.config.settings import load_settings
from openharness.state.app_state import AppState
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import WebUIState, get_session_manager, get_state, require_token

router = APIRouter(
    prefix="/api",
    tags=["modes"],
    dependencies=[Depends(require_token)],
)


def _modes_payload(state: AppState) -> dict[str, object]:
    return {
        "permission_mode": state.permission_mode,
        "fast_mode": state.fast_mode,
        "vim_enabled": state.vim_enabled,
        "effort": state.effort,
        "passes": state.passes,
        "output_style": state.output_style,
        "theme": state.theme,
    }


def _active_session_state(manager: SessionManager) -> AppState | None:
    for entry in manager.entries():
        if entry.task is None or entry.task.done():
            continue
        bundle = getattr(entry.host, "_bundle", None)
        if bundle is not None:
            return bundle.app_state.get()
    return None


def _settings_payload(state: WebUIState) -> dict[str, object]:
    settings = load_settings()
    return {
        "permission_mode": state.permission_mode or settings.permission.mode.value,
        "fast_mode": settings.fast_mode,
        "vim_enabled": settings.vim_mode,
        "effort": settings.effort,
        "passes": settings.passes,
        "output_style": settings.output_style,
        "theme": settings.theme,
    }


@router.get("/modes")
def modes(
    state: WebUIState = Depends(get_state),
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Return current UI modes from the active session, falling back to settings."""
    session_state = _active_session_state(manager)
    if session_state is not None:
        return _modes_payload(session_state)
    return _settings_payload(state)
