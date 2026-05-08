"""Project CRUD endpoints for the Web UI.

All endpoints are under ``/api/projects`` and require a valid session token
(``Authorization: Bearer <token>``). They delegate to the service layer in
:mod:`openharness.services.projects`, which operates on
``~/.openharness/projects.json`` with advisory file locking.

Broadcasts
----------
When a project is activated, :func:`activate_project_endpoint` emits a
``project_switched`` WebSocket event to all connected sessions via
:func:`_broadcast_project_switched`. Frontend clients should listen for
``project_switched`` events to update their working directory context.

Error conventions
------------------
- ``404`` — project not found.
- ``409`` — path conflict (duplicate) on create.
- ``400`` — path is not a directory on create, or active project deletion
  attempted.
"""

from __future__ import annotations

import logging

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from openharness.services.projects import (
    activate_project,
    create_project,
    delete_project,
    list_projects,
    update_project,
)
from openharness.ui.protocol import BackendEvent
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import WebUIState, get_session_manager, get_state, require_token

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_token)],
)


class ProjectCreateRequest(BaseModel):
    """Request body for POST /api/projects."""

    name: str
    path: str
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    """Request body for PATCH /api/projects/{id}."""

    name: str | None = None
    description: str | None = None


@router.get("")
def list_projects_endpoint() -> dict[str, object]:
    """List all registered projects and the active project ID.

    Returns
    -------
    {"projects": [...], "active_project_id": "<id>" | null}
    """
    projects, active_project_id = list_projects()
    return {"projects": [asdict(project) for project in projects], "active_project_id": active_project_id}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project_endpoint(body: ProjectCreateRequest) -> dict[str, object]:
    """Register a new project.

    Path must be an existing directory. Raises 409 on duplicate path.
    """
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
    """Update the name and/or description of a project.

    Returns the updated project, or 404 if not found.
    """
    updated = update_project(project_id, name=body.name, description=body.description)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return asdict(updated)


@router.delete("/{project_id}")
def delete_project_endpoint(project_id: str) -> dict[str, bool]:
    """Remove a project from the registry.

    The active project cannot be deleted (returns 400).
    Returns 404 if the ID does not match any project.
    """
    result = delete_project(project_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Active project cannot be deleted")
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"ok": True}


@router.post("/{project_id}/activate")
async def activate_project_endpoint(
    project_id: str,
    state: "WebUIState" = Depends(get_state),
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Set a project as the active project.

    Switches the backend working directory, updates session state, and
    broadcasts a ``project_switched`` WebSocket event to all connected clients.
    Returns 404 if the project ID is not found.
    """
    project = activate_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    state.switch_project(project)
    manager.update_cwd(str(state.cwd))
    await _broadcast_project_switched(manager, state.cwd, project.id)

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
