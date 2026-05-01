"""Tests for /api/history routes — happy path and error path."""

from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage
from openharness.services.session_storage import get_project_session_dir, save_session_snapshot
from openharness.webui.server.app import create_app


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet"))


def test_list_history_empty_returns_empty_list(tmp_path, monkeypatch) -> None:
    """GET /api/history with no sessions returns 401 unauthenticated, 200 with empty sessions list."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    client = _client(tmp_path)
    assert client.get("/api/history").status_code == 401

    response = client.get("/api/history", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_list_history_with_one_session(tmp_path, monkeypatch) -> None:
    """After saving a session, GET /api/history returns a list with one item."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello history")],
        usage=UsageSnapshot(),
        session_id="sess-001",
    )

    client = _client(tmp_path)
    response = client.get("/api/history", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["session_id"] == "sess-001"


def test_get_history_detail_returns_correct_data(tmp_path, monkeypatch) -> None:
    """GET /api/history/{session_id} returns the saved session snapshot."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("secret message")],
        usage=UsageSnapshot(),
        session_id="sess-002",
    )

    client = _client(tmp_path)
    response = client.get(
        "/api/history/sess-002", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "sess-002"
    assert body["model"] == "sonnet"
    assert body["cwd"] == str(tmp_path.resolve())
    assert body["messages"][0]["content"][0]["text"] == "secret message"


def test_get_history_detail_unknown_id_returns_404(tmp_path, monkeypatch) -> None:
    """GET /api/history/{unknown_id} returns 404."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    client = _client(tmp_path)
    response = client.get(
        "/api/history/nonexistent", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 404


def test_delete_history_removes_file(tmp_path, monkeypatch) -> None:
    """DELETE /api/history/{session_id} removes the session file and returns 204."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("to be deleted")],
        usage=UsageSnapshot(),
        session_id="sess-003",
    )

    session_dir = get_project_session_dir(tmp_path)
    session_path = session_dir / "session-sess-003.json"
    assert session_path.exists()

    client = _client(tmp_path)

    assert client.delete("/api/history/sess-003").status_code == 401

    response = client.delete(
        "/api/history/sess-003", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 204
    assert not session_path.exists()


def test_delete_history_unknown_id_returns_404(tmp_path, monkeypatch) -> None:
    """DELETE /api/history/{unknown_id} returns 404 when session does not exist."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    client = _client(tmp_path)
    response = client.delete(
        "/api/history/never-existed", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 404
