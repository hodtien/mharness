"""Tests for TURN_COMPLETE hook firing and TurnDiffCollector."""

from __future__ import annotations

from openharness.engine.query_engine import TurnDiffCollector
from openharness.engine.stream_events import (
    AssistantTextDelta,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from openharness.hooks.events import HookEvent


def _started(name: str, tool_input: dict) -> ToolExecutionStarted:
    return ToolExecutionStarted(tool_name=name, tool_input=tool_input)


def test_collector_tracks_file_mutating_tools():
    c = TurnDiffCollector()
    c.observe(_started("Edit", {"file_path": "/a/foo.py"}))
    c.observe(_started("Write", {"file_path": "/a/bar.py"}))
    c.observe(_started("Grep", {"pattern": "x"}))  # not mutating

    payload = c.build_payload(model="claude-test", turn_index=1)
    assert payload["event"] == HookEvent.TURN_COMPLETE.value
    assert payload["turn_index"] == 1
    assert payload["model"] == "claude-test"
    assert payload["modified_files"] == ["/a/foo.py", "/a/bar.py"]
    assert {tc["tool_name"] for tc in payload["tool_calls"]} == {"Edit", "Write", "Grep"}


def test_collector_dedupes_same_path():
    c = TurnDiffCollector()
    c.observe(_started("Edit", {"file_path": "/x.py"}))
    c.observe(_started("Edit", {"file_path": "/x.py"}))
    payload = c.build_payload(model="m", turn_index=1)
    assert payload["modified_files"] == ["/x.py"]


def test_collector_falls_back_to_path_key():
    c = TurnDiffCollector()
    c.observe(_started("NotebookEdit", {"path": "/n.ipynb"}))
    payload = c.build_payload(model="m", turn_index=1)
    assert payload["modified_files"] == ["/n.ipynb"]


def test_collector_ignores_non_started_events():
    c = TurnDiffCollector()
    c.observe(AssistantTextDelta(text="hi"))
    c.observe(ToolExecutionCompleted(tool_name="Edit", output="ok", is_error=False))
    payload = c.build_payload(model="m", turn_index=1)
    assert payload["modified_files"] == []
    assert payload["tool_calls"] == []


def test_collector_reset_clears_state():
    c = TurnDiffCollector()
    c.observe(_started("Edit", {"file_path": "/a.py"}))
    c.reset()
    payload = c.build_payload(model="m", turn_index=2)
    assert payload["modified_files"] == []
    assert payload["tool_calls"] == []
