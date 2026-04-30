from __future__ import annotations

from fastapi.testclient import TestClient

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


def test_sessions_endpoint_still_works(tmp_path) -> None:
    response = _client(tmp_path).get(
        "/api/sessions", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert isinstance(response.json()["sessions"], list)


def test_tasks_endpoint_still_works(tmp_path) -> None:
    response = _client(tmp_path).get(
        "/api/tasks", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"tasks": []}


def test_cron_jobs_endpoint_still_works(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    response = _client(tmp_path).get(
        "/api/cron/jobs", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


def test_query_token_is_accepted_for_bootstrap_clients(tmp_path) -> None:
    response = _client(tmp_path).get("/api/meta?token=test-token")

    assert response.status_code == 200
