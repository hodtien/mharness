"""Smoke tests for Web UI startup surfaces.

These cover the backend half of the browser smoke path. They verify the
``oh webui`` FastAPI app can be constructed, serves a SPA deep link at
``/chat``, exposes the API endpoints the SPA bootstraps with, and registers
the WebSocket route so browsers do not get a raw 1006 close on the first
connection attempt.

The frontend half — websocket handshake, sessions/permission dropdowns and
the OpenHarness shell sidebar toggle — lives in
``frontend/webui/src/WebUISmoke.test.tsx`` and runs under Vitest with jsdom.

Run locally:

    # Backend smoke (Python):
    uv run pytest tests/test_webui/test_smoke.py -v

    # Frontend smoke (Vitest jsdom):
    cd frontend/webui && npm ci --no-audit --no-fund \\
        && npx vitest run src/WebUISmoke.test.tsx
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app


def _build_minimal_spa(tmp_path):
    spa = tmp_path / "dist"
    spa.mkdir()
    (spa / "index.html").write_text(
        "<!doctype html><html><body><div id='root'></div></body></html>",
        encoding="utf-8",
    )
    return spa


def test_webui_chat_deep_link_serves_spa_and_meta_endpoint_works(tmp_path, monkeypatch):
    """The SPA's /chat deep link must serve index.html and /api/meta must respond.

    Catches regressions where ``create_app`` is missing required exports or
    keyword arguments (e.g. the historical ``model=...`` signature mismatch).
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

    spa = _build_minimal_spa(tmp_path)
    app = create_app(
        token="secret",
        spa_dir=spa,
        model="claude-sonnet-4-6",
        permission_mode="default",
    )

    with TestClient(app) as client:
        # Browser navigation: GET /chat must return the SPA shell, not a 404.
        chat = client.get("/chat")
        assert chat.status_code == 200, f"/chat returned {chat.status_code}: {chat.text[:200]}"
        assert "<div id='root'>" in chat.text

        # Bootstrap call the SPA makes on load (App.tsx -> api.meta()).
        meta = client.get("/api/meta", headers={"Authorization": "Bearer secret"})
        assert meta.status_code == 200
        body = meta.json()
        assert body["model"] == "claude-sonnet-4-6"

        # Sessions endpoint that the Header dropdown calls.
        history = client.get(
            "/api/history?limit=5", headers={"Authorization": "Bearer secret"}
        )
        assert history.status_code == 200

        # Permission-mode chip uses GET/PATCH /api/modes.
        modes = client.get("/api/modes", headers={"Authorization": "Bearer secret"})
        assert modes.status_code == 200


def test_webui_websocket_route_is_registered(tmp_path, monkeypatch):
    """Smoke check: the /api/ws/{session_id} route is registered.

    Catches the regression where the websocket route was not exported and
    browsers received raw 1006 closes plus a noisy 'Connection closed' banner.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

    app = create_app(token="secret", spa_dir="")
    paths = {getattr(route, "path", None) for route in app.router.routes}
    assert "/api/ws/{session_id}" in paths, (
        f"WebSocket route missing — would cause a noisy 1006 close on the SPA. "
        f"Routes: {sorted(p for p in paths if p)}"
    )
