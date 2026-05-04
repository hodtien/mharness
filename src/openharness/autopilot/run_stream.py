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
- ``checkpoint_saved`` — ``{"phase": <str>, "file": <str>}`` (filename only; no path leakage)

Each event also carries a monotonically increasing ``seq`` field per writer,
which is used by SSE consumers for deterministic dedup (timestamp precision
alone is not sufficient when many events are emitted per millisecond).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CARD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _validate_card_id(card_id: str) -> str:
    if not isinstance(card_id, str) or not _CARD_ID_RE.match(card_id):
        raise ValueError(f"invalid card_id: {card_id!r}")
    return card_id

_INPUT_SUMMARY_LIMIT = 500
_OUTPUT_SUMMARY_LIMIT = 500

# Stream rotation: keep the active file under this size; on overflow, rename
# to ``{path}.1`` (replacing any prior rotation) and start fresh.
_STREAM_FILE_MAX_BYTES = 16 * 1024 * 1024  # 16 MiB

# Registry sweep: writers older than this with no recent emit() are considered
# orphaned (process killed before release_writer() ran). Configurable via
# `set_registry_stale_seconds()` so tests can shrink the window.
_REGISTRY_STALE_SECONDS = 60 * 60  # 1 hour
_registry_stale_seconds: float = _REGISTRY_STALE_SECONDS


def set_registry_stale_seconds(seconds: float) -> None:
    """Override the registry stale TTL (for tests or dynamic configuration)."""
    global _registry_stale_seconds
    _registry_stale_seconds = float(seconds)


def _get_registry_stale_seconds() -> float:
    return _registry_stale_seconds


def _display_width(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1 for ch in value)


def _truncate(value: str, limit: int) -> str:
    """Truncate ``value`` to an approximate terminal display width."""
    if _display_width(value) <= limit:
        return value
    width = 0
    chars: list[str] = []
    for ch in value:
        ch_width = 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
        if width + ch_width > limit:
            break
        chars.append(ch)
        width += ch_width
    omitted = len(value) - len(chars)
    return "".join(chars) + f"…(+{omitted} chars)"


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
        self.card_id = _validate_card_id(card_id)
        self._runs_dir = runs_dir
        self._path = runs_dir / f"{self.card_id}-stream.jsonl"
        self._lock = threading.Lock()
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._subscriber_loops: list[asyncio.AbstractEventLoop] = []
        self._closed = False
        # Per-writer monotonic sequence counter — emitted as event["seq"] so
        # SSE consumers can dedup deterministically across replay+live tails.
        self._seq_iter = itertools.count(1)
        self._created_at = time.time()
        self._last_emit_at = self._created_at

    @property
    def path(self) -> Path:
        return self._path

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def last_emit_at(self) -> float:
        return self._last_emit_at

    @property
    def created_at(self) -> float:
        return self._created_at

    def _maybe_rotate(self) -> None:
        """Rotate the stream file when it exceeds the size cap.

        Caller must hold ``self._lock``. ``{path} -> {path}.1`` (replacing any
        prior rotation), so the active file always stays under the cap.
        """
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size < _STREAM_FILE_MAX_BYTES:
            return
        rotated = self._path.with_suffix(self._path.suffix + ".1")
        try:
            os.replace(self._path, rotated)
        except OSError as exc:
            log.warning("RunStreamWriter rotation failed for %s: %s", self.card_id, exc)

    def emit(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        """Append one event to the file and notify live subscribers.

        Safe to call from any thread or event loop. File writes use a thread
        lock; subscriber pushes use ``loop.call_soon_threadsafe`` so the SSE
        loop wakes up promptly.
        """
        if self._closed:
            return
        seq = next(self._seq_iter)
        event = {
            "ts": time.time(),
            "seq": seq,
            "kind": kind,
            "payload": dict(payload or {}),
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self._runs_dir.mkdir(parents=True, exist_ok=True)
                self._maybe_rotate()
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                log.warning("RunStreamWriter append failed for %s: %s", self.card_id, exc)
                return
            self._last_emit_at = event["ts"]
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


def _sweep_stale_locked(now: float | None = None) -> None:
    """Remove writers that look orphaned (no emit for an hour, not closed).

    Caller must hold :data:`_REGISTRY_LOCK`. Crashed runs leave entries with
    ``closed=False`` forever; this prevents unbounded memory growth and stops
    SSE clients from subscribing to a dead writer.
    """
    if now is None:
        now = time.time()
    stale_ids: list[str] = []
    for cid, w in STREAM_REGISTRY.items():
        if w.closed:
            continue
        if now - w.last_emit_at > _get_registry_stale_seconds():
            stale_ids.append(cid)
    for cid in stale_ids:
        w = STREAM_REGISTRY.pop(cid, None)
        if w is not None:
            w.close()
            log.info("Swept stale RunStreamWriter for card %s", cid)


def get_or_create_writer(card_id: str, runs_dir: Path) -> RunStreamWriter:
    with _REGISTRY_LOCK:
        _sweep_stale_locked()
        existing = STREAM_REGISTRY.get(card_id)
        if existing is not None and not existing.closed:
            return existing
        writer = RunStreamWriter(card_id, runs_dir)
        STREAM_REGISTRY[card_id] = writer
        return writer


def get_writer(card_id: str) -> RunStreamWriter | None:
    with _REGISTRY_LOCK:
        _sweep_stale_locked()
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



def read_stream_file_chunk(
    runs_dir: Path,
    card_id: str,
    *,
    after: int = 0,
    limit: int = 500,
) -> tuple[list[dict[str, Any]], int]:
    """Return at most ``limit`` events and the next line offset.

    Bad lines count toward the offset so callers can make forward progress even
    when a stream contains malformed entries. Synchronous I/O — call sites that
    run inside an asyncio event loop must wrap with ``asyncio.to_thread()``.
    """
    path = runs_dir / f"{_validate_card_id(card_id)}-stream.jsonl"
    if limit <= 0 or not path.is_file():
        return [], max(0, after)
    events: list[dict[str, Any]] = []
    next_offset = max(0, after)
    with contextlib.suppress(OSError):
        with path.open("r", encoding="utf-8") as fh:
            for idx, raw in enumerate(fh):
                if idx < after:
                    continue
                next_offset = idx + 1
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    events.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
                if len(events) >= limit:
                    break
    return events, next_offset


def read_stream_file(
    runs_dir: Path, card_id: str, *, after: int = 0
) -> list[dict[str, Any]]:
    """Return events from the on-disk stream file, skipping the first ``after`` lines.

    Bad lines (truncated or malformed) are silently skipped. Returns an empty
    list when the file does not exist. Synchronous I/O — call sites that run
    inside an asyncio event loop must wrap with ``asyncio.to_thread()``.
    """
    events: list[dict[str, Any]] = []
    offset = max(0, after)
    while True:
        chunk, next_offset = read_stream_file_chunk(runs_dir, card_id, after=offset)
        events.extend(chunk)
        if not chunk or next_offset == offset:
            return events
        offset = next_offset


def stream_file_line_count(runs_dir: Path, card_id: str) -> int:
    """Return the number of lines currently on disk for this card's stream.

    Synchronous I/O — wrap with ``asyncio.to_thread()`` from async contexts.
    """
    path = runs_dir / f"{_validate_card_id(card_id)}-stream.jsonl"
    if not path.is_file():
        return 0
    count = 0
    with contextlib.suppress(OSError):
        with path.open("r", encoding="utf-8") as fh:
            for _ in fh:
                count += 1
    return count


def stream_file_mtime(runs_dir: Path, card_id: str) -> float:
    """Return the mtime of the on-disk stream file (or 0.0 if missing).

    Used by SSE consumers to detect orphan writers that never set ``closed``
    because their process died: when mtime stops advancing for a long while,
    treat the stream as ended.
    """
    path = runs_dir / f"{_validate_card_id(card_id)}-stream.jsonl"
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def collect_old_stream_files(runs_dir: Path, *, max_age_seconds: float) -> int:
    """Delete old stream JSONL files and return the number removed."""
    if max_age_seconds <= 0 or not runs_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in runs_dir.glob("*-stream.jsonl*"):
        try:
            if not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError as exc:
            log.warning("Could not remove old stream file %s: %s", path, exc)
    return removed
