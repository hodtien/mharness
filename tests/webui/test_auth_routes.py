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
        json={"old_password": "123456", "new_password": "Changed123!"},
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

    new_login = client.post("/api/auth/login", json={"password": "Changed123!"})
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


# ---------------------------------------------------------------------------
# Throttling tests
# ---------------------------------------------------------------------------


def _bad_login(client: TestClient, i: int) -> None:
    """Attempt a bad login, asserting it fails but is not a 429 (yet)."""
    r = client.post("/api/auth/login", json={"password": f"wrong-{i}"})
    assert r.status_code == 401, f"attempt {i} gave {r.status_code} instead of 401: {r.text}"


def test_repeated_failed_login_attempts_trigger_429_after_5(
    client: TestClient,
) -> None:
    """Five wrong passwords are 401; the 6th triggers a 429 lockout."""
    for i in range(1, 5):
        _bad_login(client, i)
    r6 = client.post("/api/auth/login", json={"password": "wrong-6"})
    assert r6.status_code == 429, f"Expected 429 but got {r6.status_code}: {r6.text}"
    assert "Retry-After" in r6.headers, r6.headers
    assert r6.json()["detail"].startswith("Too many failed attempts")


def test_lockout_rejects_all_passwords(
    client: TestClient,
) -> None:
    """Once locked out, even the correct password returns 429."""
    for i in range(1, 5):
        _bad_login(client, i)
    fifth = client.post("/api/auth/login", json={"password": "wrong-5"})
    assert fifth.status_code == 429, fifth.text

    r = client.post("/api/auth/login", json={"password": "123456"})
    assert r.status_code == 429


def test_successful_login_resets_failed_attempt_counter(
    client: TestClient,
) -> None:
    """A successful login clears the failed-attempt counter."""
    # Accumulate 4 failures
    for i in range(1, 5):
        _bad_login(client, i)
    # Succeed before the lockout threshold is reached
    body = _login(client)
    assert body["access_token"]
    # Counter is reset — we can fail 4 more times again
    for i in range(10, 14):
        _bad_login(client, i)
    fifth = client.post("/api/auth/login", json={"password": "wrong-last"})
    assert fifth.status_code == 429


def test_correct_password_rejected_during_lockout(
    client: TestClient,
) -> None:
    """The correct password must also return 429 during lockout (no oracle)."""
    for i in range(1, 5):
        _bad_login(client, i)
    fifth = client.post("/api/auth/login", json={"password": "wrong-5"})
    assert fifth.status_code == 429

    r = client.post("/api/auth/login", json={"password": "123456"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


# ---------------------------------------------------------------------------
# Password strength tests
# ---------------------------------------------------------------------------


def test_change_password_rejects_too_short(client: TestClient) -> None:
    _login(client)
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "123456", "new_password": "Abc1!"},
    )
    assert r.status_code == 422  # Pydantic min_length validation


def test_change_password_rejects_no_lowercase(client: TestClient) -> None:
    _login(client)
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "123456", "new_password": "UPPERCASE123!"},
    )
    assert r.status_code == 400
    assert "lowercase" in r.json()["detail"]


def test_change_password_rejects_no_uppercase(client: TestClient) -> None:
    _login(client)
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "123456", "new_password": "lowercase123!"},
    )
    assert r.status_code == 400
    assert "uppercase" in r.json()["detail"]


def test_change_password_rejects_no_digit(client: TestClient) -> None:
    _login(client)
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "123456", "new_password": "NoDigitsHere!"},
    )
    assert r.status_code == 400
    assert "digit" in r.json()["detail"]


def test_change_password_rejects_common_passwords(client: TestClient) -> None:
    _login(client)
    # These match the weak-allowlist entries exactly after lowercasing
    for weak in ("Password1", "Qwerty123", "Letmein123"):
        r = client.post(
            "/api/auth/change-password",
            json={"old_password": "123456", "new_password": weak},
        )
        assert r.status_code == 400, f"{weak!r} should be rejected but got {r.status_code}"
        assert "common" in r.json()["detail"].lower(), r.json()["detail"]


def test_change_password_accepts_strong_password(client: TestClient) -> None:
    _login(client)
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "123456", "new_password": "Str0ng!Pass"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # New password must work
    new_login = client.post("/api/auth/login", json={"password": "Str0ng!Pass"})
    assert new_login.status_code == 200, new_login.text
