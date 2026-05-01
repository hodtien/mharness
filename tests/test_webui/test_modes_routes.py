from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet"))


def test_modes_endpoint_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/modes").status_code == 401


def test_modes_returns_settings_fallback(tmp_path) -> None:
    """When no active session exists, /modes returns defaults from settings."""
    client = _client(tmp_path)

    response = client.get("/api/modes", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    body = response.json()
    # All required fields must be present
    for field in ("permission_mode", "fast_mode", "vim_enabled", "effort", "passes", "output_style", "theme"):
        assert field in body, f"Missing field: {field}"
    # Values should be booleans, strings, or ints as appropriate
    assert isinstance(body["fast_mode"], bool)
    assert isinstance(body["vim_enabled"], bool)
    assert isinstance(body["passes"], int)
    assert isinstance(body["theme"], str)
    assert isinstance(body["output_style"], str)
