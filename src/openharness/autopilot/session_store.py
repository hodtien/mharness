"""Checkpoint persistence for resumable autopilot sessions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from openharness.engine.messages import (
    ConversationMessage,
    deserialize_conversation_message,
    serialize_conversation_message,
)
from openharness.utils.fs import atomic_write_text

log = logging.getLogger(__name__)

Phase = Literal["implement", "local_review", "remote_review", "merge"]


@dataclass(frozen=True)
class SessionCheckpoint:
    card_id: str
    phase: Phase
    attempt: int
    saved_at: float
    model: str | None
    permission_mode: str
    cwd: str
    messages: list[dict[str, Any]]
    has_pending_continuation: bool


def _sessions_dir(runs_dir: Path, card_id: str) -> Path:
    return runs_dir / "sessions" / card_id


def save_checkpoint(
    runs_dir: Path,
    card_id: str,
    phase: Phase,
    attempt: int,
    model: str | None,
    permission_mode: str,
    cwd: str,
    messages: list[ConversationMessage],
    has_pending_continuation: bool,
) -> Path:
    """Serialize engine state to a checkpoint file and return its path."""
    dest_dir = _sessions_dir(runs_dir, card_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{phase}-attempt-{attempt:02d}.json"
    path = dest_dir / filename

    payload = {
        "card_id": card_id,
        "phase": phase,
        "attempt": attempt,
        "saved_at": time.time(),
        "model": model,
        "permission_mode": permission_mode,
        "cwd": cwd,
        "has_pending_continuation": has_pending_continuation,
        "messages": [serialize_conversation_message(m) for m in messages],
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False))
    log.info(
        "Saved checkpoint %s for card %s phase=%s attempt=%d",
        path, card_id, phase, attempt,
    )
    return path


def load_latest_checkpoint(runs_dir: Path, card_id: str) -> SessionCheckpoint | None:
    """Load the most recent checkpoint for a card, or None if none exist."""
    sess_dir = _sessions_dir(runs_dir, card_id)
    if not sess_dir.is_dir():
        return None
    candidates = sorted(sess_dir.glob("*-attempt-*.json"))
    if not candidates:
        return None
    path = candidates[-1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SessionCheckpoint(
            card_id=raw["card_id"],
            phase=raw["phase"],
            attempt=raw["attempt"],
            saved_at=raw["saved_at"],
            model=raw.get("model"),
            permission_mode=raw.get("permission_mode", "default"),
            cwd=raw.get("cwd", ""),
            messages=raw.get("messages", []),
            has_pending_continuation=raw.get("has_pending_continuation", False),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.warning("Corrupt checkpoint %s: %s", path, exc)
        return None


def clear_checkpoints(runs_dir: Path, card_id: str) -> None:
    """Remove all checkpoint files for a card."""
    sess_dir = _sessions_dir(runs_dir, card_id)
    if not sess_dir.is_dir():
        return
    for f in sess_dir.glob("*-attempt-*.json"):
        f.unlink(missing_ok=True)
    try:
        sess_dir.rmdir()
    except OSError:
        pass


def restore_messages(ckpt: SessionCheckpoint) -> list[ConversationMessage]:
    """Deserialize checkpoint messages back into ConversationMessage objects."""
    return [deserialize_conversation_message(m) for m in ckpt.messages]
