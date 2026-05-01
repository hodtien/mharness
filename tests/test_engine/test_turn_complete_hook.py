"""Tests for TURN_COMPLETE hook firing and TurnDiffCollector."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, TextBlock, ToolUseBlock
from openharness.engine.query_engine import QueryEngine, TurnDiffCollector
from openharness.engine.stream_events import (
    AssistantTextDelta,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from openharness.config.settings import PermissionSettings
from openharness.hooks.events import HookEvent
from openharness.hooks.types import AggregatedHookResult
from openharness.permissions import PermissionChecker, PermissionMode
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult


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


class ScriptedApiClient:
    def __init__(self, messages: list[ConversationMessage]) -> None:
        self._messages = list(messages)

    async def stream_message(self, request):
        del request
        message = self._messages.pop(0)
        yield ApiMessageCompleteEvent(
            message=message,
            usage=UsageSnapshot(input_tokens=1, output_tokens=1),
            stop_reason=None,
        )


class RecordingHookExecutor:
    def __init__(self) -> None:
        self.turn_complete_payloads: list[dict] = []

    async def execute(self, event: HookEvent, payload: dict) -> AggregatedHookResult:
        if event == HookEvent.TURN_COMPLETE:
            self.turn_complete_payloads.append(payload)
        return AggregatedHookResult()


class ReadInput(BaseModel):
    file_path: str


class FakeReadTool(BaseTool):
    name = "Read"
    description = "Reads a synthetic file."
    input_model = ReadInput

    async def execute(self, arguments: ReadInput, context: ToolExecutionContext) -> ToolResult:
        del arguments, context
        return ToolResult(output="contents")


@pytest.mark.asyncio
async def test_turn_complete_hook_waits_for_final_assistant_turn(tmp_path):
    api_client = ScriptedApiClient(
        [
            ConversationMessage(
                role="assistant",
                content=[ToolUseBlock(id="toolu_read", name="Read", input={"file_path": "x.py"})],
            ),
            ConversationMessage(role="assistant", content=[TextBlock(text="done")]),
        ]
    )
    hooks = RecordingHookExecutor()
    registry = ToolRegistry()
    registry.register(FakeReadTool())
    engine = QueryEngine(
        api_client=api_client,
        tool_registry=registry,
        cwd=tmp_path,
        model="test-model",
        hook_executor=hooks,
        permission_checker=PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO)),
        system_prompt="",
    )

    events = [event async for event in engine.submit_message("inspect")]

    assert events[-1].message.text == "done"
    assert len(hooks.turn_complete_payloads) == 1
    assert hooks.turn_complete_payloads[0]["tool_calls"] == [{"tool_name": "Read"}]
