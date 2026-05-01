from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.services.session_storage import get_project_session_dir, save_session_snapshot
from openharness.api.usage import UsageSnapshot
from openharness.auth.storage import load_credential
from openharness.config.settings import load_settings, save_settings
from openharness.engine.messages import ConversationMessage, ToolResultBlock, ToolUseBlock
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
