from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openharness.config.settings import AutoReviewSettings, Settings
from openharness.services import auto_review


class _FakeExecutor:
    def __init__(self) -> None:
        self.spawn_calls = []

    async def spawn(self, config):
        self.spawn_calls.append(config)
        return SimpleNamespace(success=True, task_id="review-task", error=None)


class _FakeRegistry:
    def __init__(self, executor: _FakeExecutor) -> None:
        self.executor = executor

    def get_executor(self, name: str) -> _FakeExecutor:
        assert name == "subprocess"
        return self.executor


class _FakeManager:
    def __init__(self) -> None:
        self.task = SimpleNamespace(id="task-1", metadata={})

    def get_task(self, task_id: str):
        if task_id == "task-1":
            return self.task
        return None


def _settings(*, enabled: bool, max_wait_seconds: int = 0) -> Settings:
    return Settings(
        auto_review=AutoReviewSettings(
            enabled=enabled,
            max_wait_seconds=max_wait_seconds,
        )
    )


@pytest.mark.asyncio
async def test_maybe_spawn_review_skips_when_git_diff_empty(tmp_path: Path, monkeypatch) -> None:
    executor = _FakeExecutor()
    monkeypatch.setattr(auto_review, "load_settings", lambda: _settings(enabled=True))
    monkeypatch.setattr(auto_review, "_run_git_diff_stat", lambda _cwd, _base_branch: "")
    monkeypatch.setattr(auto_review, "get_task_manager", _FakeManager)
    monkeypatch.setattr("openharness.swarm.registry.get_backend_registry", lambda: _FakeRegistry(executor))

    await auto_review.maybe_spawn_review("task-1", tmp_path)

    assert executor.spawn_calls == []


@pytest.mark.asyncio
async def test_maybe_spawn_review_spawns_when_git_diff_has_changes(
    tmp_path: Path, monkeypatch
) -> None:
    executor = _FakeExecutor()
    manager = _FakeManager()
    monkeypatch.setattr(auto_review, "load_settings", lambda: _settings(enabled=True))
    monkeypatch.setattr(
        auto_review,
        "_run_git_diff_stat",
        lambda _cwd, _base_branch: "src/example.py | 2 ++",
    )
    monkeypatch.setattr(auto_review, "get_task_manager", lambda: manager)
    monkeypatch.setattr("openharness.swarm.registry.get_backend_registry", lambda: _FakeRegistry(executor))
    monkeypatch.setattr("openharness.coordinator.agent_definitions.get_agent_definition", lambda _name: None)

    await auto_review.maybe_spawn_review("task-1", tmp_path)

    assert len(executor.spawn_calls) == 1
    config = executor.spawn_calls[0]
    assert config.name == "code-reviewer"
    assert config.cwd == str(tmp_path.resolve())
    assert "src/example.py" in config.prompt
    assert manager.task.metadata["review_status"] == "timeout"


@pytest.mark.asyncio
async def test_maybe_spawn_review_skips_when_settings_disabled(tmp_path: Path, monkeypatch) -> None:
    executor = _FakeExecutor()
    monkeypatch.setattr(auto_review, "load_settings", lambda: _settings(enabled=False))
    monkeypatch.setattr(
        auto_review,
        "_run_git_diff_stat",
        lambda _cwd, _base_branch: "src/example.py | 2 ++",
    )
    monkeypatch.setattr(auto_review, "get_task_manager", _FakeManager)
    monkeypatch.setattr("openharness.swarm.registry.get_backend_registry", lambda: _FakeRegistry(executor))

    await auto_review.maybe_spawn_review("task-1", tmp_path)

    assert executor.spawn_calls == []
