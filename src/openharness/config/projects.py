"""Project registry model and helpers.

This module defines the core data model for multi-project support:
- :class:`Project` — a Pydantic model representing one registered project.
- :class:`ProjectRegistry` — a class for loading/saving the JSON registry at
  ``~/.openharness/projects.json``.

The registry file is thread-safe via advisory file locking (see
:meth:`ProjectRegistry.add_project`, :meth:`ProjectRegistry.remove_project`,
etc.).

Example
-------
::

    registry = ProjectRegistry()
    registry.add_project("my-app", "/code/my-app", description="Main app")
    project = registry.activate_project("my-app")

    # New sessions open in /code/my-app
    assert registry.get_active_project() == project

"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from openharness.config.paths import get_data_dir
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text

__all__ = ["Project", "ProjectRegistry", "get_projects_registry_path"]


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")


def get_projects_registry_path() -> Path:
    return get_data_dir() / "projects.json"


def _projects_lock_path() -> Path:
    path = get_projects_registry_path()
    return path.with_suffix(path.suffix + ".lock")


class Project(BaseModel):
    """A registered project.

    Attributes
    ----------
    id:
        URL-safe slug derived from the project name. Stable across sessions.
    name:
        Human-readable label shown in the UI.
    path:
        Absolute path to the project root on disk.
    description:
        Optional free-text description.
    created_at:
        UTC timestamp when the project was first registered.
    updated_at:
        UTC timestamp of the last modification.
    is_active:
        True when this project is the currently active project.

    The ``path`` field is resolved to an absolute path at construction time.
    All timestamps are normalized to UTC.
    """

    id: str
    name: str
    path: Path
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @staticmethod
    def _to_aware(dt: datetime) -> datetime:
        """Ensure a datetime has a timezone (assumes UTC if none)."""
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        self.path = self.path.resolve()
        self.created_at = self._to_aware(self.created_at)
        self.updated_at = self._to_aware(self.updated_at)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON serialization."""
        data = self.model_dump()
        data["path"] = str(self.path)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        """Reconstruct a Project from a plain dict (e.g. loaded from JSON)."""
        return cls(
            id=data["id"],
            name=data["name"],
            path=Path(data["path"]),
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            is_active=bool(data.get("is_active", False)),
        )


class ProjectRegistry:
    """Manage the persisted list of registered projects.

    Parameters
    ----------
    registry_path:
        Path to the JSON file. Defaults to ``~/.openharness/projects.json``.

    Thread-safety
    -------------
    All public mutation methods (``add_project``, ``remove_project``,
    ``update_project``, ``activate_project``) acquire an exclusive file lock
    before reading or writing, preventing concurrent corruption.

    File format
    -----------
    See :class:`Project` serialization (``to_dict`` / ``from_dict``).
    The top-level structure is::

        {
          "projects": [Project, ...],
          "active_project_id": "<id>" | null
        }

    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self.REGISTRY_PATH = registry_path or get_projects_registry_path()

    def load(self) -> dict[str, Any]:
        """Load the registry from disk.

        Returns ``{"projects": [], "active_project_id": None}`` when the
        file is absent or corrupted (JSON decode error).
        """
        if not self.REGISTRY_PATH.exists():
            return {"projects": [], "active_project_id": None}
        try:
            data = json.loads(self.REGISTRY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"projects": [], "active_project_id": None}
        projects = [Project.from_dict(item) for item in data.get("projects", []) if isinstance(item, dict)]
        return {"projects": projects, "active_project_id": data.get("active_project_id")}

    def save(self, registry: dict[str, Any]) -> None:
        """Write the registry atomically to disk."""
        payload = {
            "projects": [project.to_dict() for project in registry["projects"]],
            "active_project_id": registry.get("active_project_id"),
        }
        atomic_write_text(self.REGISTRY_PATH, json.dumps(payload, indent=2) + "\n")

    def add_project(self, name: str, path: str | Path, description: str = "") -> Project:
        """Register a new project.

        Args
        ----
        name:
            Human-readable label.
        path:
            Absolute path to an existing directory.
        description:
            Optional free-text description.

        Returns
        -------
        The newly created :class:`Project`.

        Raises
        ------
        ValueError
            If ``path`` is not an existing directory, or if the name or
            path is already registered.
        """
        resolved_path = Path(path).resolve()
        if not resolved_path.is_dir():
            raise ValueError(f"Path is not an existing directory: {path}")
        project_id = _slugify(name)
        with exclusive_file_lock(_projects_lock_path()):
            registry = self.load()
            if any(project.id == project_id for project in registry["projects"]):
                raise ValueError("duplicate project name")
            if any(project.path == resolved_path for project in registry["projects"]):
                raise ValueError("duplicate project path")
            project = Project(id=project_id, name=name, path=resolved_path, description=description)
            registry["projects"].append(project)
            self.save(registry)
            return project

    def remove_project(self, id: str) -> bool:
        """Remove a project by ID.

        Returns
        -------
        True if the project was found and deleted; False if no project with
        that ID exists.

        Note: the currently active project cannot be removed — see
        :meth:`activate_project`.
        """
        with exclusive_file_lock(_projects_lock_path()):
            registry = self.load()
            projects = [project for project in registry["projects"] if project.id != id]
            if len(projects) == len(registry["projects"]):
                return False
            registry["projects"] = projects
            if registry.get("active_project_id") == id:
                registry["active_project_id"] = None
            self.save(registry)
            return True

    def update_project(self, id: str, name: str | None = None, description: str | None = None) -> Project:
        """Update the name and/or description of an existing project.

        Args
        ----
        id:
            The project ID (slug).
        name:
            New human-readable label. Unchanged if ``None``.
        description:
            New free-text description. Unchanged if ``None``.

        Returns
        -------
        The updated :class:`Project`.

        Raises
        ------
        KeyError
            If no project with the given ID exists.
        """
        with exclusive_file_lock(_projects_lock_path()):
            registry = self.load()
            for project in registry["projects"]:
                if project.id == id:
                    if name is not None:
                        project.name = name
                    if description is not None:
                        project.description = description
                    project.updated_at = datetime.now(timezone.utc)
                    self.save(registry)
                    return project
            raise KeyError(id)

    def activate_project(self, id: str) -> Project:
        """Set a project as the active project.

        The active project determines the working directory for new sessions.

        Args
        ----
        id:
            The project ID (slug) to activate.

        Returns
        -------
        The newly activated :class:`Project`.

        Raises
        ------
        KeyError
            If no project with the given ID exists.
        """
        with exclusive_file_lock(_projects_lock_path()):
            registry = self.load()
            found: Project | None = None
            for project in registry["projects"]:
                project.is_active = project.id == id
                if project.is_active:
                    found = project
                    project.updated_at = datetime.now(timezone.utc)
            if found is None:
                raise KeyError(id)
            registry["active_project_id"] = id
            self.save(registry)
            return found

    def get_active_project(self) -> Project | None:
        """Return the currently active project, or ``None`` if none is active."""
        registry = self.load()
        active_id = registry.get("active_project_id")
        if not active_id:
            return None
        for project in registry["projects"]:
            if project.id == active_id:
                return project
        return None

    def ensure_default(self, cwd: Path) -> Project:
        """Return the active project, creating a default one if the registry is empty.

        If no projects are registered, a new project is created from ``cwd``
        and automatically marked as active. This provides a seamless
        first-run experience without requiring explicit ``oh project add``.

        Args
        ----
        cwd:
            Directory to use as the default project root if the registry is empty.

        Returns
        -------
        The active :class:`Project`.

        Raises
        ------
        ValueError
            If ``cwd`` is not an existing directory.
        """
        with exclusive_file_lock(_projects_lock_path()):
            registry = self.load()
            if registry["projects"]:
                active = self.get_active_project()
                if active is not None:
                    return active
                return registry["projects"][0]
            resolved_cwd = cwd.resolve()
            if not resolved_cwd.is_dir():
                raise ValueError(f"Path is not an existing directory: {cwd}")
            project = Project(id=_slugify(resolved_cwd.name or "workspace"), name=resolved_cwd.name or "workspace", path=resolved_cwd, is_active=True)
            registry["projects"].append(project)
            registry["active_project_id"] = project.id
            self.save(registry)
            return project
