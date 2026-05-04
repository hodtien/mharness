"""Tests for the per-card autopilot run event stream."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from openharness.autopilot.run_stream import (
    RunStreamWriter,
    get_or_create_writer,
    get_writer,
    read_stream_file,
    release_writer,
    stream_file_line_count,
    STREAM_REGISTRY,
)


def test_run_stream_writer_appends_jsonl(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    writer = RunStreamWriter("card-001", runs_dir)

    writer.emit("phase_start", {"phase": "implement", "attempt": 1})
    writer.emit("text_delta", {"text": "Hello"})
    writer.emit("phase_end", {"phase": "implement"})

    lines = writer.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    events = [json.loads(line) for line in lines]
    assert events[0]["kind"] == "phase_start"
    assert events[0]["payload"]["phase"] == "implement"
    assert events[1]["kind"] == "text_delta"
    assert events[1]["payload"]["text"] == "Hello"
    assert events[2]["kind"] == "phase_end"

    for event in events:
        assert "ts" in event
        assert isinstance(event["ts"], float)


def test_run_stream_writer_fans_out_to_subscribers(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    writer = RunStreamWriter("card-002", runs_dir)

    async def _run():
        loop = asyncio.get_running_loop()
        q1 = writer.subscribe(loop=loop)
        q2 = writer.subscribe(loop=loop)

        writer.emit("text_delta", {"text": "a"})
        writer.emit("text_delta", {"text": "b"})
        writer.emit("phase_end", {"phase": "implement"})

        await asyncio.sleep(0.05)

        q1_events = []
        while not q1.empty():
            q1_events.append(await q1.get())
        q2_events = []
        while not q2.empty():
            q2_events.append(await q2.get())

        assert len(q1_events) == 3
        assert len(q2_events) == 3
        assert q1_events[0]["payload"]["text"] == "a"
        assert q1_events[1]["payload"]["text"] == "b"
        assert q1_events[2]["kind"] == "phase_end"

        writer.unsubscribe(q1)
        writer.unsubscribe(q2)

    asyncio.run(_run())


def test_read_stream_file_replays_from_disk(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    writer = RunStreamWriter("card-003", runs_dir)
    writer.emit("phase_start", {"phase": "implement", "attempt": 1})
    writer.emit("text_delta", {"text": "delta-1"})
    writer.emit("text_delta", {"text": "delta-2"})
    writer.close()

    events = read_stream_file(runs_dir, "card-003")
    assert len(events) == 3
    assert events[0]["kind"] == "phase_start"
    assert events[1]["payload"]["text"] == "delta-1"
    assert events[2]["payload"]["text"] == "delta-2"


def test_read_stream_file_after_offset(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    writer = RunStreamWriter("card-004", runs_dir)
    writer.emit("phase_start", {"phase": "implement", "attempt": 1})
    writer.emit("text_delta", {"text": "a"})
    writer.emit("text_delta", {"text": "b"})
    writer.emit("phase_end", {"phase": "implement"})
    writer.close()

    events = read_stream_file(runs_dir, "card-004", after=2)
    assert len(events) == 2
    assert events[0]["payload"]["text"] == "b"
    assert events[1]["kind"] == "phase_end"


def test_stream_file_line_count(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    writer = RunStreamWriter("card-005", runs_dir)
    assert stream_file_line_count(runs_dir, "card-005") == 0

    writer.emit("phase_start", {"phase": "implement", "attempt": 1})
    writer.emit("text_delta", {"text": "x"})
    assert stream_file_line_count(runs_dir, "card-005") == 2

    writer.emit("phase_end", {"phase": "implement"})
    assert stream_file_line_count(runs_dir, "card-005") == 3


def test_read_stream_file_missing_file(tmp_path: Path) -> None:
    events = read_stream_file(tmp_path / "runs", "nonexistent")
    assert events == []


def test_closed_writer_stops_emitting(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    writer = RunStreamWriter("card-006", runs_dir)
    writer.emit("phase_start", {"phase": "implement", "attempt": 1})
    writer.close()
    writer.emit("text_delta", {"text": "should be ignored"})

    assert stream_file_line_count(runs_dir, "card-006") == 1


def test_registry_get_or_create_and_release(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    card_id = "card-registry-test"
    STREAM_REGISTRY.pop(card_id, None)

    w1 = get_or_create_writer(card_id, runs_dir)
    w2 = get_or_create_writer(card_id, runs_dir)
    assert w1 is w2

    assert get_writer(card_id) is w1

    release_writer(card_id)
    assert w1.closed
    assert get_writer(card_id) is None
    assert card_id not in STREAM_REGISTRY
