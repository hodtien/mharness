"""Tests for openharness.config.claude_bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openharness.config import claude_bridge
from openharness.config.claude_bridge import (
    CLAUDE_BRIDGE_PROFILE,
    AgentModelBinding,
    ClaudeSettings,
    apply_claude_bridge,
    build_router_profile,
    delete_agent_model,
    export_claude_auth_env,
    read_claude_settings,
    resolve_agent_model,
    write_agent_model,
    write_claude_model,
)
from openharness.config.settings import ProviderProfile, Settings


def _fixture_payload() -> dict:
    return {
        "env": {
            "ANTHROPIC_BASE_URL": "http://localhost:20128/v1",
            "ANTHROPIC_AUTH_TOKEN": "redacted-token",
            "API_TIMEOUT_MS": "60000",
        },
        "model": "claude-architect-backup",
        "models": {
            "claude-architect-backup": {
                "model": "claude-architect-backup",
                "description": "Architect backup",
            },
            "claude-sonnet-4-6": {
                "model": "claude-sonnet-4-6",
                "description": "Sonnet 4.6",
            },
        },
    }


@pytest.fixture
def claude_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "settings.json"
    target.write_text(json.dumps(_fixture_payload()), encoding="utf-8")
    monkeypatch.setattr(claude_bridge, "CLAUDE_SETTINGS_PATH", target)
    return target


class TestReadClaudeSettings:
    def test_returns_none_when_missing(self, tmp_path: Path):
        assert read_claude_settings(tmp_path / "missing.json") is None

    def test_parses_full_payload(self, claude_file: Path):
        c = read_claude_settings()
        assert c is not None
        assert c.base_url == "http://localhost:20128/v1"
        assert c.auth_token == "redacted-token"
        assert c.timeout_ms == 60000
        assert c.active_model == "claude-architect-backup"
        assert set(c.models) == {"claude-architect-backup", "claude-sonnet-4-6"}

    def test_returns_none_on_malformed_json(self, tmp_path: Path):
        target = tmp_path / "bad.json"
        target.write_text("{not valid", encoding="utf-8")
        assert read_claude_settings(target) is None


class TestBuildRouterProfile:
    def test_none_without_base_url(self):
        c = ClaudeSettings(base_url=None)
        assert build_router_profile(c) is None

    def test_builds_profile_with_models(self, claude_file: Path):
        c = read_claude_settings()
        assert c is not None
        profile = build_router_profile(c)
        assert profile is not None
        assert profile.base_url == "http://localhost:20128/v1"
        assert profile.default_model == "claude-architect-backup"
        assert "claude-sonnet-4-6" in profile.allowed_models
        assert profile.credential_slot == CLAUDE_BRIDGE_PROFILE

    def test_compaction_thresholds_set(self, claude_file: Path):
        c = read_claude_settings()
        assert c is not None
        profile = build_router_profile(c)
        assert profile is not None
        assert profile.context_window_tokens == 200_000
        assert profile.auto_compact_threshold_tokens == 160_000
        assert profile.auto_compact_threshold_tokens < profile.context_window_tokens


class TestExportClaudeAuthEnv:
    def test_sets_env_when_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        c = ClaudeSettings(auth_token="redacted-token")
        assert export_claude_auth_env(c) is True
        assert os.environ["ANTHROPIC_API_KEY"] == "redacted-token"

    def test_preserves_existing_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "user-supplied")
        c = ClaudeSettings(auth_token="redacted-token")
        assert export_claude_auth_env(c) is False
        assert os.environ["ANTHROPIC_API_KEY"] == "user-supplied"

    def test_noop_without_token(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        c = ClaudeSettings(auth_token=None)
        assert export_claude_auth_env(c) is False
        assert "ANTHROPIC_API_KEY" not in os.environ


class TestApplyClaudeBridge:
    def test_registers_router_profile(self, claude_file: Path):
        base = Settings()
        merged = apply_claude_bridge(base)
        profiles = merged.merged_profiles()
        assert CLAUDE_BRIDGE_PROFILE in profiles

    def test_activate_switches_active_profile(self, claude_file: Path):
        base = Settings()
        merged = apply_claude_bridge(base, activate=True)
        assert merged.active_profile == CLAUDE_BRIDGE_PROFILE

    def test_no_op_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            claude_bridge, "CLAUDE_SETTINGS_PATH", tmp_path / "missing.json"
        )
        base = Settings()
        merged = apply_claude_bridge(base)
        assert CLAUDE_BRIDGE_PROFILE not in merged.merged_profiles()


class TestWriteClaudeModel:
    def test_writes_model_field(self, claude_file: Path):
        assert write_claude_model("claude-sonnet-4-6", claude_file) is True
        payload = json.loads(claude_file.read_text(encoding="utf-8"))
        assert payload["model"] == "claude-sonnet-4-6"
        assert payload["models"]  # other keys preserved

    def test_returns_false_when_missing(self, tmp_path: Path):
        assert write_claude_model("x", tmp_path / "missing.json") is False


class TestResolveAgentModel:
    def test_override_takes_precedence(self, claude_file: Path):
        binding = resolve_agent_model(
            Settings(), "planner", overrides={"planner": "claude-opus-4-7"}
        )
        assert binding == AgentModelBinding(
            agent="planner",
            model="claude-opus-4-7",
            source="agent_override",
            fallbacks=(),
        )

    def test_override_with_chain(self, claude_file: Path):
        binding = resolve_agent_model(
            Settings(),
            "planner",
            overrides={"planner": ["claude-opus-4-7", "claude-architect-backup"]},
        )
        assert binding.model == "claude-opus-4-7"
        assert binding.fallbacks == ("claude-architect-backup",)
        assert binding.source == "agent_override"
        assert binding.chain == ("claude-opus-4-7", "claude-architect-backup")

    def test_agent_map_takes_precedence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        payload = _fixture_payload()
        payload["agent_models"] = {"planner": "claude-review"}
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(claude_bridge, "CLAUDE_SETTINGS_PATH", target)
        binding = resolve_agent_model(Settings(), "planner")
        assert binding == AgentModelBinding(
            agent="planner",
            model="claude-review",
            source="agent_map",
            fallbacks=(),
        )

    def test_agent_map_with_fallback_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        payload = _fixture_payload()
        payload["agent_models"] = {
            "planner": ["claude-opus-4-7", "claude-architect-backup", "claude-sonnet-4-6"]
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(claude_bridge, "CLAUDE_SETTINGS_PATH", target)
        binding = resolve_agent_model(Settings(), "planner")
        assert binding.model == "claude-opus-4-7"
        assert binding.fallbacks == ("claude-architect-backup", "claude-sonnet-4-6")
        assert binding.source == "agent_map"

    def test_falls_back_to_profile_default(self, claude_file: Path):
        s = Settings()
        binding = resolve_agent_model(s, "planner")
        assert binding.source == "profile_default"
        assert binding.model
        assert binding.fallbacks == ()


class TestAgentModelWriteDelete:
    def test_write_and_read_agent_model(self, claude_file: Path):
        assert write_agent_model("code-reviewer", "claude-review", claude_file) is True
        c = read_claude_settings()
        assert c is not None
        assert c.agent_models["code-reviewer"] == ["claude-review"]

    def test_delete_agent_model(self, claude_file: Path):
        write_agent_model("planner", "claude-architect", claude_file)
        assert delete_agent_model("planner", claude_file) is True
        c = read_claude_settings()
        assert c is not None
        assert "planner" not in c.agent_models

    def test_write_creates_block_if_missing(self, claude_file: Path):
        assert write_agent_model("worker", "gh-code", claude_file) is True
        c = read_claude_settings()
        assert c is not None
        assert c.agent_models["worker"] == ["gh-code"]

    def test_write_chain_persists_as_list(self, claude_file: Path):
        chain = ["claude-opus-4-7", "claude-architect-backup", "claude-sonnet-4-6"]
        assert write_agent_model("planner", chain, claude_file) is True
        payload = json.loads(claude_file.read_text(encoding="utf-8"))
        assert payload["agent_models"]["planner"] == chain
        c = read_claude_settings()
        assert c is not None
        assert c.agent_models["planner"] == chain

    def test_write_single_element_chain_stored_as_string(self, claude_file: Path):
        # Single-element chains stay as plain strings on disk for readability,
        # but read back as 1-item list for uniform in-memory handling.
        assert write_agent_model("planner", ["claude-review"], claude_file) is True
        payload = json.loads(claude_file.read_text(encoding="utf-8"))
        assert payload["agent_models"]["planner"] == "claude-review"
        c = read_claude_settings()
        assert c is not None
        assert c.agent_models["planner"] == ["claude-review"]

    def test_write_empty_chain_returns_false(self, claude_file: Path):
        assert write_agent_model("planner", [], claude_file) is False
        assert write_agent_model("planner", "   ", claude_file) is False
