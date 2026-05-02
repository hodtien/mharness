"""GET /api/agents — list agent definitions for the Web UI.

Loads built-in, user, and plugin agent definitions via
:func:`openharness.coordinator.agent_definitions.get_all_agent_definitions`
and returns a compact summary suitable for an agent picker UI.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from openharness.coordinator.agent_definitions import (
    EFFORT_LEVELS,
    PERMISSION_MODES,
    AgentDefinition,
    get_all_agent_definitions,
)
from openharness.webui.server.routes.models import list_models
from openharness.webui.server.state import require_token

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/agents",
    tags=["agents"],
    dependencies=[Depends(require_token)],
)


class _UpdateAgentBody(BaseModel):
    """Request body for ``PATCH /api/agents/{name}``."""

    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None


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


def _split_frontmatter_raw(content: str) -> tuple[dict[str, object], str, str]:
    """Split a markdown file into (frontmatter_dict, raw_fm_text, raw_body).

    Unlike :func:`_parse_agent_frontmatter`, this preserves the raw body bytes
    (including original whitespace and trailing newlines) so a round-trip
    write doesn't reformat the markdown body.

    If the file has no leading ``---`` block, returns ``({}, "", content)``.
    """

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, "", content

    end_index: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index is None:
        return {}, "", content

    fm_text = "".join(lines[1:end_index])
    body = "".join(lines[end_index + 1 :])
    parsed = yaml.safe_load(fm_text) if fm_text.strip() else {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, fm_text, body


def _update_field_in_place(
    frontmatter: dict[str, object],
    canonical_key: str,
    aliases: tuple[str, ...],
    value: object,
) -> None:
    """Set ``value`` in *frontmatter* using the existing alias if present.

    Agent definition files in the wild may use either snake_case
    (``permission_mode``) or camelCase (``permissionMode``). To avoid creating
    duplicate keys that disagree with each other, prefer the key that already
    appears in the file; otherwise use ``canonical_key``.
    """

    for alias in aliases:
        if alias in frontmatter:
            frontmatter[alias] = value
            return
    frontmatter[canonical_key] = value


def _model_exists(model_id: str) -> bool:
    """Return True if ``model_id`` is offered by any provider in /api/models."""

    try:
        grouped = list_models()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("failed to list models for validation: %s", exc)
        return False
    for entries in grouped.values():
        for entry in entries:
            if entry.get("id") == model_id:
                return True
    return False


@router.patch("/{name}")
def update_agent(name: str, body: _UpdateAgentBody) -> dict[str, object | None]:
    """Update selected fields of a user agent definition file.

    Accepts ``model``, ``effort``, and ``permission_mode``; only fields
    explicitly present in the request body are written. The on-disk YAML
    frontmatter is updated in place, preserving the original markdown body
    and any unrelated frontmatter keys.

    Built-in agents (no on-disk source file) cannot be edited and return
    **400**. Unknown agent names return **404**. Invalid ``effort`` /
    ``permission_mode`` values, or a ``model`` not present in
    ``GET /api/models``, return **400**.
    """

    fields_set = body.model_fields_set
    if not fields_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of model, effort, permission_mode must be provided",
        )

    try:
        agents = get_all_agent_definitions()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("failed to load agent definitions: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load agent definitions",
        ) from exc

    target = next((a for a in agents if a.name == name), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {name!r} not found",
        )

    source_path_str = _source_file(target)
    if source_path_str is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent {name!r} has no editable on-disk definition (built-in or plugin)",
        )

    source_path = Path(source_path_str)
    if not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent definition file not found: {source_path}",
        )

    # Validate before touching the file.
    if "effort" in fields_set and body.effort is not None:
        if body.effort not in EFFORT_LEVELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid effort {body.effort!r}; expected one of {list(EFFORT_LEVELS)}",
            )

    if "permission_mode" in fields_set and body.permission_mode is not None:
        if body.permission_mode not in PERMISSION_MODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid permission_mode {body.permission_mode!r}; "
                    f"expected one of {list(PERMISSION_MODES)}"
                ),
            )

    if "model" in fields_set and body.model is not None:
        if not _model_exists(body.model):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model {body.model!r} is not available in /api/models",
            )

    try:
        content = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read agent file: {exc}",
        ) from exc

    frontmatter, _fm_text, raw_body = _split_frontmatter_raw(content)

    if "model" in fields_set:
        _update_field_in_place(frontmatter, "model", ("model",), body.model)
    if "effort" in fields_set:
        _update_field_in_place(frontmatter, "effort", ("effort",), body.effort)
    if "permission_mode" in fields_set:
        _update_field_in_place(
            frontmatter,
            "permission_mode",
            ("permissionMode", "permission_mode"),
            body.permission_mode,
        )

    new_fm_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    new_content = f"---\n{new_fm_text}---\n{raw_body}"

    try:
        source_path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write agent file: {exc}",
        ) from exc

    # Reload and return the updated summary.
    refreshed = next(
        (a for a in get_all_agent_definitions() if a.name == name),
        None,
    )
    if refreshed is None:
        # Should not happen — file was just written — but stay defensive.
        return _summarize(target)
    return _summarize(refreshed)
