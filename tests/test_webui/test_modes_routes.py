from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """Redirect ~/.openharness/settings.json into a tmp dir for these tests."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


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


def test_patch_modes_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.patch("/api/modes", json={"effort": "high"}).status_code == 401


def test_patch_modes_empty_body_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
    assert "At least one field" in response.json()["detail"]


def test_patch_modes_invalid_permission_mode_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"permission_mode": "invalid"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


def test_patch_modes_invalid_effort_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"effort": "ultrahigh"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


def test_patch_modes_passes_too_low_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"passes": 0},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


def test_patch_modes_passes_too_high_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"passes": 6},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422


def test_patch_modes_returns_updated_state(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"effort": "high", "passes": 3, "fast_mode": True},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effort"] == "high"
    assert body["passes"] == 3
    assert body["fast_mode"] is True


def test_patch_modes_all_valid_fields(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={
            "permission_mode": "plan",
            "effort": "low",
            "passes": 2,
            "fast_mode": False,
            "output_style": "minimal",
            "theme": "dark",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["permission_mode"] == "plan"
    assert body["effort"] == "low"
    assert body["passes"] == 2
    assert body["fast_mode"] is False
    assert body["output_style"] == "minimal"
    assert body["theme"] == "dark"


def test_patch_modes_permission_mode_values(tmp_path) -> None:
    """Every accepted permission_mode value is accepted without 422."""
    client = _client(tmp_path)
    for mode in ("default", "plan", "full_auto"):
        response = client.patch(
            "/api/modes",
            json={"permission_mode": mode},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200, f"mode={mode} should be accepted"


def test_patch_modes_vim_enabled_persists(tmp_path) -> None:
    """PATCH vim_enabled=True updates the response and persists to settings."""
    from openharness.config.settings import load_settings

    client = _client(tmp_path)

    # Enable vim keybindings
    response = client.patch(
        "/api/modes",
        json={"vim_enabled": True},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["vim_enabled"] is True

    # Persisted to settings.vim_mode
    settings = load_settings()
    assert settings.vim_mode is True

    # A subsequent GET reflects the persisted value
    get_response = client.get("/api/modes", headers={"Authorization": "Bearer test-token"})
    assert get_response.json()["vim_enabled"] is True


def test_patch_modes_vim_enabled_false(tmp_path) -> None:
    """PATCH vim_enabled=False disables vim keybindings and persists."""
    from openharness.config.settings import load_settings

    client = _client(tmp_path)

    # First enable, then disable
    client.patch(
        "/api/modes",
        json={"vim_enabled": True},
        headers={"Authorization": "Bearer test-token"},
    )
    response = client.patch(
        "/api/modes",
        json={"vim_enabled": False},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["vim_enabled"] is False

    settings = load_settings()
    assert settings.vim_mode is False
