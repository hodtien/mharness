"""Tests for src/openharness/config/projects.py."""

from __future__ import annotations

import json

import pytest

from openharness.config.projects import Project, ProjectRegistry, _slugify

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry(tmp_path):
    """A registry pointing at a temporary projects.json."""
    fake_data = tmp_path / "data"
    fake_data.mkdir()
    registry_path = fake_data / "projects.json"
    return ProjectRegistry(registry_path=registry_path)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def raw_json(registry: ProjectRegistry) -> dict:
    if not registry.REGISTRY_PATH.exists():
        return {"projects": [], "active_project_id": None}
    return json.loads(registry.REGISTRY_PATH.read_text())


# ---------------------------------------------------------------------------
# Project model
# ---------------------------------------------------------------------------

class TestProjectModel:
    def test_to_dict_roundtrip(self):
        p = Project(id="my-project", name="My Project", path="/tmp/my-project")
        d = p.to_dict()
        restored = Project.from_dict(d)
        assert restored.name == p.name
        assert restored.path == p.path
        assert restored.is_active is False

    def test_path_resolved_absolute(self):
        p = Project(id="test", name="Test", path=".")
        assert p.path.is_absolute()

    def test_active_flag_roundtrip(self):
        p = Project(id="active", name="Active", path="/tmp/active", is_active=True)
        d = p.to_dict()
        assert d["is_active"] is True
        restored = Project.from_dict(d)
        assert restored.is_active is True

    def test_description_default_empty(self):
        p = Project(id="d", name="D", path="/tmp/d")
        assert p.description == ""


# ---------------------------------------------------------------------------
# ProjectRegistry.load / save
# ---------------------------------------------------------------------------

class TestLoadSave:
    def test_load_empty_when_file_missing(self, registry):
        result = registry.load()
        assert result["projects"] == []
        assert result["active_project_id"] is None

    def test_load_empty_on_corrupt_json(self, registry):
        registry.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        registry.REGISTRY_PATH.write_text("{invalid")
        result = registry.load()
        assert result["projects"] == []

    def test_save_and_load_roundtrip(self, registry):
        project = Project(id="foo", name="Foo", path="/tmp/foo")
        registry.save({"projects": [project], "active_project_id": None})
        result = registry.load()
        assert len(result["projects"]) == 1
        assert result["projects"][0].id == "foo"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestAddProject:
    def test_add_creates_project(self, registry, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        p = registry.add_project("My Project", project_dir, description="A test project")
        assert p.name == "My Project"
        assert p.path == project_dir.resolve()
        assert p.description == "A test project"
        assert p.is_active is False

    def test_add_invalid_path_raises(self, registry, tmp_path):
        nonexistent = tmp_path / "does-not-exist"
        with pytest.raises(ValueError, match="not an existing directory"):
            registry.add_project("Bad", nonexistent)

    def test_add_duplicate_path_raises(self, registry, tmp_path):
        project_dir = tmp_path / "dup-path"
        project_dir.mkdir()
        registry.add_project("First", project_dir)
        with pytest.raises(ValueError, match="duplicate project path"):
            registry.add_project("Second", project_dir)

    def test_add_duplicate_id_raises(self, registry, tmp_path):
        dir_a = tmp_path / "proj-a"
        dir_b = tmp_path / "proj-b"
        dir_a.mkdir()
        dir_b.mkdir()
        registry.add_project("my-project", dir_a)
        with pytest.raises(ValueError, match="duplicate project name"):
            registry.add_project("my project", dir_b)

    def test_id_is_slug_of_name(self, registry, tmp_path):
        project_dir = tmp_path / "x"
        project_dir.mkdir()
        p = registry.add_project("Some Name", project_dir)
        assert p.id == "some-name"


class TestRemoveProject:
    def test_remove_existing_returns_true(self, registry, tmp_path):
        project_dir = tmp_path / "to-remove"
        project_dir.mkdir()
        p = registry.add_project("Remove Me", project_dir)
        assert registry.remove_project(p.id) is True
        assert registry.load()["projects"] == []

    def test_remove_nonexistent_returns_false(self, registry):
        assert registry.remove_project("nonexistent-id") is False

    def test_remove_active_clears_active_id(self, registry, tmp_path):
        project_dir = tmp_path / "active-proj"
        project_dir.mkdir()
        p = registry.add_project("Active", project_dir)
        registry.activate_project(p.id)
        registry.remove_project(p.id)
        assert raw_json(registry)["active_project_id"] is None


class TestUpdateProject:
    def test_update_name(self, registry, tmp_path):
        project_dir = tmp_path / "upd-name"
        project_dir.mkdir()
        p = registry.add_project("Original Name", project_dir)
        updated = registry.update_project(p.id, name="New Name")
        assert updated.name == "New Name"
        # id is unchanged
        assert updated.id == p.id

    def test_update_description(self, registry, tmp_path):
        project_dir = tmp_path / "upd-desc"
        project_dir.mkdir()
        p = registry.add_project("Desc Test", project_dir)
        updated = registry.update_project(p.id, description="New description")
        assert updated.description == "New description"

    def test_update_both(self, registry, tmp_path):
        project_dir = tmp_path / "upd-both"
        project_dir.mkdir()
        p = registry.add_project("Both", project_dir)
        updated = registry.update_project(p.id, name="New Name", description="New desc")
        assert updated.name == "New Name"
        assert updated.description == "New desc"

    def test_update_nonexistent_raises_keyerror(self, registry):
        with pytest.raises(KeyError):
            registry.update_project("nonexistent-id", name="X")


# ---------------------------------------------------------------------------
# activation
# ---------------------------------------------------------------------------

class TestActivateProject:
    def test_activate_marks_one_active(self, registry, tmp_path):
        dir_a = tmp_path / "proj-a"
        dir_b = tmp_path / "proj-b"
        dir_a.mkdir()
        dir_b.mkdir()
        p_a = registry.add_project("Project A", dir_a)
        registry.add_project("Project B", dir_b)
        registry.activate_project(p_a.id)
        active = registry.get_active_project()
        assert active is not None
        assert active.id == p_a.id

    def test_activate_clears_others(self, registry, tmp_path):
        dir_a = tmp_path / "proj-a"
        dir_b = tmp_path / "proj-b"
        dir_a.mkdir()
        dir_b.mkdir()
        p_a = registry.add_project("Project A", dir_a)
        p_b = registry.add_project("Project B", dir_b)
        registry.activate_project(p_a.id)
        registry.activate_project(p_b.id)
        projects = registry.load()["projects"]
        active_list = [p for p in projects if p.is_active]
        assert len(active_list) == 1
        assert active_list[0].id == p_b.id

    def test_activate_nonexistent_raises(self, registry):
        with pytest.raises(KeyError):
            registry.activate_project("bad-id")

    def test_get_active_project_none_when_no_active(self, registry):
        assert registry.get_active_project() is None


# ---------------------------------------------------------------------------
# ensure_default
# ---------------------------------------------------------------------------

class TestEnsureDefault:
    def test_creates_project_when_empty(self, registry, tmp_path):
        cwd = tmp_path / "workspace"
        cwd.mkdir()
        p = registry.ensure_default(cwd)
        assert p.name == "workspace"
        assert p.path == cwd.resolve()
        assert p.is_active is True
        assert registry.get_active_project() is not None

    def test_returns_existing_when_not_empty(self, registry, tmp_path):
        dir_a = tmp_path / "proj-a"
        dir_a.mkdir()
        p_a = registry.add_project("Project A", dir_a)
        registry.activate_project(p_a.id)
        cwd = tmp_path / "other"
        cwd.mkdir()
        p = registry.ensure_default(cwd)
        assert p.id == p_a.id

    def test_returns_active_even_if_not_first(self, registry, tmp_path):
        dir_a = tmp_path / "proj-a"
        dir_b = tmp_path / "proj-b"
        dir_a.mkdir()
        dir_b.mkdir()
        registry.add_project("Project A", dir_a)
        p_b = registry.add_project("Project B", dir_b)
        registry.activate_project(p_b.id)
        cwd = tmp_path / "new"
        cwd.mkdir()
        p = registry.ensure_default(cwd)
        assert p.id == p_b.id


# ---------------------------------------------------------------------------
# duplicate prevention
# ---------------------------------------------------------------------------

class TestDuplicatePrevention:
    def test_same_path_twice_raises(self, registry, tmp_path):
        project_dir = tmp_path / "shared"
        project_dir.mkdir()
        registry.add_project("First", project_dir)
        with pytest.raises(ValueError, match="duplicate project path"):
            registry.add_project("Second", project_dir)

    def test_same_slug_twice_raises(self, registry, tmp_path):
        dir_a = tmp_path / "proj-a"
        dir_b = tmp_path / "proj-b"
        dir_a.mkdir()
        dir_b.mkdir()
        registry.add_project("Test Project", dir_a)
        with pytest.raises(ValueError, match="duplicate project name"):
            registry.add_project("TEST PROJECT", dir_b)

    def test_ensure_default_idempotent(self, registry, tmp_path):
        cwd = tmp_path / "single"
        cwd.mkdir()
        registry.ensure_default(cwd)
        registry.ensure_default(cwd)  # must not raise
        projects = registry.load()["projects"]
        assert len(projects) == 1


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_lowercase(self):
        assert _slugify("My Project") == "my-project"

    def test_multiple_spaces(self):
        assert _slugify("Hello   World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Test (v2)!") == "test-v2"

    def test_strips_trailing_hyphens(self):
        assert _slugify("Project  ") == "project"

    def test_empty_name(self):
        assert _slugify("   ") == ""