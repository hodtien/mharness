"""Tests for GET/PATCH /api/cron/config (P12.2).

Covers:
* GET /api/cron/config returns current config with human-readable descriptions.
* PATCH with valid cron expressions returns 200 and persists changes.
* PATCH with invalid cron expressions returns 400 with clear error messages.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.config.settings import load_settings
from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """Redirect ~/.openharness/settings.json into a tmp dir for these tests."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


class TestGetCronConfig:
    def test_get_returns_all_fields(self, tmp_path) -> None:
        """GET /api/cron/config returns the full config with descriptions."""
        client = _client(tmp_path)

        response = client.get("/api/cron/config", headers=AUTH)

        assert response.status_code == 200
        body = response.json()
        for field in ("enabled", "scan_cron", "tick_cron", "timezone", "install_mode",
                     "scan_cron_description", "tick_cron_description"):
            assert field in body, f"Missing field: {field}"
        assert isinstance(body["scan_cron"], str)
        assert isinstance(body["tick_cron"], str)
        assert isinstance(body["scan_cron_description"], str)
        assert isinstance(body["tick_cron_description"], str)

    def test_get_returns_default_values(self, tmp_path) -> None:
        """Default cron schedule values are returned."""
        client = _client(tmp_path)

        response = client.get("/api/cron/config", headers=AUTH)

        assert response.status_code == 200
        body = response.json()
        assert body["scan_cron"] == "*/15 * * * *"
        assert body["tick_cron"] == "0 * * * *"
        assert body["enabled"] is True
        assert body["timezone"] == "UTC"
        assert body["install_mode"] == "auto"

    def test_get_description_for_default_scan_cron(self, tmp_path) -> None:
        """scan_cron_description is present and non-empty for the default."""
        client = _client(tmp_path)

        response = client.get("/api/cron/config", headers=AUTH)

        assert response.status_code == 200
        body = response.json()
        assert body["scan_cron_description"] != ""
        assert "*/15" in body["scan_cron"] or "15" in body["scan_cron_description"]


class TestPatchCronConfig:
    def test_patch_valid_scan_cron_returns_200(self, tmp_path) -> None:
        """PATCH with a valid scan_cron returns 200 and the updated config."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"scan_cron": "*/10 * * * *"},
            headers=AUTH,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["scan_cron"] == "*/10 * * * *"

    def test_patch_valid_tick_cron_returns_200(self, tmp_path) -> None:
        """PATCH with a valid tick_cron returns 200 and the updated config."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"tick_cron": "0 */2 * * *"},
            headers=AUTH,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["tick_cron"] == "0 */2 * * *"

    def test_patch_multiple_fields_returns_200(self, tmp_path) -> None:
        """PATCH with both enabled, scan_cron, and tick_cron updates succeeds."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={
                "enabled": False,
                "scan_cron": "*/20 * * * *",
                "tick_cron": "30 */3 * * *",
            },
            headers=AUTH,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["scan_cron"] == "*/20 * * * *"
        assert body["tick_cron"] == "30 */3 * * *"

    def test_patch_valid_persists_to_settings(self, tmp_path) -> None:
        """A valid PATCH persists scan_cron to settings.json."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"scan_cron": "*/30 * * * *"},
            headers=AUTH,
        )
        assert response.status_code == 200

        settings = load_settings()
        assert settings.cron_schedule.scan_cron == "*/30 * * * *"

    def test_patch_valid_persists_tick_cron(self, tmp_path) -> None:
        """A valid PATCH persists tick_cron to settings.json."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"tick_cron": "45 * * * *"},
            headers=AUTH,
        )
        assert response.status_code == 200

        settings = load_settings()
        assert settings.cron_schedule.tick_cron == "45 * * * *"

    def test_patch_fresh_client_sees_changes(self, tmp_path) -> None:
        """A new client (same config dir) sees persisted changes."""
        client1 = _client(tmp_path)
        r1 = client1.patch(
            "/api/cron/config",
            json={"scan_cron": "0 9 * * *"},
            headers=AUTH,
        )
        assert r1.status_code == 200

        client2 = _client(tmp_path)
        r2 = client2.get("/api/cron/config", headers=AUTH)
        assert r2.status_code == 200
        assert r2.json()["scan_cron"] == "0 9 * * *"


class TestPatchCronConfigInvalid:
    def test_patch_invalid_scan_cron_returns_400(self, tmp_path) -> None:
        """PATCH with an invalid scan_cron returns 400 with a clear error."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"scan_cron": "not a cron"},
            headers=AUTH,
        )

        assert response.status_code == 400
        body = response.json()
        assert "errors" in body["detail"] or "scan_cron" in str(body.get("detail", ""))

    def test_patch_invalid_tick_cron_returns_400(self, tmp_path) -> None:
        """PATCH with an invalid tick_cron returns 400 with a clear error."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"tick_cron": "invalid-expression"},
            headers=AUTH,
        )

        assert response.status_code == 400
        body = response.json()
        assert "errors" in body["detail"] or "tick_cron" in str(body.get("detail", ""))

    def test_patch_invalid_both_returns_400(self, tmp_path) -> None:
        """PATCH with both scan_cron and tick_cron invalid returns 400 listing both."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"scan_cron": "bad", "tick_cron": "also bad"},
            headers=AUTH,
        )

        assert response.status_code == 400
        body = response.json()
        errors = body["detail"].get("errors", [])
        assert len(errors) == 2

    def test_patch_invalid_does_not_persist(self, tmp_path) -> None:
        """A PATCH with an invalid cron does not modify settings."""
        client = _client(tmp_path)

        original = client.get("/api/cron/config", headers=AUTH).json()

        response = client.patch(
            "/api/cron/config",
            json={"scan_cron": "totally wrong"},
            headers=AUTH,
        )
        assert response.status_code == 400

        current = client.get("/api/cron/config", headers=AUTH).json()
        assert current["scan_cron"] == original["scan_cron"]

    def test_patch_empty_body_returns_400(self, tmp_path) -> None:
        """PATCH with an empty body returns 400 (no fields provided)."""
        client = _client(tmp_path)

        response = client.patch("/api/cron/config", json={}, headers=AUTH)

        assert response.status_code == 400

    def test_patch_unknown_field_returns_422(self, tmp_path) -> None:
        """PATCH with an unknown field returns 422 (Pydantic extra='forbid')."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"unknown_field": "value"},
            headers=AUTH,
        )

        assert response.status_code == 422

    def test_patch_invalid_install_mode_returns_422(self, tmp_path) -> None:
        """PATCH with install_mode not in [auto, manual] returns 422."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"install_mode": "invalid_mode"},
            headers=AUTH,
        )

        assert response.status_code == 422

    def test_patch_invalid_timezone_returns_422(self, tmp_path) -> None:
        """PATCH with an invalid timezone pattern returns 422."""
        client = _client(tmp_path)

        response = client.patch(
            "/api/cron/config",
            json={"timezone": "invalid!@#"},
            headers=AUTH,
        )

        assert response.status_code == 422