"""Tests for the ``/api/ws/{session_id}`` route.

These cover the close-code paths the SPA uses to distinguish auth failure
(``1008``), unknown session (``1008``), and clean disconnect.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openharness.webui.server.app import create_app


def _client(token: str = "secret") -> TestClient:
    return TestClient(create_app(token=token, spa_dir=""))


def test_websocket_rejects_missing_token() -> None:
    client = _client()
    with pytest.raises(WebSocketDisconnect) as info:
        with client.websocket_connect("/api/ws/does-not-exist"):
            pass
    assert info.value.code == 1008


def test_websocket_rejects_wrong_token() -> None:
    client = _client()
    with pytest.raises(WebSocketDisconnect) as info:
        with client.websocket_connect("/api/ws/does-not-exist?token=nope"):
            pass
    assert info.value.code == 1008


def test_websocket_rejects_unknown_session_with_policy_violation() -> None:
    client = _client()
    with pytest.raises(WebSocketDisconnect) as info:
        with client.websocket_connect("/api/ws/missing?token=secret"):
            pass
    # Unknown session uses the same close code (1008) so the SPA does not
    # endlessly retry against a session that no longer exists.
    assert info.value.code == 1008


def test_websocket_route_is_registered() -> None:
    """Smoke check: the route exists so browsers do not get raw 1006 closes."""
    app = create_app(token="secret", spa_dir="")
    paths = {
        getattr(route, "path", None) for route in app.router.routes
    }
    assert "/api/ws/{session_id}" in paths
