"""Local cron-style registry helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from croniter import croniter

from openharness.config.paths import get_cron_registry_path
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text


def _cron_lock_path() -> Path:
    path = get_cron_registry_path()
    return path.with_suffix(path.suffix + ".lock")


def load_cron_jobs() -> list[dict[str, Any]]:
    """Load stored cron jobs."""
    path = get_cron_registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_cron_jobs(jobs: list[dict[str, Any]]) -> None:
    """Persist cron jobs to disk."""
    atomic_write_text(
        get_cron_registry_path(),
        json.dumps(jobs, indent=2) + "\n",
    )


def validate_cron_expression(expression: str) -> bool:
    """Return True if the expression is a valid cron schedule."""
    return croniter.is_valid(expression)


def next_run_time(expression: str, base: datetime | None = None) -> datetime:
    """Return the next run time for a cron expression.

    The returned datetime is naive (no tzinfo) since that is what croniter
    returns.  Callers who need an aware UTC value should attach ``timezone.utc``
    after the call.
    """
    base = base or datetime.now(timezone.utc)
    return croniter(expression, base).get_next(datetime)


def preview_cron_next_runs(
    expression: str,
    count: int = 3,
    base: datetime | None = None,
    tz_name: str | None = None,
) -> list[datetime]:
    """Return the next ``count`` run timestamps for a cron expression.

    Args:
        expression: A valid croniter-style cron expression.
        count: How many future runs to return (default 3).
        base: Reference datetime (defaults to now in UTC).
        tz_name: Timezone name to attach to the output datetimes, e.g. ``"UTC"``
                 or ``"America/New_York"``.  The label is passed through unchanged
                 for display purposes; if zoneinfo is available the datetimes
                 are converted to that zone.

    Returns:
        List of aware datetimes. Returns an empty list if the expression is
        invalid or ``count`` is 0.
    """
    if count <= 0 or not validate_cron_expression(expression):
        return []

    count = min(count, 100)  # cap to prevent unbounded iteration

    base = base or datetime.now(timezone.utc)
    iter_ = croniter(expression, base)
    runs: list[datetime] = []
    for _ in range(count):
        naive = iter_.get_next(datetime)
        # Attach UTC so isoformat() produces an unambiguous timezone marker
        runs.append(naive.replace(tzinfo=timezone.utc))

    if tz_name:
        try:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(tz_name)
            runs = [run.astimezone(tz) for run in runs]
        except Exception:
            # If timezone name is invalid or zoneinfo unavailable, keep UTC
            pass

    return runs


def upsert_cron_job(job: dict[str, Any]) -> None:
    """Insert or replace one cron job.

    Automatically sets ``enabled`` to True and computes ``next_run`` when the
    schedule is a valid cron expression.
    """
    job.setdefault("enabled", True)
    job.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    if "project_path" not in job and job.get("cwd") is not None:
        job["project_path"] = job["cwd"]

    schedule = job.get("schedule", "")
    if validate_cron_expression(schedule):
        job["next_run"] = next_run_time(schedule).isoformat()

    with exclusive_file_lock(_cron_lock_path()):
        jobs = [existing for existing in load_cron_jobs() if existing.get("name") != job.get("name")]
        jobs.append(job)
        jobs.sort(key=lambda item: str(item.get("name", "")))
        save_cron_jobs(jobs)


def delete_cron_job(name: str) -> bool:
    """Delete one cron job by name."""
    with exclusive_file_lock(_cron_lock_path()):
        jobs = load_cron_jobs()
        filtered = [job for job in jobs if job.get("name") != name]
        if len(filtered) == len(jobs):
            return False
        save_cron_jobs(filtered)
    return True


def get_cron_job(name: str) -> dict[str, Any] | None:
    """Return one cron job by name."""
    for job in load_cron_jobs():
        if job.get("name") == name:
            return job
    return None


def set_job_enabled(name: str, enabled: bool) -> bool:
    """Enable or disable a cron job. Returns False if job not found."""
    with exclusive_file_lock(_cron_lock_path()):
        jobs = load_cron_jobs()
        for job in jobs:
            if job.get("name") == name:
                job["enabled"] = enabled
                save_cron_jobs(jobs)
                return True
    return False


def mark_job_run(name: str, *, success: bool) -> None:
    """Update last_run and recompute next_run after a job executes."""
    with exclusive_file_lock(_cron_lock_path()):
        jobs = load_cron_jobs()
        now = datetime.now(timezone.utc)
        for job in jobs:
            if job.get("name") == name:
                job["last_run"] = now.isoformat()
                job["last_status"] = "success" if success else "failed"
                schedule = job.get("schedule", "")
                if validate_cron_expression(schedule):
                    job["next_run"] = next_run_time(schedule, now).isoformat()
                save_cron_jobs(jobs)
                return
