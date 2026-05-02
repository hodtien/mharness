"""Tests for the WebUI provider routes (P3.6).

Covers the scenarios required by the task:

* GET /api/providers returns the merged profile catalog with at least 9 items
  (the built-in catalog ships 9 profiles).
* POST /api/providers/{name}/activate with an unknown name returns 404.
* POST /api/providers/{name}/credentials persists the api_key and masks it
  in the response (only the last 4 characters are echoed).
* POST /api/providers/{name}/verify works against a mocked httpx response —
  the OpenAI client path is forced to fall back to httpx by returning a 404,
  and httpx itself is patched to return a successful ``/models`` payload.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.auth.storage import load_credential
from openharness.config.settings import load_settings, save_settings
from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_config_and_data(tmp_path, monkeypatch):
    """Redirect config + data dirs and force the file-based credential backend.

    Provider routes touch ~/.openharness/{settings,credentials}.json. Without
    isolation these tests would mutate the developer's real settings or the
    system keyring; both are unacceptable in a unit test.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        "openharness.auth.storage._keyring_available", lambda: False
    )
    # Pre-seed settings.json so load_settings/save_settings work against the
    # tmp config dir from the start.
    save_settings(load_settings())


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


def test_list_providers_returns_at_least_9_items(tmp_path) -> None:
    """GET /api/providers returns the full built-in catalog (≥9 entries)."""
    client = _client(tmp_path)

    response = client.get("/api/providers", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert "providers" in body
    providers = body["providers"]
    assert isinstance(providers, list)
    assert len(providers) >= 9, f"Expected ≥9 provider profiles, got {len(providers)}"


def test_activate_unknown_provider_returns_404(tmp_path) -> None:
    """POST /api/providers/{name}/activate with an unknown name → 404."""
    client = _client(tmp_path)

    response = client.post(
        "/api/providers/does-not-exist/activate", headers=AUTH
    )

    assert response.status_code == 404
    assert "Unknown provider profile" in response.json()["detail"]


def test_credentials_save_persists_api_key_and_masks_response(tmp_path) -> None:
    """Credentials are stored and the response only exposes the last 4 chars."""
    client = _client(tmp_path)

    api_key = "sk-test-PROVIDER-ROUTES-XYZ9"
    response = client.post(
        "/api/providers/openai-compatible/credentials",
        headers=AUTH,
        json={"api_key": api_key},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # Mask: all but the last 4 characters replaced with '*'.
    expected_mask = "*" * (len(api_key) - 4) + api_key[-4:]
    assert body["api_key"] == expected_mask
    # The full key must never appear in the response payload.
    assert api_key not in body["api_key"]

    # Credential is persisted under the auth-source provider name.
    assert load_credential("openai", "api_key") == api_key


def test_verify_provider_with_mocked_httpx_response(tmp_path, monkeypatch) -> None:
    """Verify falls back to httpx and returns the mocked /models payload.

    Strategy: force the OpenAI-client path to fail with a 404 so the route
    falls through to ``_fetch_models_via_httpx``. Patch ``httpx.AsyncClient``
    to return a fake response carrying a ``data: [{id: ...}]`` payload.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    captured: dict[str, object] = {}

    async def fake_openai_fetch(base_url: str, api_key: str):
        # Forces fallback path in the route.
        return False, "HTTP 404: not found", []

    class _FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "object": "list",
                "data": [
                    {"id": "gpt-mock-a"},
                    {"id": "gpt-mock-b"},
                ],
            }

    class _FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(
        "openharness.webui.server.routes.providers._fetch_models_via_openai_client",
        fake_openai_fetch,
    )
    monkeypatch.setattr(
        "openharness.webui.server.routes.providers.httpx.AsyncClient",
        _FakeAsyncClient,
    )

    response = _client(tmp_path).post(
        "/api/providers/openai-compatible/verify", headers=AUTH
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "error": None,
        "models": ["gpt-mock-a", "gpt-mock-b"],
    }
    # The httpx call must hit /models on the OpenAI base URL with the bearer.
    assert captured["url"] == "https://api.openai.com/v1/models"
    assert captured["headers"] == {"Authorization": "Bearer sk-test-key"}
