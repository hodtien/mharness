"""Project registry service.

Manages the persisted list of known projects and the active project ID in
``~/.openharness/projects.json``.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from openharness.config.paths import get_config_dir
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text


def _projects_path() -> Path:
    return get_config_dir() / "projects.json"


def _projects_lock_path() -> Path:
    return _projects_path().with_suffix(".lock")


@dataclass
class Project:
    """A registered project."""

    id: str
    name: str
    path: str
    description: str | None = None
    created_at: str | None = None


def _load_raw() -> dict:
    """Load the raw JSON dict from projects.json, or return empty structure."""
    path = _projects_path()
    if not path.exists():
        return {"projects": [], "active_project_id": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"projects": [], "active_project_id": None}


def _save_raw(data: dict) -> None:
    atomic_write_text(_projects_path(), json.dumps(data, indent=2) + "\n")


def _load_projects() -> list[Project]:
    raw = _load_raw()
    return [
        Project(
            id=p["id"],
            name=p["name"],
            path=p["path"],
            description=p.get("description"),
            created_at=p.get("created_at"),
        )
        for p in raw.get("projects", [])
        if "id" in p and "name" in p and "path" in p
    ]


def _save_projects(projects: list[Project], active_project_id: str | None) -> None:
    _save_raw(
        {
            "projects": [asdict(p) for p in projects],
            "active_project_id": active_project_id,
        }
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_projects() -> tuple[list[Project], str | None]:
    """Return (projects, active_project_id)."""
    raw = _load_raw()
    return _load_projects(), raw.get("active_project_id")


def get_project(project_id: str) -> Project | None:
    """Return one project by ID, or None if not found."""
    for p in _load_projects():
        if p.id == project_id:
            return p
    return None


def create_project(*, name: str, path: str, description: str | None = None) -> Project:
    """Create a new project entry and return it.

    Raises ValueError if the path is already registered.
    """
    resolved_path = str(Path(path).resolve())
    with exclusive_file_lock(_projects_lock_path()):
        projects, active_id = _load_projects(), _load_raw().get("active_project_id")
        if any(p.path == resolved_path for p in projects):
            raise ValueError("A project with this path already exists")
        project = Project(
            id=secrets.token_urlsafe(8),
            name=name,
            path=resolved_path,
            description=description or None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        projects.append(project)
        _save_projects(projects, active_id)
    return project


def update_project(project_id: str, *, name: str | None = None, description: str | None = None) -> Project | None:
    """Update name and/or description of an existing project. Returns updated project or None."""
    with exclusive_file_lock(_projects_lock_path()):
        projects, active_id = _load_projects(), _load_raw().get("active_project_id")
        for p in projects:
            if p.id == project_id:
                if name is not None:
                    p.name = name
                if description is not None:
                    p.description = description
                _save_projects(projects, active_id)
                return p
    return None


def delete_project(project_id: str) -> bool:
    """Delete a project by ID. Returns True if found and deleted."""
    with exclusive_file_lock(_projects_lock_path()):
        projects, active_id = _load_projects(), _load_raw().get("active_project_id")
        filtered = [p for p in projects if p.id != project_id]
        if len(filtered) == len(projects):
            return False
        _save_projects(filtered, active_id)
        return True


def activate_project(project_id: str) -> Project | None:
    """Set the active project. Returns the project or None if not found."""
    with exclusive_file_lock(_projects_lock_path()):
        projects, _ = _load_projects(), _load_raw().get("active_project_id")
        for p in projects:
            if p.id == project_id:
                _save_projects(projects, project_id)
                return p
    return None


def get_active_project() -> Project | None:
    """Return the currently active project, or None."""
    projects, active_id = list_projects()
    if active_id is None:
        return None
    for p in projects:
        if p.id == active_id:
            return p
    return None
