from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openharness.tasks.manager import get_task_manager, reset_task_manager
from openharness.tasks.types import TaskRecord
from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_task_manager(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    reset_task_manager()
    yield
    reset_task_manager()


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


def _add_task(tmp_path, *, task_id: str = "task-001", status: str = "running") -> TaskRecord:
    manager = get_task_manager()
    record = TaskRecord(
        id=task_id,
        type="local_bash",
        status=status,  # type: ignore[arg-type]
        description="Test task",
        cwd=str(tmp_path),
        output_file=Path(tmp_path / "task.log"),
        command="sleep 60",
        created_at=123.0,
        started_at=124.0,
        metadata={"progress": "10"},
    )
    record.output_file.write_text("test output", encoding="utf-8")
    manager._tasks[task_id] = record  # type: ignore[attr-defined]
    return record


def test_get_task_returns_serialized_task(tmp_path) -> None:
    _add_task(tmp_path)
    client = _client(tmp_path)

    response = client.get("/api/tasks/task-001", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "task-001"
    assert body["type"] == "local_bash"
    assert body["status"] == "running"
    assert body["description"] == "Test task"
    assert body["cwd"] == str(tmp_path)
    assert body["output_file"] == str(tmp_path / "task.log")
    assert body["command"] == "sleep 60"
    assert body["created_at"] == 123.0
    assert body["started_at"] == 124.0
    assert body["metadata"] == {"progress": "10"}


def test_get_unknown_task_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/tasks/does-not-exist", headers=AUTH)

    assert response.status_code == 404


def test_stop_task_returns_serialized_stopped_task(tmp_path, monkeypatch) -> None:
    record = _add_task(tmp_path)
    client = _client(tmp_path)

    async def fake_stop_task(task_id: str) -> TaskRecord:
        assert task_id == "task-001"
        record.status = "killed"
        record.ended_at = 125.0
        return record

    monkeypatch.setattr(get_task_manager(), "stop_task", fake_stop_task)

    response = client.post("/api/tasks/task-001/stop", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "task-001"
    assert body["status"] == "killed"
    assert body["ended_at"] == 125.0


def test_stop_unknown_task_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/tasks/does-not-exist/stop", headers=AUTH)

    assert response.status_code == 404


def test_retry_task_creates_new_task(tmp_path, monkeypatch) -> None:
    original = _add_task(tmp_path, status="failed")
    client = _client(tmp_path)

    async def fake_create_shell_task(**kwargs) -> TaskRecord:
        assert kwargs["command"] == "sleep 60"
        assert kwargs["description"] == "Test task"
        assert kwargs["task_type"] == "local_bash"
        new_record = TaskRecord(
            id="task-002",
            type="local_bash",
            status="running",
            description=kwargs["description"],
            cwd=kwargs["cwd"],
            output_file=Path(tmp_path / "task-002.log"),
            command=kwargs["command"],
            created_at=200.0,
            started_at=200.0,
        )
        return new_record

    monkeypatch.setattr(get_task_manager(), "create_shell_task", fake_create_shell_task)

    response = client.post(f"/api/tasks/{original.id}/retry", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "task-002"
    assert body["status"] == "running"
    assert body["command"] == "sleep 60"


def test_retry_unknown_task_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/tasks/does-not-exist/retry", headers=AUTH)

    assert response.status_code == 404


def test_retry_running_task_returns_400(tmp_path) -> None:
    _add_task(tmp_path, status="running")
    client = _client(tmp_path)

    response = client.post("/api/tasks/task-001/retry", headers=AUTH)

    assert response.status_code == 400
