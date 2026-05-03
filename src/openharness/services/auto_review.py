"""Task-lifecycle auto-review service.

Hooks into the background task manager's completion listeners. When a task
completes, spawns a `code-reviewer` agent if:
1. ``settings.auto_review.enabled`` is True, and
2. ``git diff --stat <base_branch>..HEAD`` in the task's cwd shows changes.

The review output is written to:
  .openharness/autopilot/runs/{task_id}/review.md

Task metadata is updated with:
  review_status: pending | in_progress | done
  review_summary: one-line summary from the reviewer agent
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path

from openharness.config.paths import get_project_autopilot_runs_dir
from openharness.config.settings import Settings, load_settings
from openharness.tasks.manager import BackgroundTaskManager, get_task_manager
from openharness.utils.fs import atomic_write_text

log = logging.getLogger(__name__)


def _run_git_diff_stat(cwd: Path, base_branch: str) -> str:
    """Return ``git diff --stat <base_branch>..HEAD`` output, or empty string on error."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", f"{base_branch}..HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _parse_changed_files(diff_stat: str) -> list[str]:
    """Extract file names from ``git diff --stat`` output."""
    files = []
    for line in diff_stat.splitlines():
        # Each line looks like: " src/foo/bar.py  |  5 +2 -3 "
        # We only want the file path (first token before " | ").
        parts = re.split(r"\s*\|\s*", line, maxsplit=1)
        if parts and "|" not in line or (len(parts) == 1 and parts[0].strip()):
            # A line with no "|" separator means no stat info, but the path is present.
            path = parts[0].strip()
            if path and not path.startswith("warning:"):
                files.append(path)
        elif parts:
            path = parts[0].strip()
            if path and not path.startswith("warning:"):
                files.append(path)
    return files


def _review_output_path(cwd: Path, task_id: str) -> Path:
    run_dir = get_project_autopilot_runs_dir(cwd) / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / "review.md"


def _save_review(output_path: Path, content: str) -> None:
    atomic_write_text(output_path, content, encoding="utf-8")


def _parse_review_summary(output: str) -> str:
    """Extract a one-line summary from the reviewer output.

    Prefers an explicit ``Severity: <LEVEL>`` line.
    Falls back to the first non-empty line.
    """
    if not output:
        return ""
    explicit = re.search(
        r"^\s*Severity:\s*(CRITICAL|HIGH|MEDIUM|LOW|NONE)\s*$",
        output,
        re.IGNORECASE | re.MULTILINE,
    )
    if explicit:
        return f"Severity: {explicit.group(1).upper()}"
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return ""


async def maybe_spawn_review(
    task_id: str,
    cwd: Path,
    base_branch: str = "main",
) -> None:
    """
    Conditionally spawn a code-reviewer agent for a completed task.

    Steps:
    1. Load settings and check ``auto_review.enabled``.
    2. Run ``git diff --stat <base_branch>..HEAD`` in *cwd*.
    3. If changes exist, spawn a ``code-reviewer`` agent with a diff summary + file list.
    4. Write review output to ``.openharness/autopilot/runs/{task_id}/review.md``.
    5. Update task metadata with ``review_status`` and ``review_summary``.
    """
    try:
        settings: Settings = load_settings()
    except Exception:
        log.warning("maybe_spawn_review: could not load settings, skipping review")
        return

    if not settings.auto_review.enabled:
        return

    cwd_path = Path(cwd).resolve()
    diff_stat = _run_git_diff_stat(cwd_path, base_branch)

    if not diff_stat:
        log.debug("maybe_spawn_review: no git changes found for task %s", task_id)
        return

    changed_files = _parse_changed_files(diff_stat)
    if not changed_files:
        return

    file_list = "\n".join(f"- {f}" for f in changed_files)

    review_prompt = (
        f"Review the following changes for task `{task_id}` in `{cwd_path}`.\n\n"
        f"## Changed files\n{file_list}\n\n"
        f"## Diff summary\n```\n{diff_stat}\n```\n\n"
        "Provide a concise code review. "
        "Focus on correctness, security, and maintainability. "
        "End your response with a line: Severity: <CRITICAL|HIGH|MEDIUM|LOW|NONE>"
    )

    output_path = _review_output_path(cwd_path, task_id)

    # Update task metadata: in_progress
    manager: BackgroundTaskManager = get_task_manager()
    task = manager.get_task(task_id)
    if task is None:
        log.warning("maybe_spawn_review: task %s not found", task_id)
        return

    task.metadata["review_status"] = "in_progress"
    task.metadata["review_summary"] = ""

    try:
        from openharness.coordinator.agent_definitions import get_agent_definition
        from openharness.swarm.registry import get_backend_registry
        from openharness.swarm.types import TeammateSpawnConfig

        agent_def = get_agent_definition("code-reviewer")
        model = None
        if agent_def is not None:
            model = getattr(agent_def, "model", None)

        registry = get_backend_registry()
        executor = registry.get_executor("subprocess")

        config = TeammateSpawnConfig(
            name="code-reviewer",
            team="",
            prompt=review_prompt,
            cwd=str(cwd_path),
            parent_session_id="main",
            model=model,
            command=None,
            system_prompt=getattr(agent_def, "system_prompt", None) if agent_def else None,
            permissions=getattr(agent_def, "permissions", None) if agent_def else None,
            task_type="local_agent",
        )

        result = await executor.spawn(config)

        if not result.success:
            log.warning("maybe_spawn_review: failed to spawn code-reviewer for task %s: %s", task_id, result.error)
            task.metadata["review_status"] = "failed"
            return

        review_task_id = result.task_id

        # Wait for the review task to complete
        max_wait = settings.auto_review.max_wait_seconds
        waited = 0
        interval = 1.0

        while waited < max_wait:
            await asyncio.sleep(interval)
            waited += interval
            review_record = manager.get_task(review_task_id)
            if review_record is None:
                break
            if review_record.status in ("completed", "failed", "killed"):
                output_text = manager.read_task_output(review_task_id, max_bytes=50000)
                _save_review(output_path, output_text)
                summary = _parse_review_summary(output_text)
                task.metadata["review_status"] = "done" if review_record.status == "completed" else "failed"
                task.metadata["review_summary"] = summary
                log.info("maybe_spawn_review: review for task %s done (status=%s)", task_id, task.metadata["review_status"])
                break
        else:
            log.warning("maybe_spawn_review: review timeout for task %s", task_id)
            task.metadata["review_status"] = "timeout"
    except Exception:
        log.exception("maybe_spawn_review: exception during review for task %s", task_id)
        task.metadata["review_status"] = "error"


def hook_auto_review(manager: BackgroundTaskManager) -> None:
    """Register ``maybe_spawn_review`` as a completion listener on *manager*."""
    manager.register_completion_listener(_on_task_completed)


async def _on_task_completed(task) -> None:
    """Callback registered as a completion listener on BackgroundTaskManager."""
    if task.status != "completed":
        return
    await maybe_spawn_review(
        task_id=task.id,
        cwd=Path(task.cwd),
        base_branch="main",
    )