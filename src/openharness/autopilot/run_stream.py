"""Per-card autopilot run event stream.

Each in-flight autopilot card has a :class:`RunStreamWriter` that:

1. Appends one JSON line per event to ``{runs_dir}/{card_id}-stream.jsonl``.
2. Fans the same events out to in-memory subscribers (``asyncio.Queue``) so
   the Web UI SSE endpoint can tail the live run.

The on-disk JSONL file is the durable replay log; the queues are ephemeral
live tails. A process-wide :data:`STREAM_REGISTRY` lets the SSE endpoint find
the writer for a currently-running card.

Event vocabulary (kept small and stable):

- ``phase_start`` / ``phase_end`` — ``payload = {"phase": <str>, "attempt": <int>}``
- ``text_delta`` — incremental assistant text, ``{"text": <str>}``
- ``tool_call`` — ``{"name": <str>, "input_summary": <str>}``
- ``tool_result`` — ``{"name": <str>, "is_error": <bool>, "summary": <str>}``
- ``error`` — ``{"message": <str>}``
- ``checkpoint_saved`` — ``{"phase": <str>, "session_path": <str>}``
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_INPUT_SUMMARY_LIMIT = 500
_OUTPUT_SUMMARY_LIMIT = 500


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"…(+{len(value) - limit} chars)"


def summarize_tool_input(payload: Any) -> str:
    """Render a compact, human-readable summary of a tool input dict."""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(payload)
    return _truncate(text, _INPUT_SUMMARY_LIMIT)


def summarize_tool_output(payload: Any) -> str:
    """Render a compact, human-readable summary of a tool output."""
    if not isinstance(payload, str):
        try:
            payload = json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            payload = repr(payload)
    return _truncate(payload, _OUTPUT_SUMMARY_LIMIT)


class RunStreamWriter:
    """Append-only writer + in-memory fan-out for one card's run stream."""

    def __init__(self, card_id: str, runs_dir: Path) -> None:
        self.card_id = card_id
        self._runs_dir = runs_dir
        self._path = runs_dir / f"{card_id}-stream.jsonl"
        self._lock = threading.Lock()
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._subscriber_loops: list[asyncio.AbstractEventLoop] = []
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def closed(self) -> bool:
        return self._closed

    def emit(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        """Append one event to the file and notify live subscribers.

        Safe to call from any thread or event loop. File writes use a thread
        lock; subscriber pushes use ``loop.call_soon_threadsafe`` so the SSE
        loop wakes up promptly.
        """
        if self._closed:
            return
        event = {
            "ts": time.time(),
            "kind": kind,
            "payload": dict(payload or {}),
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self._runs_dir.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                log.warning("RunStreamWriter append failed for %s: %s", self.card_id, exc)
                return
            subscribers = list(zip(self._subscribers, self._subscriber_loops))
        for queue, loop in subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                pass

    def subscribe(
        self, loop: asyncio.AbstractEventLoop | None = None
    ) -> asyncio.Queue[dict[str, Any]]:
        """Register an asyncio queue that receives every subsequent emission."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
        with self._lock:
            self._subscribers.append(queue)
            self._subscriber_loops.append(loop)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            for idx, q in enumerate(self._subscribers):
                if q is queue:
                    self._subscribers.pop(idx)
                    self._subscriber_loops.pop(idx)
                    return

    def close(self) -> None:
        """Mark the writer closed; future emit() calls become no-ops."""
        self._closed = True


# ---------------------------------------------------------------------------
# Process-wide registry
# ---------------------------------------------------------------------------

STREAM_REGISTRY: dict[str, RunStreamWriter] = {}
_REGISTRY_LOCK = threading.Lock()


def get_or_create_writer(card_id: str, runs_dir: Path) -> RunStreamWriter:
    with _REGISTRY_LOCK:
        existing = STREAM_REGISTRY.get(card_id)
        if existing is not None and not existing.closed:
            return existing
        writer = RunStreamWriter(card_id, runs_dir)
        STREAM_REGISTRY[card_id] = writer
        return writer


def get_writer(card_id: str) -> RunStreamWriter | None:
    with _REGISTRY_LOCK:
        writer = STREAM_REGISTRY.get(card_id)
        if writer is not None and writer.closed:
            return None
        return writer


def release_writer(card_id: str) -> None:
    """Remove a writer from the registry and close it."""
    with _REGISTRY_LOCK:
        writer = STREAM_REGISTRY.pop(card_id, None)
    if writer is not None:
        writer.close()


# ---------------------------------------------------------------------------
# Reader (file replay)
# ---------------------------------------------------------------------------


def read_stream_file(
    runs_dir: Path, card_id: str, *, after: int = 0
) -> list[dict[str, Any]]:
    """Return events from the on-disk stream file, skipping the first ``after`` lines.

    Bad lines (truncated or malformed) are silently skipped. Returns an empty
    list when the file does not exist.
    """
    path = runs_dir / f"{card_id}-stream.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    with contextlib.suppress(OSError):
        with path.open("r", encoding="utf-8") as fh:
            for idx, raw in enumerate(fh):
                if idx < after:
                    continue
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    events.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    return events


def stream_file_line_count(runs_dir: Path, card_id: str) -> int:
    """Return the number of lines currently on disk for this card's stream."""
    path = runs_dir / f"{card_id}-stream.jsonl"
    if not path.is_file():
        return 0
    count = 0
    with contextlib.suppress(OSError):
        with path.open("r", encoding="utf-8") as fh:
            for _ in fh:
                count += 1
    return count
