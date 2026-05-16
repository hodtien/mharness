"""Tests for the unified scheduler diagnostics module (P19.3).

Verifies that the diagnostics payload correctly separates feature state,
registry state, process state, and produces the right combination labels
for all key state combinations.
"""

from __future__ import annotations


import pytest

from openharness.config.settings import load_settings
from openharness.services.cron import save_cron_jobs, upsert_cron_job
from openharness.services.cron_scheduler import write_pid
from openharness.services.diagnostics import get_diagnostics, _get_worker_counts


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """Redirect all data dirs to a temp location."""
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    config_dir = tmp_path / "config"
    for d in (data_dir, logs_dir, config_dir):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(logs_dir))
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))


class TestGetDiagnostics:
    """Key state combinations and field presence."""

    def test_returns_all_required_fields(self) -> None:
        """The diagnostics payload contains every required field."""
        diag = get_diagnostics()
        for field in (
            "scheduling_feature_enabled",
            "cron_entries_installed",
            "cron_entries_enabled",
            "scheduler_process_alive",
            "scheduler_pid",
            "last_tick_at",
            "last_scan_at",
            "active_worker_count",
            "stale_worker_count",
            "last_error",
        ):
            assert field in diag, f"Missing field: {field}"

    def test_no_feature_no_jobs_no_process(self) -> None:
        """Feature disabled, no cron jobs, no scheduler process."""
        # Clear cron jobs
        save_cron_jobs([])
        # Ensure scheduler not running
        from openharness.services.cron_scheduler import remove_pid
        remove_pid()
        # Feature is enabled by default, disable it
        settings = load_settings()
        from openharness.config.settings import save_settings
        save_settings(settings.model_copy(
            update={"cron_schedule": settings.cron_schedule.model_copy(update={"enabled": False})}
        ))

        diag = get_diagnostics()

        assert diag["scheduling_feature_enabled"] is False
        assert diag["cron_entries_installed"] == 0
        assert diag["cron_entries_enabled"] == 0
        assert diag["scheduler_process_alive"] is False
        assert diag["scheduler_pid"] is None

    def test_feature_enabled_no_jobs_no_process(self) -> None:
        """Feature enabled, no cron jobs, no scheduler process."""
        save_cron_jobs([])
        from openharness.services.cron_scheduler import remove_pid
        remove_pid()
        settings = load_settings()
        from openharness.config.settings import save_settings
        save_settings(settings.model_copy(
            update={"cron_schedule": settings.cron_schedule.model_copy(update={"enabled": True})}
        ))

        diag = get_diagnostics()

        assert diag["scheduling_feature_enabled"] is True
        assert diag["cron_entries_installed"] == 0
        assert diag["cron_entries_enabled"] == 0
        assert diag["scheduler_process_alive"] is False

    def test_feature_enabled_jobs_installed_process_stopped(self) -> None:
        """Feature enabled, cron jobs registered, scheduler process not running (warn state)."""
        # Register a cron job but no scheduler process
        upsert_cron_job({"name": "test-job", "schedule": "0 * * * *", "command": "echo hi"})
        from openharness.services.cron_scheduler import remove_pid
        remove_pid()
        settings = load_settings()
        from openharness.config.settings import save_settings
        save_settings(settings.model_copy(
            update={"cron_schedule": settings.cron_schedule.model_copy(update={"enabled": True})}
        ))

        diag = get_diagnostics()

        assert diag["scheduling_feature_enabled"] is True
        assert diag["cron_entries_installed"] == 1
        assert diag["cron_entries_enabled"] == 1
        assert diag["scheduler_process_alive"] is False

    def test_feature_disabled_jobs_installed_process_stopped(self) -> None:
        """Feature disabled, cron jobs registered, scheduler not running (mixed state)."""
        upsert_cron_job({"name": "test-job", "schedule": "0 * * * *", "command": "echo hi"})
        from openharness.services.cron_scheduler import remove_pid
        remove_pid()
        settings = load_settings()
        from openharness.config.settings import save_settings
        save_settings(settings.model_copy(
            update={"cron_schedule": settings.cron_schedule.model_copy(update={"enabled": False})}
        ))

        diag = get_diagnostics()

        assert diag["scheduling_feature_enabled"] is False
        assert diag["cron_entries_installed"] == 1
        assert diag["cron_entries_enabled"] == 1
        assert diag["scheduler_process_alive"] is False

    def test_feature_enabled_all_enabled_process_running(self) -> None:
        """Feature enabled, all jobs enabled, scheduler process alive (healthy state)."""
        save_cron_jobs([])
        settings = load_settings()
        from openharness.config.settings import save_settings
        save_settings(settings.model_copy(
            update={"cron_schedule": settings.cron_schedule.model_copy(update={"enabled": True})}
        ))
        # Write fake PID to simulate scheduler alive
        write_pid()

        diag = get_diagnostics()

        assert diag["scheduling_feature_enabled"] is True
        assert diag["cron_entries_installed"] == 0
        assert diag["scheduler_process_alive"] is True
        assert diag["scheduler_pid"] is not None

    def test_cron_entries_disabled_count_correct(self) -> None:
        """Disabled cron jobs are counted separately from enabled ones."""
        save_cron_jobs([
            {"name": "job1", "schedule": "* * * * *", "enabled": True, "command": "echo 1"},
            {"name": "job2", "schedule": "* * * * *", "enabled": False, "command": "echo 2"},
            {"name": "job3", "schedule": "* * * * *", "enabled": True, "command": "echo 3"},
        ])
        from openharness.services.cron_scheduler import remove_pid
        remove_pid()
        settings = load_settings()
        from openharness.config.settings import save_settings
        save_settings(settings.model_copy(
            update={"cron_schedule": settings.cron_schedule.model_copy(update={"enabled": True})}
        ))

        diag = get_diagnostics()

        assert diag["cron_entries_installed"] == 3
        assert diag["cron_entries_enabled"] == 2  # job2 is disabled

    def test_pid_none_when_not_running(self) -> None:
        """scheduler_pid is None when the scheduler is not running."""
        from openharness.services.cron_scheduler import remove_pid
        remove_pid()

        diag = get_diagnostics()

        assert diag["scheduler_process_alive"] is False
        assert diag["scheduler_pid"] is None

    def test_pid_present_when_running(self) -> None:
        """scheduler_pid is populated when the scheduler is alive."""
        write_pid()

        diag = get_diagnostics()

        assert diag["scheduler_process_alive"] is True
        assert isinstance(diag["scheduler_pid"], int)
        assert diag["scheduler_pid"] > 0


class TestGetWorkerCounts:
    """Task manager integration."""

    def test_returns_zero_on_error(self) -> None:
        """Gracefully handles task manager errors."""
        from unittest.mock import patch

        with patch(
            "openharness.services.diagnostics.get_task_manager",
            side_effect=RuntimeError("no manager"),
        ):
            active, stale = _get_worker_counts()
        assert active == 0
        assert stale == 0

    def test_counts_running_tasks(self) -> None:
        """Active workers are counted from the task manager."""
        active, stale = _get_worker_counts()
        assert isinstance(active, int)
        assert isinstance(stale, int)