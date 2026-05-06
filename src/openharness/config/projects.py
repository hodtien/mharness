"""Project model and registry helpers."""

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
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        self.path = self.path.resolve()
        self.created_at = self._to_aware(self.created_at)
        self.updated_at = self._to_aware(self.updated_at)

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["path"] = str(self.path)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
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
    def __init__(self, registry_path: Path | None = None) -> None:
        self.REGISTRY_PATH = registry_path or get_projects_registry_path()

    def load(self) -> dict[str, Any]:
        if not self.REGISTRY_PATH.exists():
            return {"projects": [], "active_project_id": None}
        try:
            data = json.loads(self.REGISTRY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"projects": [], "active_project_id": None}
        projects = [Project.from_dict(item) for item in data.get("projects", []) if isinstance(item, dict)]
        return {"projects": projects, "active_project_id": data.get("active_project_id")}

    def save(self, registry: dict[str, Any]) -> None:
        payload = {
            "projects": [project.to_dict() for project in registry["projects"]],
            "active_project_id": registry.get("active_project_id"),
        }
        atomic_write_text(self.REGISTRY_PATH, json.dumps(payload, indent=2) + "\n")

    def add_project(self, name: str, path: str | Path, description: str = "") -> Project:
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
        registry = self.load()
        active_id = registry.get("active_project_id")
        if not active_id:
            return None
        for project in registry["projects"]:
            if project.id == active_id:
                return project
        return None

    def ensure_default(self, cwd: Path) -> Project:
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
