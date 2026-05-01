"""Tests for autopilot data models."""

from __future__ import annotations

from datetime import datetime, timezone

from openharness.autopilot.types import RepoAutopilotRegistry, RepoTaskCard


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
