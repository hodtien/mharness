"""Bridge session REST endpoints for the Web UI."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from openharness.services.session_storage import load_session_by_id
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import (
    WebUIState,
    get_bridge_manager,
    get_session_manager,
    get_state,
    require_token,
)

router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_token)],
)


class CreateSessionRequest(BaseModel):
    resume_id: str | None = None


def _entry_payload(entry) -> dict[str, object]:
    return {
        "session_id": entry.id,
        "id": entry.id,
        "created_at": entry.created_at,
        "active": entry.task is not None and not entry.task.done(),
        "resumed_from": entry.resumed_from,
    }


@router.get("")
def list_sessions() -> dict[str, object]:
    """Return active bridge sessions in UI-safe form."""
    return {"sessions": [asdict(session) for session in get_bridge_manager().list_sessions()]}


@router.get("/")
def list_sessions_slash() -> dict[str, object]:
    """Keep behavior stable for callers that include a trailing slash."""
    return list_sessions()


@router.post("")
def create_session(
    body: CreateSessionRequest | None = None,
    state: WebUIState = Depends(get_state),
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Create a Web UI session, optionally restoring messages from history."""
    restore_messages: list[dict] | None = None
    restore_tool_metadata: dict[str, object] | None = None
    resumed_from: str | None = None

    if body and body.resume_id:
        snapshot = load_session_by_id(state.cwd, body.resume_id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
        messages = snapshot.get("messages")
        if isinstance(messages, list):
            restore_messages = messages
        tool_metadata = snapshot.get("tool_metadata")
        if isinstance(tool_metadata, dict):
            restore_tool_metadata = tool_metadata
        resumed_from = body.resume_id

    entry = manager.create_session(
        restore_messages=restore_messages,
        restore_tool_metadata=restore_tool_metadata,
        resumed_from=resumed_from,
    )
    return _entry_payload(entry)


@router.post("/")
def create_session_slash(
    body: CreateSessionRequest | None = None,
    state: WebUIState = Depends(get_state),
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Keep behavior stable for callers that include a trailing slash."""
    return create_session(body=body, state=state, manager=manager)
