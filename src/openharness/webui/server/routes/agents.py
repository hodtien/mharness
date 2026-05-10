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


class _AgentDetailResponse(BaseModel):
    name: str
    description: str
    system_prompt: str | None
    tools: list[str] | None  # None means all tools
    model: str | None
    effort: str | None
    permission_mode: str | None
    source_file: str | None
    has_system_prompt: bool


def _tools_list(agent: AgentDefinition) -> list[str] | None:
    """Return the tools list, or None if the agent allows all tools."""
    tools = agent.tools
    if tools is None:
        return None
    if len(tools) == 1 and tools[0] == "*":
        return None
    return list(tools)


@router.get("/{name}", response_model=_AgentDetailResponse)
def get_agent(name: str) -> _AgentDetailResponse:
    """Return full details for a single agent definition, including the
    complete ``system_prompt`` and the ``tools`` list.

    Returns **404** if no agent with the given name is found.
    """
    try:
        agents = get_all_agent_definitions()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("failed to load agent definitions: %s", exc)
        agents = []

    target = next((a for a in agents if a.name == name), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {name!r} not found",
        )

    return _AgentDetailResponse(
        name=target.name,
        description=target.description,
        system_prompt=target.system_prompt,
        tools=_tools_list(target),
        model=target.model,
        effort=target.effort,
        permission_mode=target.permission_mode,
        source_file=_source_file(target),
        has_system_prompt=bool(target.system_prompt),
    )


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


class _CloneAgentBody(BaseModel):
    """Request body for ``POST /api/agents/{name}/clone``."""

    new_name: str


@router.post("/{name}/clone")
def clone_agent(name: str, body: _CloneAgentBody) -> dict[str, object | None]:
    """Clone an existing agent definition into a new user-owned file.

    The new file is written to ``<config_dir>/agents/<new_name>.md``.  The
    original agent's body and all frontmatter except ``name`` are preserved.
    Returns the summary of the newly-created agent.

    Raises **404** if the source agent is not found.
    Raises **400** if ``new_name`` is empty, already taken, or contains
    path-unsafe characters.
    """

    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="new_name must not be empty",
        )
    # Guard against path traversal.
    if any(c in new_name for c in ("/", "\\", "\0", ".")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="new_name must not contain path separators or dots",
        )

    try:
        agents = get_all_agent_definitions()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("failed to load agent definitions: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load agent definitions",
        ) from exc

    # Ensure target name is not already taken.
    if any(a.name == new_name for a in agents):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An agent named {new_name!r} already exists",
        )

    source_agent = next((a for a in agents if a.name == name), None)
    if source_agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {name!r} not found",
        )

    # Build the new agent file content.
    source_path_str = _source_file(source_agent)
    if source_path_str is not None and Path(source_path_str).is_file():
        # Preserve original markdown body from disk.
        original_content = Path(source_path_str).read_text(encoding="utf-8")
        fm_dict, _fm_text, raw_body = _split_frontmatter_raw(original_content)
    else:
        # Built-in: synthesize minimal frontmatter from the definition.
        fm_dict = {
            "description": source_agent.description,
        }
        if source_agent.model:
            fm_dict["model"] = source_agent.model
        if source_agent.effort:
            fm_dict["effort"] = source_agent.effort
        if source_agent.permission_mode:
            fm_dict["permission_mode"] = source_agent.permission_mode
        raw_body = source_agent.system_prompt or ""

    fm_dict["name"] = new_name
    new_fm_text = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True)
    new_content = f"---\n{new_fm_text}---\n{raw_body}"

    from openharness.config.paths import get_config_dir  # local import avoids circular

    dest_dir = get_config_dir() / "agents"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{new_name}.md"

    try:
        dest_path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write clone file: {exc}",
        ) from exc

    # Return summary for the newly-created agent.
    refreshed = next(
        (a for a in get_all_agent_definitions() if a.name == new_name),
        None,
    )
    if refreshed is None:
        # Fallback: synthesize from source.
        return {
            "name": new_name,
            "description": source_agent.description,
            "model": source_agent.model,
            "effort": source_agent.effort,
            "permission_mode": source_agent.permission_mode,
            "tools_count": _tools_count(source_agent),
            "has_system_prompt": bool(source_agent.system_prompt),
            "source_file": str(dest_path),
        }
    return _summarize(refreshed)


class _ValidateAgentBody(BaseModel):
    """Request body for ``POST /api/agents/{name}/validate``."""

    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None


class _ValidateAgentResponse(BaseModel):
    valid: bool
    errors: list[str]


@router.post("/{name}/validate", response_model=_ValidateAgentResponse)
def validate_agent(name: str, body: _ValidateAgentBody) -> _ValidateAgentResponse:
    """Validate a prospective agent configuration patch without persisting it.

    Returns ``{"valid": true, "errors": []}`` when the proposed values are all
    acceptable.  When one or more values are invalid, returns
    ``{"valid": false, "errors": ["...", ...]}``.

    Unknown agent names return **404**.  The endpoint never modifies any file.
    """

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

    errors: list[str] = []

    if body.effort is not None and body.effort not in EFFORT_LEVELS:
        errors.append(
            f"Invalid effort {body.effort!r}; expected one of {list(EFFORT_LEVELS)}"
        )

    if body.permission_mode is not None and body.permission_mode not in PERMISSION_MODES:
        errors.append(
            f"Invalid permission_mode {body.permission_mode!r}; "
            f"expected one of {list(PERMISSION_MODES)}"
        )

    if body.model is not None and not _model_exists(body.model):
        errors.append(f"Model {body.model!r} is not available in /api/models")

    return _ValidateAgentResponse(valid=len(errors) == 0, errors=errors)
