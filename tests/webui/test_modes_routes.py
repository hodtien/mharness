"""Tests for the WebUI modes routes (P2.6).

Covers the scenarios required by the task:

* GET /api/modes returns the documented field set.
* PATCH /api/modes with valid values returns 200 and the changed values.
* PATCH /api/modes with an invalid effort returns 422.
* PATCH /api/modes with permission_mode=full_auto persists to settings.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.config.settings import load_settings
from openharness.webui.server.app import create_app

EXPECTED_FIELDS = (
    "permission_mode",
    "fast_mode",
    "vim_enabled",
    "effort",
    "passes",
    "output_style",
    "theme",
)

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """Redirect ~/.openharness/settings.json into a tmp dir for these tests."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


def test_get_modes_returns_expected_fields(tmp_path) -> None:
    """GET /api/modes returns the full field set with the documented types."""
    client = _client(tmp_path)

    response = client.get("/api/modes", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    for field in EXPECTED_FIELDS:
        assert field in body, f"Missing field: {field}"
    assert isinstance(body["permission_mode"], str)
    assert isinstance(body["fast_mode"], bool)
    assert isinstance(body["vim_enabled"], bool)
    assert isinstance(body["effort"], str)
    assert isinstance(body["passes"], int)
    assert isinstance(body["output_style"], str)
    assert isinstance(body["theme"], str)


def test_patch_modes_with_valid_values_returns_200_and_applies_changes(tmp_path) -> None:
    """PATCH with valid values returns 200 and the response reflects the changes."""
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"effort": "high", "passes": 3, "fast_mode": True},
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["effort"] == "high"
    assert body["passes"] == 3
    assert body["fast_mode"] is True

    # A subsequent GET observes the same values.
    follow = client.get("/api/modes", headers=AUTH).json()
    assert follow["effort"] == "high"
    assert follow["passes"] == 3
    assert follow["fast_mode"] is True


def test_patch_modes_invalid_effort_returns_422(tmp_path) -> None:
    """PATCH with effort=invalid is rejected by Pydantic validation (422)."""
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"effort": "invalid"},
        headers=AUTH,
    )

    assert response.status_code == 422


def test_patch_modes_permission_mode_full_auto_persists(tmp_path) -> None:
    """PATCH permission_mode=full_auto writes through to settings.json."""
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"permission_mode": "full_auto"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["permission_mode"] == "full_auto"

    # Persisted on disk: load_settings reads from OPENHARNESS_CONFIG_DIR.
    settings = load_settings()
    assert settings.permission.mode.value == "full_auto"

    # And a fresh GET on a new client (same config dir) still observes it.
    client2 = _client(tmp_path)
    body = client2.get("/api/modes", headers=AUTH).json()
    assert body["permission_mode"] == "full_auto"


def test_patch_modes_vim_enabled_persists(tmp_path) -> None:
    """PATCH vim_enabled=True updates the response and persists to settings."""
    client = _client(tmp_path)

    response = client.patch(
        "/api/modes",
        json={"vim_enabled": True},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["vim_enabled"] is True

    settings = load_settings()
    assert settings.vim_mode is True

    get_response = client.get("/api/modes", headers=AUTH)
    assert get_response.json()["vim_enabled"] is True


def test_patch_modes_vim_enabled_false(tmp_path) -> None:
    """PATCH vim_enabled=False disables vim keybindings and persists."""
    client = _client(tmp_path)

    enable = client.patch("/api/modes", json={"vim_enabled": True}, headers=AUTH)
    assert enable.status_code == 200
    assert enable.json()["vim_enabled"] is True
    assert load_settings().vim_mode is True

    response = client.patch(
        "/api/modes",
        json={"vim_enabled": False},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["vim_enabled"] is False

    assert load_settings().vim_mode is False
    assert client.get("/api/modes", headers=AUTH).json()["vim_enabled"] is False


def test_patch_modes_vim_enabled_round_trip_true_then_false(tmp_path) -> None:
    """PATCH vim_enabled supports both boolean values and each value is observable via GET."""
    client = _client(tmp_path)

    enable = client.patch("/api/modes", json={"vim_enabled": True}, headers=AUTH)
    assert enable.status_code == 200
    assert enable.json()["vim_enabled"] is True
    assert client.get("/api/modes", headers=AUTH).json()["vim_enabled"] is True

    disable = client.patch("/api/modes", json={"vim_enabled": False}, headers=AUTH)
    assert disable.status_code == 200
    assert disable.json()["vim_enabled"] is False
    assert client.get("/api/modes", headers=AUTH).json()["vim_enabled"] is False


def test_patch_modes_empty_body_returns_400(tmp_path) -> None:
    """PATCH /api/modes rejects empty update bodies."""
    client = _client(tmp_path)

    response = client.patch("/api/modes", json={}, headers=AUTH)

    assert response.status_code == 400


def test_patch_modes_unknown_field_returns_422(tmp_path) -> None:
    """PATCH /api/modes forbids unknown fields to keep the API contract tight."""
    client = _client(tmp_path)

    response = client.patch("/api/modes", json={"not_a_mode": True}, headers=AUTH)

    assert response.status_code == 422
