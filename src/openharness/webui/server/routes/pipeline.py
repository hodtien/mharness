"""Pipeline (autopilot registry) REST endpoints for the Web UI."""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from openharness.autopilot.run_stream import (
    get_writer,
    read_stream_file,
    stream_file_line_count,
)
from openharness.autopilot.service import RepoAutopilotStore
from openharness.autopilot.session_store import (
    clear_checkpoints,
    load_latest_checkpoint,
)
from openharness.config.paths import get_project_autopilot_policy_path
from openharness.autopilot.types import RepoAutopilotRegistry, RepoJournalEntry, RepoTaskStatus
from openharness.webui.server.state import WebUIState, get_state, get_task_manager, require_token

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[Depends(require_token)],
)


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
        "created_at": card["created_at"],
        "updated_at": card["updated_at"],
        "model": _safe_text(metadata.get("execution_model")),
        "attempt_count": int(metadata.get("attempt_count", 0) or 0),
        "metadata": {
            "last_note": _safe_text(metadata.get("last_note")),
            "linked_pr_url": _safe_text(metadata.get("linked_pr_url")),
            "resume_available": bool(metadata.get("resume_available")),
            "resume_phase": _safe_text(metadata.get("resume_phase")),
        },
    }


def _safe_text(value: str | None) -> str | None:
    return value if value else None


def _serialize_journal_entry(entry: RepoJournalEntry) -> dict:
    """Return the JSON representation for one repo journal entry."""
    return entry.model_dump(mode="json")


@router.get("/journal")
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


@router.get("/cards")
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


@router.post("/cards", status_code=status.HTTP_201_CREATED)
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


@router.post("/cards/{card_id}/action")
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
    {"preparing", "running", "verifying", "waiting_ci", "repairing"}
)


@router.patch("/cards/{card_id}/model")
def patch_pipeline_card_model(
    card_id: str,
    body: CardModelPatchRequest,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Override the execution model used the next time this card runs.

    Pass ``model: null`` (or empty string) to clear the override and fall back
    to the policy default. Rejected with HTTP 409 while the card is in an
    active run state, since the model is captured at run-start time.
    """
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    if card.status in _ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "card_active",
                "message": "Cannot change model while card is running.",
                "card_id": card_id,
                "status": card.status,
            },
        )
    raw_model = (body.model or "").strip()
    updated = store.update_status(
        card_id,
        status=card.status,
        metadata_updates={"execution_model": raw_model},
    )
    return _serialize_card(updated.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Autopilot run-next trigger
# ---------------------------------------------------------------------------


@router.post("/run-next", status_code=status.HTTP_202_ACCEPTED)
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
    active_statuses = {"preparing", "running", "verifying", "repairing", "waiting_ci", "pr_open"}
    if any(c.status in active_statuses for c in cards):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "already_running", "message": "An autopilot task is already active."},
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


@router.get("/policy")
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


@router.patch("/policy")
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
    policy_path = get_project_autopilot_policy_path(state.cwd)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(body.yaml_content, encoding="utf-8")
    return {"yaml_content": body.yaml_content, "parsed": parsed}


# ---------------------------------------------------------------------------
# Per-card realtime event stream (SSE)
# ---------------------------------------------------------------------------


def _sse_format(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.get("/cards/{card_id}/stream")
async def stream_card_events(
    card_id: str,
    after: int = 0,
    state: WebUIState = Depends(get_state),
) -> StreamingResponse:
    """Server-Sent Events feed for one autopilot card's run stream.

    Replays ``{runs_dir}/{card_id}-stream.jsonl`` from offset ``after``, then
    if the card is currently running, subscribes to the live writer and
    tails subsequent events. Sends a heartbeat comment every 15s.
    """
    runs_dir = state.cwd / ".openharness" / "autopilot" / "runs"

    async def _generator() -> AsyncIterator[bytes]:
        offset = max(0, int(after))

        # Subscribe BEFORE reading the file so that any events emitted during
        # replay are buffered into the queue (no replay-to-subscribe gap). If
        # the writer is not live, fall back to a pure on-disk replay.
        writer = get_writer(card_id)
        queue: asyncio.Queue[dict[str, Any]] | None = None
        if writer is not None:
            loop = asyncio.get_running_loop()
            queue = writer.subscribe(loop=loop)

        try:
            replay = read_stream_file(runs_dir, card_id, after=offset)
            for event in replay:
                yield _sse_format(event).encode("utf-8")
            offset += len(replay)

            if writer is None or queue is None:
                current_total = stream_file_line_count(runs_dir, card_id)
                if current_total > offset:
                    tail = read_stream_file(runs_dir, card_id, after=offset)
                    for event in tail:
                        yield _sse_format(event).encode("utf-8")
                yield b": stream-ended\n\n"
                return

            # Catch any lines that were appended between replay-read and
            # subscribe-time (the file is the durable source; any such line
            # is also queued, so we dedup using ts+kind+payload comparison).
            seen_keys: set[tuple[float, str, str]] = set()
            tail_after_subscribe = read_stream_file(runs_dir, card_id, after=offset)
            for event in tail_after_subscribe:
                key = (
                    float(event.get("ts", 0.0)),
                    str(event.get("kind", "")),
                    json.dumps(event.get("payload", {}), sort_keys=True, default=str),
                )
                seen_keys.add(key)
                yield _sse_format(event).encode("utf-8")
            offset += len(tail_after_subscribe)

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield f": heartbeat {time.time():.0f}\n\n".encode("utf-8")
                    if writer.closed:
                        break
                    continue
                key = (
                    float(event.get("ts", 0.0)),
                    str(event.get("kind", "")),
                    json.dumps(event.get("payload", {}), sort_keys=True, default=str),
                )
                if key in seen_keys:
                    seen_keys.discard(key)
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


@router.get("/cards/{card_id}/checkpoint")
def get_card_checkpoint(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Return checkpoint info for a card, or 404 if none exists."""
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


@router.post("/cards/{card_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_card(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Resume an interrupted autopilot card from its latest checkpoint.

    Validates that a resumable checkpoint exists, that the card is not
    currently active, and then spawns ``oh autopilot run-next`` with the
    card pre-queued for resume. Returns HTTP 202 with the background task id.
    """
    store = RepoAutopilotStore(state.cwd)
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    if card.status in _ACTIVE_STATUSES:
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
    if ckpt is None or not ckpt.has_pending_continuation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "no_resumable_checkpoint",
                "message": "No resumable checkpoint found for this card.",
                "card_id": card_id,
            },
        )
    store.update_status(
        card_id,
        status="queued",
        metadata_updates={"resume_requested": True},
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


@router.delete("/cards/{card_id}/checkpoint")
def delete_card_checkpoint(
    card_id: str,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Delete all checkpoints for a card."""
    runs_dir = state.cwd / ".openharness" / "autopilot" / "runs"
    clear_checkpoints(runs_dir, card_id)
    return {"card_id": card_id, "cleared": True}