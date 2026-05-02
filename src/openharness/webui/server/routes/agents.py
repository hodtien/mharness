"""GET /api/agents — list agent definitions for the Web UI.

Loads built-in, user, and plugin agent definitions via
:func:`openharness.coordinator.agent_definitions.get_all_agent_definitions`
and returns a compact summary suitable for an agent picker UI.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends

from openharness.coordinator.agent_definitions import (
    AgentDefinition,
    get_all_agent_definitions,
)
from openharness.webui.server.state import require_token

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/agents",
    tags=["agents"],
    dependencies=[Depends(require_token)],
)


def _tools_count(agent: AgentDefinition) -> int | None:
    """Return the number of tools allowed by the agent.

    ``None`` (or ``["*"]``) on :attr:`AgentDefinition.tools` means *all tools*;
    we surface that as ``None`` so the UI can render it differently from an
    empty list.
    """
    tools = agent.tools
    if tools is None:
        return None
    if len(tools) == 1 and tools[0] == "*":
        return None
    return len(tools)


def _source_file(agent: AgentDefinition) -> str | None:
    """Return a best-effort absolute path of the agent definition file.

    Built-in agents (``base_dir == "built-in"``) have no on-disk file, so we
    return ``None`` for them. For loaded markdown agents we join ``base_dir``
    and ``filename`` and re-add the ``.md`` extension stripped during load.
    """
    if agent.filename is None or agent.base_dir is None:
        return None
    if agent.base_dir == "built-in":
        return None
    return os.path.join(agent.base_dir, f"{agent.filename}.md")


def _summarize(agent: AgentDefinition) -> dict[str, object | None]:
    return {
        "name": agent.name,
        "description": agent.description,
        "model": agent.model,
        "effort": agent.effort,
        "permission_mode": agent.permission_mode,
        "tools_count": _tools_count(agent),
        "has_system_prompt": bool(agent.system_prompt),
        "source_file": _source_file(agent),
    }


@router.get("")
def list_agents() -> list[dict[str, object | None]]:
    """Return a list of agent-definition summaries.

    The order mirrors :func:`get_all_agent_definitions`: built-ins first, then
    user, then plugin agents (with later entries overriding earlier ones for
    the same ``name``).
    """
    try:
        agents = get_all_agent_definitions()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("failed to load agent definitions: %s", exc)
        agents = []
    return [_summarize(agent) for agent in agents]


@router.get("/")
def list_agents_slash() -> list[dict[str, object | None]]:
    """Keep behavior stable for callers that include a trailing slash."""
    return list_agents()
