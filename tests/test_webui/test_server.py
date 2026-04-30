"""Smoke tests for the Web UI HTTP / WebSocket server."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient

from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.ui.backend_host import BackendHostConfig
from openharness.webui.server.app import create_app
from openharness.webui.server.bridge import WebSocketBackendHost


class StaticApiClient:
    """Fake streaming client (mirrors test_react_backend.StaticApiClient)."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def stream_message(self, request):  # noqa: D401 - test stub
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text=self._text)]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


def test_health_does_not_require_token():
    app = create_app(token="secret")
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


def test_meta_requires_token():
    app = create_app(token="secret")
    with TestClient(app) as client:
        r = client.get("/api/meta")
        assert r.status_code == 401
        r = client.get("/api/meta", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200


def test_meta_accepts_query_token():
    app = create_app(token="secret")
    with TestClient(app) as client:
        r = client.get("/api/meta?token=secret")
        assert r.status_code == 200


def test_meta_rejects_wrong_token():
    app = create_app(token="secret")
    with TestClient(app) as client:
        r = client.get("/api/meta", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401


def test_list_sessions_requires_token():
    app = create_app(token="secret")
    with TestClient(app) as client:
        r = client.get("/api/sessions")
        assert r.status_code == 401
        r = client.get("/api/sessions", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200
        assert "sessions" in r.json()


@pytest.mark.asyncio
async def test_websocket_backend_host_round_trip(tmp_path, monkeypatch):
    """The WS subclass should preserve the same dispatch as ReactBackendHost."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

    from openharness.ui.runtime import build_runtime, close_runtime, start_runtime

    host = WebSocketBackendHost(
        BackendHostConfig(api_client=StaticApiClient("hello from webui"))
    )
    host._bundle = await build_runtime(api_client=StaticApiClient("hello from webui"))

    captured: list[bytes] = []

    async def _capture(payload: bytes) -> None:
        captured.append(payload)

    host._write_event = _capture  # type: ignore[method-assign]
    await start_runtime(host._bundle)
    try:
        ok = await host._process_line("hi")
    finally:
        await close_runtime(host._bundle)

    assert ok is True
    # The transport hook should have received serialised events as bytes.
    assert any(b'"assistant_complete"' in p for p in captured)
    # Each event ends with newline (framing for line-based transports).
    assert all(p.endswith(b"\n") for p in captured)


def test_meta_returns_state_fields():
    """Meta endpoint exposes the state fields the SPA needs to bootstrap."""
    app = create_app(token="secret", model="claude-sonnet-4-6")
    with TestClient(app) as client:
        r = client.get("/api/meta", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "claude-sonnet-4-6"
        assert "cwd" in body
