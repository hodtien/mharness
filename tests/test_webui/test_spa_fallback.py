"""Tests for the SPA fallback behaviour of the Web UI FastAPI app.

The frontend uses react-router-dom ``BrowserRouter``, so deep links such as
``/chat`` must return the bundled ``index.html`` instead of a 404 — otherwise
hard-refreshing a sub-route breaks the app. API routes (``/api/*``) and
WebSocket routes (``/ws/*``) must still surface their real status codes so
errors are not masked by an HTML response.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app


@pytest.fixture
def spa_dir(tmp_path):
    """A minimal built SPA: ``index.html`` plus a real static asset."""
    spa = tmp_path / "dist"
    spa.mkdir()
    (spa / "index.html").write_text(
        "<!doctype html><html><body><div id='root'></div></body></html>",
        encoding="utf-8",
    )
    (spa / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    assets = spa / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("/* bundle */", encoding="utf-8")
    return spa


def _client(spa_dir):
    app = create_app(token="secret", spa_dir=str(spa_dir))
    return TestClient(app)


def test_root_serves_index_html(spa_dir):
    with _client(spa_dir) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "<div id='root'>" in r.text


def test_unknown_path_falls_back_to_index_html(spa_dir):
    """Deep links like ``/chat`` must serve index.html for client-side routing."""
    with _client(spa_dir) as client:
        for path in ("/chat", "/history", "/settings/profile", "/anything/deep/here"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert "<div id='root'>" in r.text, path


def test_real_static_files_are_served(spa_dir):
    """Files that exist in the bundle must be served verbatim, not as index.html."""
    with _client(spa_dir) as client:
        r = client.get("/favicon.svg")
        assert r.status_code == 200
        assert r.text == "<svg/>"

        r = client.get("/assets/app.js")
        assert r.status_code == 200
        assert "/* bundle */" in r.text


def test_api_routes_are_not_shadowed(spa_dir):
    """Real API errors must surface — the SPA fallback must skip /api/*."""
    with _client(spa_dir) as client:
        # Existing route, valid auth → 200 JSON (not the SPA index).
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["ok"] is True

        # Existing route, missing auth → real 401, not a 200 HTML response.
        r = client.get("/api/meta")
        assert r.status_code == 401
        assert "<div id='root'>" not in r.text

        # Non-existent /api/* path → 404, not the SPA index.
        r = client.get("/api/does-not-exist")
        assert r.status_code == 404
        assert "<div id='root'>" not in r.text


def test_path_traversal_is_refused(spa_dir):
    with _client(spa_dir) as client:
        r = client.get("/../etc/passwd")
        # Either 404 from our fallback or normalized to /etc/passwd by the
        # client; in both cases we must not leak filesystem contents.
        assert r.status_code in {200, 404}
        assert "root:" not in r.text


def test_create_app_without_spa_dir_skips_mount(spa_dir):
    """Empty string disables SPA mounting (used by API-only tests)."""
    app = create_app(token="secret", spa_dir="")
    with TestClient(app) as client:
        r = client.get("/")
        # No SPA mounted → root has no handler → 404.
        assert r.status_code == 404
        # API routes still work.
        r = client.get("/api/health")
        assert r.status_code == 200
