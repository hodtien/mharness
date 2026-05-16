"""Persisted chat history endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from openharness.services.projects import get_project
from openharness.services.session_storage import (
    delete_session_by_id,
    list_session_snapshots,
    load_session_by_id,
)
from openharness.webui.server.state import WebUIState, get_state, require_token

router = APIRouter(
    prefix="/api/history",
    tags=["history"],
    dependencies=[Depends(require_token)],
)


def _resolve_cwd(state: WebUIState, project: str | None) -> str:
    """Resolve the working directory for a history operation.

    If *project* is supplied as a query parameter the session will use that
    project's working directory instead of the server-side global active project.
    This enables per-tab project isolation: each browser tab sends its own
    ``?project=`` so two tabs can target different projects simultaneously.
    """
    if project:
        proj = get_project(project)
        if proj is None:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )
        return proj.path
    # Fall back to global state cwd
    return str(state.cwd)


@router.get("")
def list_history(
    limit: int = 20,
    state: WebUIState = Depends(get_state),
    project: str | None = Query(default=None, alias="project"),
) -> dict[str, object]:
    """Return persisted session snapshots for the configured working directory.

    When ``project_id`` is supplied via query param, the session history is
    scoped to that project, enabling per-tab project isolation.
    """
    cwd = _resolve_cwd(state, project)
    return {"sessions": list_session_snapshots(cwd, limit)}


@router.get("/")
def list_history_slash(
    limit: int = 20,
    state: WebUIState = Depends(get_state),
    project: str | None = Query(default=None, alias="project"),
) -> dict[str, object]:
    """Trailing-slash form so existing clients keep working."""
    return list_history(limit=limit, state=state, project=project)


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
    project: str | None = Query(default=None, alias="project"),
) -> dict[str, Any]:
    """Return the full snapshot for ``session_id`` with tool_result truncation.

    When ``project_id`` is supplied via query param, the session detail is
    scoped to that project, enabling per-tab project isolation.
    """
    cwd = _resolve_cwd(state, project)
    snapshot = load_session_by_id(cwd, session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _truncate_tool_results(snapshot)


@router.delete("/{session_id}", status_code=204)
def delete_history(
    session_id: str,
    state: WebUIState = Depends(get_state),
    project: str | None = Query(default=None, alias="project"),
) -> Response:
    """Delete the persisted snapshot for ``session_id``.

    When ``project_id`` is supplied via query param, the deletion is
    scoped to that project, enabling per-tab project isolation.
    """
    cwd = _resolve_cwd(state, project)
    if not delete_session_by_id(cwd, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)
