from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    return home


@pytest.fixture()
def client(tmp_path, isolated_home) -> TestClient:
    return TestClient(create_app(token="legacy-startup-token", cwd=tmp_path, model="sonnet", spa_dir=""))


def _login(client: TestClient, password: str = "123456") -> dict[str, object]:
    response = client.post("/api/auth/login", json={"password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _auth_file(home: Path) -> Path:
    return home / ".harness" / "webui" / "auth.json"


def _auth_json(home: Path) -> dict[str, object]:
    return json.loads(_auth_file(home).read_text(encoding="utf-8"))


def _write_auth_json(home: Path, payload: dict[str, object]) -> None:
    _auth_file(home).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_login_accepts_json_body_and_rejects_wrong_default_password(client: TestClient) -> None:
    failure = client.post("/api/auth/login", json={"password": "wrong-password"})
    assert failure.status_code == 401

    body = _login(client)

    assert body["access_token"]
    assert body["refresh_token"]
    assert body["access_expires_in"] > 0
    assert body["refresh_expires_in"] > body["access_expires_in"]
    assert body["is_default_password"] is True


def test_access_token_authorizes_existing_protected_meta_route(
    client: TestClient,
    tmp_path: Path,
) -> None:
    body = _login(client)

    response = client.get(
        "/api/meta",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["cwd"] == str(tmp_path)


def test_validate_endpoint_reads_authorization_header(client: TestClient) -> None:
    body = _login(client)

    response = client.get(
        "/api/auth/validate",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}


def test_refresh_rotates_tokens_and_does_not_store_raw_refresh_token(
    client: TestClient,
    isolated_home: Path,
) -> None:
    first = _login(client)

    refresh = client.post(
        "/api/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )

    assert refresh.status_code == 200, refresh.text
    second = refresh.json()
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]

    persisted = _auth_file(isolated_home).read_text(encoding="utf-8")
    assert first["refresh_token"] not in persisted
    assert second["refresh_token"] not in persisted

    old_refresh = client.post(
        "/api/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert old_refresh.status_code == 401


def test_tokens_can_be_reused_after_app_restart(
    tmp_path: Path,
    isolated_home: Path,
) -> None:
    first_client = TestClient(
        create_app(token="first-startup-token", cwd=tmp_path, model="sonnet", spa_dir="")
    )
    body = _login(first_client)

    restarted_client = TestClient(
        create_app(token="second-startup-token", cwd=tmp_path, model="sonnet", spa_dir="")
    )
    response = restarted_client.get(
        "/api/meta",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert response.status_code == 200, response.text
    assert _auth_file(isolated_home).is_file()


def test_expired_access_token_can_be_refreshed_without_password(
    client: TestClient,
    isolated_home: Path,
) -> None:
    body = _login(client)
    auth = _auth_json(isolated_home)
    assert isinstance(auth.get("token_pair"), dict)
    auth["token_pair"]["access_expires_at"] = 0
    _write_auth_json(isolated_home, auth)

    expired = client.get(
        "/api/meta",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert expired.status_code == 401

    refresh = client.post(
        "/api/auth/refresh",
        json={"refresh_token": body["refresh_token"]},
    )

    assert refresh.status_code == 200, refresh.text
    refreshed = refresh.json()
    retried = client.get(
        "/api/meta",
        headers={"Authorization": f"Bearer {refreshed['access_token']}"},
    )
    assert retried.status_code == 200, retried.text


def test_change_password_clears_default_flag_revokes_tokens_and_rejects_old_password(
    client: TestClient,
    isolated_home: Path,
) -> None:
    body = _login(client)

    response = client.post(
        "/api/auth/change-password",
        json={"old_password": "123456", "new_password": "changed-password"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "is_default_password": False}
    assert _auth_json(isolated_home)["is_default_password"] is False

    old_login = client.post("/api/auth/login", json={"password": "123456"})
    assert old_login.status_code == 401

    revoked = client.get(
        "/api/meta",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert revoked.status_code == 401

    new_login = client.post("/api/auth/login", json={"password": "changed-password"})
    assert new_login.status_code == 200, new_login.text


def test_missing_refresh_returns_401_clears_tokens_and_allows_password_login_fallback(
    client: TestClient,
    isolated_home: Path,
) -> None:
    body = _login(client)

    response = client.post("/api/auth/refresh", json={})

    assert response.status_code == 401
    persisted = _auth_file(isolated_home).read_text(encoding="utf-8")
    assert body["access_token"] not in persisted
    assert body["refresh_token"] not in persisted

    revoked = client.get(
        "/api/meta",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert revoked.status_code == 401

    fallback = client.post("/api/auth/login", json={"password": "123456"})
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()["access_token"]


def test_invalid_refresh_returns_401_clears_tokens_and_allows_password_login_fallback(
    client: TestClient,
    isolated_home: Path,
) -> None:
    body = _login(client)

    response = client.post("/api/auth/refresh", json={"refresh_token": "not-current"})

    assert response.status_code == 401
    persisted = _auth_file(isolated_home).read_text(encoding="utf-8")
    assert body["access_token"] not in persisted
    assert body["refresh_token"] not in persisted

    revoked = client.get(
        "/api/meta",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert revoked.status_code == 401

    fallback = client.post("/api/auth/login", json={"password": "123456"})
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()["access_token"]
