from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.config.settings import ProviderProfile, Settings, load_settings, save_settings
from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


def test_list_models_returns_grouped_models(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/models", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body
    first_group = next(iter(body.values()))
    assert first_group
    assert {"id", "label", "context_window", "is_default", "is_custom"} <= set(first_group[0])


def test_add_custom_model_persists_to_provider_profile(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "claude-api": ProviderProfile(
                    label="Anthropic-Compatible API",
                    provider="anthropic",
                    api_format="anthropic",
                    auth_source="anthropic_api_key",
                    default_model="claude-sonnet-4-6",
                    allowed_models=[],
                )
            }
        )
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/models",
        headers=AUTH,
        json={"provider": "claude-api", "model_id": "custom-test-model"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "ok": True,
        "provider": "claude-api",
        "model_id": "custom-test-model",
    }
    assert "custom-test-model" in load_settings().merged_profiles()["claude-api"].allowed_models


def test_delete_custom_model_removes_it(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "claude-api": ProviderProfile(
                    label="Anthropic-Compatible API",
                    provider="anthropic",
                    api_format="anthropic",
                    auth_source="anthropic_api_key",
                    default_model="claude-sonnet-4-6",
                    allowed_models=["custom-test-model"],
                )
            }
        )
    )
    client = _client(tmp_path)

    response = client.delete("/api/models/claude-api/custom-test-model", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider": "claude-api",
        "model_id": "custom-test-model",
    }
    assert "custom-test-model" not in load_settings().merged_profiles()["claude-api"].allowed_models


def test_delete_builtin_model_returns_400(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "claude-api": ProviderProfile(
                    label="Anthropic-Compatible API",
                    provider="anthropic",
                    api_format="anthropic",
                    auth_source="anthropic_api_key",
                    default_model="claude-sonnet-4-6",
                    allowed_models=[],
                )
            }
        )
    )
    client = _client(tmp_path)

    response = client.delete("/api/models/claude-api/sonnet", headers=AUTH)

    assert response.status_code == 400
    assert "Cannot delete built-in model" in response.json()["detail"]
