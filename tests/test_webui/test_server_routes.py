from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.services.session_storage import save_session_snapshot
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage
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
