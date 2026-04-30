"""Persisted chat history endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from openharness.services.session_storage import (
    get_project_session_dir,
    list_session_snapshots,
    load_session_by_id,
)
from openharness.webui.server.auth import make_http_auth_dependency
from openharness.webui.server.config import WebUIConfig

_MAX_TOOL_RESULT_CHARS = 500


def _cwd(config: WebUIConfig) -> str:
    return config.cwd or str(Path.cwd())


def _truncate_tool_results(value: Any) -> Any:
    """Return a copy with oversized tool_result content shortened."""
    if isinstance(value, dict):
        out = {key: _truncate_tool_results(item) for key, item in value.items()}
        if out.get("type") == "tool_result" and isinstance(out.get("content"), str):
            content = out["content"]
            if len(content) > _MAX_TOOL_RESULT_CHARS:
                out["content"] = (
                    content[:_MAX_TOOL_RESULT_CHARS]
                    + f"\n… truncated {len(content) - _MAX_TOOL_RESULT_CHARS} chars"
                )
        return out
    if isinstance(value, list):
        return [_truncate_tool_results(item) for item in value]
    return value


def build_router(config: WebUIConfig) -> APIRouter:
    """Build the persisted history router for ``config``."""
    router = APIRouter(prefix="/api/history", tags=["history"])
    require_auth = make_http_auth_dependency(config)

    @router.get("", dependencies=[Depends(require_auth)])
    async def list_history(request: Request, limit: int = 20) -> dict[str, Any]:
        cfg: WebUIConfig = request.app.state.webui_config
        safe_limit = max(1, min(limit, 100))
        return {"sessions": list_session_snapshots(_cwd(cfg), safe_limit)}

    @router.get("/{session_id}", dependencies=[Depends(require_auth)])
    async def get_history_session(request: Request, session_id: str) -> dict[str, Any]:
        cfg: WebUIConfig = request.app.state.webui_config
        snapshot = load_session_by_id(_cwd(cfg), session_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"session": _truncate_tool_results(snapshot)}

    @router.delete("/{session_id}", dependencies=[Depends(require_auth)], status_code=204)
    async def delete_history_session(request: Request, session_id: str) -> Response:
        cfg: WebUIConfig = request.app.state.webui_config
        session_dir = get_project_session_dir(_cwd(cfg))
        session_path = session_dir / f"session-{session_id}.json"
        latest_path = session_dir / "latest.json"
        deleted = False

        if session_path.exists():
            session_path.unlink()
            deleted = True

        if latest_path.exists():
            try:
                latest = json.loads(latest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                latest = {}
            if latest.get("session_id") == session_id or session_id == "latest":
                latest_path.unlink()
                deleted = True

        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return Response(status_code=204)

    return router
