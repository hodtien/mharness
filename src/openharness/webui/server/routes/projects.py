"""Project CRUD endpoints for the Web UI."""

from __future__ import annotations

import logging

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from openharness.services.projects import (
    activate_project,
    create_project,
    delete_project,
    get_active_project,
    list_projects,
    update_project,
)
from openharness.ui.protocol import BackendEvent
from openharness.webui.server.config import WebUIConfig
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import WebUIState, get_session_manager, get_state, require_token

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_token)],
)


class ProjectCreateRequest(BaseModel):
    name: str
    path: str
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("")
def list_projects_endpoint() -> dict[str, object]:
    projects, active_project_id = list_projects()
    return {"projects": [asdict(project) for project in projects], "active_project_id": active_project_id}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project_endpoint(body: ProjectCreateRequest) -> dict[str, object]:
    path = Path(body.path)
    if not path.is_dir():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path is not a directory")
    try:
        project = create_project(name=body.name, path=body.path, description=body.description)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate project path") from None
    return asdict(project)


@router.patch("/{project_id}")
def update_project_endpoint(project_id: str, body: ProjectUpdateRequest) -> dict[str, object]:
    updated = update_project(project_id, name=body.name, description=body.description)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return asdict(updated)


@router.delete("/{project_id}")
def delete_project_endpoint(project_id: str) -> dict[str, bool]:
    active = get_active_project()
    if active is not None and active.id == project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Active project cannot be deleted")
    if not delete_project(project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"ok": True}


@router.post("/{project_id}/activate")
async def activate_project_endpoint(
    project_id: str,
    request: Request,
    state: "WebUIState" = Depends(get_state),
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    project = activate_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Update WebUIState
    state.switch_project(project)

    # Recreate SessionManager with new cwd
    new_config = WebUIConfig(
        token=state.token,
        cwd=str(project.path),
        model=state.model,
        api_format=state.api_format,
        permission_mode=state.permission_mode,
    )
    new_manager = SessionManager(new_config, app=request.app)

    # Update the app state with the new manager
    request.app.state.webui_session_manager = new_manager

    # Broadcast project_switched event to all connected clients
    await _broadcast_project_switched(new_manager, project.path, project.id)

    return {"ok": True, "project": asdict(project)}


async def _broadcast_project_switched(manager: SessionManager, project_path: Path, project_id: str) -> None:
    """Emit a project_switched event to every active WebSocket session."""
    event = BackendEvent(type="project_switched", project_id=project_id, project_path=str(project_path))
    for entry in manager.entries():
        host = entry.host
        emit = getattr(host, "_emit", None)
        if emit is None:
            continue
        try:
            await emit(event)
        except Exception as exc:  # pragma: no cover - transport failure
            log.debug("project_switched broadcast failed: %s", exc)
