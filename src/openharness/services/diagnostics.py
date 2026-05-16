"""Unified diagnostics for scheduler, cron, and autopilot status.

Used by Sidebar, Control Center, and Settings/Schedule to display consistent
operational state. One source of truth for all status labels.
"""

from __future__ import annotations

import json
import time
from typing import Any

from openharness.config.settings import load_settings
from openharness.services.cron import load_cron_jobs
from openharness.services.cron_scheduler import get_history_path, is_scheduler_running, read_pid
from openharness.tasks.manager import get_task_manager


def get_diagnostics() -> dict[str, Any]:
    """Return a unified diagnostics payload for all frontend surfaces.

    The payload separates three distinct concerns:

    1. scheduling_feature_enabled — whether the autopilot scheduling feature
       is turned on in settings. Distinct from process state.
    2. cron_entries_* — entries in the local cron registry (installed/disabled
       counts). Distinct from feature flag and process state.
    3. scheduler_process_* — whether the scheduler daemon is alive, its PID,
       and when it last ticked/scanned.

    Mixed/warn states (e.g., feature disabled, or process stopped with jobs
    installed) are communicated by the combination of these fields rather
    than by deriving labels independently in components.
    """
    settings = load_settings()
    cron_enabled = settings.cron_schedule.enabled

    # Cron registry
    jobs = load_cron_jobs()
    cron_entries_installed = len(jobs)
    cron_entries_enabled = sum(1 for j in jobs if j.get("enabled", True))

    # Scheduler process
    pid = read_pid()
    scheduler_process_alive = is_scheduler_running()

    # Timing metadata from history
    last_tick_at, last_scan_at, last_error = _read_history_timestamps(jobs)

    # Task manager (workers)
    active_worker_count, stale_worker_count = _get_worker_counts()

    return {
        # Feature state
        "scheduling_feature_enabled": cron_enabled,
        # Registry state
        "cron_entries_installed": cron_entries_installed,
        "cron_entries_enabled": cron_entries_enabled,
        # Process state
        "scheduler_process_alive": scheduler_process_alive,
        "scheduler_pid": pid,
        # Timing
        "last_tick_at": last_tick_at,
        "last_scan_at": last_scan_at,
        # Workers
        "active_worker_count": active_worker_count,
        "stale_worker_count": stale_worker_count,
        # Errors
        "last_error": last_error,
    }


def _read_history_timestamps(
    jobs: list[dict[str, Any]],
) -> tuple[str | None, str | None, str | None]:
    """Read last tick, last scan, and last error from the history file."""
    path = get_history_path()
    if not path.exists():
        return None, None, None

    entries: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    except Exception:
        return None, None, None

    if not entries:
        return None, None, None

    # Sort by started_at descending (most recent first)
    entries.sort(key=lambda e: e.get("started_at", ""), reverse=True)

    last_tick: str | None = None
    last_scan: str | None = None
    last_err: str | None = None

    for entry in entries:
        name = str(entry.get("name", ""))
        status = str(entry.get("status", ""))
        started_at = entry.get("started_at")

        if name.startswith("autopilot.tick") and last_tick is None:
            last_tick = started_at
        if name.startswith("autopilot.scan") and last_scan is None:
            last_scan = started_at
        if status in ("failed", "error", "timeout") and last_err is None:
            last_err = entry.get("stderr") or entry.get("message") or "Unknown error"
            if len(str(last_err)) > 200:
                last_err = str(last_err)[:200] + "…"

        if last_tick is not None and last_scan is not None and last_err is not None:
            break

    return last_tick, last_scan, last_err


def _get_worker_counts() -> tuple[int, int]:
    """Return active and stale worker counts from the task manager."""
    try:
        tm = get_task_manager()
        records = tm.list_tasks()
    except Exception:
        return 0, 0

    active = 0
    stale = 0
    now = time.time()

    for task in records:
        status = task.status
        heartbeat = task.last_heartbeat_at or task.started_at or task.created_at or 0

        if status in ("running",):
            active += 1

        # Check staleness: 15+ minutes without heartbeat
        if now - heartbeat > 15 * 60:
            stale += 1

    return active, stale