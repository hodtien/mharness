"""Background task REST endpoints for the Web UI."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from openharness.tasks.types import TaskRecord
from openharness.webui.server.state import get_task_manager, require_token

router = APIRouter(
    prefix="/api/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_token)],
)


def _serialize_task(task: TaskRecord) -> dict[str, object]:
    """Convert a :class:`TaskRecord` into a JSON-safe dict.

    ``output_file`` is a :class:`pathlib.Path` which we coerce eagerly so the
    response shape matches the rest of the JSON API.
    """
    payload = asdict(task)
    payload["output_file"] = str(task.output_file)
    return payload


@router.get("")
def list_tasks() -> dict[str, object]:
    """Return background tasks ordered most-recent first."""
    return {"tasks": [_serialize_task(task) for task in get_task_manager().list_tasks()]}


@router.get("/")
def list_tasks_slash() -> dict[str, object]:
    """Trailing-slash form so existing clients keep working."""
    return list_tasks()
