"""Tool for spawning local agent tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from openharness.config.claude_bridge import resolve_agent_model
from openharness.config.settings import load_settings
from openharness.coordinator.agent_definitions import get_agent_definition
from openharness.coordinator.coordinator_mode import get_team_registry
from openharness.hooks import HookEvent
from openharness.swarm.registry import get_backend_registry
from openharness.swarm.types import TeammateSpawnConfig
from openharness.tasks import get_task_manager
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class AgentToolInput(BaseModel):
    """Arguments for local agent spawning."""

    description: str = Field(description="Short description of the delegated work")
    prompt: str = Field(description="Full prompt for the local agent")
    subagent_type: str | None = Field(
        default=None,
        description="Agent type for definition lookup (e.g. 'general-purpose', 'Explore', 'worker')",
    )
    model: str | None = Field(default=None)
    command: str | None = Field(default=None, description="Override spawn command")
    team: str | None = Field(default=None, description="Optional team to attach the agent to")
    mode: str = Field(
        default="local_agent",
        description="Agent mode: local_agent, remote_agent, or in_process_teammate",
    )


class AgentTool(BaseTool):
    """Spawn a local agent subprocess."""

    name = "agent"
    description = "Spawn a local background agent task."
    input_model = AgentToolInput

    async def execute(self, arguments: AgentToolInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.mode not in {"local_agent", "remote_agent", "in_process_teammate"}:
            return ToolResult(
                output="Invalid mode. Use local_agent, remote_agent, or in_process_teammate.",
                is_error=True,
            )

        # Look up agent definition if subagent_type is specified
        agent_def = None
        if arguments.subagent_type:
            agent_def = get_agent_definition(arguments.subagent_type)

        # Resolve team and agent name for the swarm backend
        team = arguments.team or "default"
        agent_name = arguments.subagent_type or "agent"

        # Resolve model via precedence chain:
        # arguments.model > agent_def.model > resolve_agent_model() (profile/claude active).
        # When a fallback chain is configured for the agent, ``model_chain``
        # carries every model in priority order so callers can retry on
        # transient failures. The primary (``resolved_model``) is always the
        # first entry.
        resolved_model = arguments.model or (agent_def.model if agent_def else None)
        model_chain: tuple[str, ...] = (resolved_model,) if resolved_model else ()
        if not resolved_model:
            try:
                binding = resolve_agent_model(load_settings(), agent_name)
                resolved_model = binding.model
                model_chain = binding.chain
            except Exception:
                resolved_model = None
                model_chain = ()

        # Drop any model the active profile explicitly disallows. This catches
        # the common deprecated-model case before we hand the chain to the
        # subprocess.
        if model_chain:
            try:
                _, profile = load_settings().resolve_profile()
                allowed = set(profile.allowed_models or [])
            except Exception:
                allowed = set()
            if allowed:
                filtered = tuple(m for m in model_chain if m in allowed)
                if filtered:
                    model_chain = filtered
                    resolved_model = filtered[0]

        # Use subprocess backend so spawned agents are registered in
        # BackgroundTaskManager and are pollable by the task tools.
        # in_process tasks return asyncio-internal IDs that task tools
        # cannot query, and subprocess is always available on all platforms.
        registry = get_backend_registry()
        executor = registry.get_executor("subprocess")

        config = TeammateSpawnConfig(
            name=agent_name,
            team=team,
            prompt=arguments.prompt,
            cwd=str(context.cwd),
            parent_session_id="main",
            model=resolved_model,
            command=arguments.command,
            system_prompt=agent_def.system_prompt if agent_def else None,
            permissions=agent_def.permissions if agent_def else [],
            task_type=arguments.mode,
        )

        try:
            result = await executor.spawn(config)
        except Exception as exc:
            logger.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        if arguments.team:
            registry = get_team_registry()
            try:
                registry.add_agent(arguments.team, result.task_id)
            except ValueError:
                registry.create_team(arguments.team)
                registry.add_agent(arguments.team, result.task_id)

        if context.hook_executor is not None:
            manager = get_task_manager()
            unregister = None

            async def _emit_subagent_stop(task_record) -> None:
                nonlocal unregister
                if task_record.id != result.task_id:
                    return
                if unregister is not None:
                    unregister()
                    unregister = None
                await context.hook_executor.execute(
                    HookEvent.SUBAGENT_STOP,
                    {
                        "event": HookEvent.SUBAGENT_STOP.value,
                        "agent_id": result.agent_id,
                        "task_id": result.task_id,
                        "backend_type": result.backend_type,
                        "status": task_record.status,
                        "return_code": task_record.return_code,
                        "description": arguments.description,
                        "subagent_type": arguments.subagent_type or "agent",
                        "team": team,
                        "mode": arguments.mode,
                    },
                )

            unregister = manager.register_completion_listener(_emit_subagent_stop)
            task_record = manager.get_task(result.task_id)
            if task_record is not None and task_record.status in {"completed", "failed", "killed"}:
                await _emit_subagent_stop(task_record)

        return ToolResult(
            output=(
                f"Spawned agent {result.agent_id} "
                f"(task_id={result.task_id}, backend={result.backend_type})"
            ),
            metadata={
                "agent_id": result.agent_id,
                "task_id": result.task_id,
                "backend_type": result.backend_type,
                "description": arguments.description,
            },
        )
