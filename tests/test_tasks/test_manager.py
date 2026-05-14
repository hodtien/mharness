"""Tests for background task management."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openharness.tasks.manager import BackgroundTaskManager, _encode_task_worker_payload


@pytest.mark.asyncio
async def test_create_shell_task_and_read_output(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="printf 'hello task'",
        description="hello",
        cwd=tmp_path,
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "completed"
    assert "hello task" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_create_agent_task_with_command_override_and_write(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="first",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    assert "got:first" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_create_agent_task_preserves_multiline_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="line 1\nline 2\nline 3",
        description="agent",
        cwd=tmp_path,
        command=(
            "python -u -c \"import sys, json; "
            "print(json.loads(sys.stdin.readline())['text'].replace(chr(10), '|'))\""
        ),
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    assert "line 1|line 2|line 3" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_write_to_stopped_agent_task_restarts_process(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="ready",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    await manager.write_to_task(task.id, "follow-up")
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    output = manager.read_task_output(task.id)
    assert "got:ready" in output
    assert "[OpenHarness] Agent task restarted; prior interactive context was not preserved." in output
    assert "got:follow-up" in output
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.metadata["restart_count"] == "1"
    assert updated.metadata["status_note"] == "Task restarted; prior interactive context was not preserved."


def test_encode_task_worker_payload_wraps_multiline_text() -> None:
    payload = _encode_task_worker_payload("alpha\nbeta\n")
    assert json.loads(payload.decode("utf-8")) == {"text": "alpha\nbeta"}


def test_encode_task_worker_payload_preserves_structured_messages() -> None:
    raw = '{"text":"follow up","from":"coordinator"}'
    payload = _encode_task_worker_payload(raw)
    assert payload.decode("utf-8") == raw + "\n"


@pytest.mark.asyncio
async def test_stop_task(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="sleep 30",
        description="sleeper",
        cwd=tmp_path,
    )
    await manager.stop_task(task.id)
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "killed"


@pytest.mark.asyncio
async def test_completion_listener_fires_when_task_finishes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    seen: list[tuple[str, str, int | None]] = []
    done = asyncio.Event()

    async def _listener(task):
        seen.append((task.id, task.status, task.return_code))
        done.set()

    manager.register_completion_listener(_listener)

    task = await manager.create_shell_task(
        command="printf 'done'",
        description="listener",
        cwd=tmp_path,
    )

    await asyncio.wait_for(done.wait(), timeout=5)

    assert seen == [(task.id, "completed", 0)]


@pytest.mark.asyncio
async def test_task_sets_terminal_fields_on_exit(tmp_path: Path, monkeypatch):
    """Verify exit_code, terminal_at, and last_log_excerpt are set when task ends."""
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="printf 'output line one\\noutput line two\\noutput line three'",
        description="terminal_fields",
        cwd=tmp_path,
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.return_code == 0
    assert updated.terminal_at is not None
    assert updated.last_heartbeat_at is not None
    assert updated.last_log_excerpt is not None
    assert "output line three" in updated.last_log_excerpt


@pytest.mark.asyncio
async def test_failed_task_captures_error_excerpt(tmp_path: Path, monkeypatch):
    """Verify failed tasks capture last few lines as error summary."""
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="printf 'error occurred\\nsecond error\\nfatal: last error' && exit 1",
        description="failed_task",
        cwd=tmp_path,
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.return_code == 1
    assert updated.terminal_at is not None
    assert updated.error_summary == "Exit code: 1"
    assert updated.last_log_excerpt is not None
    assert "fatal: last error" in updated.last_log_excerpt


@pytest.mark.asyncio
async def test_stale_threshold_read_from_env(tmp_path: Path, monkeypatch):
    """Verify get_task_manager reads OPENHARNESS_TASK_STALE_THRESHOLD_SECONDS from env."""
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENHARNESS_TASK_STALE_THRESHOLD_SECONDS", "42.0")
    # Reset the singleton so it picks up the new env value
    from openharness.tasks.manager import reset_task_manager

    reset_task_manager()
    try:
        from openharness.tasks.manager import get_task_manager

        manager = get_task_manager()
        assert manager._stale_threshold_seconds == 42.0, (
            f"Expected 42.0, got {manager._stale_threshold_seconds}"
        )
    finally:
        reset_task_manager()


@pytest.mark.asyncio
async def test_stale_watchdog_marks_stale_task_failed(tmp_path: Path, monkeypatch):
    """Verify stale watchdog marks long-running tasks with no heartbeat as failed."""
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    # Use a 2 second threshold - task has no heartbeat after initial set
    manager = BackgroundTaskManager(stale_threshold_seconds=2.0)
    manager.start_stale_watchdog()

    # Create a task with a very short sleep so process exits quickly
    # but we'll block the output reader to prevent heartbeat updates
    task = await manager.create_shell_task(
        command="sleep 60",
        description="stalled_task",
        cwd=tmp_path,
    )
    assert task.status == "running"

    # Simulate time passing by clearing heartbeat (process still "alive" in test context)
    task.last_heartbeat_at = task.last_heartbeat_at - 10  # 10 seconds ago

    # Track listener calls for double-notification check
    call_count = 0

    async def _listener(t):
        nonlocal call_count
        call_count += 1

    manager.register_completion_listener(_listener)

    await manager._mark_stale_tasks()
    await asyncio.sleep(0.2)

    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error_summary is not None
    assert "heartbeat" in updated.error_summary or "stalled" in updated.error_summary
    # CRITICAL fix verification: subprocess and waiter must be cleaned up
    assert task.id not in manager._processes, "process should be removed after stale marking"
    assert task.id not in manager._waiters, "waiter should be removed after stale marking"
    # Listener should have been called exactly once (not twice)
    assert call_count == 1, f"Expected 1 listener call, got {call_count}"

    manager.stop_stale_watchdog()
    await manager.aclose()


@pytest.mark.asyncio
async def test_heartbeat_updated_on_output(tmp_path: Path, monkeypatch):
    """Verify last_heartbeat_at is updated when task produces output."""
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager(stale_threshold_seconds=2.0)
    manager.start_stale_watchdog()

    task = await manager.create_shell_task(
        command="sleep 1 && printf 'heartbeat test'",
        description="heartbeat_task",
        cwd=tmp_path,
    )

    # Wait for output to be processed
    await asyncio.sleep(0.5)
    updated = manager.get_task(task.id)
    assert updated is not None
    # Heartbeat should be updated after output
    assert updated.last_heartbeat_at is not None

    manager.stop_stale_watchdog()
    await manager.aclose()
