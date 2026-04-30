"""Tests for FallbackApiClient runtime model switching."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from openharness.api.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiStreamEvent,
    ApiTextDeltaEvent,
)
from openharness.api.errors import AuthenticationFailure, RateLimitFailure, RequestFailure
from openharness.api.fallback import FallbackApiClient, ModelSwitchEvent
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage


def _make_request(model: str = "model-a") -> ApiMessageRequest:
    return ApiMessageRequest(
        model=model,
        messages=[ConversationMessage.from_user_text("hello")],
        system_prompt="test",
    )


class FakeClient:
    """Stub client whose behaviour is controlled per-model."""

    def __init__(self, model_actions: dict[str, str | Exception]) -> None:
        self._model_actions = model_actions
        self.called_models: list[str] = []

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        self.called_models.append(request.model)
        action = self._model_actions.get(request.model, "ok")
        if isinstance(action, Exception):
            raise action
        yield ApiTextDeltaEvent(text=f"reply-from-{request.model}")
        yield ApiMessageCompleteEvent(
            message=ConversationMessage.from_user_text("done"),
            usage=UsageSnapshot(input_tokens=10, output_tokens=5),
            stop_reason="end_turn",
        )


@pytest.mark.asyncio
async def test_single_model_passthrough():
    inner = FakeClient({"model-a": "ok"})
    client = FallbackApiClient(inner, ("model-a",))
    events = [e async for e in client.stream_message(_make_request())]
    assert any(isinstance(e, ApiTextDeltaEvent) for e in events)
    assert inner.called_models == ["model-a"]


@pytest.mark.asyncio
async def test_fallback_on_request_failure():
    inner = FakeClient({
        "model-a": RequestFailure("model-a down"),
        "model-b": "ok",
    })
    client = FallbackApiClient(inner, ("model-a", "model-b"))
    events = [e async for e in client.stream_message(_make_request())]
    switch_events = [e for e in events if isinstance(e, ModelSwitchEvent)]
    assert len(switch_events) == 1
    assert switch_events[0].failed_model == "model-a"
    assert switch_events[0].next_model == "model-b"
    assert inner.called_models == ["model-a", "model-b"]


@pytest.mark.asyncio
async def test_fallback_on_rate_limit():
    inner = FakeClient({
        "model-a": RateLimitFailure("429 exhausted"),
        "model-b": "ok",
    })
    client = FallbackApiClient(inner, ("model-a", "model-b"))
    events = [e async for e in client.stream_message(_make_request())]
    switch_events = [e for e in events if isinstance(e, ModelSwitchEvent)]
    assert len(switch_events) == 1
    assert switch_events[0].failed_model == "model-a"


@pytest.mark.asyncio
async def test_auth_failure_never_retried():
    inner = FakeClient({
        "model-a": AuthenticationFailure("bad creds"),
        "model-b": "ok",
    })
    client = FallbackApiClient(inner, ("model-a", "model-b"))
    with pytest.raises(AuthenticationFailure):
        _ = [e async for e in client.stream_message(_make_request())]
    assert inner.called_models == ["model-a"]


@pytest.mark.asyncio
async def test_all_models_fail_raises_last_error():
    inner = FakeClient({
        "model-a": RequestFailure("a down"),
        "model-b": RequestFailure("b down"),
        "model-c": RequestFailure("c down"),
    })
    client = FallbackApiClient(inner, ("model-a", "model-b", "model-c"))
    with pytest.raises(RequestFailure, match="c down"):
        _ = [e async for e in client.stream_message(_make_request())]
    assert inner.called_models == ["model-a", "model-b", "model-c"]


@pytest.mark.asyncio
async def test_chain_property():
    inner = FakeClient({})
    chain = ("x", "y", "z")
    client = FallbackApiClient(inner, chain)
    assert client.model_chain == chain


@pytest.mark.asyncio
async def test_model_switch_event_position_tracking():
    inner = FakeClient({
        "a": RequestFailure("a"),
        "b": RequestFailure("b"),
        "c": "ok",
    })
    client = FallbackApiClient(inner, ("a", "b", "c"))
    events = [e async for e in client.stream_message(_make_request("a"))]
    switches = [e for e in events if isinstance(e, ModelSwitchEvent)]
    assert len(switches) == 2
    assert switches[0].position == 2
    assert switches[0].chain_length == 3
    assert switches[1].position == 3
    assert switches[1].chain_length == 3
