"""Tests for /api/review endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


# ---------------------------------------------------------------------------
# GET /api/review/{task_id} — 404 when no review exists
# ---------------------------------------------------------------------------

def test_get_review_not_found_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/review/nonexistent-task-id", headers=AUTH)

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"] == "review_not_found"
    assert body["detail"]["task_id"] == "nonexistent-task-id"


# ---------------------------------------------------------------------------
# GET /api/review/{task_id} — returns review content
# ---------------------------------------------------------------------------

def test_get_review_returns_markdown_and_metadata(tmp_path) -> None:
    client = _client(tmp_path)

    # Create the review file manually.
    runs_dir = tmp_path / ".openharness" / "autopilot" / "runs" / "task-42"
    runs_dir.mkdir(parents=True, exist_ok=True)
    review_file = runs_dir / "review.md"
    review_file.write_text("# Code Review\n\nAll good.", encoding="utf-8")

    response = client.get("/api/review/task-42", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "task-42"
    assert body["status"] == "done"
    assert body["markdown"] == "# Code Review\n\nAll good."
    assert "created_at" in body


# ---------------------------------------------------------------------------
# POST /api/review/{task_id}/rerun — returns immediately with ok=true
# ---------------------------------------------------------------------------

def test_rerun_review_returns_ok_and_message(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/review/task-99/rerun", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["message"] == "Review started"