"""Tests for the projects REST API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app


@pytest.fixture
def token() -> str:
    return "test-token-123"


@pytest.fixture(autouse=True)
def _redirect_projects_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect projects registry to a temp file for each test."""
    import openharness.services.projects as svc

    monkeypatch.setattr(svc, "_projects_path", lambda: tmp_path / "projects.json")
    monkeypatch.setattr(svc, "_projects_lock_path", lambda: tmp_path / "projects.json.lock")


@pytest.fixture
def client(token: str, tmp_path: Path) -> TestClient:
    """Create a test client with a temporary projects registry."""
    app = create_app(token=token, cwd=str(tmp_path), spa_dir="")
    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


class TestProjectsApiCrud:
    def test_list_empty(self, client) -> None:
        r = client.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        assert "projects" in data
        assert "active_project_id" in data

    def test_create_and_list(self, client, tmp_path) -> None:
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        r = client.post("/api/projects", json={"name": "My App", "path": str(project_dir)})
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "My App"
        assert data["path"] == str(project_dir.resolve())

    def test_create_returns_400_for_non_dir(self, client) -> None:
        r = client.post("/api/projects", json={"name": "Bad", "path": "/nonexistent/path/xyz"})
        assert r.status_code == 400

    def test_create_returns_409_for_duplicate_path(self, client, tmp_path) -> None:
        project_dir = tmp_path / "dup"
        project_dir.mkdir()
        client.post("/api/projects", json={"name": "First", "path": str(project_dir)})
        r = client.post("/api/projects", json={"name": "Second", "path": str(project_dir)})
        assert r.status_code == 409

    def test_patch_updates_project(self, client, tmp_path) -> None:
        project_dir = tmp_path / "patchtest"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "OldName", "path": str(project_dir)})
        project_id = cr.json()["id"]
        r = client.patch(f"/api/projects/{project_id}", json={"name": "NewName"})
        assert r.status_code == 200
        assert r.json()["name"] == "NewName"

    def test_patch_updates_description(self, client, tmp_path) -> None:
        project_dir = tmp_path / "desctest"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "DescProj", "path": str(project_dir)})
        project_id = cr.json()["id"]
        r = client.patch(f"/api/projects/{project_id}", json={"description": "New description"})
        assert r.status_code == 200
        assert r.json()["description"] == "New description"

    def test_patch_returns_404_for_missing(self, client) -> None:
        r = client.patch("/api/projects/nope", json={"name": "Whatever"})
        assert r.status_code == 404

    def test_delete_removes_project(self, client, tmp_path) -> None:
        project_dir = tmp_path / "todelete"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "DeleteMe", "path": str(project_dir)})
        project_id = cr.json()["id"]
        r = client.delete(f"/api/projects/{project_id}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_delete_returns_404_for_missing(self, client) -> None:
        r = client.delete("/api/projects/nope")
        assert r.status_code == 404

    def test_delete_returns_400_for_active(self, client, tmp_path) -> None:
        project_dir = tmp_path / "activeproj"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "ActiveProj", "path": str(project_dir)})
        project_id = cr.json()["id"]
        client.post(f"/api/projects/{project_id}/activate")
        r = client.delete(f"/api/projects/{project_id}")
        assert r.status_code == 400


class TestActivateEndpoint:
    def test_activate_sets_active(self, client, tmp_path) -> None:
        project_dir = tmp_path / "toactivate"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "ToActivate", "path": str(project_dir)})
        project_id = cr.json()["id"]
        r = client.post(f"/api/projects/{project_id}/activate")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["project"]["id"] == project_id

    def test_activate_returns_404_for_missing(self, client) -> None:
        r = client.post("/api/projects/nope/activate")
        assert r.status_code == 404

    def test_list_shows_active_project_id(self, client, tmp_path) -> None:
        project_dir = tmp_path / "showactive"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "ShowActive", "path": str(project_dir)})
        project_id = cr.json()["id"]
        client.post(f"/api/projects/{project_id}/activate")
        r = client.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        assert data["active_project_id"] == project_id

    def test_activate_preserves_session_manager_config(self, client, tmp_path) -> None:
        manager = client.app.state.webui_session_manager
        manager._config.base_url = "https://api.example.test"
        manager._config.api_key = "sk-test"
        manager._config.system_prompt = "Use project context"

        project_dir = tmp_path / "preserve-config"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "PreserveConfig", "path": str(project_dir)})
        project_id = cr.json()["id"]
        r = client.post(f"/api/projects/{project_id}/activate")

        assert r.status_code == 200
        assert client.app.state.webui_session_manager is manager
        assert manager._config.cwd == str(project_dir.resolve())
        assert manager._config.base_url == "https://api.example.test"
        assert manager._config.api_key == "sk-test"
        assert manager._config.system_prompt == "Use project context"

    def test_activate_broadcasts_project_switch_to_existing_sessions(self, client, tmp_path, monkeypatch) -> None:
        manager = client.app.state.webui_session_manager
        entry = manager.create_session()
        events = []

        async def fake_emit(event):
            events.append(event)

        monkeypatch.setattr(entry.host, "_emit", fake_emit)
        project_dir = tmp_path / "broadcast-switch"
        project_dir.mkdir()
        cr = client.post("/api/projects", json={"name": "BroadcastSwitch", "path": str(project_dir)})
        project_id = cr.json()["id"]
        r = client.post(f"/api/projects/{project_id}/activate")

        assert r.status_code == 200
        assert client.app.state.webui_session_manager is manager
        assert len(events) == 1
        assert events[0].type == "project_switched"
        assert events[0].project_id == project_id
        assert events[0].project_path == str(project_dir.resolve())


class TestValidationErrors:
    def test_create_requires_name(self, client, tmp_path) -> None:
        project_dir = tmp_path / "noname"
        project_dir.mkdir()
        r = client.post("/api/projects", json={"path": str(project_dir)})
        assert r.status_code == 422

    def test_create_requires_path(self, client) -> None:
        r = client.post("/api/projects", json={"name": "NoPath"})
        assert r.status_code == 422

    def test_unauthenticated_rejected(self, tmp_path) -> None:
        app = create_app(token="real-token", cwd=str(tmp_path), spa_dir="")
        with TestClient(app, raise_server_exceptions=False) as c:
            c.headers["Authorization"] = "Bearer wrong-token"
            r = c.get("/api/projects")
            assert r.status_code == 401
