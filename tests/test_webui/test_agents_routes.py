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
