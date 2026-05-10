from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


def _write_user_agent(config_dir: Path, name: str, *, model: str = "haiku") -> Path:
    agents_dir = config_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / f"{name}.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: Test agent for unit tests.\n"
        f"model: {model}\n"
        "effort: low\n"
        "permissionMode: acceptEdits\n"
        "tools: [Read, Glob, Grep]\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )
    return path


def test_list_agents_returns_builtins(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/agents", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body
    by_name = {entry["name"]: entry for entry in body}
    assert "general-purpose" in by_name
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
        assert set(entry) == expected_keys


def test_patch_agent_updates_model(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)

    # Pick a real model exposed by /api/models so server-side validation passes.
    models = client.get("/api/models", headers=AUTH).json()
    target_model = next(iter(next(iter(models.values()))))["id"]

    response = client.patch(
        "/api/agents/my-agent",
        headers=AUTH,
        json={"model": target_model},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "my-agent"
    assert payload["model"] == target_model


def test_patch_unknown_agent_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/agents/does-not-exist",
        headers=AUTH,
        json={"effort": "high"},
    )

    assert response.status_code == 404


def test_clone_agent_creates_new_file(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "source-agent", model="sonnet")

    client = _client(tmp_path)

    response = client.post(
        "/api/agents/source-agent/clone",
        headers=AUTH,
        json={"new_name": "cloned-agent"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "cloned-agent"
    # Verify the file was created.
    agents_dir = config_dir / "agents"
    assert (agents_dir / "cloned-agent.md").is_file()


def test_clone_agent_rejects_duplicate_name(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "original")
    _write_user_agent(config_dir, "duplicate")

    client = _client(tmp_path)

    response = client.post(
        "/api/agents/original/clone",
        headers=AUTH,
        json={"new_name": "duplicate"},
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_clone_unknown_agent_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/agents/nonexistent/clone",
        headers=AUTH,
        json={"new_name": "new-name"},
    )

    assert response.status_code == 404


def test_validate_agent_returns_valid(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)

    response = client.post(
        "/api/agents/my-agent/validate",
        headers=AUTH,
        json={"effort": "high", "permission_mode": "acceptEdits"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is True
    assert payload["errors"] == []


def test_validate_agent_returns_errors_for_invalid_values(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))
    _write_user_agent(config_dir, "my-agent")

    client = _client(tmp_path)

    response = client.post(
        "/api/agents/my-agent/validate",
        headers=AUTH,
        json={"effort": "invalid-effort", "model": "nonexistent-model-xyz"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    assert "invalid-effort" in payload["errors"][0]
    assert "nonexistent-model-xyz" in payload["errors"][1]


def test_validate_unknown_agent_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/agents/nonexistent/validate",
        headers=AUTH,
        json={"effort": "low"},
    )

    assert response.status_code == 404
