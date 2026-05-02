from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.config.settings import ProviderProfile, Settings, save_settings
from openharness.webui.server.app import create_app


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet", spa_dir=""))


def test_models_endpoint_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/models").status_code == 401


def test_models_returns_builtin_claude_aliases_and_custom_models(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "claude-api": ProviderProfile(
                    label="Anthropic-Compatible API",
                    provider="anthropic",
                    api_format="anthropic",
                    auth_source="anthropic_api_key",
                    default_model="claude-sonnet-4-6",
                    allowed_models=["custom-claude-model"],
                    context_window_tokens=12345,
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.get("/api/models", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    body = response.json()
    claude_models = {model["id"]: model for model in body["claude-api"]}
    assert claude_models["claude-sonnet-4-6"] == {
        "id": "claude-sonnet-4-6",
        "label": "claude-sonnet-4-6",
        "context_window": 12345,
        "is_default": True,
        "is_custom": False,
    }
    assert claude_models["sonnet"]["label"] == "Sonnet"
    assert claude_models["sonnet"]["is_custom"] is False
    assert claude_models["custom-claude-model"]["is_custom"] is True
    assert claude_models["custom-claude-model"]["context_window"] == 12345


def test_models_are_grouped_by_provider_profile(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "moonshot": ProviderProfile(
                    label="Moonshot (Kimi)",
                    provider="moonshot",
                    api_format="openai",
                    auth_source="moonshot_api_key",
                    default_model="kimi-k2.5",
                    allowed_models=["kimi-custom"],
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.get("/api/models", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    body = response.json()
    assert "moonshot" in body
    moonshot_models = {model["id"]: model for model in body["moonshot"]}
    assert moonshot_models["kimi-k2.5"]["is_default"] is True
    assert moonshot_models["kimi-custom"]["is_custom"] is True
    assert "sonnet" not in moonshot_models
