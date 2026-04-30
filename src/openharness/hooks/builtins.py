"""Built-in hooks shipped with OpenHarness.

These hooks are registered by default and can be disabled via settings.
"""

from __future__ import annotations

from openharness.hooks.events import HookEvent
from openharness.hooks.schemas import AgentHookDefinition

_SUBAGENT_REVIEW_PROMPT = (
    "A sub-agent just finished. Spawn the `code-reviewer` agent to review the "
    "modifications it produced. Skip review if the sub-agent itself was the "
    "code-reviewer (subagent_type == 'code-reviewer') to avoid recursion. "
    "Summarize CRITICAL/HIGH findings; emit `Severity: <CRITICAL|HIGH|MEDIUM|LOW|NONE>` "
    "on the final line."
)

_TURN_REVIEW_PROMPT = (
    "An assistant turn just completed. If `modified_files` is non-empty, spawn the "
    "`code-reviewer` agent on those files; otherwise return immediately. "
    "Emit `Severity: <CRITICAL|HIGH|MEDIUM|LOW|NONE>` on the final line."
)


def default_subagent_review_hook() -> AgentHookDefinition:
    """Return the default SUBAGENT_STOP code review hook."""
    return AgentHookDefinition(
        prompt=_SUBAGENT_REVIEW_PROMPT,
        timeout_seconds=300,
        block_on_failure=False,
    )


def default_turn_review_hook() -> AgentHookDefinition:
    """Return the default TURN_COMPLETE code review hook."""
    return AgentHookDefinition(
        prompt=_TURN_REVIEW_PROMPT,
        timeout_seconds=300,
        block_on_failure=False,
    )


def register_builtins(registry, *, disabled: bool = False) -> None:
    """Register built-in hooks on a HookRegistry.

    Caller can pass disabled=True to skip registration entirely (settings toggle).
    """
    if disabled:
        return
    registry.register(HookEvent.SUBAGENT_STOP, default_subagent_review_hook())
    registry.register(HookEvent.TURN_COMPLETE, default_turn_review_hook())
