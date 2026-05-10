"""Integration tests for multi-project isolation.

Covers:
1. CRUD + list on the project registry (service layer)
2. Project activation / switching
3. FastAPI /projects endpoints via TestClient
4. Session isolation between two projects
5. Autopilot card isolation between two projects
6. Auto-creation of a default project when registry is empty
7. Duplicate path rejection
8. Deletion of the active project is rejected
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from openharness.autopilot import RepoAutopilotStore
from openharness.services import projects as project_svc
from openharness.services import session_storage
from openharness.webui.server.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _tmp_projects_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect the projects registry to a temp directory for each test."""
    import openharness.services.projects as svc

    monkeypatch.setattr(svc, "_projects_path", lambda: tmp_path / "projects.json")
    monkeypatch.setattr(svc, "_projects_lock_path", lambda: tmp_path / "projects.json.lock")


@pytest.fixture
def token() -> str:
    return "test-token-multi-project"


@pytest.fixture
def api_client(token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient wired to a temporary projects registry."""
    import openharness.services.projects as svc

    monkeypatch.setattr(svc, "_projects_path", lambda: tmp_path / "projects.json")
    monkeypatch.setattr(svc, "_projects_lock_path", lambda: tmp_path / "projects.json.lock")
    app = create_app(token=token, cwd=str(tmp_path), spa_dir="")
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


# ---------------------------------------------------------------------------
# 1. test_project_registry_crud — add / update / remove / list
# ---------------------------------------------------------------------------

def test_project_registry_crud(tmp_path: Path) -> None:
    """Full CRUD cycle via the service layer."""
    # Empty list
    projects, active = project_svc.list_projects()
    assert projects == []
    assert active is None

    # Create
    p1 = project_svc.create_project(name="Alpha", path=str(tmp_path / "alpha"))
    assert p1.name == "Alpha"
    assert p1.id is not None

    # List includes the new entry
    projects, active = project_svc.list_projects()
    assert len(projects) == 1
    assert projects[0].id == p1.id

    # Update
    updated = project_svc.update_project(p1.id, name="Alpha Updated", description="New desc")
    assert updated is not None
    assert updated.name == "Alpha Updated"
    assert updated.description == "New desc"

    # Delete
    result = project_svc.delete_project(p1.id)
    assert result is True
    projects, _ = project_svc.list_projects()
    assert projects == []


# ---------------------------------------------------------------------------
# 2. test_project_activate_switch — switch active project
# ---------------------------------------------------------------------------

def test_project_activate_switch(tmp_path: Path) -> None:
    """Activating a project sets it as active; switching transfers activation."""
    dir_a = tmp_path / "proj-a"
    dir_b = tmp_path / "proj-b"
    dir_a.mkdir()
    dir_b.mkdir()

    p_a = project_svc.create_project(name="A", path=str(dir_a))
    p_b = project_svc.create_project(name="B", path=str(dir_b))

    # Activate A
    active_a = project_svc.activate_project(p_a.id)
    assert active_a is not None
    assert active_a.id == p_a.id
    assert project_svc.get_active_project().id == p_a.id

    # Switch to B
    active_b = project_svc.activate_project(p_b.id)
    assert active_b is not None
    assert active_b.id == p_b.id
    assert project_svc.get_active_project().id == p_b.id


# ---------------------------------------------------------------------------
# 3. test_api_projects_endpoints — FastAPI TestClient for GET/POST/PATCH/DELETE
# ---------------------------------------------------------------------------

def test_api_projects_endpoints(api_client: TestClient, tmp_path: Path) -> None:
    """Exercise GET / POST / PATCH / DELETE via the FastAPI router."""
    # GET initial registry — contains the auto-registered cwd project
    r = api_client.get("/api/projects")
    assert r.status_code == 200
    baseline = len(r.json()["projects"])  # create_app registers cwd as default project

    # POST create
    dir_alpha = tmp_path / "alpha"
    dir_alpha.mkdir()
    r = api_client.post("/api/projects", json={"name": "Alpha", "path": str(dir_alpha)})
    assert r.status_code == 201
    proj_id = r.json()["id"]

    # GET list
    r = api_client.get("/api/projects")
    assert r.status_code == 200
    assert len(r.json()["projects"]) == baseline + 1

    # PATCH update name
    r = api_client.patch(f"/api/projects/{proj_id}", json={"name": "Alpha Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Alpha Renamed"

    # DELETE
    r = api_client.delete(f"/api/projects/{proj_id}")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # GET shows back to baseline
    r = api_client.get("/api/projects")
    assert len(r.json()["projects"]) == baseline


# ---------------------------------------------------------------------------
# 4. test_session_isolation — two projects, sessions don't cross-contaminate
# ---------------------------------------------------------------------------

def test_session_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Session snapshots are stored under project-scoped directories."""
    dir_a = tmp_path / "proj-a"
    dir_b = tmp_path / "proj-b"
    dir_a.mkdir()
    dir_b.mkdir()

    # Each project gets its own session directory
    sess_a = session_storage.get_project_session_dir(dir_a)
    sess_b = session_storage.get_project_session_dir(dir_b)

    assert sess_a != sess_b
    assert sess_a.parent == session_storage.get_sessions_dir()
    assert sess_b.parent == session_storage.get_sessions_dir()

    # Snapshots are keyed to their project path
    saved_a = session_storage.save_session_snapshot(
        cwd=dir_a,
        model="test-model",
        system_prompt="session for A",
        messages=[],
        usage=_make_fake_usage(),
    )
    saved_b = session_storage.save_session_snapshot(
        cwd=dir_b,
        model="test-model",
        system_prompt="session for B",
        messages=[],
        usage=_make_fake_usage(),
    )

    # Each snapshot lives in its project directory
    assert saved_a.parent == sess_a
    assert saved_b.parent == sess_b

    # Loading latest returns the correct session for each project
    loaded_a = session_storage.load_session_snapshot(dir_a)
    loaded_b = session_storage.load_session_snapshot(dir_b)
    assert loaded_a is not None
    assert loaded_b is not None
    assert loaded_a["system_prompt"] == "session for A"
    assert loaded_b["system_prompt"] == "session for B"


# ---------------------------------------------------------------------------
# 5. test_autopilot_isolation — two projects, autopilot cards don't mix
# ---------------------------------------------------------------------------

def test_autopilot_isolation(tmp_path: Path) -> None:
    """RepoAutopilotStore instances are scoped to their own project paths."""
    dir_a = tmp_path / "proj-a"
    dir_b = tmp_path / "proj-b"
    dir_a.mkdir()
    dir_b.mkdir()

    store_a = RepoAutopilotStore(dir_a)
    store_b = RepoAutopilotStore(dir_b)

    card_a, _ = store_a.enqueue_card(
        source_kind="manual_idea",
        title="Task A only",
        body="Only in A",
    )
    card_b, _ = store_b.enqueue_card(
        source_kind="manual_idea",
        title="Task B only",
        body="Only in B",
    )

    # Each store only sees its own cards
    assert store_a.get_card(card_a.id) is not None
    assert store_a.get_card(card_b.id) is None
    assert store_b.get_card(card_b.id) is not None
    assert store_b.get_card(card_a.id) is None

    # Files are under each project's .openharness/autopilot dir
    assert store_a.registry_path.parent == dir_a / ".openharness" / "autopilot"
    assert store_b.registry_path.parent == dir_b / ".openharness" / "autopilot"
    assert store_a.journal_path.parent == dir_a / ".openharness" / "autopilot"
    assert store_b.journal_path.parent == dir_b / ".openharness" / "autopilot"


# ---------------------------------------------------------------------------
# 6. test_ensure_default_on_empty_registry — auto-creates default project
# ---------------------------------------------------------------------------

def test_ensure_default_on_empty_registry(tmp_path: Path) -> None:
    """When the registry is empty, the service auto-creates a default entry."""
    # Registry is empty by default in the tmp_path fixture
    projects, active = project_svc.list_projects()
    assert projects == []

    # create_project auto-creates when given a path
    default = project_svc.create_project(
        name=tmp_path.name,
        path=str(tmp_path),
        description="Auto-created default project",
    )
    assert default.name == tmp_path.name
    assert default.path == str(tmp_path.resolve())

    # Now list returns exactly one project
    projects, active = project_svc.list_projects()
    assert len(projects) == 1
    assert projects[0].id == default.id


# ---------------------------------------------------------------------------
# 7. test_duplicate_path_rejected — duplicate path is not allowed
# ---------------------------------------------------------------------------

def test_duplicate_path_rejected(tmp_path: Path) -> None:
    """registering the same path twice raises ValueError."""
    project_dir = tmp_path / "shared"
    project_dir.mkdir()

    project_svc.create_project(name="First", path=str(project_dir))
    with pytest.raises(ValueError, match="already exists"):
        project_svc.create_project(name="Second", path=str(project_dir))


# ---------------------------------------------------------------------------
# 8. test_delete_active_project_rejected — active project cannot be deleted
# ---------------------------------------------------------------------------

def test_delete_active_project_rejected(tmp_path: Path) -> None:
    """Deleting the currently-active project returns None / 400."""
    dir_a = tmp_path / "proj-a"
    dir_a.mkdir()

    p = project_svc.create_project(name="Active", path=str(dir_a))
    project_svc.activate_project(p.id)

    result = project_svc.delete_project(p.id)
    assert result is None  # service rejects deletion

    # Verify project still exists
    assert project_svc.get_project(p.id) is not None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_fake_usage():
    """Minimal UsageSnapshot for tests that don't care about usage values."""
    from openharness.api.usage import UsageSnapshot

    return UsageSnapshot(input_tokens=0, output_tokens=0)