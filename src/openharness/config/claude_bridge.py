"""Bidirectional bridge between ``~/.claude/settings.json`` and OpenHarness.

This module lets OpenHarness consume the Claude Code user-level config so
custom proxy-routed models (e.g. ``http://localhost:PORT/v1``) registered in
``~/.claude/settings.json`` show up as a first-class provider profile inside
OpenHarness — without forcing the user to duplicate them in
``~/.openharness/settings.json``.

Read direction (claude → openharness):
    * Pulls ``env.ANTHROPIC_BASE_URL`` / ``env.ANTHROPIC_AUTH_TOKEN``.
    * Pulls every entry under ``models`` and registers them as
      ``allowed_models`` on a synthetic profile named ``claude-router``.
    * Picks the active model from the top-level ``model`` field.

Write direction (openharness → claude):
    * Updates the top-level ``model`` field when the user switches models
      via OpenHarness CLI or the harness self-modifies for an agent.

The bridge is opt-in. Callers must explicitly invoke
:func:`apply_claude_bridge` (e.g. from ``load_settings``) — we do not silently
mutate the user's Claude config.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openharness.config.settings import (
    ProviderProfile,
    Settings,
    default_provider_profiles,
)
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text


CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CLAUDE_BRIDGE_PROFILE = "claude-router"

# Anthropic-class default context budget.  Routed models (claude-architect,
# claude-review, etc.) all sit on Sonnet/Opus-grade backends, so a 200k window
# with auto-compact at ~80% gives long-running coordinator sessions enough
# headroom before the engine triggers compaction.
DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000
DEFAULT_AUTO_COMPACT_THRESHOLD_TOKENS = 160_000


class ClaudeModelEntry(BaseModel):
    """Single entry from the ``models`` block of ``~/.claude/settings.json``."""

    name: str
    model: str
    description: str = ""


class ClaudeSettings(BaseModel):
    """Subset of ``~/.claude/settings.json`` we care about."""

    base_url: str | None = None
    auth_token: str | None = None
    active_model: str | None = None
    timeout_ms: int | None = None
    models: dict[str, ClaudeModelEntry] = Field(default_factory=dict)
    # Each agent maps to an ordered fallback chain. Single-string entries in
    # the JSON are coerced to a 1-item list so the in-memory shape is uniform.
    agent_models: dict[str, list[str]] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_model_chain(value: Any) -> list[str]:
    """Normalize a string or list into a non-empty list of model names."""
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
        return out
    return []


def read_claude_settings(path: Path | None = None) -> ClaudeSettings | None:
    """Read ``~/.claude/settings.json`` and return the parsed projection.

    Returns ``None`` when the file does not exist or cannot be parsed.
    Never raises — a malformed Claude config should not block OpenHarness.
    """
    target = path or CLAUDE_SETTINGS_PATH
    if not target.exists():
        return None
    try:
        raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    env = raw.get("env") or {}
    base_url = env.get("ANTHROPIC_BASE_URL") or None
    auth_token = env.get("ANTHROPIC_AUTH_TOKEN") or None
    timeout_ms = _coerce_int(env.get("API_TIMEOUT_MS"))

    models_block = raw.get("models") or {}
    models: dict[str, ClaudeModelEntry] = {}
    if isinstance(models_block, dict):
        for name, entry in models_block.items():
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model") or name).strip()
            if not model_id:
                continue
            models[name] = ClaudeModelEntry(
                name=name,
                model=model_id,
                description=str(entry.get("description") or ""),
            )

    active_model = raw.get("model") or None
    if isinstance(active_model, str):
        active_model = active_model.strip() or None

    agent_models_block = raw.get("agent_models") or {}
    agent_models: dict[str, list[str]] = {}
    if isinstance(agent_models_block, dict):
        for agent, value in agent_models_block.items():
            if not isinstance(agent, str):
                continue
            agent = agent.strip()
            if not agent:
                continue
            chain = _coerce_model_chain(value)
            if chain:
                agent_models[agent] = chain

    return ClaudeSettings(
        base_url=base_url,
        auth_token=auth_token,
        active_model=active_model,
        timeout_ms=timeout_ms,
        models=models,
        agent_models=agent_models,
        raw=raw,
    )


def build_router_profile(claude: ClaudeSettings) -> ProviderProfile | None:
    """Translate Claude's router config into an OpenHarness ``ProviderProfile``.

    Returns ``None`` when there is no usable base_url — without a router URL
    there is nothing to route to.
    """
    if not claude.base_url:
        return None

    allowed = sorted({entry.model for entry in claude.models.values()})
    default_model = (
        claude.active_model
        or (allowed[0] if allowed else "claude-sonnet-4-6")
    )

    return ProviderProfile(
        label="Claude Router (~/.claude/settings.json)",
        provider="anthropic",
        api_format="anthropic",
        auth_source="anthropic_api_key",
        default_model=default_model,
        last_model=claude.active_model,
        base_url=claude.base_url,
        credential_slot=CLAUDE_BRIDGE_PROFILE,
        allowed_models=allowed,
        context_window_tokens=DEFAULT_CONTEXT_WINDOW_TOKENS,
        auto_compact_threshold_tokens=DEFAULT_AUTO_COMPACT_THRESHOLD_TOKENS,
    )


def export_claude_auth_env(claude: ClaudeSettings) -> bool:
    """Promote ``ANTHROPIC_AUTH_TOKEN`` from Claude settings into the process env.

    OpenHarness's auth resolver reads ``ANTHROPIC_API_KEY`` from the environment
    when no scoped credential is configured. Claude Code stores the proxy token
    under ``env.ANTHROPIC_AUTH_TOKEN`` instead, so without this shim users hit
    "No API key configured" even after activating ``claude-router``.

    Only sets the variable when it is not already present — never clobbers an
    explicit user override. Returns True when an env var was injected.
    """
    if not claude.auth_token:
        return False
    if os.environ.get("ANTHROPIC_API_KEY"):
        return False
    os.environ["ANTHROPIC_API_KEY"] = claude.auth_token
    return True


def apply_claude_bridge(settings: Settings, *, activate: bool = False) -> Settings:
    """Merge the Claude router profile into ``settings`` if available.

    When ``activate`` is True, also flips ``active_profile`` to
    ``claude-router`` so the next API call routes through the proxy without
    extra CLI flags. Otherwise the profile is registered but not selected.

    As a side effect, also exports ``ANTHROPIC_AUTH_TOKEN`` from
    ``~/.claude/settings.json`` to ``ANTHROPIC_API_KEY`` so the auth resolver
    can satisfy ``anthropic_api_key`` profiles without a separate ``oh auth
    login`` step. Existing env vars are preserved.
    """
    claude = read_claude_settings()
    if claude is None:
        return settings
    profile = build_router_profile(claude)
    if profile is None:
        return settings

    export_claude_auth_env(claude)

    profiles = settings.merged_profiles()
    profiles[CLAUDE_BRIDGE_PROFILE] = profile

    updates: dict[str, Any] = {"profiles": profiles}
    if activate:
        updates["active_profile"] = CLAUDE_BRIDGE_PROFILE

    merged = settings.model_copy(update=updates)
    if activate:
        return merged.materialize_active_profile()
    return merged


def write_claude_model(model_name: str, path: Path | None = None) -> bool:
    """Persist ``model_name`` as the active model in ``~/.claude/settings.json``.

    Returns True on success, False if the file is missing or unwritable.
    Uses the same atomic-write + file-lock primitives as OpenHarness's own
    settings persistence so concurrent Claude Code processes don't see a
    half-written file.
    """
    target = path or CLAUDE_SETTINGS_PATH
    if not target.exists():
        return False

    try:
        raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    raw["model"] = model_name
    lock_path = target.with_suffix(target.suffix + ".lock")
    try:
        with exclusive_file_lock(lock_path):
            atomic_write_text(target, json.dumps(raw, indent=2) + "\n")
    except OSError:
        return False
    return True


def _mutate_claude_settings(
    target: Path,
    mutate: Any,
) -> bool:
    """Read, mutate in place, atomic-write ``~/.claude/settings.json``."""
    if not target.exists():
        return False
    try:
        raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    mutate(raw)
    lock_path = target.with_suffix(target.suffix + ".lock")
    try:
        with exclusive_file_lock(lock_path):
            atomic_write_text(target, json.dumps(raw, indent=2) + "\n")
    except OSError:
        return False
    return True


def write_agent_model(
    agent: str,
    model_name: str | list[str],
    path: Path | None = None,
) -> bool:
    """Set ``agent_models[agent]`` in ``~/.claude/settings.json``.

    Accepts either a single model name (stored as string for readability) or
    an ordered fallback chain (stored as JSON list). Empty / whitespace-only
    entries are dropped. Returns False when the file is missing or unwritable.
    """
    target = path or CLAUDE_SETTINGS_PATH
    chain = _coerce_model_chain(model_name)
    if not chain:
        return False
    # Persist single-element chains as plain strings so existing configs keep
    # the same shape; only expand to a list when there is real fallback.
    stored: str | list[str] = chain[0] if len(chain) == 1 else chain

    def _set(raw: dict[str, Any]) -> None:
        block = raw.get("agent_models")
        if not isinstance(block, dict):
            block = {}
        block[agent] = stored
        raw["agent_models"] = block

    return _mutate_claude_settings(target, _set)


def delete_agent_model(agent: str, path: Path | None = None) -> bool:
    """Remove ``agent_models[agent]`` from ``~/.claude/settings.json``."""
    target = path or CLAUDE_SETTINGS_PATH

    def _del(raw: dict[str, Any]) -> None:
        block = raw.get("agent_models")
        if isinstance(block, dict):
            block.pop(agent, None)
            raw["agent_models"] = block

    return _mutate_claude_settings(target, _del)


@dataclass(frozen=True)
class AgentModelBinding:
    """Resolved model selection for a coordinator agent.

    ``model`` is the primary choice; ``fallbacks`` are tried in order when the
    primary fails with a transient error (5xx, 429, timeout). Empty tuple
    means no fallback configured.
    """

    agent: str
    model: str
    source: str  # "agent_override" | "agent_map" | "profile_default" | "claude_active"
    fallbacks: tuple[str, ...] = ()

    @property
    def chain(self) -> tuple[str, ...]:
        """Full ordered chain: primary first, then fallbacks."""
        return (self.model, *self.fallbacks)


def resolve_agent_model(
    settings: Settings,
    agent: str,
    *,
    overrides: dict[str, str | list[str]] | None = None,
) -> AgentModelBinding:
    """Pick the model an agent should use given current settings.

    Precedence (highest first):
      1. ``overrides[agent]`` — runtime override map (e.g. CLI flag).
      2. ``agent_models[agent]`` — persistent per-agent map in ``~/.claude/settings.json``.
      3. Active profile's ``last_model`` if set, else ``default_model``.
      4. ``~/.claude/settings.json`` top-level ``model``.

    When the chosen source has multiple models (fallback chain), the first is
    the primary and the rest populate ``fallbacks``.
    """
    if overrides and agent in overrides:
        chain = _coerce_model_chain(overrides[agent])
        if chain:
            return AgentModelBinding(
                agent=agent,
                model=chain[0],
                source="agent_override",
                fallbacks=tuple(chain[1:]),
            )

    claude = read_claude_settings()
    if claude is not None and agent in claude.agent_models:
        chain = claude.agent_models[agent]
        if chain:
            return AgentModelBinding(
                agent=agent,
                model=chain[0],
                source="agent_map",
                fallbacks=tuple(chain[1:]),
            )

    _, profile = settings.resolve_profile()
    profile_model = (profile.last_model or "").strip() or profile.default_model
    if profile_model:
        return AgentModelBinding(agent=agent, model=profile_model, source="profile_default")

    if claude is not None and claude.active_model:
        return AgentModelBinding(agent=agent, model=claude.active_model, source="claude_active")

    fallback = default_provider_profiles()["claude-api"].default_model
    return AgentModelBinding(agent=agent, model=fallback, source="profile_default")
