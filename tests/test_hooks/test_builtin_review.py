"""Tests for built-in code-review hooks."""

from __future__ import annotations

from types import SimpleNamespace

from openharness.hooks.builtins import (
    default_subagent_review_hook,
    default_turn_review_hook,
    register_builtins,
)
from openharness.hooks.events import HookEvent
from openharness.hooks.loader import HookRegistry, load_hook_registry
from openharness.hooks.schemas import AgentHookDefinition


def test_default_subagent_review_hook_is_agent_type():
    hook = default_subagent_review_hook()
    assert isinstance(hook, AgentHookDefinition)
    assert "code-reviewer" in hook.prompt
    assert hook.block_on_failure is False


def test_default_turn_review_hook_is_agent_type():
    hook = default_turn_review_hook()
    assert isinstance(hook, AgentHookDefinition)
    assert "code-reviewer" in hook.prompt


def test_register_builtins_installs_both_events():
    registry = HookRegistry()
    register_builtins(registry)
    assert len(registry.get(HookEvent.SUBAGENT_STOP)) == 1
    assert len(registry.get(HookEvent.TURN_COMPLETE)) == 1


def test_register_builtins_disabled_skips():
    registry = HookRegistry()
    register_builtins(registry, disabled=True)
    assert registry.get(HookEvent.SUBAGENT_STOP) == []
    assert registry.get(HookEvent.TURN_COMPLETE) == []


def test_load_hook_registry_includes_builtins_by_default():
    settings = SimpleNamespace(hooks={}, disable_builtin_review=False)
    registry = load_hook_registry(settings)
    assert any(
        isinstance(h, AgentHookDefinition) for h in registry.get(HookEvent.SUBAGENT_STOP)
    )
    assert any(
        isinstance(h, AgentHookDefinition) for h in registry.get(HookEvent.TURN_COMPLETE)
    )


def test_load_hook_registry_respects_disable_flag():
    settings = SimpleNamespace(hooks={}, disable_builtin_review=True)
    registry = load_hook_registry(settings)
    assert registry.get(HookEvent.SUBAGENT_STOP) == []
    assert registry.get(HookEvent.TURN_COMPLETE) == []
