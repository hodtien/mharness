from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from openharness.services.session_storage import get_project_session_dir, save_session_snapshot
from openharness.api.usage import UsageSnapshot
from openharness.auth.storage import load_credential
from openharness.config.settings import load_settings, save_settings
from openharness.engine.messages import ConversationMessage, ToolResultBlock, ToolUseBlock
from openharness.tasks.manager import get_task_manager
from openharness.webui.server.app import create_app


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet"))


def test_health_is_available_without_auth(tmp_path) -> None:
    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_meta_requires_auth_and_returns_bootstrap_state(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/meta").status_code == 401

    response = client.get("/api/meta", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json()["cwd"] == str(tmp_path.resolve())
    assert response.json()["model"] == "sonnet"


def test_sessions_endpoint_requires_auth_and_returns_list(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/sessions").status_code == 401

    response = client.get("/api/sessions", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert isinstance(response.json()["sessions"], list)


def test_tasks_endpoint_requires_auth_and_returns_list(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/tasks").status_code == 401

    response = client.get("/api/tasks", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {"tasks": []}


def test_tasks_detail_returns_404_for_unknown_id(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get(
        "/api/tasks/nonexistent", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 404


def test_tasks_output_returns_404_for_unknown_id(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get(
        "/api/tasks/nonexistent/output", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 404


def test_tasks_stop_returns_404_for_unknown_id(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/tasks/nonexistent/stop", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 404


def test_cron_jobs_endpoint_requires_auth_and_returns_list(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    client = _client(tmp_path)

    assert client.get("/api/cron/jobs").status_code == 401

    response = client.get(
        "/api/cron/jobs", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


def test_non_bearer_authorization_header_is_rejected(tmp_path) -> None:
    response = _client(tmp_path).get(
        "/api/meta", headers={"Authorization": "test-token"}
    )

    assert response.status_code == 401


def test_query_token_is_accepted_for_bootstrap_clients(tmp_path) -> None:
    response = _client(tmp_path).get("/api/meta?token=test-token")

    assert response.status_code == 200


def test_history_endpoint_requires_auth_and_lists_session_snapshots(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello history")],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    client = _client(tmp_path)

    assert client.get("/api/history").status_code == 401

    response = client.get("/api/history?limit=20", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {
        "sessions": [
            {
                "session_id": "abc123",
                "summary": "hello history",
                "message_count": 1,
                "model": "sonnet",
                "created_at": response.json()["sessions"][0]["created_at"],
            }
        ]
    }


def test_history_detail_returns_session_and_truncates_tool_results(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    long_result = "x" * 501
    tool_use = ToolUseBlock(id="toolu_123", name="read_file", input={})
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[
            ConversationMessage.from_user_text("hello history"),
            ConversationMessage(role="assistant", content=[tool_use]),
            ConversationMessage.from_user_content(
                [ToolResultBlock(tool_use_id="toolu_123", content=long_result)]
            ),
        ],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    client = _client(tmp_path)

    response = client.get(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "abc123"
    result = body["messages"][2]["content"][0]
    assert result["type"] == "tool_result"
    assert result["content"] == f"{'x' * 500}… [truncated 1 chars]"
    assert result["truncated"] is True
    assert result["original_length"] == 501

    missing = client.get(
        "/api/history/missing", headers={"Authorization": "Bearer test-token"}
    )
    assert missing.status_code == 404


def test_history_delete_removes_session_and_clears_latest_when_matching(
    tmp_path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello history")],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    session_dir = get_project_session_dir(tmp_path)
    session_path = session_dir / "session-abc123.json"
    latest_path = session_dir / "latest.json"
    assert session_path.exists()
    assert latest_path.exists()

    client = _client(tmp_path)

    assert client.delete("/api/history/abc123").status_code == 401

    response = client.delete(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 204
    assert response.content == b""
    assert not session_path.exists()
    assert not latest_path.exists()

    missing = client.delete(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )
    assert missing.status_code == 404


def test_history_delete_keeps_latest_pointing_to_other_session(
    tmp_path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("first")],
        usage=UsageSnapshot(),
        session_id="aaa111",
    )
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("second")],
        usage=UsageSnapshot(),
        session_id="bbb222",
    )
    session_dir = get_project_session_dir(tmp_path)
    older_path = session_dir / "session-aaa111.json"
    newer_path = session_dir / "session-bbb222.json"
    latest_path = session_dir / "latest.json"
    assert latest_path.exists()

    client = _client(tmp_path)

    response = client.delete(
        "/api/history/aaa111", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 204
    assert not older_path.exists()
    # latest.json points to the most recently saved session (bbb222), so it stays.
    assert latest_path.exists()
    assert newer_path.exists()


def test_post_sessions_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    assert client.post("/api/sessions").status_code == 401


def test_post_sessions_creates_fresh_session_without_body(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    client = _client(tmp_path)

    response = client.post(
        "/api/sessions", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["session_id"], str) and body["session_id"]
    assert body["resumed_from"] is None
    assert body["active"] is False

    manager = client.app.state.webui_session_manager
    entry = manager.get(body["session_id"])
    assert entry is not None
    assert entry.host._config.restore_messages is None


def test_post_sessions_with_resume_id_loads_snapshot(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("resume me please")],
        usage=UsageSnapshot(),
        session_id="resume99",
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/sessions",
        headers={"Authorization": "Bearer test-token"},
        json={"resume_id": "resume99"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resumed_from"] == "resume99"

    manager = client.app.state.webui_session_manager
    entry = manager.get(body["session_id"])
    assert entry is not None
    restored = entry.host._config.restore_messages
    assert restored is not None and len(restored) == 1
    assert restored[0]["role"] == "user"


def test_post_sessions_unknown_resume_id_returns_404(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    client = _client(tmp_path)

    response = client.post(
        "/api/sessions",
        headers={"Authorization": "Bearer test-token"},
        json={"resume_id": "missing"},
    )
    assert response.status_code == 404


def test_history_delete_removes_latest_only_session(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("latest only")],
        usage=UsageSnapshot(),
        session_id="abc123",
    )
    session_dir = get_project_session_dir(tmp_path)
    (session_dir / "session-abc123.json").unlink()
    latest_path = session_dir / "latest.json"
    assert latest_path.exists()

    client = _client(tmp_path)

    response = client.delete(
        "/api/history/abc123", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 204
    assert not latest_path.exists()


def test_providers_endpoint_requires_auth_and_returns_list(tmp_path, monkeypatch) -> None:
    """GET /api/providers returns the merged profile catalog with flags."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    client = _client(tmp_path)

    # No auth → 401
    assert client.get("/api/providers").status_code == 401

    response = client.get(
        "/api/providers", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    body = response.json()
    assert "providers" in body
    assert isinstance(body["providers"], list)

    # Built-in profiles are always present
    ids = {p["id"] for p in body["providers"]}
    for builtin in ("claude-api", "openai-compatible", "moonshot"):
        assert builtin in ids, f"Expected built-in profile {builtin} in {ids}"

    # Every item has the expected shape
    for item in body["providers"]:
        assert "id" in item
        assert "label" in item
        assert "provider" in item
        assert "api_format" in item
        assert "default_model" in item
        assert "base_url" in item
        assert isinstance(item["has_credentials"], bool)
        assert isinstance(item["is_active"], bool)

    # Exactly one profile is active
    active = [p for p in body["providers"] if p["is_active"]]
    assert len(active) == 1


def test_providers_trailing_slash_behavior(tmp_path, monkeypatch) -> None:
    """GET /api/providers/ returns the same list as GET /api/providers."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    client = _client(tmp_path)

    r1 = client.get("/api/providers", headers={"Authorization": "Bearer test-token"})
    r2 = client.get("/api/providers/", headers={"Authorization": "Bearer test-token"})

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_activate_provider_switches_profile_and_returns_new_model(tmp_path, monkeypatch) -> None:
    """POST /api/providers/{name}/activate persists the profile and returns the new model."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    # Pre-seed a settings file with a known active_profile so we're starting
    # from a known state (not the global ~/.openharness/settings.json).
    init_settings = load_settings()
    save_settings(init_settings)

    client = _client(tmp_path)

    # Attempt to activate an unknown profile → 404
    unknown_resp = client.post(
        "/api/providers/nonexistent-profile/activate",
        headers={"Authorization": "Bearer test-token"},
    )
    assert unknown_resp.status_code == 404
    assert "Unknown provider profile" in unknown_resp.json()["detail"]

    # Activate a built-in profile (openai-compatible).
    resp = client.post(
        "/api/providers/openai-compatible/activate",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["model"], str) and body["model"]

    # settings.json on disk must reflect the new active_profile.
    persisted = load_settings()
    assert persisted.active_profile == "openai-compatible"
    # The flat `model` field is materialized from the profile by save_settings.
    assert persisted.model == body["model"]

    # New sessions pick up the updated defaults.
    new_session = client.post(
        "/api/sessions", headers={"Authorization": "Bearer test-token"}
    )
    assert new_session.status_code == 200
    session_id = new_session.json()["session_id"]
    entry = client.app.state.webui_session_manager.get(session_id)
    assert entry is not None
    # The fresh session gets the new model from the reloaded config.
    assert entry.host._config.model == body["model"]

    # Revert to the default profile.
    revert_resp = client.post(
        "/api/providers/claude-api/activate",
        headers={"Authorization": "Bearer test-token"},
    )
    assert revert_resp.status_code == 200
    assert revert_resp.json()["ok"] is True

    # Auth is required.
    assert client.post("/api/providers/openai-compatible/activate").status_code == 401


def test_set_provider_credentials_persists_api_key_and_base_url(tmp_path, monkeypatch) -> None:
    """POST /api/providers/{name}/credentials stores api_key + base_url override."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    # Force file-based credential backend so tests don't touch the user's keyring.
    monkeypatch.setattr(
        "openharness.auth.storage._keyring_available", lambda: False
    )
    save_settings(load_settings())

    client = _client(tmp_path)

    # Auth is required.
    assert client.post(
        "/api/providers/openai-compatible/credentials", json={"api_key": "x"}
    ).status_code == 401

    # Unknown profile → 404.
    not_found = client.post(
        "/api/providers/nonexistent/credentials",
        headers={"Authorization": "Bearer test-token"},
        json={"api_key": "sk-abcdef1234"},
    )
    assert not_found.status_code == 404

    # Empty body → 400 (must provide api_key or base_url).
    empty = client.post(
        "/api/providers/openai-compatible/credentials",
        headers={"Authorization": "Bearer test-token"},
        json={},
    )
    assert empty.status_code == 400

    # Set both api_key and base_url for an API-key based profile.
    api_key_value = "sk-test-1234567890ABCD"
    response = client.post(
        "/api/providers/openai-compatible/credentials",
        headers={"Authorization": "Bearer test-token"},
        json={"api_key": api_key_value, "base_url": "https://example.test/v1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # Only the last 4 characters of the api_key are exposed.
    assert body["api_key"] == "*" * (len(api_key_value) - 4) + api_key_value[-4:]
    assert api_key_value not in body["api_key"][: -4]
    assert body["base_url"] == "https://example.test/v1"

    # Credential is persisted under the profile's auth-source provider name.
    assert load_credential("openai", "api_key") == api_key_value

    # base_url override is persisted on the profile in settings.json.
    persisted = load_settings()
    assert persisted.merged_profiles()["openai-compatible"].base_url == "https://example.test/v1"

    # Clearing base_url with empty string falls back to the built-in default
    # (the openai-compatible built-in has base_url=None).
    response_clear = client.post(
        "/api/providers/openai-compatible/credentials",
        headers={"Authorization": "Bearer test-token"},
        json={"base_url": ""},
    )
    assert response_clear.status_code == 200
    assert response_clear.json()["base_url"] is None
    # No api_key was sent → response must not include the api_key field.
    assert "api_key" not in response_clear.json()

    # Subscription-style profiles (no API key) reject api_key updates.
    reject = client.post(
        "/api/providers/codex/credentials",
        headers={"Authorization": "Bearer test-token"},
        json={"api_key": "should-not-store"},
    )
    assert reject.status_code == 400


def test_verify_provider_returns_models_from_openai_models_endpoint(tmp_path, monkeypatch) -> None:
    """POST /api/providers/{name}/verify prefers the free /v1/models endpoint."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    save_settings(load_settings())

    async def fake_fetch_models(base_url: str, api_key: str):
        assert base_url == "https://api.openai.com/v1"
        assert api_key == "sk-test"
        return True, None, ["gpt-test-a", "gpt-test-b"]

    async def fail_completion_probe(*_args, **_kwargs):  # pragma: no cover - should not be called
        raise AssertionError("completion probe should not run when models endpoint succeeds")

    monkeypatch.setattr(
        "openharness.webui.server.routes.providers._fetch_models_via_openai_client",
        fake_fetch_models,
    )
    monkeypatch.setattr(
        "openharness.webui.server.routes.providers._completion_probe",
        fail_completion_probe,
    )

    client = _client(tmp_path)

    assert client.post("/api/providers/openai-compatible/verify").status_code == 401

    response = client.post(
        "/api/providers/openai-compatible/verify",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "error": None, "models": ["gpt-test-a", "gpt-test-b"]}


def test_verify_provider_falls_back_to_completion_probe(tmp_path, monkeypatch) -> None:
    """If /v1/models is unavailable, verify sends one tiny completion probe."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    save_settings(load_settings())

    async def fake_fetch_models(*_args, **_kwargs):
        return False, "HTTP 404: not found", []

    async def fake_httpx_models(*_args, **_kwargs):
        return False, "HTTP 404: not found", []

    async def fake_completion_probe(base_url: str, api_key: str, model: str):
        assert base_url == "https://api.openai.com/v1"
        assert api_key == "sk-test"
        assert model
        return None

    monkeypatch.setattr(
        "openharness.webui.server.routes.providers._fetch_models_via_openai_client",
        fake_fetch_models,
    )
    monkeypatch.setattr(
        "openharness.webui.server.routes.providers._fetch_models_via_httpx",
        fake_httpx_models,
    )
    monkeypatch.setattr(
        "openharness.webui.server.routes.providers._completion_probe",
        fake_completion_probe,
    )

    response = _client(tmp_path).post(
        "/api/providers/openai-compatible/verify",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "error": None, "models": None}


def test_verify_provider_reports_missing_api_key(tmp_path, monkeypatch) -> None:
    """Verification fails cleanly when no credential can be resolved."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_settings(load_settings())

    client = _client(tmp_path)

    not_found = client.post(
        "/api/providers/nonexistent/verify",
        headers={"Authorization": "Bearer test-token"},
    )
    assert not_found.status_code == 404

    response = client.post(
        "/api/providers/openai-compatible/verify",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "No API key available."
    assert response.json()["models"] is None


def test_pipeline_cards_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/pipeline/cards").status_code == 401


def test_pipeline_cards_returns_empty_when_no_registry_file(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"cards": [], "updated_at": 0.0}


def test_pipeline_cards_returns_empty_for_missing_autopilot_dir(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"cards": [], "updated_at": 0.0}


def test_pipeline_cards_returns_empty_for_malformed_json(tmp_path) -> None:
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text("{bad")
    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"cards": [], "updated_at": 0.0}


def test_pipeline_cards_returns_serialized_cards(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.5,
        "cards": [
            {
                "id": "card-1",
                "title": "Fix bug",
                "body": "Fix the bug",
                "status": "queued",
                "source_kind": "manual_idea",
                "source_ref": "ap-1",
                "fingerprint": "manual_idea:abc123",
                "score": 42,
                "score_reasons": [],
                "labels": ["bug", "urgent"],
                "metadata": {},
                "created_at": 900.0,
                "updated_at": 950.0,
            },
            {
                "id": "card-2",
                "title": "Add feature",
                "body": "",
                "status": "running",
                "source_kind": "github_issue",
                "source_ref": "#123",
                "fingerprint": "github_issue:def456",
                "score": 10,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 800.0,
                "updated_at": 800.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["updated_at"] == 1000.5
    assert len(data["cards"]) == 2

    card1 = data["cards"][0]
    assert card1["id"] == "card-1"
    assert card1["title"] == "Fix bug"
    assert card1["status"] == "queued"
    assert card1["source_kind"] == "manual_idea"
    assert card1["score"] == 42
    assert card1["labels"] == ["bug", "urgent"]
    assert card1["created_at"] == 900.0
    assert card1["updated_at"] == 950.0
    # body, model, attempt_count, pending retry fields are included for the card detail drawer.
    assert card1["body"] == "Fix the bug"
    assert card1["model"] is None
    assert card1["attempt_count"] == 0
    assert card1["pending_reason"] is None
    assert card1["next_retry_at"] is None
    assert card1["retry_count"] == 0
    # Extra internal fields (fingerprint, source_ref, score_reasons)
    # must NOT appear in the response.
    assert "fingerprint" not in card1
    assert "source_ref" not in card1
    assert "score_reasons" not in card1
    # metadata IS included for the blocker banner (last_note + linked_pr_url)
    assert "metadata" in card1
    assert "last_note" in card1["metadata"]
    assert "linked_pr_url" in card1["metadata"]


def test_pipeline_cards_post_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.post("/api/pipeline/cards", json={"title": "x"})
    assert response.status_code == 401


def test_pipeline_cards_post_enqueues_manual_idea(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
        json={"title": "Add dashboard", "body": "Show cards", "labels": ["ui"]},
    )

    assert response.status_code == 201
    card = response.json()
    assert card["title"] == "Add dashboard"
    assert card["status"] == "queued"
    assert card["source_kind"] == "manual_idea"
    assert card["labels"] == ["ui"]
    assert card["id"]

    list_response = client.get(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
    )
    assert list_response.status_code == 200
    assert list_response.json()["cards"] == [card]


def test_pipeline_cards_post_returns_409_for_duplicate_fingerprint(tmp_path) -> None:
    client = _client(tmp_path)
    payload = {"title": "Add dashboard", "body": "Show cards"}

    first = client.post(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
        json=payload,
    )
    duplicate = client.post(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
        json=payload,
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"] == "duplicate_card"
    assert duplicate.json()["detail"]["card_id"] == first.json()["id"]


def test_pipeline_cards_post_rejects_empty_title(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
        json={"title": ""},
    )
    assert response.status_code == 422


# ----------------------------------------------------------------------
# POST /api/pipeline/cards/{id}/action
# ----------------------------------------------------------------------

def test_pipeline_cards_action_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.post("/api/pipeline/cards/ap-abc123/action", json={"action": "accept"})
    assert response.status_code == 401


def test_pipeline_cards_action_returns_404_when_card_not_found(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-existing",
                "title": "Existing card",
                "body": "",
                "status": "queued",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:abc123",
                "score": 10,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 900.0,
                "updated_at": 950.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards/ap-nonexistent/action",
        headers={"Authorization": "Bearer test-token"},
        json={"action": "accept"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "card_not_found"


def test_pipeline_cards_action_accept_sets_status_accepted(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-test-card",
                "title": "Test card",
                "body": "Body text",
                "status": "queued",
                "source_kind": "manual_idea",
                "source_ref": "manual_ref",
                "fingerprint": "manual_idea:test123",
                "score": 20,
                "score_reasons": ["source=manual_idea"],
                "labels": ["ui"],
                "metadata": {},
                "created_at": 800.0,
                "updated_at": 900.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards/ap-test-card/action",
        headers={"Authorization": "Bearer test-token"},
        json={"action": "accept"},
    )
    assert response.status_code == 200
    card = response.json()
    assert card["id"] == "ap-test-card"
    assert card["status"] == "accepted"
    assert card["body"] == "Body text"
    assert card["model"] is None
    assert card["attempt_count"] == 0
    # Verify persisted
    registry_path = tmp_path / ".openharness" / "autopilot" / "registry.json"
    saved = json.loads(registry_path.read_text())
    assert saved["cards"][0]["status"] == "accepted"


def test_pipeline_cards_action_reject_sets_status_rejected(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-reject-me",
                "title": "Reject me",
                "body": "",
                "status": "running",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:xyz789",
                "score": 15,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 700.0,
                "updated_at": 800.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards/ap-reject-me/action",
        headers={"Authorization": "Bearer test-token"},
        json={"action": "reject"},
    )
    assert response.status_code == 200
    card = response.json()
    assert card["status"] == "rejected"


def test_pipeline_cards_action_retry_resets_status_to_queued(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-retry-me",
                "title": "Retry me",
                "body": "",
                "status": "failed",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:retry111",
                "score": 5,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 600.0,
                "updated_at": 700.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards/ap-retry-me/action",
        headers={"Authorization": "Bearer test-token"},
        json={"action": "retry"},
    )
    assert response.status_code == 200
    card = response.json()
    assert card["status"] == "queued"


def test_pipeline_retry_now_accepts_failed_card_and_spawns_task(tmp_path, monkeypatch) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-retry-now",
                "title": "Retry now",
                "body": "",
                "status": "failed",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:retry-now",
                "score": 5,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 600.0,
                "updated_at": 700.0,
            },
        ],
    }
    reg_dir = tmp_path / ".openharness" / "autopilot"
    reg_dir.mkdir(parents=True)
    (reg_dir / "registry.json").write_text(json.dumps(registry))

    async def fake_create_shell_task(*, command, description, cwd, task_type):
        return SimpleNamespace(id="task-retry-now")

    monkeypatch.setattr(get_task_manager(), "create_shell_task", fake_create_shell_task)

    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards/ap-retry-now/retry-now",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 202
    assert response.json()["task_id"] == "task-retry-now"
    saved = json.loads((reg_dir / "registry.json").read_text())
    card = next(card for card in saved["cards"] if card["id"] == "ap-retry-now")
    assert card["status"] == "preparing"
    assert card["metadata"]["attempt_count"] == 1
    assert card["metadata"]["retry_requested"] is True
    assert card["metadata"]["retry_by"] == "user"


def test_pipeline_retry_now_accepts_pending_card(tmp_path, monkeypatch) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-pending-retry",
                "title": "Pending retry",
                "body": "",
                "status": "pending",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:pending-retry",
                "score": 5,
                "score_reasons": [],
                "labels": [],
                "metadata": {
                    "pending_reason": "preflight_transient",
                    "next_retry_at": 0.0,
                    "retry_count": 2,
                },
                "created_at": 600.0,
                "updated_at": 700.0,
            },
        ],
    }
    reg_dir = tmp_path / ".openharness" / "autopilot"
    reg_dir.mkdir(parents=True)
    (reg_dir / "registry.json").write_text(json.dumps(registry))

    async def fake_create_shell_task(*, command, description, cwd, task_type):
        return SimpleNamespace(id="task-pending-retry")

    monkeypatch.setattr(get_task_manager(), "create_shell_task", fake_create_shell_task)

    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards/ap-pending-retry/retry-now",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 202
    saved = json.loads((reg_dir / "registry.json").read_text())
    card = next(card for card in saved["cards"] if card["id"] == "ap-pending-retry")
    assert card["status"] == "preparing"


def test_pipeline_cards_action_rejects_invalid_action(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-any",
                "title": "Any card",
                "body": "",
                "status": "queued",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:any",
                "score": 0,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 500.0,
                "updated_at": 500.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.post(
        "/api/pipeline/cards/ap-any/action",
        headers={"Authorization": "Bearer test-token"},
        json={"action": "invalid"},
    )
    assert response.status_code == 422


def test_pipeline_cards_returns_pending_retry_fields(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.5,
        "cards": [
            {
                "id": "card-pending",
                "title": "Pending card",
                "body": "Waiting for retry",
                "status": "pending",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:pending",
                "score": 50,
                "score_reasons": [],
                "labels": ["pending"],
                "metadata": {
                    "pending_reason": "preflight_transient",
                    "next_retry_at": 1000.0,
                    "retry_count": 3,
                    "last_note": "Transient failure, will retry",
                },
                "created_at": 900.0,
                "updated_at": 950.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/cards",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["cards"]) == 1

    card = data["cards"][0]
    assert card["id"] == "card-pending"
    assert card["status"] == "pending"
    assert card["pending_reason"] == "preflight_transient"
    assert card["next_retry_at"] == 1000.0
    assert card["retry_count"] == 3


def test_pipeline_cards_model_patch_updates_execution_model(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-model-card",
                "title": "Model card",
                "body": "Body",
                "status": "queued",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:model",
                "score": 0,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 1.0,
                "updated_at": 1.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/cards/ap-model-card/model",
        headers={"Authorization": "Bearer test-token"},
        json={"model": "gpt-4.1"},
    )
    assert response.status_code == 200
    assert response.json()["model"] == "gpt-4.1"
    saved = json.loads((tmp_path / ".openharness" / "autopilot" / "registry.json").read_text())
    assert saved["cards"][0]["model"] == "gpt-4.1"


def test_pipeline_cards_model_patch_allows_active_card(tmp_path) -> None:
    registry = {
        "version": 1,
        "updated_at": 1000.0,
        "cards": [
            {
                "id": "ap-running-card",
                "title": "Running card",
                "body": "",
                "status": "running",
                "source_kind": "manual_idea",
                "source_ref": "",
                "fingerprint": "manual_idea:running",
                "score": 0,
                "score_reasons": [],
                "labels": [],
                "metadata": {},
                "created_at": 1.0,
                "updated_at": 1.0,
            },
        ],
    }
    (tmp_path / ".openharness" / "autopilot").mkdir(parents=True)
    (tmp_path / ".openharness" / "autopilot" / "registry.json").write_text(
        json.dumps(registry)
    )
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/cards/ap-running-card/model",
        headers={"Authorization": "Bearer test-token"},
        json={"model": "gpt-4.1"},
    )
    assert response.status_code == 200
    assert response.json()["model"] == "gpt-4.1"


# ----------------------------------------------------------------------
# GET /api/pipeline/journal
# ----------------------------------------------------------------------


def _write_journal(tmp_path, lines: list[str]) -> None:
    journal_dir = tmp_path / ".openharness" / "autopilot"
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / "repo_journal.jsonl").write_text("\n".join(lines) + "\n")


def test_pipeline_journal_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/pipeline/journal").status_code == 401


def test_pipeline_journal_returns_empty_when_no_file(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/journal",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"entries": []}


def test_pipeline_journal_returns_entries_newest_first(tmp_path) -> None:
    entries = [
        json.dumps(
            {
                "timestamp": 100.0,
                "kind": "intake_added",
                "summary": "first",
                "task_id": "ap-1",
                "metadata": {},
            }
        ),
        json.dumps(
            {
                "timestamp": 200.0,
                "kind": "status_running",
                "summary": "second",
                "task_id": "ap-1",
                "metadata": {},
            }
        ),
        json.dumps(
            {
                "timestamp": 300.0,
                "kind": "status_completed",
                "summary": "third",
                "task_id": "ap-1",
                "metadata": {"k": "v"},
            }
        ),
    ]
    _write_journal(tmp_path, entries)

    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/journal",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    summaries = [entry["summary"] for entry in body["entries"]]
    assert summaries == ["third", "second", "first"]
    # Each serialized entry should preserve the journal schema fields.
    first_entry = body["entries"][0]
    assert first_entry["timestamp"] == 300.0
    assert first_entry["kind"] == "status_completed"
    assert first_entry["task_id"] == "ap-1"
    assert first_entry["metadata"] == {"k": "v"}


def test_pipeline_journal_respects_limit(tmp_path) -> None:
    entries = [
        json.dumps(
            {
                "timestamp": float(i),
                "kind": "tick",
                "summary": f"entry-{i}",
                "task_id": None,
                "metadata": {},
            }
        )
        for i in range(10)
    ]
    _write_journal(tmp_path, entries)

    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/journal?limit=3",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    summaries = [entry["summary"] for entry in response.json()["entries"]]
    # Newest 3 entries, newest first.
    assert summaries == ["entry-9", "entry-8", "entry-7"]


def test_pipeline_journal_skips_malformed_lines(tmp_path) -> None:
    entries = [
        "not json",
        json.dumps(
            {
                "timestamp": 1.0,
                "kind": "intake_added",
                "summary": "good",
                "task_id": None,
                "metadata": {},
            }
        ),
        "",
        "{not even json",
    ]
    _write_journal(tmp_path, entries)

    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/journal",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["summary"] == "good"


# GET/PATCH /api/pipeline/policy


def _policy_yaml(*, include_repair: bool = True) -> str:
    content = """intake:
  mode: unified_queue
decision:
  default_human_gate: true
execution:
  default_model: oc-medium
  max_parallel_runs: 2
github:
  issue_comment_style: bilingual
"""
    if include_repair:
        content += """repair:
  max_rounds: 2
"""
    return content


def test_pipeline_policy_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/pipeline/policy").status_code == 401
    assert client.patch(
        "/api/pipeline/policy",
        json={"yaml_content": _policy_yaml()},
    ).status_code == 401


def test_pipeline_policy_get_returns_yaml_content_and_parsed_json(tmp_path) -> None:
    policy_path = tmp_path / ".openharness" / "autopilot" / "autopilot_policy.yaml"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(_policy_yaml(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["yaml_content"] == _policy_yaml()
    assert data["parsed"] == {
        "intake": {"mode": "unified_queue"},
        "decision": {"default_human_gate": True},
        "execution": {"default_model": "oc-medium", "max_parallel_runs": 2},
        "github": {"issue_comment_style": "bilingual"},
        "repair": {"max_rounds": 2},
    }
    assert data["defaults"]["default_model"] == "oc-medium"


def test_pipeline_policy_get_returns_empty_when_file_missing(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["yaml_content"] == ""
    assert data["parsed"] is None
    assert data["defaults"]["default_model"] is None


def test_pipeline_policy_patch_validates_and_writes_policy(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
        json={"yaml_content": _policy_yaml()},
    )

    assert response.status_code == 200
    assert response.json()["parsed"]["execution"] == {"default_model": "oc-medium", "max_parallel_runs": 2}
    assert (
        tmp_path / ".openharness" / "autopilot" / "autopilot_policy.yaml"
    ).read_text(encoding="utf-8") == _policy_yaml()


def test_pipeline_policy_patch_rejects_invalid_yaml(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
        json={"yaml_content": "intake: ["},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_yaml"


def test_pipeline_policy_patch_requires_top_level_keys(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
        json={"yaml_content": _policy_yaml(include_repair=False)},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "error": "missing_required_keys",
        "missing": ["repair"],
        "required": ["intake", "decision", "execution", "github", "repair"],
    }


def test_pipeline_policy_patch_rejects_max_parallel_runs_too_low(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
        json={"yaml_content": _policy_yaml().replace("max_parallel_runs: 2", "max_parallel_runs: 0")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_max_parallel_runs"


def test_pipeline_policy_patch_rejects_max_parallel_runs_too_high(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
        json={"yaml_content": _policy_yaml().replace("max_parallel_runs: 2", "max_parallel_runs: 11")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_max_parallel_runs"


def test_pipeline_policy_patch_rejects_max_parallel_runs_non_integer(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/pipeline/policy",
        headers={"Authorization": "Bearer test-token"},
        json={"yaml_content": _policy_yaml().replace("max_parallel_runs: 2", "max_parallel_runs: 'three'")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_max_parallel_runs"
