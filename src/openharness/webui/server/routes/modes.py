"""Current mode endpoint for the Web UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from openharness.config.settings import load_settings, save_settings
from openharness.permissions.modes import PermissionMode
from openharness.state.app_state import AppState
from openharness.ui.protocol import BackendEvent
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import WebUIState, get_session_manager, get_state, require_token

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["modes"],
    dependencies=[Depends(require_token)],
)


class ModesPatch(BaseModel):
    """Body for PATCH /api/modes.

    All fields are optional; only the provided ones are applied.
    """

    model_config = ConfigDict(extra="forbid")

    permission_mode: str | None = Field(default=None, pattern="^(default|plan|full_auto)$")
    effort: str | None = Field(default=None, pattern="^(low|medium|high)$")
    passes: int | None = Field(default=None, ge=1, le=5)
    fast_mode: bool | None = None
    output_style: str | None = None
    theme: str | None = None


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


def _apply_to_app_states(manager: SessionManager, updates: dict[str, object]) -> AppState | None:
    """Apply updates to every active session's AppStateStore; return one snapshot."""
    snapshot: AppState | None = None
    for entry in manager.entries():
        bundle = getattr(entry.host, "_bundle", None)
        if bundle is None:
            continue
        snapshot = bundle.app_state.set(**updates)
    return snapshot


def _apply_to_settings(updates: dict[str, object]) -> AppState:
    """Persist updates to ~/.openharness/settings.json and return a synthesized snapshot."""
    settings = load_settings()
    settings_updates: dict[str, object] = {}
    if "permission_mode" in updates:
        settings_updates["permission"] = settings.permission.model_copy(
            update={"mode": PermissionMode(updates["permission_mode"])}
        )
    for key in ("effort", "passes", "fast_mode", "output_style", "theme"):
        if key in updates:
            settings_updates[key] = updates[key]
    if settings_updates:
        settings = settings.model_copy(update=settings_updates)
        save_settings(settings)
    return AppState(
        model=settings.model,
        permission_mode=settings.permission.mode.value,
        theme=settings.theme,
        cwd=str(settings_updates.get("cwd", ".")),
        provider=settings.provider or "unknown",
        fast_mode=settings.fast_mode,
        effort=settings.effort,
        passes=settings.passes,
        output_style=settings.output_style,
        vim_enabled=settings.vim_mode,
    )


async def _broadcast_state_snapshot(manager: SessionManager) -> None:
    """Emit a state_snapshot event to every active WebSocket session."""
    for entry in manager.entries():
        host = entry.host
        bundle = getattr(host, "_bundle", None)
        if bundle is None:
            continue
        event = BackendEvent.state_snapshot(bundle.app_state.get())
        emit = getattr(host, "_emit", None)
        if emit is None:
            continue
        try:
            await emit(event)
        except Exception as exc:  # pragma: no cover - transport failure
            log.debug("state_snapshot broadcast failed: %s", exc)


@router.patch("/modes")
async def patch_modes(
    payload: ModesPatch,
    state: WebUIState = Depends(get_state),
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Update runtime modes, persist to settings, and broadcast a state_snapshot."""
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided",
        )

    snapshot = _apply_to_app_states(manager, updates)

    try:
        if snapshot is None:
            snapshot = _apply_to_settings(updates)
        else:
            _apply_to_settings(updates)
    except Exception as exc:
        log.warning("save_settings failed for PATCH /api/modes: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist settings: {exc}",
        ) from exc

    if "permission_mode" in updates:
        state.permission_mode = updates["permission_mode"]  # type: ignore[assignment]

    try:
        await _broadcast_state_snapshot(manager)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("broadcast failed: %s", exc)

    return _modes_payload(snapshot)
