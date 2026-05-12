"""Tests for the projects service layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openharness.services.projects import (
    Project,
    activate_project,
    cleanup_projects,
    create_project,
    delete_project,
    get_active_project,
    get_project,
    get_project_metadata,
    list_projects,
    list_projects_with_metadata,
    update_project,
    _is_temp_like,
    _is_worktree_like,
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


class TestIsTempLike:
    def test_pytest_cache_dir(self) -> None:
        assert _is_temp_like("/private/var/folders/xx/pytest123") is True
        assert _is_temp_like("/Users/me/project/.pytest") is True
        assert _is_temp_like("/tmp/some-dir/.pytest_cache") is True

    def test_pycache_dir(self) -> None:
        assert _is_temp_like("/workspace/app/__pycache__") is True
        assert _is_temp_like("/private/var/folders/y/__pycache__") is True

    def test_tmp_path(self) -> None:
        assert _is_temp_like("/tmp/random") is True
        assert _is_temp_like("/tmp/pytest-abc") is True

    def test_private_tmp(self) -> None:
        assert _is_temp_like("/private/tmp/xyz") is True

    def test_real_project(self) -> None:
        assert _is_temp_like("/workspace/my-app") is False
        assert _is_temp_like("/Users/me/code/project") is False
        assert _is_temp_like("/var/www/app") is False
        assert _is_temp_like("/home/user/projects/app") is False
        # macOS temp dir with no pytest association is not temp-like
        assert _is_temp_like("/private/var/folders/51/abc123") is False
        # macOS temp dir with no pytest association is not temp-like
        assert _is_temp_like("/private/var/folders/51/abc123") is False


class TestIsWorktreeLike:
    def test_git_worktree_dir(self) -> None:
        assert _is_worktree_like("/repo/.git/worktrees/feature") is True
        assert _is_worktree_like("/repo/.git/worktree/feature") is True
        assert _is_worktree_like("/repo/.git/worktrees/") is True

    def test_real_project(self) -> None:
        assert _is_worktree_like("/workspace/my-app") is False
        assert _is_worktree_like("/repo/.git/objects") is False
        assert _is_worktree_like("/repo/.git/refs/heads") is False


class TestGetProjectMetadata:
    def test_existing_project(self) -> None:
        real_dir = Path("/Users/hodtien/.openharness/worktrees/autopilot+ap-755d6eae/test-real-project")
        real_dir.mkdir(exist_ok=True)
        p = create_project(name="Real App", path=str(real_dir))
        meta = get_project_metadata(p)
        assert meta.exists is True
        assert meta.is_temp_like is False
        assert meta.is_worktree_like is False

    def test_missing_project(self) -> None:
        p = Project(id="x", name="Gone", path="/nonexistent/gone-path-xyz", created_at=None)
        meta = get_project_metadata(p)
        assert meta.exists is False
        assert meta.is_temp_like is False

    def test_temp_like_project(self) -> None:
        p = Project(id="x", name="Pytest", path="/private/tmp/pytest123", created_at=None)
        meta = get_project_metadata(p)
        assert meta.exists is False
        assert meta.is_temp_like is True


class TestListProjectsWithMetadata:
    def test_returns_metadata_for_all_projects(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        real = create_project(name="Real", path=str(real_dir))
        gone = create_project(name="Gone", path="/nonexistent/gone")
        items, active_id = list_projects_with_metadata()
        ids = {item.project.id for item in items}
        assert real.id in ids
        assert gone.id in ids

    def test_filter_missing_only(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        create_project(name="Real", path=str(real_dir))
        gone = create_project(name="Gone", path="/nonexistent/gone")
        items, _ = list_projects_with_metadata({"missing_only": True})
        assert len(items) == 1
        assert items[0].project.id == gone.id
        assert items[0].project.name == "Gone"

    def test_filter_temp_like_only(self, tmp_path: Path) -> None:
        # Use /workspace paths that won't be flagged as temp-like
        create_project(name="Real", path="/workspace/my-project")
        temp = create_project(name="Temp", path="/tmp/pytest-abc")
        items, _ = list_projects_with_metadata({"temp_like_only": True})
        assert len(items) == 1
        assert items[0].project.name == "Temp"

    def test_filter_exclude_active(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "active"
        real_dir.mkdir()
        p = create_project(name="ActiveProj", path=str(real_dir))
        activate_project(p.id)
        items, active_id = list_projects_with_metadata({"exclude_active": True})
        assert all(item.project.id != active_id for item in items)


class TestCleanupProjects:
    def test_cleanup_removes_only_matching_projects(self, tmp_path: Path) -> None:
        """Verify cleanup only unregisters records — it must not delete disk directories."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        real = create_project(name="Real", path=str(real_dir))
        gone = create_project(name="Gone", path="/nonexistent/gone")
        activate_project(real.id)

        deleted = cleanup_projects(missing_only=True)
        assert len(deleted) == 1
        assert deleted[0] == gone.id
        # Active project must not be deleted
        _, active_id = list_projects()
        assert active_id == real.id
        # Directory must still exist on disk
        assert real_dir.exists(), "cleanup must never delete project directories from disk"
        assert real_dir.is_dir()

    def test_cleanup_dry_run(self, tmp_path: Path) -> None:
        gone = create_project(name="Gone", path="/nonexistent/gone")
        deleted = cleanup_projects(missing_only=True, dry_run=True)
        assert deleted == [gone.id]
        # Project must still exist in registry
        assert get_project(gone.id) is not None

    def test_cleanup_temp_like(self) -> None:
        temp1 = create_project(name="Temp1", path="/private/tmp/pytest-a")
        temp2 = create_project(name="Temp2", path="/tmp/pytest-b")
        deleted = cleanup_projects(temp_like_only=True)
        assert set(deleted) == {temp1.id, temp2.id}

    def test_cleanup_excludes_active(self, tmp_path: Path) -> None:
        active_dir = tmp_path / "active"
        active_dir.mkdir()
        p = create_project(name="Active", path=str(active_dir))
        activate_project(p.id)
        deleted = cleanup_projects(missing_only=True)
        assert p.id not in deleted
