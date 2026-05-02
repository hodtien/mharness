"""Background task REST endpoints for the Web UI."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

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


@router.get("/{task_id}")
def get_task(task_id: str) -> dict[str, object]:
    """Return one background task by ID."""
    task = get_task_manager().get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No task found with ID: {task_id}",
        )
    return _serialize_task(task)


@router.get("/{task_id}/output")
def get_task_output(task_id: str, tail: int = Query(default=200, ge=0)) -> dict[str, object]:
    """Return the tail of a task's output log as lines."""
    manager = get_task_manager()
    task = manager.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No task found with ID: {task_id}",
        )

    lines = manager.read_task_output_lines(task_id, tail=tail)
    return {"task_id": task_id, "tail": tail, "lines": lines, "output": "\n".join(lines)}


@router.post("/{task_id}/stop")
async def stop_task(task_id: str) -> dict[str, object]:
    """Stop a running background task."""
    manager = get_task_manager()
    if manager.get_task(task_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No task found with ID: {task_id}",
        )
    try:
        task = await manager.stop_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _serialize_task(task)


@router.post("/{task_id}/retry")
async def retry_task(task_id: str) -> dict[str, object]:
    """Re-create a failed task with the same parameters."""
    manager = get_task_manager()
    original = manager.get_task(task_id)
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No task found with ID: {task_id}",
        )
    if original.status not in {"failed", "killed"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only retry failed/killed tasks, got: {original.status}",
        )

    if original.prompt:
        new_task = await manager.create_agent_task(
            prompt=original.prompt,
            description=original.description,
            cwd=str(original.cwd),
            task_type=original.type,
            model=original.metadata.get("model"),
        )
    else:
        new_task = await manager.create_shell_task(
            command=original.command,
            description=original.description,
            cwd=str(original.cwd),
            task_type=original.type,
        )
    return _serialize_task(new_task)
