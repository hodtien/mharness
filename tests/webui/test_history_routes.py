from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app
from openharness.services.session_storage import get_project_session_dir, save_session_snapshot
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet"))


def test_list_history_empty_returns_empty_list(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    client = _client(tmp_path)

    assert client.get("/api/history").status_code == 401

    response = client.get("/api/history", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_list_history_with_one_session(tmp_path, monkeypatch) -> None:
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
    sessions = response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sess-001"


def test_get_history_detail_loads_correct_data(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("specific detail text")],
        usage=UsageSnapshot(),
        session_id="sess-001",
    )
    client = _client(tmp_path)

    response = client.get(
        "/api/history/sess-001", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "sess-001"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == [
        {"type": "text", "text": "specific detail text"}
    ]


def test_get_history_detail_unknown_id_returns_404(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    client = _client(tmp_path)

    response = client.get(
        "/api/history/nonexistent", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 404


def test_delete_history_removes_file(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("delete me")],
        usage=UsageSnapshot(),
        session_id="sess-001",
    )
    session_path = get_project_session_dir(tmp_path) / "session-sess-001.json"
    assert session_path.exists()
    client = _client(tmp_path)

    response = client.delete(
        "/api/history/sess-001", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 204
    assert not session_path.exists()

    missing = client.delete(
        "/api/history/nonexistent", headers={"Authorization": "Bearer test-token"}
    )
    assert missing.status_code == 404
