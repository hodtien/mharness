"""Project registry service.

Manages the persisted list of known projects and the active project ID in
``~/.openharness/projects.json``.

Metadata Classification
-----------------------
The service computes additional metadata for each project:

- ``exists``: Whether the path still exists on disk.
- ``is_temp_like``: Whether the path looks like a pytest/tmp test directory
  (contains segments like ``.pytest``, ``tmp``, ``private`` with ``.pytest`` or
  ``__pycache__``, or is under ``/private/`` or ``/tmp/``).
- ``is_worktree_like``: Whether the path is inside a ``.git/worktrees`` directory.
- ``last_seen_at``: UTC timestamp of last registration activity (alias for ``created_at``).

Cleanup
-------
:meth:`cleanup_projects` unregisters projects matching the supplied filter flags.
It never deletes any directory from disk — it only removes project records from
the JSON registry. The active project is never included in a cleanup.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from openharness.config.paths import get_config_dir
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEMP_LIKE_PATTERNS = (
    re.compile(r"/\.pytest(/|$)"),
    re.compile(r"/__pycache__(/|$)"),
    re.compile(r"/tmp[/-]"),
    re.compile(r"^/tmp/"),
    re.compile(r"^/private/(?!var/folders/)"),  # exclude macOS /private/var/folders
)

_WORKTREE_LIKE_PATTERNS = (
    re.compile(r"/\.git/worktrees?/"),  # Standard git worktree directories
    re.compile(r"\.openharness/worktrees?/"),  # Harness worktree storage
    re.compile(r"[\./]worktrees?/"),  # Standalone worktrees directory (.worktrees or /worktrees)
    re.compile(r"/worktrees?/autopilot\+"),  # Autopilot+ prefixed worktrees
)


def _is_temp_like(path: str) -> bool:
    """Return True if ``path`` looks like a pytest or temporary test directory.

    Detects:
    - Paths containing ``/.pytest`` or ``/.pytest_cache`` segments.
    - Paths containing ``/__pycache__`` segments.
    - Paths under ``/tmp/`` or containing ``/tmp-`` subdirectories.
    - Paths under ``/private/`` but NOT under ``/private/var/folders/``
      (macOS default temp location used by normal processes).
    """
    if "/.pytest" in path or "/.pytest_cache" in path:
        return True
    if "/__pycache__" in path:
        return True
    if path.startswith("/tmp/") or "/tmp-" in path:
        return True
    if path.startswith("/private/var/folders/"):
        return "pytest" in path or ".pytest" in path or "/tmp" in path
    # Flag other /private/ paths as temp-like
    if path.startswith("/private/"):
        return True
    return False


def _is_worktree_like(path: str) -> bool:
    """Return True if ``path`` is a git worktree or harness-managed worktree.

    Detects:
    - Paths inside ``.git/worktrees`` or ``.git/worktree`` directories.
    - Paths under ``.openharness/worktrees`` or ``.openharness/worktree``.
    - Paths under ``.worktrees`` or ``worktrees`` subdirectories.
    - Paths containing ``/worktrees/autopilot+`` segment (autopilot+ worktree names).
    """
    for pattern in _WORKTREE_LIKE_PATTERNS:
        if pattern.search(path):
            return True
    return False


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


@dataclass
class ProjectMetadata:
    """Computed metadata for a project (not persisted)."""

    project: Project
    exists: bool
    is_temp_like: bool
    is_worktree_like: bool
    last_seen_at: str | None


class CleanupFilter(TypedDict, total=False):
    """Filter flags for :func:`cleanup_projects`."""

    missing_only: bool
    temp_like_only: bool
    worktree_like_only: bool
    exclude_active: bool


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


def delete_project(project_id: str) -> bool | None:
    """Delete a project by ID.

    Returns True if found and deleted, False if not found,
    or None if attempting to delete the currently active project.
    """
    with exclusive_file_lock(_projects_lock_path()):
        projects, active_id = _load_projects(), _load_raw().get("active_project_id")
        if active_id == project_id:
            return None
        filtered = [p for p in projects if p.id != project_id]
        if len(filtered) == len(projects):
            return False
        # Clear active_project_id if we deleted the active project
        new_active_id = None if active_id == project_id else active_id
        _save_projects(filtered, new_active_id)
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


def ensure_default_project(cwd: str | Path) -> Project:
    """Return the project for cwd, creating and activating it when needed."""
    resolved = Path(cwd).resolve()
    if not resolved.is_dir():
        raise ValueError(f"Path is not a directory: {cwd}")
    resolved_path = str(resolved)
    with exclusive_file_lock(_projects_lock_path()):
        raw = _load_raw()
        projects = _load_projects()
        for project in projects:
            if project.path == resolved_path:
                if raw.get("active_project_id") != project.id:
                    _save_projects(projects, project.id)
                return project
        project = Project(
            id=secrets.token_urlsafe(8),
            name=resolved.name or "workspace",
            path=resolved_path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        projects.append(project)
        _save_projects(projects, project.id)
        return project


# ---------------------------------------------------------------------------
# Metadata & Cleanup
# ---------------------------------------------------------------------------


def get_project_metadata(project: Project) -> ProjectMetadata:
    """Compute runtime metadata for a single project.

    Checks whether the path exists, and classifies it as temp-like or worktree-like.
    """
    p = Path(project.path)
    exists = p.exists()
    is_temp_like = _is_temp_like(project.path)
    is_worktree_like = _is_worktree_like(project.path)
    return ProjectMetadata(
        project=project,
        exists=exists,
        is_temp_like=is_temp_like,
        is_worktree_like=is_worktree_like,
        last_seen_at=project.created_at,
    )


def list_projects_with_metadata(
    filter: CleanupFilter | None = None,
) -> tuple[list[ProjectMetadata], str | None]:
    """Return (projects_with_metadata, active_project_id).

    Each item carries runtime metadata (``exists``, ``is_temp_like``, etc.).

    Args
    ----
    filter:
        Optional filter flags. If ``missing_only`` is True, only projects whose
        directory does not exist are returned. If ``temp_like_only`` is True,
        only temp-like projects are returned. If ``worktree_like_only`` is True,
        only worktree-like projects are returned. These three flags are ORed together,
        so any matching flag causes inclusion. ``exclude_active`` removes the active
        project from results.
    """
    raw = _load_raw()
    active_id = raw.get("active_project_id")
    projects = _load_projects()

    items: list[ProjectMetadata] = []
    for p in projects:
        meta = get_project_metadata(p)
        # Apply filter if provided
        if filter:
            if filter.get("missing_only") and meta.exists:
                continue
            if filter.get("temp_like_only") and not meta.is_temp_like:
                continue
            if filter.get("worktree_like_only") and not meta.is_worktree_like:
                continue
            if filter.get("exclude_active") and p.id == active_id:
                continue

        items.append(meta)

    return items, active_id


def cleanup_projects(
    *,
    missing_only: bool = False,
    temp_like_only: bool = False,
    worktree_like_only: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Unregister stale/temp projects from the registry.

    **This function never deletes any directory from disk.** It only removes
    matching project records from ``projects.json``.

    Args
    ----
    missing_only:
        Remove only projects whose directory no longer exists.
    temp_like_only:
        Remove only projects that look like pytest/tmp test directories.
    worktree_like_only:
        Remove only projects that are inside git worktree directories.
    dry_run:
        If True, return the list of project IDs that *would* be deleted without
        actually modifying the registry.

    Returns
    -------
    The list of project IDs that were (or would be) removed.
    """
    with exclusive_file_lock(_projects_lock_path()):
        raw = _load_raw()
        active_id = raw.get("active_project_id")
        projects = _load_projects()

        if not (missing_only or temp_like_only or worktree_like_only):
            return []

        to_delete: list[Project] = []
        for p in projects:
            if p.id == active_id:
                continue  # Never remove the active project
            meta = get_project_metadata(p)
            if missing_only and meta.exists:
                continue
            if temp_like_only and not meta.is_temp_like:
                continue
            if worktree_like_only and not meta.is_worktree_like:
                continue
            to_delete.append(p)

        ids = [p.id for p in to_delete]

        if not dry_run:
            remaining = [p for p in projects if p.id not in ids]
            _save_projects(remaining, active_id)

        return ids
