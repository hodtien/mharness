"""Persisted chat history endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from openharness.services.session_storage import list_session_snapshots, load_session_by_id
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


_TOOL_RESULT_MAX_CHARS = 500


def _truncate_tool_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with each tool_result content truncated for transport.

    Long tool outputs are abbreviated with a marker so the detail view can
    surface a snapshot without paying the full transfer cost.
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            text = block.get("content")
            if isinstance(text, str) and len(text) > _TOOL_RESULT_MAX_CHARS:
                kept = text[:_TOOL_RESULT_MAX_CHARS]
                block["content"] = (
                    f"{kept}… [truncated {len(text) - _TOOL_RESULT_MAX_CHARS} chars]"
                )
                block["truncated"] = True
                block["original_length"] = len(text)
    return payload


@router.get("/{session_id}")
def get_history_detail(
    session_id: str,
    state: WebUIState = Depends(get_state),
) -> dict[str, Any]:
    """Return the full snapshot for ``session_id`` with tool_result truncation."""
    snapshot = load_session_by_id(state.cwd, session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _truncate_tool_results(snapshot)
