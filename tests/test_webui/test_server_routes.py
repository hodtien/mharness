from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.services.session_storage import get_project_session_dir, save_session_snapshot
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, ToolResultBlock, ToolUseBlock
from openharness.webui.server.app import create_app


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet"))


def test_health_is_available_without_auth(tmp_path) -> None:
    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_meta_requires_auth_and_returns_bootstrap_state(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/meta").status_code == 401

    response = client.get("/api/meta", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["cwd"] == str(tmp_path.resolve())
    assert response.json()["model"] == "sonnet"


def test_sessions_endpoint_requires_auth_and_returns_list(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/sessions").status_code == 401

    response = client.get("/api/sessions", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert isinstance(response.json()["sessions"], list)


def test_tasks_endpoint_requires_auth_and_returns_list(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/tasks").status_code == 401

    response = client.get("/api/tasks", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {"tasks": []}


def test_cron_jobs_endpoint_requires_auth_and_returns_list(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    client = _client(tmp_path)

    assert client.get("/api/cron/jobs").status_code == 401

    response = client.get(
        "/api/cron/jobs", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


def test_non_bearer_authorization_header_is_rejected(tmp_path) -> None:
    response = _client(tmp_path).get(
        "/api/meta", headers={"Authorization": "test-token"}
    )

    assert response.status_code == 401


def test_query_token_is_accepted_for_bootstrap_clients(tmp_path) -> None:
    response = _client(tmp_path).get("/api/meta?token=test-token")

    assert response.status_code == 200


def test_history_endpoint_requires_auth_and_lists_session_snapshots(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello history")],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    client = _client(tmp_path)

    assert client.get("/api/history").status_code == 401

    response = client.get("/api/history?limit=20", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {
        "sessions": [
            {
                "session_id": "abc123",
                "summary": "hello history",
                "message_count": 1,
                "model": "sonnet",
                "created_at": response.json()["sessions"][0]["created_at"],
            }
        ]
    }


def test_history_detail_returns_session_and_truncates_tool_results(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    long_result = "x" * 501
    tool_use = ToolUseBlock(id="toolu_123", name="read_file", input={})
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[
            ConversationMessage.from_user_text("hello history"),
            ConversationMessage(role="assistant", content=[tool_use]),
            ConversationMessage.from_user_content(
                [ToolResultBlock(tool_use_id="toolu_123", content=long_result)]
            ),
        ],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    client = _client(tmp_path)

    response = client.get(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "abc123"
    result = body["messages"][2]["content"][0]
    assert result["type"] == "tool_result"
    assert result["content"] == f"{'x' * 500}… [truncated 1 chars]"
    assert result["truncated"] is True
    assert result["original_length"] == 501

    missing = client.get(
        "/api/history/missing", headers={"Authorization": "Bearer test-token"}
    )
    assert missing.status_code == 404


def test_history_delete_removes_session_and_clears_latest_when_matching(
    tmp_path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello history")],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    session_dir = get_project_session_dir(tmp_path)
    session_path = session_dir / "session-abc123.json"
    latest_path = session_dir / "latest.json"
    assert session_path.exists()
    assert latest_path.exists()

    client = _client(tmp_path)

    assert client.delete("/api/history/abc123").status_code == 401

    response = client.delete(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 204
    assert response.content == b""
    assert not session_path.exists()
    assert not latest_path.exists()

    missing = client.delete(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )
    assert missing.status_code == 404


def test_history_delete_keeps_latest_pointing_to_other_session(
    tmp_path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("first")],
        usage=UsageSnapshot(),
        session_id="aaa111",
    )
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("second")],
        usage=UsageSnapshot(),
        session_id="bbb222",
    )
    session_dir = get_project_session_dir(tmp_path)
    older_path = session_dir / "session-aaa111.json"
    newer_path = session_dir / "session-bbb222.json"
    latest_path = session_dir / "latest.json"
    assert latest_path.exists()

    client = _client(tmp_path)

    response = client.delete(
        "/api/history/aaa111", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 204
    assert not older_path.exists()
    # latest.json points to the most recently saved session (bbb222), so it stays.
    assert latest_path.exists()
    assert newer_path.exists()


def test_post_sessions_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    assert client.post("/api/sessions").status_code == 401


def test_post_sessions_creates_fresh_session_without_body(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    client = _client(tmp_path)

    response = client.post(
        "/api/sessions", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["session_id"], str) and body["session_id"]
    assert body["resumed_from"] is None
    assert body["active"] is False

    manager = client.app.state.webui_session_manager
    entry = manager.get(body["session_id"])
    assert entry is not None
    assert entry.host._config.restore_messages is None


def test_post_sessions_with_resume_id_loads_snapshot(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("resume me please")],
        usage=UsageSnapshot(),
        session_id="resume99",
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/sessions",
        headers={"Authorization": "Bearer test-token"},
        json={"resume_id": "resume99"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resumed_from"] == "resume99"

    manager = client.app.state.webui_session_manager
    entry = manager.get(body["session_id"])
    assert entry is not None
    restored = entry.host._config.restore_messages
    assert restored is not None and len(restored) == 1
    assert restored[0]["role"] == "user"


def test_post_sessions_unknown_resume_id_returns_404(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    client = _client(tmp_path)

    response = client.post(
        "/api/sessions",
        headers={"Authorization": "Bearer test-token"},
        json={"resume_id": "missing"},
    )
    assert response.status_code == 404


def test_history_delete_removes_latest_only_session(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("latest only")],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    session_dir = get_project_session_dir(tmp_path)
    (session_dir / "session-abc123.json").unlink()
    latest_path = session_dir / "latest.json"
    assert latest_path.exists()

    client = _client(tmp_path)

    response = client.delete(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 204
    assert not latest_path.exists()
