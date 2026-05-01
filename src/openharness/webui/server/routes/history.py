"""Persisted chat history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from openharness.services.session_storage import list_session_snapshots
from openharness.webui.server.state import WebUIState, get_state, require_token

router = APIRouter(
    prefix="/api/history",
    tags=["history"],
    dependencies=[Depends(require_token)],
)


@router.get("")
def list_history(
    limit: int = 20,
    state: WebUIState = Depends(get_state),
) -> dict[str, object]:
    """Return persisted session snapshots for the configured working directory."""
    return {"sessions": list_session_snapshots(state.cwd, limit)}


@router.get("/")
def list_history_slash(
    limit: int = 20,
    state: WebUIState = Depends(get_state),
) -> dict[str, object]:
    """Trailing-slash form so existing clients keep working."""
    return list_history(limit=limit, state=state)
