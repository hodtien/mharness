"""Bridge session REST endpoints for the Web UI."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from openharness.webui.server.state import get_bridge_manager, require_token

router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_token)],
)


@router.get("")
def list_sessions() -> dict[str, object]:
    """Return active bridge sessions in UI-safe form."""
    return {"sessions": [asdict(session) for session in get_bridge_manager().list_sessions()]}


@router.get("/")
def list_sessions_slash() -> dict[str, object]:
    """Keep behavior stable for callers that include a trailing slash."""
    return list_sessions()
