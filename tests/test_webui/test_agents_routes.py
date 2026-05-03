from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet", spa_dir=""))


def test_agents_endpoint_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/agents").status_code == 401


def test_agents_returns_builtin_definitions(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/agents", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body, "expected at least one built-in agent"

    expected_keys = {
        "name",
        "description",
        "model",
        "effort",
        "permission_mode",
        "tools_count",
        "has_system_prompt",
        "source_file",
    }
    for entry in body:
        assert set(entry.keys()) == expected_keys

    by_name = {entry["name"]: entry for entry in body}

    # general-purpose is a built-in agent with a system prompt.
    assert "general-purpose" in by_name
    general = by_name["general-purpose"]
    assert general["has_system_prompt"] is True
    # Built-ins have no on-disk source file.
    assert general["source_file"] is None


def test_agents_includes_user_defined_agent(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))

    agents_dir = config_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agents_dir / "my-agent.md"
    agent_file.write_text(
        "---\n"
        "name: my-agent\n"
        "description: A user-defined helper for unit testing.\n"
        "model: haiku\n"
        "effort: low\n"
        "permissionMode: acceptEdits\n"
        "tools: [Read, Glob, Grep]\n"
        "---\n"
        "You are a helpful test agent.\n",
        encoding="utf-8",
    )

    client = _client(tmp_path)
    response = client.get("/api/agents", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    by_name = {entry["name"]: entry for entry in response.json()}

    assert "my-agent" in by_name
    entry = by_name["my-agent"]
    assert entry["description"] == "A user-defined helper for unit testing."
    assert entry["model"] == "haiku"
    assert entry["effort"] == "low"
    assert entry["permission_mode"] == "acceptEdits"
    assert entry["tools_count"] == 3
    assert entry["has_system_prompt"] is True
    assert entry["source_file"] == str(agent_file)


def test_agents_trailing_slash_is_supported(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/agents/", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# PATCH /api/agents/{name}
# ---------------------------------------------------------------------------


_AUTH = {"Authorization": "Bearer test-token"}


def _write_user_agent(config_dir, name: str, body: str = "Hello body.\n") -> "object":
    """Write a minimal user agent definition file under ``config_dir/agents``."""

    from pathlib import Path

    agents_dir = Path(config_dir) / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / f"{name}.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: A user-defined helper for unit testing.\n"
        "model: haiku\n"
        "effort: low\n"
        "permissionMode: acceptEdits\n"
        "tools: [Read, Glob, Grep]\n"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# GET /api/agents/{name}
# ---------------------------------------------------------------------------


def test_get_agent_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/agents/general-purpose").status_code == 401


def test_get_agent_returns_404_for_unknown_name(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/agents/does-not-exist", headers=_AUTH)
    assert response.status_code == 404


def test_get_agent_returns_builtin_details(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/agents/general-purpose", headers=_AUTH)

    assert response.status_code == 200
    payload = response.json()

    expected_keys = {
        "name",
        "description",
        "system_prompt",
        "tools",
        "model",
        "effort",
        "permission_mode",
        "source_file",
        "has_system_prompt",
    }
    assert set(payload.keys()) == expected_keys

    assert payload["name"] == "general-purpose"
    assert payload["has_system_prompt"] is True
    # system_prompt is the full content, not None or truncated
    assert payload["system_prompt"] is not None
    assert len(payload["system_prompt"]) > 0
    # Built-ins have no on-disk source file
    assert payload["source_file"] is None


def test_get_agent_returns_user_agent_details(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    path = _write_user_agent(config_dir, "my-agent", body="You are a test agent.\n")

    client = _client(tmp_path)
    response = client.get("/api/agents/my-agent", headers=_AUTH)

    assert response.status_code == 200
    payload = response.json()

    assert payload["name"] == "my-agent"
    assert payload["description"] == "A user-defined helper for unit testing."
    assert payload["model"] == "haiku"
    assert payload["effort"] == "low"
    assert payload["permission_mode"] == "acceptEdits"
    assert payload["source_file"] == str(path)
    assert payload["has_system_prompt"] is True
    # The loader strips trailing whitespace from the body.
    assert payload["system_prompt"] in ("You are a test agent.", "You are a test agent.\n")
    # tools list is returned as an array
    assert payload["tools"] == ["Read", "Glob", "Grep"]


def test_get_agent_tools_is_none_for_all_tools_agent(tmp_path, monkeypatch) -> None:
    """An agent with tools: ['*'] should return tools: null (None means all)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))

    agents_dir = config_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "all-tools.md").write_text(
        "---\n"
        "name: all-tools\n"
        "description: Agent with all tools.\n"
        "tools: ['*']\n"
        "---\n"
        "All tools agent.\n",
        encoding="utf-8",
    )

    client = _client(tmp_path)
    response = client.get("/api/agents/all-tools", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["tools"] is None


# ---------------------------------------------------------------------------
# PATCH /api/agents/{name}
# ---------------------------------------------------------------------------


def test_patch_agent_requires_auth(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch("/api/agents/whatever", json={"effort": "high"})
    assert response.status_code == 401


def test_patch_agent_returns_404_for_unknown_name(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/agents/does-not-exist",
        json={"effort": "high"},
        headers=_AUTH,
    )
    assert response.status_code == 404


def test_patch_agent_rejects_builtin(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.patch(
        "/api/agents/general-purpose",
        json={"effort": "high"},
        headers=_AUTH,
    )
    assert response.status_code == 400


def test_patch_agent_requires_at_least_one_field(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)
    response = client.patch("/api/agents/my-agent", json={}, headers=_AUTH)
    assert response.status_code == 400


def test_patch_agent_rejects_invalid_effort(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)
    response = client.patch(
        "/api/agents/my-agent",
        json={"effort": "extreme"},
        headers=_AUTH,
    )
    assert response.status_code == 400


def test_patch_agent_rejects_invalid_permission_mode(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)
    response = client.patch(
        "/api/agents/my-agent",
        json={"permission_mode": "totallyAllow"},
        headers=_AUTH,
    )
    assert response.status_code == 400


def test_patch_agent_rejects_unknown_model(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)
    response = client.patch(
        "/api/agents/my-agent",
        json={"model": "ghost-model-9000"},
        headers=_AUTH,
    )
    assert response.status_code == 400


def test_patch_agent_updates_only_supplied_fields_and_preserves_body(
    tmp_path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    body = "You are a helpful test agent.\n\n## Notes\n\n- one\n- two\n"
    path = _write_user_agent(config_dir, "my-agent", body=body)

    client = _client(tmp_path)

    # Pick a real model from /api/models so validation passes.
    models = client.get("/api/models", headers=_AUTH).json()
    sample_model = next(iter(next(iter(models.values()))))["id"]

    response = client.patch(
        "/api/agents/my-agent",
        json={"model": sample_model, "effort": "high"},
        headers=_AUTH,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "my-agent"
    assert payload["model"] == sample_model
    assert payload["effort"] == "high"
    # permission_mode was NOT in the request; preserved from the file.
    assert payload["permission_mode"] == "acceptEdits"
    assert payload["has_system_prompt"] is True

    # File-on-disk: markdown body and unrelated frontmatter are preserved.
    new_text = path.read_text(encoding="utf-8")
    assert new_text.endswith(body)
    # Frontmatter still contains description and tools (unchanged keys).
    assert "description: A user-defined helper for unit testing." in new_text
    assert "tools:" in new_text
    # camelCase permissionMode key is preserved (we did not touch it).
    assert "permissionMode: acceptEdits" in new_text


def test_patch_agent_can_update_permission_mode_only(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)
    response = client.patch(
        "/api/agents/my-agent",
        json={"permission_mode": "plan"},
        headers=_AUTH,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["permission_mode"] == "plan"
    # Untouched fields are still the original values.
    assert payload["model"] == "haiku"
    assert payload["effort"] == "low"
