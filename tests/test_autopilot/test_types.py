"""Tests for autopilot data models."""

from __future__ import annotations

from datetime import datetime, timezone

from openharness.autopilot.types import (
    CronScheduleConfig,
    RepoAutopilotRegistry,
    RepoTaskCard,
)


def test_repo_task_card_accepts_iso_timestamps():
    card = RepoTaskCard.model_validate(
        {
            "id": "ap-test",
            "fingerprint": "fp",
            "title": "Test card",
            "source_kind": "manual_idea",
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-01T00:00:01+00:00",
        }
    )

    assert card.created_at == 1777593600.0
    assert card.updated_at == 1777593601.0


def test_registry_accepts_iso_updated_at():
    registry = RepoAutopilotRegistry.model_validate(
        {
            "version": 1,
            "updated_at": "2026-05-01T00:00:00Z",
            "cards": [],
        }
    )

    assert registry.updated_at == 1777593600.0


def test_coerce_timestamp_accepts_datetime_object():
    ts = 1777593600.0
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    card = RepoTaskCard.model_validate(
        {
            "id": "ap-dt",
            "fingerprint": "fp",
            "title": "Datetime card",
            "source_kind": "manual_idea",
            "created_at": dt,
            "updated_at": dt,
        }
    )
    assert card.created_at == ts
    assert card.updated_at == ts


class TestCronScheduleConfig:
    def test_defaults(self):
        cfg = CronScheduleConfig()
        assert cfg.enabled is True
        assert cfg.scan_cron == "*/15 * * * *"
        assert cfg.tick_cron == "0 * * * *"
        assert cfg.timezone == "UTC"
        assert cfg.install_mode == "auto"

    def test_validate_crons_valid(self):
        cfg = CronScheduleConfig(scan_cron="*/5 * * * *", tick_cron="0 */2 * * *")
        errors = cfg.validate_crons()
        assert errors == []

    def test_validate_crons_invalid_scan_cron(self):
        cfg = CronScheduleConfig(scan_cron="not a cron")
        errors = cfg.validate_crons()
        assert len(errors) == 1
        assert "scan_cron" in errors[0]

    def test_validate_crons_invalid_tick_cron(self):
        cfg = CronScheduleConfig(tick_cron="60 * * * *")  # 60 invalid in minute
        errors = cfg.validate_crons()
        assert len(errors) == 1
        assert "tick_cron" in errors[0]

    def test_validate_crons_both_invalid(self):
        cfg = CronScheduleConfig(scan_cron="bad", tick_cron="also bad")
        errors = cfg.validate_crons()
        assert len(errors) == 2

    def test_serialization_roundtrip(self):
        cfg = CronScheduleConfig(
            enabled=False,
            scan_cron="*/10 * * * *",
            tick_cron="30 * * * *",
            timezone="Asia/Ho_Chi_Minh",
            install_mode="manual",
        )
        loaded = CronScheduleConfig.model_validate(cfg.model_dump())
        assert loaded.enabled is False
        assert loaded.scan_cron == "*/10 * * * *"
        assert loaded.tick_cron == "30 * * * *"
        assert loaded.timezone == "Asia/Ho_Chi_Minh"
        assert loaded.install_mode == "manual"
