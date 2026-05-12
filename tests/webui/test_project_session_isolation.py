"""Integration tests for per-project session/chat isolation.

Verifies that sessions, history, and resume flows are scoped to the active
project's working directory and do not cross-contaminate between projects.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage
from openharness.services.session_storage import (
    get_project_session_dir,
    list_session_snapshots,
    load_session_by_id,
    save_session_snapshot,
)
from openharness.webui.server.app import create_app


def _client(cwd: str, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=cwd, model="sonnet"))


def test_history_list_is_scoped_to_project(tmp_path, monkeypatch) -> None:
    """GET /api/history returns only sessions from the client's cwd, not other projects."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_a.mkdir()
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    # Create a session in project_a
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello from project A")],
        usage=UsageSnapshot(),
        session_id="a-001",
    )

    # Create a session in project_b
    save_session_snapshot(
        cwd=project_b,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello from project B")],
        usage=UsageSnapshot(),
        session_id="b-001",
    )

    # Client scoped to project_a should only see project_a's session
    client_a = _client(str(project_a))
    response_a = client_a.get("/api/history", headers={"Authorization": "Bearer test-token"})
    assert response_a.status_code == 200
    sessions_a = response_a.json()["sessions"]
    assert len(sessions_a) == 1
    assert sessions_a[0]["session_id"] == "a-001"

    # Client scoped to project_b should only see project_b's session
    client_b = _client(str(project_b))
    response_b = client_b.get("/api/history", headers={"Authorization": "Bearer test-token"})
    assert response_b.status_code == 200
    sessions_b = response_b.json()["sessions"]
    assert len(sessions_b) == 1
    assert sessions_b[0]["session_id"] == "b-001"


def test_history_detail_respects_project_scope(tmp_path, monkeypatch) -> None:
    """GET /api/history/{id} returns 404 when the session belongs to another project."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_a.mkdir()
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    # Save session in project_a
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("project A session")],
        usage=UsageSnapshot(),
        session_id="cross-001",
    )

    client_b = _client(str(project_b))

    # project_b client trying to read project_a's session should get 404
    response = client_b.get(
        "/api/history/cross-001", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 404


def test_delete_history_respects_project_scope(tmp_path, monkeypatch) -> None:
    """DELETE /api/history/{id} only deletes within the scoped project."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_a.mkdir()
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    # Save session in project_a
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("project A to delete")],
        usage=UsageSnapshot(),
        session_id="delete-001",
    )
    session_dir_a = get_project_session_dir(project_a)
    session_path_a = session_dir_a / "session-delete-001.json"
    assert session_path_a.exists()

    client_b = _client(str(project_b))

    # project_b client trying to delete project_a's session should get 404
    response = client_b.delete(
        "/api/history/delete-001", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 404

    # Verify project_a's session was NOT deleted
    assert session_path_a.exists()


def test_resume_session_respects_project_scope(tmp_path, monkeypatch) -> None:
    """POST /api/sessions with resume_id only finds sessions within the scoped project."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_a.mkdir()
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    # Save session in project_a
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("resumable from project A")],
        usage=UsageSnapshot(),
        session_id="resume-001",
    )

    client_b = _client(str(project_b))

    # project_b client trying to resume project_a's session should get 404
    response = client_b.post(
        "/api/sessions",
        headers={"Authorization": "Bearer test-token"},
        json={"resume_id": "resume-001"},
    )
    assert response.status_code == 404


def test_resume_session_loads_correct_project_data(tmp_path, monkeypatch) -> None:
    """When resuming within the correct project, messages are restored correctly."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_a.mkdir()

    # Save session in project_a
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("resumable message")],
        usage=UsageSnapshot(),
        session_id="resume-ok-001",
    )

    client_a = _client(str(project_a))

    # project_a client resuming its own session
    response = client_a.post(
        "/api/sessions",
        headers={"Authorization": "Bearer test-token"},
        json={"resume_id": "resume-ok-001"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resumed_from"] == "resume-ok-001"

    # Verify the session entry has the restored messages
    manager = client_a.app.state.webui_session_manager
    entry = manager.get(body["session_id"])
    assert entry is not None
    restored = entry.host._config.restore_messages
    assert restored is not None
    assert len(restored) == 1
    assert restored[0]["role"] == "user"


def test_get_project_session_dir_deduplication(tmp_path) -> None:
    """Two different cwd paths that resolve to the same directory get the same session dir."""
    project_a = tmp_path / "project_a"
    project_a.mkdir()

    # Resolve both to the same absolute path
    dir_a = str(project_a.resolve())

    # Same directory via different path representations
    dir_a_alt = project_a.resolve().as_posix()

    dir1 = get_project_session_dir(dir_a)
    dir2 = get_project_session_dir(dir_a_alt)

    assert dir1 == dir2, f"Same directory should produce same session dir: {dir1} vs {dir2}"


def test_session_dirs_are_different_for_different_projects(tmp_path) -> None:
    """Two distinct project directories produce distinct session directories."""
    project_a = tmp_path / "project_a"
    project_a.mkdir()
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    dir_a = get_project_session_dir(project_a)
    dir_b = get_project_session_dir(project_b)

    assert dir_a != dir_b, f"Different projects should have different session dirs: {dir_a} == {dir_b}"

    # Verify hash-based naming includes project-specific content
    name_a = dir_a.name
    name_b = dir_b.name
    assert name_a != name_b


def test_list_session_snapshots_empty_for_new_project(tmp_path) -> None:
    """A project with no saved sessions returns an empty list."""
    project = tmp_path / "brand_new_project"
    project.mkdir()

    sessions = list_session_snapshots(project, limit=10)
    assert sessions == []


def test_cross_project_latest_session_pointer(tmp_path, monkeypatch) -> None:
    """The latest.json pointer for each project is independent."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_a.mkdir()
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    # Save two sessions in project_a (a-002 is latest)
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("first in A")],
        usage=UsageSnapshot(),
        session_id="a-001",
    )
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("latest in A")],
        usage=UsageSnapshot(),
        session_id="a-002",
    )

    # Save one session in project_b
    save_session_snapshot(
        cwd=project_b,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("only in B")],
        usage=UsageSnapshot(),
        session_id="b-001",
    )

    # Load latest for project_a
    latest_a = load_session_by_id(project_a, "latest")
    assert latest_a is not None
    assert latest_a["session_id"] == "a-002"

    # Load latest for project_b
    latest_b = load_session_by_id(project_b, "latest")
    assert latest_b is not None
    assert latest_b["session_id"] == "b-001"


def test_session_storage_functions_isolated_by_cwd(tmp_path, monkeypatch) -> None:
    """Session storage functions operate independently per cwd argument."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_a.mkdir()
    project_b = tmp_path / "project_b"
    project_b.mkdir()

    # Save in project_a
    save_session_snapshot(
        cwd=project_a,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("A specific message")],
        usage=UsageSnapshot(),
        session_id="storage-a",
    )

    # Verify project_b has no sessions
    sessions_b = list_session_snapshots(project_b)
    assert sessions_b == []

    # Verify project_a has the session
    sessions_a = list_session_snapshots(project_a)
    assert len(sessions_a) == 1
    assert sessions_a[0]["session_id"] == "storage-a"

    # Load by ID from project_a should work
    loaded = load_session_by_id(project_a, "storage-a")
    assert loaded is not None
    assert loaded["session_id"] == "storage-a"

    # Load by ID from project_b should fail
    loaded_b = load_session_by_id(project_b, "storage-a")
    assert loaded_b is None


def test_multiple_sessions_per_project(tmp_path, monkeypatch) -> None:
    """A single project can have multiple saved sessions."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project = tmp_path / "multi_session_project"
    project.mkdir()

    # Create 5 sessions
    for i in range(5):
        save_session_snapshot(
            cwd=project,
            model="sonnet",
            system_prompt="system",
            messages=[ConversationMessage.from_user_text(f"session {i}")],
            usage=UsageSnapshot(),
            session_id=f"multi-{i:03d}",
        )

    # list should return all 5
    sessions = list_session_snapshots(project, limit=10)
    assert len(sessions) == 5

    # All session IDs should be present
    ids = {s["session_id"] for s in sessions}
    for i in range(5):
        assert f"multi-{i:03d}" in ids


def test_two_sessions_with_different_project_id_have_isolated_state(tmp_path, monkeypatch) -> None:
    """Two sessions created with different project_id values use separate project contexts.

    This is the core regression test for P16.3a: per-tab project isolation via
    ``?project_id=`` query parameter. Sessions must not share a global active
    project — each session carries its own project context.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    # Create the app with a separate global cwd so project_a/project_b are explicit projects.
    global_cwd = tmp_path / "global"
    global_cwd.mkdir()
    client = TestClient(create_app(token="test-token", cwd=str(global_cwd), model="sonnet"))
    auth = {"Authorization": "Bearer test-token"}

    # Register both projects so they are available via project_id
    resp_a = client.post("/api/projects", json={"name": "Project A", "path": str(project_a)}, headers=auth)
    assert resp_a.status_code == 201
    project_a_id = resp_a.json()["id"]

    resp_b = client.post("/api/projects", json={"name": "Project B", "path": str(project_b)}, headers=auth)
    assert resp_b.status_code == 201
    project_b_id = resp_b.json()["id"]

    # Create session 1 with ?project_id=project_a_id
    r1 = client.post(f"/api/sessions?project_id={project_a_id}", headers=auth)
    assert r1.status_code == 200
    session1 = r1.json()
    assert session1["project_id"] == project_a_id

    # Create session 2 with ?project_id=project_b_id
    r2 = client.post(f"/api/sessions?project_id={project_b_id}", headers=auth)
    assert r2.status_code == 200
    session2 = r2.json()
    assert session2["project_id"] == project_b_id

    # Verify both sessions are distinct
    assert session1["session_id"] != session2["session_id"]

    # Retrieve the session entries and check their cwd / project isolation
    manager = client.app.state.webui_session_manager

    entry1 = manager.get(session1["session_id"])
    assert entry1 is not None
    assert entry1.project_id == project_a_id
    assert entry1.host._config.cwd == str(project_a.resolve())

    entry2 = manager.get(session2["session_id"])
    assert entry2 is not None
    assert entry2.project_id == project_b_id
    assert entry2.host._config.cwd == str(project_b.resolve())

    # The global state (WebUIState) must NOT be affected by session creation.
    # It stays at the startup cwd / active project, independent of either session.
    state = client.app.state.webui
    assert state.cwd == global_cwd.resolve()
    assert state.active_project_id is not None
    assert state.active_project_id not in {project_a_id, project_b_id}

    # Verify session 3 without project_id inherits the global state
    r3 = client.post("/api/sessions", headers=auth)
    assert r3.status_code == 200
    session3 = r3.json()
    assert session3["project_id"] is None  # no explicit project_id passed

    entry3 = manager.get(session3["session_id"])
    assert entry3 is not None
    assert entry3.host._config.cwd == str(global_cwd.resolve())  # falls back to global cwd