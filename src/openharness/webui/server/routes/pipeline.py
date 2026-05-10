"""Pipeline (autopilot registry) REST endpoints for the Web UI."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from openharness.autopilot.run_stream import (
    get_writer,
    read_stream_file_chunk,
    stream_file_line_count,
    stream_file_mtime,
)
from openharness.autopilot.service import _DEFAULT_AUTOPILOT_POLICY, RepoAutopilotStore
from openharness.autopilot.session_store import (
    clear_checkpoints,
    load_latest_checkpoint,
)
from openharness.config.paths import get_project_autopilot_policy_path
from openharness.autopilot.types import RepoAutopilotRegistry, RepoJournalEntry, RepoTaskStatus
from openharness.webui.server.state import WebUIState, get_state, get_task_manager, require_stream_token, require_token

_CARD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _ensure_safe_card_id(card_id: str) -> None:
    """Reject path-traversal attempts at the HTTP boundary."""
    if not isinstance(card_id, str) or not _CARD_ID_RE.match(card_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_card_id"},
        )


router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
)

_AUTH_DEPENDENCY = [Depends(require_token)]


class CreateManualCardRequest(BaseModel):
    """Payload for POST /api/pipeline/cards.

    ``title`` is required; ``body`` and ``labels`` are optional.
    """

    title: str = Field(..., min_length=1)
    body: str | None = None
    labels: list[str] | None = None


class CardActionRequest(BaseModel):
    """Payload for POST /api/pipeline/cards/{id}/action.

    ``action`` must be one of: ``accept``, ``reject``, ``retry``, ``reset``.
    ``reset`` requeues failed/rejected/killed cards back to ``queued``.
    """

    action: Literal["accept", "reject", "retry", "reset"]


class CardModelPatchRequest(BaseModel):
    """Payload for PATCH /api/pipeline/cards/{id}/model."""

    model: str | None = None


def _serialize_card(card: dict) -> dict:
    """Return the JSON representation required by the Web UI card contract."""
    metadata = card.get("metadata", {})
    return {
        "id": card["id"],
        "title": card["title"],
        "body": _safe_text(card.get("body")) or "",
        "status": card["status"],
        "source_kind": card["source_kind"],
        "score": card["score"],
        "labels": card["labels"],
        "model": card.get("model") or _safe_text(metadata.get("execution_model")),
        "created_at": card["created_at"],
        "updated_at": card["updated_at"],
        "attempt_count": int(metadata.get("attempt_count", 0) or 0),
        "metadata": {
            "last_note": _safe_text(metadata.get("last_note")),
            "linked_pr_url": _safe_text(metadata.get("linked_pr_url")),
            "resume_available": bool(metadata.get("resume_available")),
            "resume_phase": _safe_text(metadata.get("resume_phase")),
        },
    }


def _serialize_card_detail(card: dict, *, available_models: list[str]) -> dict:
    """Return the detailed card payload for GET /api/pipeline/cards/{id}."""
    metadata = card.get("metadata") or {}
    return {
        "id": card["id"],
        "title": card["title"],
        "status": card["status"],
        "source_kind": card["source_kind"],
        "source_ref": card.get("source_ref", ""),
        "score": card["score"],
        "score_reasons": card.get("score_reasons", []),
        "labels": card["labels"],
        "model": card.get("model"),
        "body": card.get("body", ""),
        "metadata": metadata,
        "linked_pr_url": _safe_text(metadata.get("linked_pr_url")),
        "attempt_count": int(metadata.get("attempt_count", 0) or 0),
        "available_models": available_models,
        "created_at": card["created_at"],
        "updated_at": card["updated_at"],
    }


def _collect_available_models(state: WebUIState) -> list[str]:
    """Return a deduplicated list of allowed models across provider profiles."""
    try:
        from openharness.config.settings import load_settings
    except Exception:
        return []
    try:
        settings = load_settings()
    except Exception:
        return []
    seen: dict[str, None] = {}
    for profile in settings.profiles.values():
        for model in profile.allowed_models or []:
            if model and model not in seen:
                seen[model] = None
    return list(seen.keys())


def _safe_text(value: str | None) -> str | None:
    return value if value else None


def _serialize_journal_entry(entry: RepoJournalEntry) -> dict:
    """Return the JSON representation for one repo journal entry."""
    return entry.model_dump(mode="json")


@router.get("/journal", dependencies=_AUTH_DEPENDENCY)
def list_pipeline_journal(
    limit: int = 50,
    card_id: str | None = None,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Return journal entries, optionally filtered to one card, newest first."""
    store = RepoAutopilotStore(state.cwd)
    if card_id:
        # Fetch a wider window then filter, so the limit applies to matched rows.
        raw = list(reversed(store.load_journal(limit=max(limit * 10, limit))))
        matched = [e for e in raw if e.task_id == card_id][:limit]
        return {"entries": [_serialize_journal_entry(entry) for entry in matched]}
    entries = list(reversed(store.load_journal(limit=limit)))
    return {"entries": [_serialize_journal_entry(entry) for entry in entries]}


@router.get("/cards", dependencies=_AUTH_DEPENDENCY)
def list_pipeline_cards(state: WebUIState = Depends(get_state)) -> dict:
    """Return the autopilot task card list from the per-repo registry.

    Reads ``.openharness/autopilot/registry.json``. Returns an empty card list
    if the file does not exist or is malformed, matching the behaviour of
    :meth:`openharness.autopilot.service.RepoAutopilotService._load_registry`.
    """
    registry_path = state.cwd / ".openharness" / "autopilot" / "registry.json"
    if not registry_path.is_file():
        return {"cards": [], "updated_at": 0.0}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cards": [], "updated_at": 0.0}
    try:
        registry = RepoAutopilotRegistry.model_validate(payload)
    except ValidationError:
        return {"cards": [], "updated_at": 0.0}
    return {
        "cards": [_serialize_card(card.model_dump(mode="json")) for card in registry.cards],
        "updated_at": registry.updated_at,
    }


@router.post("/cards", status_code=status.HTTP_201_CREATED, dependencies=_AUTH_DEPENDENCY)
def enqueue_manual_card(
    body: CreateManualCardRequest,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Enqueue a manual idea card into the per-repo autopilot registry.

    Returns the freshly-created card (using the same minimal serialization as
    the list endpoint). Responds with HTTP 409 if a card with the same
    fingerprint already exists, matching the autopilot intake dedupe contract.
    """
    store = RepoAutopilotStore(state.cwd)
    card, created = store.enqueue_card(
        source_kind="manual_idea",
        title=body.title,
        body=body.body or "",
        labels=body.labels,
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_card",
                "message": "A card with the same fingerprint already exists.",
                "card_id": card.id,
            },
        )
    return _serialize_card(card.model_dump(mode="json"))


_ACTION_TO_STATUS: dict[str, RepoTaskStatus] = {
    "accept": "accepted",
    "reject": "rejected",
    "retry": "queued",
    "reset": "queued",
}


@router.post("/cards/{card_id}/action", dependencies=_AUTH_DEPENDENCY)
def action_pipeline_card(
    card_id: str,
    body: CardActionRequest,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Apply a manual lifecycle action to a pipeline card.

    Loads the per-repo registry, finds the card by ``id``, updates its
    ``status`` according to the action (accept→accepted, reject→rejected,
    retry→queued), persists the registry, and returns the updated card.
    Returns HTTP 404 if no card with the given id exists.
    """
    store = RepoAutopilotStore(state.cwd)
    if store.get_card(card_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    new_status = _ACTION_TO_STATUS[body.action]
    card = store.update_status(card_id, status=new_status)
    return _serialize_card(card.model_dump(mode="json"))


_ACTIVE_STATUSES: frozenset[str] = frozenset(
    {"preparing", "running", "verifying", "waiting_ci", "repairing", "pr_open"}
)


def _load_autopilot_policy(cwd: Path) -> dict[str, Any]:
    policy_path = get_project_autopilot_policy_path(cwd)
    if not policy_path.is_file():
        return dict(_DEFAULT_AUTOPILOT_POLICY)
    try:
        payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return dict(_DEFAULT_AUTOPILOT_POLICY)
    return payload if isinstance(payload, dict) else dict(_DEFAULT_AUTOPILOT_POLICY)


@router.get("/cards/{card_id}", dependencies=_AUTH_DEPENDENCY)
def get_pipeline_card(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Return full detail for a single pipeline card.

    Includes ``model``, full ``metadata``, ``body``, ``linked_pr_url``,
    ``attempt_count`` and the ``available_models`` list collected from
    configured provider profiles. Returns HTTP 404 if the card does not exist.
    """
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    return _serialize_card_detail(
        card.model_dump(mode="json"),
        available_models=_collect_available_models(state),
    )


@router.get("/cards/{card_id}/preflight", dependencies=_AUTH_DEPENDENCY)
def get_card_preflight(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Run preflight checks for a card and return results.

    Returns {"ok": bool, "checks": [{name, status, reason, transient, detail}...]}.
    Returns HTTP 404 if the card does not exist.
    """
    _ensure_safe_card_id(card_id)
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    result = store.run_preflight(card)
    return {
        "ok": result.passed,
        "checks": [c.model_dump() for c in result.checks],
    }


@router.patch("/cards/{card_id}/model", dependencies=_AUTH_DEPENDENCY)
def patch_pipeline_card_model(
    card_id: str,
    body: CardModelPatchRequest,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Set or clear the model override for a pipeline card.

    Pass ``{"model": "<id>"}`` to override the default execution model, or
    ``{"model": null}`` to reset back to the autopilot default.

    The supplied model is *not* strictly validated against the configured
    provider profiles — unknown values are accepted but a warning is recorded
    in the response so the Web UI can surface it. Returns HTTP 404 if the
    card does not exist.
    """
    store = RepoAutopilotStore(state.cwd)
    if store.get_card(card_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    available = _collect_available_models(state)
    warning: str | None = None
    if body.model is not None and available and body.model not in available:
        warning = (
            f"Model {body.model!r} is not in the allowed models of any "
            "configured provider profile."
        )
    card = store.update_card_model(card_id, body.model)
    payload = _serialize_card(card.model_dump(mode="json"))
    if warning:
        payload["warning"] = warning
    return payload


# ---------------------------------------------------------------------------
# Autopilot run-next trigger
# ---------------------------------------------------------------------------


@router.post("/run-next", status_code=status.HTTP_202_ACCEPTED, dependencies=_AUTH_DEPENDENCY)
async def run_next_card(state: WebUIState = Depends(get_state)) -> dict:
    """Spawn ``oh autopilot run-next`` as a background task.

    Returns HTTP 409 when no queued cards exist (checked before spawning).
    Returns HTTP 409 when another autopilot run is already in progress.
    Otherwise returns HTTP 202 with the background ``task_id`` so the caller
    can track progress via the Tasks API.
    """
    registry_path = state.cwd / ".openharness" / "autopilot" / "registry.json"
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
        cards = RepoAutopilotRegistry.model_validate(payload).cards if payload else []
    except (json.JSONDecodeError, OSError, ValidationError):
        cards = []
    queued = [c for c in cards if c.status in {"queued", "accepted"}]
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_queued_cards", "message": "No queued autopilot cards."},
        )
    policies = _load_autopilot_policy(state.cwd)
    active_count = sum(1 for c in cards if c.status in _ACTIVE_STATUSES)
    execution = policies.get("execution")
    if not isinstance(execution, dict):
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
    max_parallel = int(execution.get("max_parallel_runs", 0))
    if active_count >= max_parallel:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "capacity_reached",
                "message": f"Maximum parallel runs ({max_parallel}) reached. {active_count} tasks currently active.",
            },
        )
    oh_executable = str(Path(sys.executable).with_name("oh"))
    command = f"{shlex.quote(oh_executable)} autopilot run-next --cwd {shlex.quote(str(state.cwd))}"
    manager = get_task_manager()
    task = await manager.create_shell_task(
        command=command,
        description="autopilot run-next",
        cwd=state.cwd,
        task_type="local_bash",
    )
    return {"task_id": task.id, "status": "accepted"}


# ---------------------------------------------------------------------------
# Autopilot policy CRUD
# ---------------------------------------------------------------------------

_POLICY_REQUIRED_KEYS = ("intake", "decision", "execution", "github", "repair")


class UpdatePolicyRequest(BaseModel):
    """Payload for PATCH /api/pipeline/policy."""

    yaml_content: str


def _policy_defaults(policies: dict[str, Any]) -> dict[str, str | None]:
    """Extract selectable model defaults from a parsed policy dict."""
    execution = policies.get("execution")
    if not isinstance(execution, dict):
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
    return {
        "default_model": (execution.get("default_model") or "").strip() or None,
        "permission_mode": (execution.get("permission_mode") or "full_auto").strip(),
        "max_attempts": str(execution.get("max_attempts", "") or ""),
    }


@router.get("/policy", dependencies=_AUTH_DEPENDENCY)
def get_pipeline_policy(state: WebUIState = Depends(get_state)) -> dict:
    """Return the autopilot policy as both raw YAML and parsed JSON.

    Reads ``.openharness/autopilot/autopilot_policy.yaml``. Returns empty
    string and ``None`` for ``parsed`` when the file does not exist, so the
    Web UI can offer the user an empty editor instead of a 404.
    """
    policy_path = get_project_autopilot_policy_path(state.cwd)
    if not policy_path.is_file():
        return {"yaml_content": "", "parsed": None, "defaults": {"default_model": None}}
    yaml_content = policy_path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        parsed = None
    defaults = _policy_defaults(parsed) if isinstance(parsed, dict) else {"default_model": None}
    return {"yaml_content": yaml_content, "parsed": parsed, "defaults": defaults}


@router.patch("/policy", dependencies=_AUTH_DEPENDENCY)
def update_pipeline_policy(
    body: UpdatePolicyRequest,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Validate and persist a new autopilot policy YAML.

    Validation steps (all must pass before the file is written):
    1. ``yaml_content`` must be syntactically valid YAML.
    2. The parsed document must be a mapping.
    3. The mapping must contain every required top-level key:
       ``intake``, ``decision``, ``execution``, ``github``, ``repair``.
    """
    try:
        parsed = yaml.safe_load(body.yaml_content)
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_yaml", "message": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_policy",
                "message": "Autopilot policy must be a YAML mapping at the top level.",
            },
        )
    missing = [key for key in _POLICY_REQUIRED_KEYS if key not in parsed]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "missing_required_keys",
                "missing": missing,
                "required": list(_POLICY_REQUIRED_KEYS),
            },
        )
    # Validate max_parallel_runs in execution section (1 ≤ value ≤ 10)
    execution = parsed.get("execution", {})
    if isinstance(execution, dict) and "max_parallel_runs" in execution:
        raw = execution["max_parallel_runs"]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_max_parallel_runs",
                    "message": "max_parallel_runs must be an integer.",
                },
            )
        if not (1 <= value <= 10):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_max_parallel_runs",
                    "message": "max_parallel_runs must be between 1 and 10 (inclusive).",
                },
            )
    policy_path = get_project_autopilot_policy_path(state.cwd)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(body.yaml_content, encoding="utf-8")
    return {"yaml_content": body.yaml_content, "parsed": parsed}


# ---------------------------------------------------------------------------
# Per-card realtime event stream (SSE)
# ---------------------------------------------------------------------------


def _sse_format(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


_SSE_HEARTBEAT_INTERVAL = 15.0
_SSE_STALE_FILE_SECONDS = 300.0  # no mtime change for 5 min → treat stream as ended


@router.get("/cards/{card_id}/stream")
async def stream_card_events(
    card_id: str,
    after: int = 0,
    state: WebUIState = Depends(get_state),
    _: None = Depends(require_stream_token),
) -> StreamingResponse:
    """Server-Sent Events feed for one autopilot card's run stream.

    Replays ``{runs_dir}/{card_id}-stream.jsonl`` from offset ``after``, then
    if the card is currently running, subscribes to the live writer and
    tails subsequent events. Sends a heartbeat comment every 15s.

    File I/O is offloaded to a thread pool so the ASGI event loop is never
    blocked (H3). Dedup uses the ``seq`` field that each :class:`RunStreamWriter`
    stamps on every event (H4). Stale writers (process died without calling
    ``close()``) are detected via the stream file's mtime not advancing for
    five minutes (H5).
    """
    _ensure_safe_card_id(card_id)
    runs_dir = state.cwd / ".openharness" / "autopilot" / "runs"

    async def _generator() -> AsyncIterator[bytes]:
        offset = max(0, int(after))

        writer = get_writer(card_id)
        queue: asyncio.Queue[dict[str, Any]] | None = None
        if writer is not None:
            loop = asyncio.get_running_loop()
            queue = writer.subscribe(loop=loop)

        try:
            # Replay in 500-event chunks so we never hold the full file in memory.
            while True:
                chunk, next_offset = await asyncio.to_thread(
                    read_stream_file_chunk, runs_dir, card_id, after=offset
                )
                for event in chunk:
                    yield _sse_format(event).encode("utf-8")
                if not chunk or next_offset == offset:
                    break
                offset = next_offset

            if writer is None or queue is None:
                current_total = await asyncio.to_thread(stream_file_line_count, runs_dir, card_id)
                if current_total > offset:
                    while True:
                        chunk, next_offset = await asyncio.to_thread(
                            read_stream_file_chunk, runs_dir, card_id, after=offset
                        )
                        for event in chunk:
                            yield _sse_format(event).encode("utf-8")
                        if not chunk or next_offset == offset:
                            break
                        offset = next_offset
                yield b": stream-ended\n\n"
                return

            # Dedup bridge: read lines emitted between the file-replay and
            # subscribe instant. Use seq for deterministic dedup (H4).
            seen_seqs: set[int] = set()
            while True:
                chunk, next_offset = await asyncio.to_thread(
                    read_stream_file_chunk, runs_dir, card_id, after=offset
                )
                for event in chunk:
                    seq = event.get("seq")
                    if seq is not None:
                        seen_seqs.add(int(seq))
                    yield _sse_format(event).encode("utf-8")
                if not chunk or next_offset == offset:
                    break
                offset = next_offset

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    yield f": heartbeat {int(time.time())}\n\n".encode("utf-8")
                    if writer.closed:
                        break
                    mtime = await asyncio.to_thread(stream_file_mtime, runs_dir, card_id)
                    if mtime and (time.time() - mtime) > _SSE_STALE_FILE_SECONDS:
                        yield b": stream-stale\n\n"
                        break
                    continue
                seq = event.get("seq")
                if seq is not None and int(seq) in seen_seqs:
                    seen_seqs.discard(int(seq))
                    if writer.closed and queue.empty():
                        break
                    continue
                yield _sse_format(event).encode("utf-8")
                if writer.closed and queue.empty():
                    break
        finally:
            if queue is not None and writer is not None:
                writer.unsubscribe(queue)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Per-card checkpoint / resume
# ---------------------------------------------------------------------------


@router.get("/cards/{card_id}/checkpoint", dependencies=_AUTH_DEPENDENCY)
def get_card_checkpoint(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Return checkpoint info for a card, or 404 if none exists."""
    _ensure_safe_card_id(card_id)
    runs_dir = state.cwd / ".openharness" / "autopilot" / "runs"
    ckpt = load_latest_checkpoint(runs_dir, card_id)
    if ckpt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_checkpoint", "card_id": card_id},
        )
    return {
        "card_id": ckpt.card_id,
        "phase": ckpt.phase,
        "attempt": ckpt.attempt,
        "saved_at": ckpt.saved_at,
        "has_pending_continuation": ckpt.has_pending_continuation,
        "model": ckpt.model,
        "permission_mode": ckpt.permission_mode,
    }


@router.post("/cards/{card_id}/resume", status_code=status.HTTP_202_ACCEPTED, dependencies=_AUTH_DEPENDENCY)
async def resume_card(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Resume an interrupted autopilot card from its latest checkpoint.

    Validates that a resumable checkpoint exists, that the card is not
    currently active, and then spawns ``oh autopilot run-next`` with the
    card pre-queued for resume. Returns HTTP 202 with the background task id.
    """
    _ensure_safe_card_id(card_id)
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    is_stale_active = (
        card.status in _ACTIVE_STATUSES
        and time.time() - float(card.updated_at or 0) > store.STUCK_CARD_STALE_SECONDS
    )
    if card.status in _ACTIVE_STATUSES and not is_stale_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "card_active",
                "message": "Cannot resume while card is running.",
                "card_id": card_id,
            },
        )
    runs_dir = state.cwd / ".openharness" / "autopilot" / "runs"
    ckpt = load_latest_checkpoint(runs_dir, card_id)
    has_resumable_checkpoint = ckpt is not None and ckpt.has_pending_continuation
    if not has_resumable_checkpoint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "no_resumable_checkpoint",
                "message": "No resumable checkpoint found for this card.",
                "card_id": card_id,
            },
        )
    metadata_updates: dict[str, Any] = {"resume_requested": True}
    if is_stale_active:
        metadata_updates["stuck_resume"] = {
            "from_status": card.status,
            "stale_seconds": int(time.time() - float(card.updated_at or 0)),
            "checkpoint_phase": ckpt.phase,
            "checkpoint_attempt": ckpt.attempt,
        }
    store.update_status(
        card_id,
        status="queued",
        metadata_updates=metadata_updates,
    )
    oh_executable = str(Path(sys.executable).with_name("oh"))
    command = f"{shlex.quote(oh_executable)} autopilot run-next --cwd {shlex.quote(str(state.cwd))}"
    manager = get_task_manager()
    task = await manager.create_shell_task(
        command=command,
        description=f"autopilot resume {card_id}",
        cwd=state.cwd,
        task_type="local_bash",
    )
    return {"task_id": task.id, "card_id": card_id, "status": "accepted"}


@router.delete("/cards/{card_id}/checkpoint", dependencies=_AUTH_DEPENDENCY)
def delete_card_checkpoint(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Delete all checkpoints for a card."""
    runs_dir = state.cwd / ".openharness" / "autopilot" / "runs"
    clear_checkpoints(runs_dir, card_id)
    return {"card_id": card_id, "cleared": True}


# ---------------------------------------------------------------------------
# Direct card control: run, pause, resume, retry-now
# ---------------------------------------------------------------------------


@router.post("/cards/{card_id}/run", status_code=status.HTTP_202_ACCEPTED, dependencies=_AUTH_DEPENDENCY)
async def run_card_direct(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Start running a specific autopilot card immediately.

    The card must be in ``queued`` or ``accepted`` status (or ``paused`` for a
    staged restart). Spawns ``oh autopilot run-next --card-id`` as a background
    task. Returns HTTP 409 if the card is already active with a live worker.
    """
    _ensure_safe_card_id(card_id)
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    if card.status in _ACTIVE_STATUSES and card.metadata.get("worker_id"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "card_already_active",
                "card_id": card_id,
                "status": card.status,
                "message": "Card is already running. Use /pause first.",
            },
        )
    if card.status not in {"queued", "accepted", "paused"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_status_for_run",
                "card_id": card_id,
                "status": card.status,
                "message": "Card must be queued, accepted, or paused to start.",
            },
        )
    oh_executable = str(Path(sys.executable).with_name("oh"))
    command = f"{shlex.quote(oh_executable)} autopilot run-next --cwd {shlex.quote(str(state.cwd))} --card-id {shlex.quote(card_id)}"
    manager = get_task_manager()
    task = await manager.create_shell_task(
        command=command,
        description=f"autopilot run {card_id}",
        cwd=state.cwd,
        task_type="local_bash",
    )
    return {"task_id": task.id, "card_id": card_id, "status": "accepted"}


@router.post("/cards/{card_id}/pause", dependencies=_AUTH_DEPENDENCY)
async def pause_card(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Pause an active autopilot card by resetting its status to ``paused``.

    Only cards in ``preparing``, ``running``, ``verifying``, or ``repairing``
    status can be paused. Cards already in ``queued``, ``accepted``, ``paused``,
    or terminal statuses return HTTP 409.
    """
    _ensure_safe_card_id(card_id)
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    if card.status not in {"preparing", "running", "verifying", "repairing"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_status_for_pause",
                "card_id": card_id,
                "status": card.status,
                "message": f"Cannot pause a card in {card.status} status.",
            },
        )
    updated = store.update_status(
        card_id,
        status="paused",
        note="paused by user",
        metadata_updates={"paused_by": "user"},
    )
    return _serialize_card(updated.model_dump(mode="json"))


@router.post("/cards/{card_id}/resume", dependencies=_AUTH_DEPENDENCY)
async def resume_card_direct(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Resume a paused autopilot card by re-claiming and re-running it.

    The card must be in ``paused`` status. Clears the ``paused_by`` metadata
    and re-queues the card with a fresh worker_id, then spawns the run-next
    background task.
    """
    _ensure_safe_card_id(card_id)
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    if card.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_status_for_resume",
                "card_id": card_id,
                "status": card.status,
                "message": f"Cannot resume a card in {card.status} status. Only paused cards can be resumed.",
            },
        )
    worker_id = f"pid-{os.getpid()}-{uuid4().hex[:8]}"
    claimed = store.pick_specific_card(card_id, worker_id)
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "claim_failed",
                "card_id": card_id,
                "message": "Could not claim the card for resume.",
            },
        )
    # Clear paused metadata
    store.update_status(
        card_id,
        status="preparing",
        note="resumed by user",
        metadata_updates={"resumed_by": "user"},
    )
    oh_executable = str(Path(sys.executable).with_name("oh"))
    command = f"{shlex.quote(oh_executable)} autopilot run-next --cwd {shlex.quote(str(state.cwd))}"
    manager = get_task_manager()
    task = await manager.create_shell_task(
        command=command,
        description=f"autopilot resume {card_id}",
        cwd=state.cwd,
        task_type="local_bash",
    )
    return {"task_id": task.id, "card_id": card_id, "status": "accepted"}


@router.post("/cards/{card_id}/retry-now", status_code=status.HTTP_202_ACCEPTED, dependencies=_AUTH_DEPENDENCY)
async def retry_card_now(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Retry a failed/killed card immediately by re-claiming and re-running it.

    The card must be in ``failed``, ``killed``, or ``rejected`` status.
    Increments the attempt counter, uses :meth:`pick_specific_card` to claim
    the card, then spawns the run-next background task.
    """
    _ensure_safe_card_id(card_id)
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    if card.status not in {"failed", "killed", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_status_for_retry",
                "card_id": card_id,
                "status": card.status,
                "message": f"Can only retry failed/killed/rejected cards, got: {card.status}",
            },
        )
    current_attempt = int(card.metadata.get("attempt_count", 0) or 0)
    worker_id = f"pid-{os.getpid()}-{uuid4().hex[:8]}"
    store.update_status(
        card_id,
        status="queued",
        metadata_updates={
            "retry_requested": True,
            "retry_by": "user",
            "attempt_count": current_attempt + 1,
        },
    )
    claimed = store.pick_specific_card(card_id, worker_id)
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "claim_failed",
                "card_id": card_id,
                "message": "Could not claim the card for retry.",
            },
        )
    oh_executable = str(Path(sys.executable).with_name("oh"))
    command = f"{shlex.quote(oh_executable)} autopilot run-next --cwd {shlex.quote(str(state.cwd))}"
    manager = get_task_manager()
    task = await manager.create_shell_task(
        command=command,
        description=f"autopilot retry {card_id}",
        cwd=state.cwd,
        task_type="local_bash",
    )
    return {"task_id": task.id, "card_id": card_id, "status": "accepted", "attempt": current_attempt + 1}