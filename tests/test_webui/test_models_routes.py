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


# -------------------------------------------------------------------
# POST /api/models — add custom model
# -------------------------------------------------------------------


def test_add_custom_model_creates_entry(tmp_path) -> None:
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
                    context_window_tokens=100000,
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/models",
        json={"provider": "claude-api", "model_id": "my-custom-model", "label": "My Custom", "context_window": 200000},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {"ok": True, "provider": "claude-api", "model_id": "my-custom-model"}

    # Verify the model is now in allowed_models and appears in GET /api/models.
    list_resp = client.get("/api/models", headers={"Authorization": "Bearer test-token"})
    claude_models = {m["id"]: m for m in list_resp.json()["claude-api"]}
    assert claude_models["my-custom-model"]["is_custom"] is True
    assert claude_models["my-custom-model"]["label"] == "my-custom-model"  # label is ignored; id used as label
    assert claude_models["my-custom-model"]["context_window"] == 100000  # profile-level context_window used


def test_add_custom_model_unknown_provider_returns_404(tmp_path) -> None:
    save_settings(Settings())
    client = _client(tmp_path)

    response = client.post(
        "/api/models",
        json={"provider": "does-not-exist", "model_id": "m"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404
    assert "Unknown provider profile" in response.json()["detail"]


def test_add_custom_model_empty_provider_returns_400(tmp_path) -> None:
    save_settings(Settings())
    client = _client(tmp_path)

    response = client.post(
        "/api/models",
        json={"provider": "  ", "model_id": "m"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400
    assert "provider must not be empty" in response.json()["detail"]


def test_add_custom_model_empty_model_id_returns_400(tmp_path) -> None:
    save_settings(Settings())
    client = _client(tmp_path)

    response = client.post(
        "/api/models",
        json={"provider": "claude-api", "model_id": "  "},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400
    assert "model_id must not be empty" in response.json()["detail"]


def test_add_custom_model_idempotent_returns_409(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "claude-api": ProviderProfile(
                    label="Anthropic-Compatible API",
                    provider="anthropic",
                    api_format="anthropic",
                    auth_source="anthropic_api_key",
                    default_model="claude-sonnet-4-6",
                    allowed_models=["already-there"],
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/models",
        json={"provider": "claude-api", "model_id": "already-there"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


# -------------------------------------------------------------------
# DELETE /api/models/{provider}/{model_id} — remove custom model
# -------------------------------------------------------------------


def test_delete_custom_model_removes_from_allowed_models(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "moonshot": ProviderProfile(
                    label="Moonshot (Kimi)",
                    provider="moonshot",
                    api_format="openai",
                    auth_source="moonshot_api_key",
                    default_model="kimi-k2.5",
                    allowed_models=["kimi-extra", "kimi-other"],
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.delete(
        "/api/models/moonshot/kimi-extra",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "provider": "moonshot", "model_id": "kimi-extra"}

    # Verify the model is gone from allowed_models and GET no longer returns it.
    list_resp = client.get("/api/models", headers={"Authorization": "Bearer test-token"})
    moonshot_models = {m["id"]: m for m in list_resp.json()["moonshot"]}
    assert "kimi-extra" not in moonshot_models
    assert "kimi-other" in moonshot_models  # other custom models still there


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
                ),
            }
        )
    )
    client = _client(tmp_path)

    # Trying to delete a Claude alias (built-in) should return 400.
    response = client.delete(
        "/api/models/claude-api/sonnet",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400
    assert "Cannot delete built-in model" in response.json()["detail"]


def test_delete_default_model_returns_400(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "moonshot": ProviderProfile(
                    label="Moonshot (Kimi)",
                    provider="moonshot",
                    api_format="openai",
                    auth_source="moonshot_api_key",
                    default_model="kimi-k2.5",
                    allowed_models=[],
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.delete(
        "/api/models/moonshot/kimi-k2.5",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400
    assert "Cannot delete built-in model" in response.json()["detail"]


def test_delete_unknown_provider_returns_404(tmp_path) -> None:
    save_settings(Settings())
    client = _client(tmp_path)

    response = client.delete(
        "/api/models/nonexistent/my-model",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404
    assert "Unknown provider profile" in response.json()["detail"]


def test_delete_nonexistent_custom_model_returns_404(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "claude-api": ProviderProfile(
                    label="Anthropic-Compatible API",
                    provider="anthropic",
                    api_format="anthropic",
                    auth_source="anthropic_api_key",
                    default_model="claude-sonnet-4-6",
                    allowed_models=[],  # no custom models
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.delete(
        "/api/models/claude-api/never-was-added",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_delete_custom_model_requires_auth(tmp_path) -> None:
    save_settings(
        Settings(
            profiles={
                "claude-api": ProviderProfile(
                    label="Anthropic-Compatible API",
                    provider="anthropic",
                    api_format="anthropic",
                    auth_source="anthropic_api_key",
                    default_model="claude-sonnet-4-6",
                    allowed_models=["custom-x"],
                ),
            }
        )
    )
    client = _client(tmp_path)

    response = client.delete("/api/models/claude-api/custom-x")
    assert response.status_code == 401

    response = client.delete(
        "/api/models/claude-api/custom-x",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
