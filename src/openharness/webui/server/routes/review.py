"""Review REST endpoints for the Web UI."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from openharness.config.paths import get_project_autopilot_runs_dir
from openharness.services.auto_review import maybe_spawn_review
from openharness.webui.server.state import WebUIState, get_state, require_token

router = APIRouter(
    prefix="/api/review",
    tags=["review"],
    dependencies=[Depends(require_token)],
)


@router.get("/{task_id}")
def get_review(task_id: str, state: WebUIState = Depends(get_state)) -> dict:
    """Return the saved review markdown for an autopilot task."""
    review_path = get_project_autopilot_runs_dir(state.cwd) / task_id / "review.md"
    if not review_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "review_not_found", "task_id": task_id},
        )
    stat = review_path.stat()
    return {
        "task_id": task_id,
        "status": "done",
        "markdown": review_path.read_text(encoding="utf-8"),
        "created_at": stat.st_ctime,
    }


@router.post("/{task_id}/rerun")
def rerun_review(
    task_id: str,
    background_tasks: BackgroundTasks,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Force-start a code-reviewer run for an autopilot task."""
    background_tasks.add_task(maybe_spawn_review, task_id=task_id, cwd=state.cwd, base_branch="main", force=True)
    return {"ok": True, "message": "Review started"}
