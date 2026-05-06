"""Tests for the projects service layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openharness.services.projects import (
    Project,
    activate_project,
    create_project,
    delete_project,
    get_active_project,
    get_project,
    list_projects,
    update_project,
)


@pytest.fixture(autouse=True)
def _tmp_projects_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect the projects registry to a temp directory."""
    import openharness.services.projects as svc

    monkeypatch.setattr(svc, "_projects_path", lambda: tmp_path / "projects.json")
    monkeypatch.setattr(svc, "_projects_lock_path", lambda: tmp_path / "projects.json.lock")


class TestProjectModel:
    def test_asdict(self) -> None:
        p = Project(id="abc", name="My Proj", path="/tmp/foo", description="A test", created_at="2026-01-01T00:00:00Z")
        d = p.__dict__
        assert d["id"] == "abc"
        assert d["name"] == "My Proj"
        assert d["path"] == "/tmp/foo"
        assert d["description"] == "A test"
        assert d["created_at"] == "2026-01-01T00:00:00Z"


class TestListProjects:
    def test_empty(self) -> None:
        projects, active = list_projects()
        assert projects == []
        assert active is None

    def test_returns_active_id(self) -> None:
        import openharness.services.projects as svc

        path = svc._projects_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"projects": [], "active_project_id": "abc"}', encoding="utf-8")
        projects, active = list_projects()
        assert active == "abc"

    def test_skips_malformed_entries(self) -> None:
        import openharness.services.projects as svc

        path = svc._projects_path()
        path.write_text(
            json.dumps(
                {
                    "projects": [
                        {"id": "a", "name": "A", "path": "/a"},
                        {"id": "b"},  # missing name/path
                        {"name": "C", "path": "/c"},
                    ],
                    "active_project_id": None,
                }
            ),
            encoding="utf-8",
        )
        projects, _ = list_projects()
        assert len(projects) == 1
        assert projects[0].name == "A"


class TestCreateProject:
    def test_creates_and_returns(self, tmp_path: Path) -> None:
        project = create_project(name="My App", path=str(tmp_path), description="Test desc")
        assert project.name == "My App"
        assert project.path == str(tmp_path.resolve())
        assert project.description == "Test desc"
        assert project.id is not None

    def test_duplicate_collision(self, tmp_path: Path) -> None:
        create_project(name="First", path=str(tmp_path))
        with pytest.raises(ValueError):
            create_project(name="Second", path=str(tmp_path))


class TestGetProject:
    def test_found(self, tmp_path: Path) -> None:
        created = create_project(name="Foo", path=str(tmp_path))
        assert get_project(created.id) is not None
        assert get_project(created.id).name == "Foo"

    def test_not_found(self) -> None:
        assert get_project("does-not-exist") is None


class TestUpdateProject:
    def test_updates_name(self, tmp_path: Path) -> None:
        p = create_project(name="Old", path=str(tmp_path))
        updated = update_project(p.id, name="New")
        assert updated is not None
        assert updated.name == "New"

    def test_updates_description(self, tmp_path: Path) -> None:
        p = create_project(name="Foo", path=str(tmp_path))
        updated = update_project(p.id, description="New desc")
        assert updated is not None
        assert updated.description == "New desc"

    def test_not_found(self) -> None:
        assert update_project("does-not-exist", name="X") is None


class TestDeleteProject:
    def test_deletes(self, tmp_path: Path) -> None:
        p = create_project(name="ToDelete", path=str(tmp_path))
        assert delete_project(p.id) is True
        assert get_project(p.id) is None

    def test_not_found(self) -> None:
        assert delete_project("does-not-exist") is False


class TestActivateProject:
    def test_activates(self, tmp_path: Path) -> None:
        p = create_project(name="ToActivate", path=str(tmp_path))
        activated = activate_project(p.id)
        assert activated is not None
        assert activated.id == p.id
        projects, active_id = list_projects()
        assert active_id == p.id

    def test_not_found(self) -> None:
        assert activate_project("does-not-exist") is None


class TestGetActiveProject:
    def test_none_when_no_active(self) -> None:
        assert get_active_project() is None

    def test_returns_active(self, tmp_path: Path) -> None:
        p = create_project(name="ActiveProj", path=str(tmp_path))
        activate_project(p.id)
        assert get_active_project() is not None
        assert get_active_project().id == p.id
