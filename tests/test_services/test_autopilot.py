"""Tests for project repo autopilot state."""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any
from unittest.mock import AsyncMock
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MethodType, SimpleNamespace

from openharness.autopilot import PreflightCheck, PreflightResult, RepoAutopilotStore, RepoTaskCard, RepoVerificationStep
from openharness.swarm.worktree import WorktreeInfo
from openharness.autopilot.service import _DEFAULT_AUTOPILOT_POLICY, _DEFAULT_VERIFICATION_POLICY
from openharness.autopilot.session_store import save_checkpoint
from openharness.config.paths import (
    get_project_active_repo_context_path,
    get_project_autopilot_policy_path,
    get_project_release_policy_path,
    get_project_verification_policy_path,
)


def test_autopilot_enqueue_creates_layout_and_context(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    store = RepoAutopilotStore(repo)
    card, created = store.enqueue_card(
        source_kind="manual_idea",
        title="Add repo autopilot queue",
        body="Persist repo-level work items for self-evolution.",
    )

    assert created is True
    assert card.score > 0
    assert get_project_autopilot_policy_path(repo).exists()
    assert get_project_verification_policy_path(repo).exists()
    assert get_project_release_policy_path(repo).exists()
    context = get_project_active_repo_context_path(repo).read_text(encoding="utf-8")
    assert "Current Task Focus" in context
    assert "Add repo autopilot queue" in context


def test_autopilot_pick_next_prefers_highest_score(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store.enqueue_card(
        source_kind="claude_code_candidate",
        title="Evaluate claude-code agent",
        body="candidate",
    )
    store.enqueue_card(
        source_kind="ohmo_request",
        title="Fix production issue",
        body="urgent bug in channel bridge",
    )

    next_card = store.pick_next_card()

    assert next_card is not None
    assert next_card.source_kind == "ohmo_request"


def test_autopilot_pick_next_breaks_score_ties_by_creation_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    first, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="First idea",
        body="earliest",
    )
    second, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Second idea",
        body="later",
    )

    assert first.score == second.score, "score parity is the precondition for this test"
    assert first.created_at <= second.created_at

    registry = store._load_registry()
    for card in registry.cards:
        if card.id == second.id:
            card.updated_at = first.updated_at + 1_000_000
    store._save_registry(registry)

    chosen = store.pick_next_card()

    assert chosen is not None
    assert chosen.id == first.id, (
        "FIFO tie-break: earliest-created queued card must run first even when "
        "another card was updated more recently"
    )


def test_autopilot_pick_next_includes_accepted_cards(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Accepted idea",
        body="ready to run",
    )
    store.update_status(card.id, status="accepted")

    chosen = store.pick_next_card()

    assert chosen is not None
    assert chosen.id == card.id


def test_pick_and_claim_returns_highest_score(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    low, _ = store.enqueue_card(
        source_kind="claude_code_candidate", title="Low priority", body="candidate"
    )
    high, _ = store.enqueue_card(
        source_kind="ohmo_request", title="High priority", body="urgent bug"
    )
    medium, _ = store.enqueue_card(source_kind="manual_idea", title="Medium priority", body="idea")

    claimed = store.pick_and_claim_card("worker-1")

    assert claimed is not None
    assert claimed.id == high.id
    assert claimed.id not in {low.id, medium.id}
    assert claimed.status == "preparing"


def test_pick_and_claim_skips_already_claimed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    first, _ = store.enqueue_card(source_kind="ohmo_request", title="First", body="urgent bug")
    second, _ = store.enqueue_card(source_kind="manual_idea", title="Second", body="idea")
    store.update_status(first.id, status="preparing")

    claimed = store.pick_and_claim_card("worker-1")

    assert claimed is not None
    assert claimed.id == second.id


def test_pick_and_claim_sets_worker_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Work", body="body")

    claimed = store.pick_and_claim_card("worker-1")

    assert claimed is not None
    assert claimed.id == card.id
    assert claimed.metadata["worker_id"] == "worker-1"
    reloaded = store.get_card(card.id)
    assert reloaded is not None
    assert reloaded.metadata["worker_id"] == "worker-1"


def test_concurrent_claim_no_duplicate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    first, _ = store.enqueue_card(source_kind="manual_idea", title="First", body="idea")
    second, _ = store.enqueue_card(source_kind="manual_idea", title="Second", body="idea")

    def claim(worker_id: str) -> str | None:
        claimed = RepoAutopilotStore(repo).pick_and_claim_card(worker_id)
        return claimed.id if claimed is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_ids = list(executor.map(claim, ["worker-1", "worker-2"]))

    assert sorted(claimed_id for claimed_id in claimed_ids if claimed_id is not None) == sorted(
        [first.id, second.id]
    )


def test_pick_and_claim_none_when_empty(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    assert store.pick_and_claim_card("worker-1") is None


def test_count_active_cards(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    first, _ = store.enqueue_card(source_kind="manual_idea", title="First", body="body")
    second, _ = store.enqueue_card(source_kind="manual_idea", title="Second", body="body")
    store.enqueue_card(source_kind="manual_idea", title="Third", body="body")
    store.update_status(first.id, status="running")
    store.update_status(second.id, status="verifying")

    assert store.count_active_cards() == 2


def test_has_capacity_true(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="First", body="body")
    store.update_status(card.id, status="running")
    policies = store.load_policies()
    policies["autopilot"]["execution"]["max_parallel_runs"] = 2

    assert store.has_capacity(policies) is True


def test_has_capacity_false(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    first, _ = store.enqueue_card(source_kind="manual_idea", title="First", body="body")
    second, _ = store.enqueue_card(source_kind="manual_idea", title="Second", body="body")
    store.update_status(first.id, status="running")
    store.update_status(second.id, status="verifying")
    policies = store.load_policies()
    policies["autopilot"]["execution"]["max_parallel_runs"] = 2

    assert store.has_capacity(policies) is False


def test_pending_not_active(tmp_path: Path) -> None:
    """pending cards should not be counted as active."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="First", body="body")
    store.update_status(card.id, status="pending")

    assert store.count_active_cards() == 0


def test_paused_not_active(tmp_path: Path) -> None:
    """paused cards should not be counted as active."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="First", body="body")
    store.update_status(card.id, status="paused")

    assert store.count_active_cards() == 0


def test_pending_skipped_until_retry_time(tmp_path: Path) -> None:
    """Pending card with future next_retry_at should be skipped by pick_next_card."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Pending test", body="body")

    # Set pending with future next_retry_at
    future_time = time.time() + 3600
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={"pending_reason": "test", "next_retry_at": future_time, "retry_count": 1},
    )

    assert store.pick_next_card() is None, "Pending card with future retry time should be skipped"


def test_pending_becomes_pickable_after_retry_time(tmp_path: Path) -> None:
    """Pending card with past next_retry_at should be picked by pick_next_card."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Pending test", body="body")

    # Set pending with past next_retry_at
    past_time = time.time() - 60
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={"pending_reason": "test", "next_retry_at": past_time, "retry_count": 1},
    )

    chosen = store.pick_next_card()
    assert chosen is not None
    assert chosen.id == card.id, "Pending card with past retry time should be picked"


def test_pick_and_claim_pending_resets_to_preparing(tmp_path: Path) -> None:
    """pick_and_claim_card should reset pending status to preparing and log journal."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Pending retry", body="body")

    past_time = time.time() - 60
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={"pending_reason": "preflight_transient", "next_retry_at": past_time, "retry_count": 2},
    )

    claimed = store.pick_and_claim_card("worker-1")
    assert claimed is not None
    assert claimed.id == card.id
    assert claimed.status == "preparing"
    assert claimed.metadata.get("resumed_from_pending") is True

    # Check journal was appended
    journal = store.load_journal(limit=10)
    resumed_entries = [e for e in journal if e.kind == "resumed_from_pending"]
    assert len(resumed_entries) == 1
    assert card.id in resumed_entries[0].task_id


def test_pick_and_claim_pending_retry_exhausted_fails(tmp_path: Path) -> None:
    """pick_and_claim_card should move exhausted pending cards to failed."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Exhausted retry", body="body")

    # Set pending at max retry count (7)
    past_time = time.time() - 60
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={"pending_reason": "preflight_transient", "next_retry_at": past_time, "retry_count": 7},
    )

    claimed = store.pick_and_claim_card("worker-1")
    assert claimed is None  # Should return None because card moved to failed

    # Verify card is now failed
    failed_card = store.get_card(card.id)
    assert failed_card is not None
    assert failed_card.status == "failed"
    assert failed_card.metadata.get("last_failure_stage") == "retry_exhausted"
    assert "exhausted 7 pending retries" in failed_card.metadata.get("last_failure_summary", "")

    # Check journal for retry_exhausted entry
    journal = store.load_journal(limit=10)
    exhausted_entries = [e for e in journal if e.kind == "retry_exhausted"]
    assert len(exhausted_entries) == 1
    assert card.id in exhausted_entries[0].task_id


def test_pick_specific_card_manual_retry_clears_pending(tmp_path: Path) -> None:
    """pick_specific_card for pending card should clear pending metadata immediately."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Manual retry", body="body")

    future_time = time.time() + 3600
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={
            "pending_reason": "preflight_transient",
            "next_retry_at": future_time,
            "retry_count": 3,
        },
    )

    # Manual retry should clear pending even with future next_retry_at
    claimed = store.pick_specific_card(card.id, "worker-manual")
    assert claimed is not None
    assert claimed.status == "preparing"
    assert "next_retry_at" not in claimed.metadata
    assert "pending_reason" not in claimed.metadata
    assert "retry_count" not in claimed.metadata
    assert claimed.metadata.get("manual_retry") is True

    # Check journal for manual_retry entry
    journal = store.load_journal(limit=10)
    manual_retry_entries = [e for e in journal if e.kind == "manual_retry"]
    assert len(manual_retry_entries) == 1
    assert card.id in manual_retry_entries[0].task_id


def test_calc_next_retry_at_exponential_backoff() -> None:
    """Test that _calc_next_retry_at uses exponential backoff."""
    import time

    from openharness.autopilot.service import _calc_next_retry_at

    now = time.time()

    # Retry 1: ~5 min delay
    t1 = _calc_next_retry_at(1)
    assert 5 * 60 - 5 <= t1 - now <= 5 * 60 + 5, f"Retry 1 delay: {t1 - now}s"

    # Retry 2: ~15 min delay
    t2 = _calc_next_retry_at(2)
    assert 15 * 60 - 5 <= t2 - now <= 15 * 60 + 5, f"Retry 2 delay: {t2 - now}s"

    # Retry 4: ~1h delay
    t4 = _calc_next_retry_at(4)
    assert 60 * 60 - 5 <= t4 - now <= 60 * 60 + 5, f"Retry 4 delay: {t4 - now}s"

    # Retry 10+: capped at ~8h
    t10 = _calc_next_retry_at(10)
    assert 8 * 3600 - 5 <= t10 - now <= 8 * 3600 + 5, f"Retry 10 delay: {t10 - now}s"


def test_autopilot_scan_claude_code_candidates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    claude_root = tmp_path / "claude-code"
    (claude_root / "commands").mkdir(parents=True)
    (claude_root / "agents").mkdir(parents=True)
    (claude_root / "commands" / "compact.md").write_text("compact feature", encoding="utf-8")
    (claude_root / "agents" / "reviewer.md").write_text("reviewer feature", encoding="utf-8")

    store = RepoAutopilotStore(repo)
    cards = store.scan_claude_code_candidates(limit=5, root=claude_root)

    assert len(cards) == 2
    titles = {card.title for card in cards}
    assert "Evaluate claude-code command: compact" in titles
    assert "Evaluate claude-code agent: reviewer" in titles


def test_default_max_parallel_runs_is_2() -> None:
    assert _DEFAULT_AUTOPILOT_POLICY["execution"]["max_parallel_runs"] == 2


def test_policy_round_trip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    policy_path = get_project_autopilot_policy_path(repo)
    original = policy_path.read_text(encoding="utf-8")
    updated = original.replace("max_parallel_runs: 2", "max_parallel_runs: 3")
    policy_path.write_text(updated, encoding="utf-8")

    loaded = store.load_policies()["autopilot"]
    assert loaded["execution"]["max_parallel_runs"] == 3


def test_default_verification_policy_uses_repeatable_local_tsc_command() -> None:
    commands = _DEFAULT_VERIFICATION_POLICY["commands"]

    def _command_text(entry: object) -> str:
        if isinstance(entry, dict):
            return str(entry.get("command", ""))
        return str(entry)

    texts = [_command_text(entry) for entry in commands]
    assert any("./node_modules/.bin/tsc --noEmit" in text for text in texts)
    assert any("npm ci --no-audit --no-fund" in text for text in texts)
    # The tsc step relies on `cd ... && ...` and must opt in to shell=true so
    # the metacharacters are allowed through the verification runner.
    tsc_entry = next(
        entry
        for entry in commands
        if isinstance(entry, dict) and "tsc --noEmit" in str(entry.get("command", ""))
    )
    assert tsc_entry["shell"] is True


def test_autopilot_ci_rollup_treats_missing_checks_as_pending(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    state, summary, checks = store._ci_rollup({"statusCheckRollup": []})

    assert state == "pending"
    assert "have not appeared yet" in summary
    assert checks == []


def test_autopilot_export_dashboard_writes_static_site(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store.enqueue_card(
        source_kind="manual_idea",
        title="Build kanban page",
        body="Make the self-evolution direction visible.",
    )
    store.enqueue_card(
        source_kind="github_issue",
        title="GitHub issue #42: Fix dashboard filters",
        body="search should work",
        source_ref="issue:42",
    )

    output_dir = repo / "docs" / "autopilot"
    exported = store.export_dashboard(output_dir)

    assert exported == output_dir.resolve()
    index_path = output_dir / "index.html"
    snapshot_path = output_dir / "snapshot.json"
    assert index_path.exists()
    assert snapshot_path.exists()
    index_text = index_path.read_text(encoding="utf-8")
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    assert "Autopilot Kanban" in index_text
    assert "snapshot.json" in index_text
    assert "Build kanban page" in snapshot_text
    assert '"status_order"' in snapshot_text


def test_autopilot_run_card_marks_completed_after_verification(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Implement repo autopilot tick",
        body="run next queued task and verify it",
    )

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        assert "Implement repo autopilot tick" in prompt
        return "Implemented the change and ran targeted checks."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        return [
            RepoVerificationStep(
                command="uv run pytest -q",
                returncode=0,
                status="success",
                stdout="63 passed",
            )
        ]

    store._run_agent_prompt = MethodType(fake_run_agent_prompt, store)
    store._run_verification_steps = MethodType(fake_run_verification_steps, store)

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "completed"


def test_autopilot_run_card_marks_failed_when_verification_fails(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Ship broken change",
        body="this should fail verification",
    )

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        return "Made a risky change."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        return [
            RepoVerificationStep(
                command="uv run pytest -q",
                returncode=1,
                status="failed",
                stderr="1 failed",
            )
        ]

    store._run_agent_prompt = MethodType(fake_run_agent_prompt, store)
    store._run_verification_steps = MethodType(fake_run_verification_steps, store)

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "failed"
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "failed"


def test_autopilot_tick_scans_then_runs_next(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store.enqueue_card(source_kind="manual_idea", title="Do queued work", body="body")

    def fake_scan_all_sources(self, *, issue_limit: int = 10, pr_limit: int = 10):
        return {"github_issue": 0, "github_pr": 0, "claude_code_candidate": 0}

    async def fake_run_next(self, *, model=None, max_turns=None, permission_mode=None, card_id=None):
        from openharness.autopilot import RepoRunResult

        return RepoRunResult(
            card_id="ap-test",
            status="completed",
            assistant_summary="done",
            run_report_path=str(self.runs_dir / "ap-test-run.md"),
            verification_report_path=str(self.runs_dir / "ap-test-verification.md"),
            verification_steps=[],
        )

    store.scan_all_sources = MethodType(fake_scan_all_sources, store)
    store.run_next = MethodType(fake_run_next, store)

    import asyncio

    result = asyncio.run(store.tick())

    assert result is not None
    assert result.card_id == "ap-test"


def test_run_next_claims_specific_card_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    first, _ = store.enqueue_card(source_kind="manual_idea", title="First card", body="body")
    second, _ = store.enqueue_card(source_kind="manual_idea", title="Second card", body="body")

    async def fake_run_card(card_id, *, model=None, max_turns=None, permission_mode=None, _claimed_by=None):
        from openharness.autopilot import RepoRunResult

        return RepoRunResult(
            card_id=card_id,
            status="completed",
            assistant_summary="done",
            run_report_path=str(store.runs_dir / f"{card_id}-run.md"),
            verification_report_path=str(store.runs_dir / f"{card_id}-verification.md"),
            verification_steps=[],
        )

    store.run_card = fake_run_card

    import asyncio

    result = asyncio.run(store.run_next(card_id=second.id))

    assert result.card_id == second.id
    assert store.get_card(second.id).status == "preparing"
    assert store.get_card(second.id).metadata.get("worker_id")
    assert store.get_card(first.id).status == "queued"



def test_autopilot_tick_recovers_stuck_card(tmp_path: Path) -> None:
    """A card stuck in an active state with stale ``updated_at`` is reset to queued."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Stuck card",
        body="simulated abandoned run",
    )

    registry = store._load_registry()
    target = next(c for c in registry.cards if c.id == card.id)
    target.status = "running"
    target.updated_at = time.time() - (store.STUCK_CARD_STALE_SECONDS + 60)
    store._save_registry(registry)
    save_checkpoint(
        store.runs_dir,
        card.id,
        phase="implement",
        attempt=1,
        model="sonnet",
        permission_mode="full_auto",
        cwd=str(repo),
        messages=[],
        has_pending_continuation=True,
    )

    def fake_scan_all_sources(self, *, issue_limit: int = 10, pr_limit: int = 10):
        return {"github_issue": 0, "github_pr": 0, "claude_code_candidate": 0}

    async def fake_run_next(self, *, model=None, max_turns=None, permission_mode=None, card_id=None):
        return None

    store.scan_all_sources = MethodType(fake_scan_all_sources, store)
    store.run_next = MethodType(fake_run_next, store)

    import asyncio

    asyncio.run(store.tick())

    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "queued"
    assert "stuck_recovery" in refreshed.metadata
    assert refreshed.metadata["stuck_recovery"]["from_status"] == "running"
    assert refreshed.metadata["resume_available"] is True
    assert refreshed.metadata["resume_phase"] == "implement"


def test_autopilot_tick_does_not_recover_fresh_active_card(tmp_path: Path) -> None:
    """An active card with a recent ``updated_at`` is left alone."""
    import time

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Fresh active card",
        body="still running",
    )

    registry = store._load_registry()
    target = next(c for c in registry.cards if c.id == card.id)
    target.status = "running"
    target.updated_at = time.time()
    store._save_registry(registry)

    def fake_scan_all_sources(self, *, issue_limit: int = 10, pr_limit: int = 10):
        return {"github_issue": 0, "github_pr": 0, "claude_code_candidate": 0}

    store.scan_all_sources = MethodType(fake_scan_all_sources, store)

    import asyncio

    result = asyncio.run(store.tick())

    assert result is None
    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert "stuck_recovery" not in refreshed.metadata


def test_recover_stuck_waiting_ci_with_open_pr(tmp_path: Path, monkeypatch) -> None:
    """A waiting_ci card whose linked PR is still OPEN stays in waiting_ci."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Waiting CI card",
        body="PR is still open",
    )
    registry = store._load_registry()
    target = next(c for c in registry.cards if c.id == card.id)
    target.status = "waiting_ci"
    target.updated_at = time.time() - (store.STUCK_CARD_STALE_SECONDS + 60)
    target.metadata["linked_pr_number"] = 42
    target.metadata["head_branch"] = "autopilot/test-branch"
    store._save_registry(registry)

    monkeypatch.setattr(
        store,
        "_pr_status_snapshot",
        lambda pr_number: {"state": "OPEN", "headRefName": "autopilot/test-branch"},
    )

    recovered = store._recover_stuck_cards()
    assert card.id in recovered
    refreshed = store.get_card(card.id)
    assert refreshed.status == "waiting_ci"
    assert refreshed.metadata["stuck_recovery"]["from_status"] == "waiting_ci"


def test_recover_stuck_waiting_ci_with_merged_pr(tmp_path: Path, monkeypatch) -> None:
    """A waiting_ci card whose linked PR is MERGED transitions to merged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Already merged card",
        body="PR was merged externally",
    )
    registry = store._load_registry()
    target = next(c for c in registry.cards if c.id == card.id)
    target.status = "waiting_ci"
    target.updated_at = time.time() - (store.STUCK_CARD_STALE_SECONDS + 60)
    target.metadata["linked_pr_number"] = 99
    target.metadata["head_branch"] = "autopilot/merged-branch"
    store._save_registry(registry)

    monkeypatch.setattr(
        store,
        "_pr_status_snapshot",
        lambda pr_number: {"state": "MERGED", "headRefName": "autopilot/merged-branch"},
    )

    recovered = store._recover_stuck_cards()
    assert card.id in recovered
    refreshed = store.get_card(card.id)
    assert refreshed.status == "merged"
    assert refreshed.metadata["human_gate_pending"] is False


def test_recover_stuck_waiting_ci_with_branch_mismatch(tmp_path: Path, monkeypatch) -> None:
    """A waiting_ci card whose linked PR points to a different branch resets to queued."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Wrong PR card",
        body="PR number belongs to different branch",
    )
    registry = store._load_registry()
    target = next(c for c in registry.cards if c.id == card.id)
    target.status = "waiting_ci"
    target.updated_at = time.time() - (store.STUCK_CARD_STALE_SECONDS + 60)
    target.metadata["linked_pr_number"] = 92
    target.metadata["head_branch"] = "autopilot/ap-cbf8a49e"
    store._save_registry(registry)

    monkeypatch.setattr(
        store,
        "_pr_status_snapshot",
        lambda pr_number: {"state": "MERGED", "headRefName": "codex/harden-path-rules"},
    )

    recovered = store._recover_stuck_cards()
    assert card.id in recovered
    refreshed = store.get_card(card.id)
    assert refreshed.status == "queued"
    assert refreshed.metadata.get("linked_pr_number") is None
    assert refreshed.metadata.get("verification_failed") is False


def test_recover_stuck_waiting_ci_with_unreachable_pr(tmp_path: Path, monkeypatch) -> None:
    """A waiting_ci card whose linked PR cannot be fetched resets to queued."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Unreachable PR card",
        body="gh CLI fails",
    )
    registry = store._load_registry()
    target = next(c for c in registry.cards if c.id == card.id)
    target.status = "waiting_ci"
    target.updated_at = time.time() - (store.STUCK_CARD_STALE_SECONDS + 60)
    target.metadata["linked_pr_number"] = 999
    target.metadata["head_branch"] = "autopilot/missing"
    store._save_registry(registry)

    def raise_on_snapshot(pr_number):
        raise RuntimeError("gh: Could not resolve to a PullRequest")

    monkeypatch.setattr(store, "_pr_status_snapshot", raise_on_snapshot)

    recovered = store._recover_stuck_cards()
    assert card.id in recovered
    refreshed = store.get_card(card.id)
    assert refreshed.status == "queued"
    assert refreshed.metadata.get("linked_pr_number") is None


def test_recover_stuck_repairing_with_manual_intervention_fails_card(tmp_path: Path) -> None:
    """A stale repairing card requiring human intervention should stop looking active."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Manual repair card",
        body="needs a person to resolve branch sync",
    )
    registry = store._load_registry()
    target = next(c for c in registry.cards if c.id == card.id)
    target.status = "repairing"
    target.updated_at = time.time() - (store.STUCK_CARD_STALE_SECONDS + 60)
    target.metadata["manual_intervention_required"] = True
    target.metadata["human_gate_pending"] = True
    store._save_registry(registry)

    recovered = store._recover_stuck_cards()

    assert card.id in recovered
    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.metadata["stuck_recovery"]["from_status"] == "repairing"
    assert refreshed.metadata["manual_intervention_required"] is True
    assert refreshed.metadata["human_gate_pending"] is True


def test_worktree_cleanup_on_exception(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Cleanup on boom", body="body")

    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    worktree_info = WorktreeInfo(
        slug=f"autopilot/{card.id}",
        path=worktree_path,
        branch=f"worktree-autopilot+{card.id}",
        original_path=repo,
        created_at=time.time(),
    )

    async def fake_create_worktree(self, cwd, slug, branch=None, agent_id=None):
        return worktree_info

    remove_calls: list[str] = []

    async def fake_remove_worktree(self, slug: str) -> bool:
        remove_calls.append(slug)
        return True

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    # Mock preflight checks to pass
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )
    store._run_agent_prompt = MethodType(fake_run_agent_prompt, store)

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "failed"
    assert remove_calls == [f"autopilot/{card.id}"]


def test_worktree_cleanup_failure_non_fatal(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Cleanup warning", body="body")

    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    worktree_info = WorktreeInfo(
        slug=f"autopilot/{card.id}",
        path=worktree_path,
        branch=f"worktree-autopilot+{card.id}",
        original_path=repo,
        created_at=time.time(),
    )

    async def fake_create_worktree(self, cwd, slug, branch=None, agent_id=None):
        return worktree_info

    async def fake_remove_worktree(self, slug: str) -> bool:
        raise RuntimeError("cleanup failed")

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )
    store._run_agent_prompt = MethodType(fake_run_agent_prompt, store)

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    journal = store.journal_path.read_text(encoding="utf-8")

    assert result.status == "failed"
    assert "cleanup_warning" in journal
    assert "cleanup failed" in journal


def test_startup_cleans_stale_worktrees(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    seed_store = RepoAutopilotStore(repo)
    card, _ = seed_store.enqueue_card(source_kind="manual_idea", title="Done", body="body")
    worktree_path = tmp_path / ".openharness" / "worktrees" / f"autopilot+{card.id}"
    worktree_path.mkdir(parents=True)

    removed: list[str] = []

    async def fake_list_worktrees(self):
        return [
            WorktreeInfo(
                slug=f"autopilot/{card.id}",
                path=worktree_path,
                branch="worktree-autopilot",
                original_path=repo,
                created_at=time.time(),
            )
        ]

    async def fake_remove_worktree(self, slug: str) -> bool:
        removed.append(slug)
        if worktree_path.exists():
            for child in worktree_path.iterdir():
                if child.is_file() or child.is_symlink():
                    child.unlink()
            worktree_path.rmdir()
        return True

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.list_worktrees", fake_list_worktrees
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    seed_store.update_status(card.id, status="failed")

    RepoAutopilotStore(repo)

    assert removed == [f"autopilot/{card.id}"]
    assert not worktree_path.exists()


def test_startup_keeps_active_worktrees(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    card, _ = RepoAutopilotStore(repo).enqueue_card(
        source_kind="manual_idea", title="Active", body="body"
    )
    worktree_path = tmp_path / ".openharness" / "worktrees" / f"autopilot+{card.id}"
    worktree_path.mkdir(parents=True)

    async def fake_list_worktrees(self):
        return [
            WorktreeInfo(
                slug=f"autopilot/{card.id}",
                path=worktree_path,
                branch="worktree-autopilot",
                original_path=repo,
                created_at=time.time(),
            )
        ]

    remove_mock = AsyncMock(return_value=True)

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.list_worktrees", fake_list_worktrees
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", remove_mock
    )
    store = RepoAutopilotStore(repo)

    import asyncio

    asyncio.run(store._cleanup_stale_worktrees())

    assert worktree_path.exists()
    assert remove_mock.await_count == 0


def test_autopilot_install_default_cron_creates_jobs(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    recorded: list[dict[str, str]] = []

    monkeypatch.setattr(
        "openharness.services.cron.upsert_cron_job",
        lambda job: recorded.append(job),
    )

    report = store.install_default_cron()

    names = [job["name"] for job in report["installed"]]
    assert names == ["autopilot.scan", "autopilot.tick"]
    assert len(recorded) == 2
    assert recorded[0]["name"] == "autopilot.scan"
    for job in recorded:
        assert "project_path" in job
        assert job["project_path"] == str(repo)
    # Response includes cron_lines for user audit
    assert len(report["cron_lines"]) == 2
    assert "oh autopilot scan" in report["cron_lines"][0]
    assert "oh autopilot tick" in report["cron_lines"][1]


def test_install_default_cron_uses_configured_schedules(tmp_path: Path, monkeypatch) -> None:
    """install_default_cron reads scan_cron/tick_cron from settings, not hardcoded values."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Override the config dir so load_settings() picks up our custom values
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(config_dir))

    from openharness.config.settings import Settings, CronScheduleConfig, save_settings
    custom_cfg = CronScheduleConfig(
        scan_cron="*/5 * * * *",
        tick_cron="30 */3 * * *",
        enabled=True,
    )
    save_settings(Settings(cron_schedule=custom_cfg), config_dir / "settings.json")

    recorded: list[dict[str, str]] = []
    monkeypatch.setattr(
        "openharness.services.cron.upsert_cron_job",
        lambda job: recorded.append(job),
    )

    store = RepoAutopilotStore(repo)
    report = store.install_default_cron()

    # The installed jobs must use the configured schedules, not hardcoded defaults
    scan_job = next(j for j in report["installed"] if j["name"] == "autopilot.scan")
    tick_job = next(j for j in report["installed"] if j["name"] == "autopilot.tick")
    assert scan_job["schedule"] == "*/5 * * * *"
    assert tick_job["schedule"] == "30 */3 * * *"
    assert recorded[0]["schedule"] == "*/5 * * * *"
    assert recorded[1]["schedule"] == "30 */3 * * *"


def test_two_projects_have_isolated_autopilot_state(tmp_path: Path, monkeypatch) -> None:
    """Cards, journal entries, and registry files of two projects must not bleed into each other."""
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    store_a = RepoAutopilotStore(project_a)
    store_b = RepoAutopilotStore(project_b)

    card_a, _ = store_a.enqueue_card(
        source_kind="manual_idea",
        title="Task for project A",
        body="Only for A",
    )
    card_b, _ = store_b.enqueue_card(
        source_kind="manual_idea",
        title="Task for project B",
        body="Only for B",
    )

    store_a.append_journal(kind="note", summary="journal A entry", task_id=card_a.id)
    store_b.append_journal(kind="note", summary="journal B entry", task_id=card_b.id)

    # Each store reads only its own registry
    assert store_a.get_card(card_a.id) is not None
    assert store_a.get_card(card_b.id) is None
    assert store_b.get_card(card_b.id) is not None
    assert store_b.get_card(card_a.id) is None

    # Paths are scoped to their respective projects
    assert store_a.registry_path.parent == project_a / ".openharness" / "autopilot"
    assert store_b.registry_path.parent == project_b / ".openharness" / "autopilot"
    assert store_a.journal_path.parent == project_a / ".openharness" / "autopilot"
    assert store_b.journal_path.parent == project_b / ".openharness" / "autopilot"

    # Journal entries are isolated (enqueue_card also writes intake_added internally)
    journal_a = store_a.load_journal()
    journal_b = store_b.load_journal()
    note_entries_a = [e for e in journal_a if e.kind == "note"]
    note_entries_b = [e for e in journal_b if e.kind == "note"]
    assert len(note_entries_a) == 1
    assert "journal A entry" in note_entries_a[0].summary
    assert len(note_entries_b) == 1
    assert "journal B entry" in note_entries_b[0].summary
    assert all("journal B entry" not in e.summary for e in journal_a)
    assert all("journal A entry" not in e.summary for e in journal_b)


def test_autopilot_run_card_opens_pr_and_waits_for_ci(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Ship autopilot PR flow",
        body="exercise PR/CI orchestration",
    )

    async def fake_create_worktree(self, repo_path, slug, branch=None, agent_id=None):
        return SimpleNamespace(path=worktree)

    async def fake_remove_worktree(self, slug):
        return True

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        assert cwd == worktree
        return "Implemented the requested feature."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        assert cwd == worktree
        return [RepoVerificationStep(command="uv run pytest -q", returncode=0, status="success")]

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return (
            "success",
            "All reported remote checks passed.",
            {"url": "https://example/pr/17", "labels": [], "isDraft": False},
            [],
        )

    # Import PreflightCheck for mocking
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        fake_run_verification_steps,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_commit_all",
        lambda self, cwd, message: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        lambda self, cwd, *, base_branch, head_branch, policies, card_id=None: (
            True,
            "branch_push_done",
            f"Pushed {head_branch}.",
        ),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 17,
            "url": "https://example/pr/17",
        },
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "completed"
    assert result.pr_number == 17
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.metadata["linked_pr_number"] == 17
    assert updated.metadata["human_gate_pending"] is True


def test_autopilot_run_card_repairs_after_local_verification_failure(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Repair failing verification",
        body="first verification fails, second passes",
    )

    verification_calls = {"count": 0}

    async def fake_create_worktree(self, repo_path, slug, branch=None, agent_id=None):
        return SimpleNamespace(path=worktree)

    async def fake_remove_worktree(self, slug):
        return True

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        return f"attempt for {cwd}"

    def fake_run_verification_steps(self, policies, *, cwd=None):
        verification_calls["count"] += 1
        if verification_calls["count"] == 1:
            return [
                RepoVerificationStep(
                    command="uv run pytest -q", returncode=1, status="failed", stderr="1 failed"
                )
            ]
        return [RepoVerificationStep(command="uv run pytest -q", returncode=0, status="success")]

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return (
            "success",
            "All reported remote checks passed.",
            {"url": "https://example/pr/23", "labels": ["autopilot:merge"], "isDraft": False},
            [],
        )

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    merged = {"called": False}

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    # Mock preflight checks to pass
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        fake_run_verification_steps,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_commit_all",
        lambda self, cwd, message: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        lambda self, cwd, *, base_branch, head_branch, policies, card_id=None: (
            True,
            "branch_push_done",
            f"Pushed {head_branch}.",
        ),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 23,
            "url": "https://example/pr/23",
        },
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: merged.__setitem__("called", True),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "merged"
    assert result.attempt_count == 2
    assert merged["called"] is True
    assert verification_calls["count"] == 2


def test_autopilot_run_card_stops_repeated_local_verification_failure(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Repeated reviewer failure",
        body="reviewer failure repeats",
    )
    verification_calls = {"count": 0}

    async def fake_create_worktree(self, repo_path, slug, branch=None, agent_id=None):
        return SimpleNamespace(path=worktree)

    async def fake_remove_worktree(self, slug):
        return True

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        return "attempted repair"

    def fake_run_verification_steps(self, policies, *, cwd=None):
        verification_calls["count"] += 1
        return [
            RepoVerificationStep(
                command="agent:code-reviewer (diff vs main)",
                returncode=1,
                status="failed",
                stdout="Severity: CRITICAL",
                stderr="severity=critical",
            )
        ]

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore.run_preflight",
        lambda self, card: PreflightResult(passed=True, checks=[], fatal=[], transient=[]),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        fake_run_verification_steps,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._max_repeated_failure_attempts",
        lambda self, policies: 2,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "failed"
    assert verification_calls["count"] == 2
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.metadata["last_failure_stage"] == "local_verification_failed"
    assert updated.metadata["repeated_failure_count"] == 2


def test_autopilot_run_card_reuses_existing_branch_progress(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Reuse existing branch commit",
        body="agent may commit directly before the service tries to commit",
    )

    async def fake_create_worktree(self, repo_path, slug, branch=None, agent_id=None):
        return SimpleNamespace(path=worktree)

    async def fake_remove_worktree(self, slug):
        return True

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        return "A direct git commit already exists on the branch."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        return [RepoVerificationStep(command="uv run pytest -q", returncode=0, status="success")]

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return (
            "success",
            "All reported remote checks passed.",
            {"url": "https://example/pr/29", "labels": [], "isDraft": False},
            [],
        )

    pushed = {"called": False}

    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        fake_run_verification_steps,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_commit_all",
        lambda self, cwd, message: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_branch_has_progress",
        lambda self, cwd, *, base_branch: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        lambda self, cwd, *, base_branch, head_branch, policies, card_id=None: (
            pushed.__setitem__("called", True) or True,
            "branch_push_done",
            f"Pushed {head_branch}.",
        ),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 29,
            "url": "https://example/pr/29",
        },
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "completed"
    assert result.pr_number == 29
    assert pushed["called"] is True
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.metadata["human_gate_pending"] is True


def test_autopilot_existing_pr_card_can_auto_merge(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #88: Existing autopilot PR",
        body="already open",
        source_ref="pr:88",
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        assert pr_number == 88
        return (
            "success",
            "All reported remote checks passed.",
            {"url": "https://example/pr/88", "labels": ["autopilot:merge"], "isDraft": False},
            [],
        )

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    merged = {"called": False}

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: merged.__setitem__("called", True),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pull_base_branch",
        lambda self, *, base_branch: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "merged"
    assert result.pr_number == 88
    assert merged["called"] is True


def test_automerge_eligible_accepts_always_mode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    eligible = store._automerge_eligible(
        {"labels": [], "isDraft": False},
        {"autopilot": {"github": {"auto_merge": {"mode": "always"}}}},
    )

    assert eligible is True


def test_wait_for_pr_ci_allows_repos_with_no_remote_checks_after_grace(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    times = iter([1000.0, 1000.0, 1006.0, 1006.0])
    monkeypatch.setattr("openharness.autopilot.service.time.time", lambda: next(times))
    monkeypatch.setattr(
        "openharness.autopilot.service.asyncio.sleep",
        lambda _seconds: __import__("asyncio").sleep(0),
    )
    monkeypatch.setattr(
        store,
        "_pr_status_snapshot",
        lambda pr_number: {"url": "https://example/pr/31", "statusCheckRollup": []},
    )

    import asyncio

    state, summary, snapshot, checks = asyncio.run(
        store._wait_for_pr_ci(
            31,
            {
                "autopilot": {
                    "github": {
                        "ci_poll_interval_seconds": 1,
                        "ci_timeout_seconds": 30,
                        "no_checks_grace_seconds": 5,
                    }
                }
            },
        )
    )

    assert state == "success"
    assert "grace period" in summary
    assert snapshot["url"] == "https://example/pr/31"
    assert checks == []


def test_wait_for_pr_ci_waits_for_check_settle_window(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    current_time = {"value": 1000.0}
    monkeypatch.setattr("openharness.autopilot.service.time.time", lambda: current_time["value"])
    snapshots = [
        {
            "url": "https://example/pr/33",
            "statusCheckRollup": [
                {
                    "name": "GitGuardian Security Checks",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                }
            ],
        },
        {
            "url": "https://example/pr/33",
            "statusCheckRollup": [
                {
                    "name": "GitGuardian Security Checks",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                },
                {"name": "Python tests (3.10)", "status": "IN_PROGRESS", "conclusion": ""},
            ],
        },
        {
            "url": "https://example/pr/33",
            "statusCheckRollup": [
                {
                    "name": "GitGuardian Security Checks",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                },
                {"name": "Python tests (3.10)", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
        },
    ]
    snapshot_index = {"value": 0}
    sleep_calls: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)
        current_time["value"] += seconds

    monkeypatch.setattr("openharness.autopilot.service.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        store,
        "_pr_status_snapshot",
        lambda pr_number: snapshots[min(snapshot_index.setdefault("value", 0), len(snapshots) - 1)],
    )
    original_snapshot = store._pr_status_snapshot

    def advancing_snapshot(pr_number: int):
        value = snapshot_index["value"]
        snapshot_index["value"] = value + 1
        return original_snapshot(pr_number)

    monkeypatch.setattr(store, "_pr_status_snapshot", advancing_snapshot)

    import asyncio

    state, summary, snapshot, checks = asyncio.run(
        store._wait_for_pr_ci(
            33,
            {
                "autopilot": {
                    "github": {
                        "ci_poll_interval_seconds": 5,
                        "ci_timeout_seconds": 60,
                        "no_checks_grace_seconds": 5,
                        "checks_settle_seconds": 10,
                    }
                }
            },
        )
    )

    assert state == "success"
    assert summary == "All reported remote checks passed."
    assert snapshot["url"] == "https://example/pr/33"
    assert len(checks) == 2
    assert sleep_calls == [5, 5]


def test_merge_pull_request_does_not_request_branch_deletion(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda args, *, cwd=None, check=False: captured.update(
            {"args": args, "cwd": cwd, "check": check}
        ),
    )

    store._merge_pull_request(41)

    assert captured["args"] == ["pr", "merge", "41", "--repo", "hodtien/mharness", "--squash"]
    assert captured["check"] is True


def test_find_open_pr_for_branch_uses_repo_qualified_head_lookup(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    captured: dict[str, object] = {}

    def fake_gh_json(args, *, cwd=None):
        captured.update({"args": args, "cwd": cwd})
        return [{"number": 12, "url": "https://example/pr/12"}]

    monkeypatch.setattr(store, "_gh_json", fake_gh_json)

    pr = store._find_open_pr_for_branch("autopilot/ap-test")

    assert pr == {"number": 12, "url": "https://example/pr/12"}
    assert captured["cwd"] == repo
    assert captured["args"] == [
        "pr",
        "list",
        "--repo",
        "hodtien/mharness",
        "--state",
        "open",
        "--head",
        "autopilot/ap-test",
        "--json",
        "number,url,isDraft,labels,headRefName,baseRefName,mergeStateStatus,reviewDecision",
    ]


def test_comment_on_pr_uses_repo_qualified_command(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda args, *, cwd=None, check=False: captured.update(
            {"args": args, "cwd": cwd, "check": check}
        ),
    )

    store._comment_on_pr(12, "hello")

    assert captured == {
        "args": ["pr", "comment", "12", "--repo", "hodtien/mharness", "--body", "hello"],
        "cwd": repo,
        "check": True,
    }


def test_pr_status_snapshot_uses_repo_qualified_view(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    captured: dict[str, object] = {}

    def fake_gh_json(args, *, cwd=None):
        captured.update({"args": args, "cwd": cwd})
        return {"number": 12, "labels": [{"name": "autopilot"}]}

    monkeypatch.setattr(store, "_gh_json", fake_gh_json)

    snapshot = store._pr_status_snapshot(12)

    assert snapshot["labels"] == ["autopilot"]
    assert captured["cwd"] == repo
    assert captured["args"] == [
        "pr",
        "view",
        "12",
        "--repo",
        "hodtien/mharness",
        "--json",
        "state,number,url,isDraft,labels,headRefName,baseRefName,mergeStateStatus,reviewDecision,statusCheckRollup",
    ]


def test_best_effort_add_labels_uses_repo_qualified_edit(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda args, *, cwd=None, check=False: captured.update(
            {"args": args, "cwd": cwd, "check": check}
        ),
    )

    store._best_effort_add_labels(12, ["autopilot", "ready"])

    assert captured == {
        "args": [
            "pr",
            "edit",
            "12",
            "--repo",
            "hodtien/mharness",
            "--add-label",
            "autopilot",
            "--add-label",
            "ready",
        ],
        "cwd": repo,
        "check": False,
    }


def test_create_pr_succeeds_on_first_attempt(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    body_path = tmp_path / "body.md"
    body_path.write_text("body", encoding="utf-8")
    store = RepoAutopilotStore(repo)
    calls: list[list[str]] = []

    def fake_run_gh(args, *, cwd=None, check=False):
        calls.append(args)
        return subprocess.CompletedProcess(["gh", *args], 0, "", "")

    monkeypatch.setattr(store, "_run_gh", fake_run_gh)

    store._create_pull_request(
        head_branch="autopilot/ap-test",
        base_branch="main",
        title="Autopilot: Test",
        body_path=body_path,
    )

    assert calls == [
        [
            "pr",
            "create",
            "--title",
            "Autopilot: Test",
            "--body-file",
            str(body_path),
            "--base",
            "main",
            "--head",
            "autopilot/ap-test",
        ],
    ]


def test_create_pr_retries_with_explicit_repo_on_head_resolution_error(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    body_path = tmp_path / "body.md"
    body_path.write_text("body", encoding="utf-8")
    store = RepoAutopilotStore(repo)
    calls: list[list[str]] = []

    def fake_run_gh(args, *, cwd=None, check=False):
        calls.append(args)
        if args[:2] == ["repo", "view"]:
            return subprocess.CompletedProcess(
                ["gh", *args], 0, '{"nameWithOwner":"hodtien/mharness"}', ""
            )
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                ["gh", *args],
                1,
                "",
                "GraphQL: Head sha can't be blank, Base sha can't be blank, No commits between main and autopilot/ap-test, Head ref must be a branch",
            )
        return subprocess.CompletedProcess(["gh", *args], 0, "", "")

    monkeypatch.setattr(store, "_run_gh", fake_run_gh)

    store._create_pull_request(
        head_branch="autopilot/ap-test",
        base_branch="main",
        title="Autopilot: Test",
        body_path=body_path,
    )

    assert calls[0] == [
        "pr",
        "create",
        "--title",
        "Autopilot: Test",
        "--body-file",
        str(body_path),
        "--base",
        "main",
        "--head",
        "autopilot/ap-test",
    ]
    assert calls[1] == ["repo", "view", "--json", "nameWithOwner"]
    assert calls[2] == [
        "pr",
        "create",
        "--repo",
        "hodtien/mharness",
        "--title",
        "Autopilot: Test",
        "--body-file",
        str(body_path),
        "--base",
        "main",
        "--head",
        "hodtien:autopilot/ap-test",
    ]


def test_create_pr_raises_on_non_resolution_error(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    body_path = tmp_path / "body.md"
    body_path.write_text("body", encoding="utf-8")
    store = RepoAutopilotStore(repo)

    def fake_run_gh(args, *, cwd=None, check=False):
        return subprocess.CompletedProcess(["gh", *args], 1, "", "authentication required")

    monkeypatch.setattr(store, "_run_gh", fake_run_gh)

    try:
        store._create_pull_request(
            head_branch="autopilot/ap-test",
            base_branch="main",
            title="Autopilot: Test",
            body_path=body_path,
        )
    except subprocess.CalledProcessError as exc:
        assert exc.stderr == "authentication required"
    else:
        raise AssertionError("Expected CalledProcessError for non-resolution gh error")


def test_current_repo_full_name_prefers_origin_remote(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    def fake_run_git(args, *, cwd=None, check=False):
        assert args == ["remote", "get-url", "origin"]
        return subprocess.CompletedProcess(
            ["git", *args],
            0,
            "https://github.com/hodtien/mharness.git\n",
            "",
        )

    monkeypatch.setattr(store, "_run_git", fake_run_git)
    monkeypatch.setattr(
        store,
        "_gh_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("gh should not run")),
    )

    assert store._current_repo_full_name() == "hodtien/mharness"


def test_current_repo_full_name_handles_ssh_origin_remote(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    def fake_run_git(args, *, cwd=None, check=False):
        return subprocess.CompletedProcess(
            ["git", *args], 0, "git@github.com:hodtien/mharness.git\n", ""
        )

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    assert store._current_repo_full_name() == "hodtien/mharness"


def test_current_repo_full_name_falls_back_to_gh_when_origin_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    def fake_run_git(args, *, cwd=None, check=False):
        return subprocess.CompletedProcess(["git", *args], 1, "", "no origin")

    monkeypatch.setattr(store, "_run_git", fake_run_git)
    monkeypatch.setattr(
        store, "_gh_json", lambda args, *, cwd=None: {"nameWithOwner": "fallback/repo"}
    )

    assert store._current_repo_full_name() == "fallback/repo"


def _remote_review_policy(*, enabled: bool = True, repair: dict[str, int] | None = None) -> dict:
    policy = {
        "autopilot": {
            "github": {
                "remote_code_review": {
                    "enabled": enabled,
                    "block_on": ["critical"],
                    "max_turns": 6,
                    "max_diff_chars": 80000,
                }
            }
        }
    }
    if repair is not None:
        policy["autopilot"]["repair"] = repair
    return policy


def _green_pr_snapshot(pr_number: int) -> tuple[str, str, dict, list]:
    return (
        "success",
        "All reported remote checks passed.",
        {"url": f"https://example/pr/{pr_number}", "labels": ["autopilot:merge"], "isDraft": False},
        [],
    )


def test_local_code_review_zero_max_turns_disables_turn_limit(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Review no turn limit", body="")
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        store,
        "_run_git",
        lambda args, *, cwd=None, check=False: subprocess.CompletedProcess(
            args,
            0,
            stdout="diff --git a/src/example.py b/src/example.py\n",
            stderr="",
        ),
    )

    async def fake_run_agent_prompt(
        prompt,
        *,
        model,
        max_turns,
        permission_mode,
        cwd=None,
        stream=None,
        checkpoint_card_id=None,
        checkpoint_phase=None,
        checkpoint_attempt=1,
        resume_messages=None,
        phase=None,
    ):
        seen["max_turns"] = max_turns
        return "Severity: NONE"

    monkeypatch.setattr(store, "_run_agent_prompt", fake_run_agent_prompt)

    step = asyncio.run(
        store._run_code_review_step(
            card,
            cwd=worktree,
            base_branch="main",
            policies={"verification": {"code_review": {"max_turns": 0}}},
            model="test-model",
        )
    )

    assert step.status == "success"
    assert seen["max_turns"] is None


def test_remote_code_review_step_skips_when_disabled(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Review opt out", body="disabled")

    calls = {"gh": 0, "agent": 0}
    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda *args, **kwargs: calls.__setitem__("gh", calls["gh"] + 1),
    )

    async def fake_run_agent_prompt(*args, **kwargs):
        calls["agent"] += 1
        return "Severity: NONE"

    monkeypatch.setattr(store, "_run_agent_prompt", fake_run_agent_prompt)

    import asyncio

    step = asyncio.run(
        store._run_remote_code_review_step(
            card,
            12,
            policies=_remote_review_policy(enabled=False),
            model=None,
        )
    )

    assert step.status == "skipped"
    assert calls == {"gh": 0, "agent": 0}


def test_remote_code_review_step_blocks_tracked_virtualenv(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    card, _ = store.enqueue_card(
        source_kind="manual_idea", title="Review virtualenv", body="review"
    )
    calls = {"agent": 0}

    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda args, *, cwd=None, check=False: subprocess.CompletedProcess(
            args,
            0,
            stdout="diff --git a/.venv b/.venv\nnew file mode 120000\n",
            stderr="",
        ),
    )

    async def fake_run_agent_prompt(*args, **kwargs):
        calls["agent"] += 1
        return "Severity: NONE"

    monkeypatch.setattr(store, "_run_agent_prompt", fake_run_agent_prompt)

    import asyncio

    step = asyncio.run(
        store._run_remote_code_review_step(
            card,
            12,
            policies=_remote_review_policy(),
            model="test-model",
        )
    )

    assert step.status == "failed"
    assert step.stderr == "severity=critical"
    assert ".venv" in step.stdout
    assert calls["agent"] == 0


def test_remote_code_review_step_blocks_nested_virtualenv_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    card, _ = store.enqueue_card(
        source_kind="manual_idea", title="Review virtualenv", body="review"
    )

    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda args, *, cwd=None, check=False: subprocess.CompletedProcess(
            args,
            0,
            stdout="diff --git a/.venv/bin/python b/.venv/bin/python\nnew file mode 120000\n",
            stderr="",
        ),
    )

    import asyncio

    step = asyncio.run(
        store._run_remote_code_review_step(
            card,
            12,
            policies=_remote_review_policy(),
            model="test-model",
        )
    )

    assert step.status == "failed"
    assert step.stderr == "severity=critical"


def test_remote_code_review_prompt_requires_requirement_completeness(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    card, _ = store.enqueue_card(
        source_kind="manual_idea", title="Configurable max_parallel_runs policy", body="review"
    )

    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda args, *, cwd=None, check=False: subprocess.CompletedProcess(
            args,
            0,
            stdout="diff --git a/src/openharness/autopilot/service.py b/src/openharness/autopilot/service.py\n",
            stderr="",
        ),
    )

    async def fake_run_agent_prompt(
        prompt,
        *,
        model,
        max_turns,
        permission_mode,
        cwd=None,
        stream=None,
        checkpoint_card_id=None,
        checkpoint_phase=None,
        checkpoint_attempt=1,
        resume_messages=None,
        phase=None,
    ):
        assert "satisfies the task requirement" in prompt
        assert "missing behavior for named configuration options" in prompt
        return "Severity: NONE"

    monkeypatch.setattr(store, "_run_agent_prompt", fake_run_agent_prompt)

    import asyncio

    step = asyncio.run(
        store._run_remote_code_review_step(
            card,
            12,
            policies=_remote_review_policy(),
            model="test-model",
        )
    )

    assert step.status == "success"


def test_remote_code_review_step_blocks_on_critical(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Review critical", body="review")

    monkeypatch.setattr(
        store,
        "_run_gh",
        lambda args, *, cwd=None, check=False: subprocess.CompletedProcess(
            args,
            0,
            stdout="diff --git a/a b/a",
            stderr="",
        ),
    )

    async def fake_run_agent_prompt(
        prompt,
        *,
        model,
        max_turns,
        permission_mode,
        cwd=None,
        stream=None,
        checkpoint_card_id=None,
        checkpoint_phase=None,
        checkpoint_attempt=1,
        resume_messages=None,
        phase=None,
    ):
        assert "Review GitHub PR #12" in prompt
        return "Severity: CRITICAL\nFindings:\n  - a.py:1 bug broken\nSummary: blocked"

    monkeypatch.setattr(store, "_run_agent_prompt", fake_run_agent_prompt)

    import asyncio

    step = asyncio.run(
        store._run_remote_code_review_step(
            card,
            12,
            policies=_remote_review_policy(),
            model="test-model",
        )
    )

    assert step.status == "failed"
    assert step.returncode == 1
    assert step.stderr == "severity=critical"


def test_remote_code_review_blocks_merge_and_sets_human_gate(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #88: Existing autopilot PR",
        body="open",
        source_ref="pr:88",
    )
    store.update_status(card.id, status="queued", metadata_updates={"attempt_count": 3})

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=1,
            status="failed",
            stderr="severity=critical",
        )

    merged = {"called": False}
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: merged.__setitem__("called", True),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    updated = store.get_card(card.id)

    assert result.status == "completed"
    assert merged["called"] is False
    assert updated is not None
    assert updated.metadata["human_gate_pending"] is True
    assert updated.metadata["remote_review_status"] == "failed"


def test_remote_code_review_error_routes_to_human_gate(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #89: Existing autopilot PR",
        body="open",
        source_ref="pr:89",
    )
    store.update_status(card.id, status="queued", metadata_updates={"attempt_count": 3})

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=2,
            status="error",
            stderr="gh pr diff failed",
        )

    merged = {"called": False}
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: merged.__setitem__("called", True),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    updated = store.get_card(card.id)

    assert result.status == "completed"
    assert merged["called"] is False
    assert updated is not None
    assert updated.metadata["human_gate_pending"] is True
    assert updated.metadata["remote_review_status"] == "error"


def test_existing_pr_remote_code_review_failure_repairs_when_attempts_remain(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #91: Existing autopilot PR",
        body="open",
        source_ref="pr:91",
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=1,
            status="failed",
            stderr="severity=critical",
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store._process_existing_pr_card(card, 91, _remote_review_policy()))
    updated = store.get_card(card.id)

    assert result.status == "queued"
    assert updated is not None
    assert updated.status == "queued"
    assert updated.metadata["human_gate_pending"] is False
    assert updated.metadata["autopilot_managed"] is True
    assert updated.metadata["attempt_count"] == 1
    assert updated.metadata["last_failure_stage"] == "remote_review_failed"
    assert updated.metadata["last_failure_summary"] == "severity=critical"


def test_pull_base_branch_called_after_merge(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #90: Existing autopilot PR",
        body="open",
        source_ref="pr:90",
    )

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    pulled = {"base_branch": None}
    installed = {"called": False}
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pull_base_branch",
        lambda self, *, base_branch: pulled.__setitem__("base_branch", base_branch),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._install_editable",
        lambda self: installed.__setitem__("called", True),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "merged"
    assert pulled["base_branch"] == "main"
    assert installed["called"] is True


def test_pull_base_branch_failure_is_non_fatal(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #91: Existing autopilot PR",
        body="open",
        source_ref="pr:91",
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    def fail_pull(self, *, base_branch: str):
        raise RuntimeError("not fast-forward")

    installed = {"called": False}

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pull_base_branch", fail_pull
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._install_editable",
        lambda self: installed.__setitem__("called", True),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    journal = (repo / ".openharness" / "autopilot" / "repo_journal.jsonl").read_text(
        encoding="utf-8"
    )

    assert result.status == "merged"
    assert "merge_warning" in journal
    assert "post-merge pull failed" in journal
    assert installed["called"] is False


def test_install_editable_failure_is_non_fatal(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #92: Existing autopilot PR",
        body="open",
        source_ref="pr:92",
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pull_base_branch",
        lambda self, *, base_branch: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._install_editable",
        lambda self: (_ for _ in ()).throw(RuntimeError("uv failed")),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    journal = (repo / ".openharness" / "autopilot" / "repo_journal.jsonl").read_text(
        encoding="utf-8"
    )

    assert result.status == "merged"
    assert "merge_warning" in journal
    assert "post-merge install failed" in journal


def test_list_cards_queued_before_merged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    card_merged, _ = store.enqueue_card(source_kind="manual_idea", title="old merged task", body="")
    store.update_status(card_merged.id, status="merged")

    store.enqueue_card(source_kind="manual_idea", title="new queued task", body="")

    cards = store.list_cards()
    statuses = [c.status for c in cards]

    assert statuses.index("queued") < statuses.index("merged")


def test_pull_base_branch_fetch_and_ff_only(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append((args, cwd, check))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    store._pull_base_branch(base_branch="main")

    assert calls == [
        (["fetch", "origin", "main"], repo, True),
        (["pull", "--ff-only", "origin", "main"], repo, True),
    ]


def test_default_rebase_strategy_is_on_conflict() -> None:
    assert _DEFAULT_AUTOPILOT_POLICY["execution"]["rebase_strategy"] == "on_conflict"


def test_rebase_none_skips_rebase(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="0", stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)
    store._sync_worktree_to_base(
        repo,
        base_branch="main",
        head_branch="autopilot/card",
        reset=False,
        rebase_strategy="none",
        card_id="card",
    )

    assert ["rebase", "origin/main"] not in calls
    assert calls == [["fetch", "origin", "main"], ["checkout", "autopilot/card"]]


def test_rebase_on_advance_rebases_when_base_ahead(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append(args)
        stdout = "1" if args[:2] == ["rev-list", "--count"] else ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)
    store._sync_worktree_to_base(
        repo,
        base_branch="main",
        head_branch="autopilot/card",
        reset=False,
        rebase_strategy="on_advance",
        card_id="card",
    )

    assert ["rebase", "origin/main"] in calls


def test_reset_worktree_prefers_remote_head_branch_when_present(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    store._sync_worktree_to_base(
        repo,
        base_branch="main",
        head_branch="autopilot/card",
        reset=True,
        rebase_strategy="on_conflict",
        card_id="card",
    )

    assert calls == [
        ["fetch", "origin", "main"],
        ["fetch", "origin", "autopilot/card"],
        ["checkout", "-B", "autopilot/card", "origin/autopilot/card"],
    ]


def test_reset_worktree_falls_back_to_base_when_remote_head_branch_missing(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append(args)
        if args == ["fetch", "origin", "autopilot/card"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="missing")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    store._sync_worktree_to_base(
        repo,
        base_branch="main",
        head_branch="autopilot/card",
        reset=True,
        rebase_strategy="on_conflict",
        card_id="card",
    )

    assert calls == [
        ["fetch", "origin", "main"],
        ["fetch", "origin", "autopilot/card"],
        ["checkout", "-B", "autopilot/card", "origin/main"],
    ]


def test_rebase_conflict_aborts_cleanly_and_journals(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append(args)
        if args == ["rebase", "origin/main"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="conflict")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    assert store._rebase_head_onto_base(repo, base_branch="main", card_id="card") is False

    entries = store.load_journal(limit=5)
    assert ["rebase", "--abort"] in calls
    assert entries[-1].kind == "rebase_conflict"
    assert entries[-1].metadata["non_fatal"] is True


def test_rebase_inflight_worktrees_strategy_none_skips_active_cards(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    active_wt = tmp_path / "active-wt"
    active_wt.mkdir()
    store = RepoAutopilotStore(repo)
    _, _ = store.enqueue_card(source_kind="manual_idea", title="Merged", body="done")
    active, _ = store.enqueue_card(source_kind="manual_idea", title="Active", body="work")
    store.update_status(
        active.id, status="running", metadata_updates={"worktree_path": str(active_wt)}
    )
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append((args, cwd))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    store.rebase_inflight_worktrees(base_branch="main", rebase_strategy="none")

    assert calls == []


def test_rebase_inflight_worktrees_updates_active_cards(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    active_wt = tmp_path / "active-wt"
    active_wt.mkdir()
    store = RepoAutopilotStore(repo)
    merged, _ = store.enqueue_card(source_kind="manual_idea", title="Merged", body="done")
    active, _ = store.enqueue_card(source_kind="manual_idea", title="Active", body="work")
    store.update_status(
        active.id, status="running", metadata_updates={"worktree_path": str(active_wt)}
    )
    calls = []

    def fake_run_git(args, *, cwd=None, check=False):
        calls.append((args, cwd))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    store.rebase_inflight_worktrees(base_branch="main", merged_card_id=merged.id)

    entries = store.load_journal(limit=10)
    assert (["fetch", "origin", "main"], active_wt) in calls
    assert (["rebase", "origin/main"], active_wt) in calls
    assert any(entry.kind == "rebase_done" and entry.task_id == active.id for entry in entries)

def test_journal_base_advance_for_active_cards(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    merged, _ = store.enqueue_card(source_kind="manual_idea", title="Merged", body="body")
    active, _ = store.enqueue_card(source_kind="manual_idea", title="Active", body="body")
    queued, _ = store.enqueue_card(source_kind="manual_idea", title="Queued", body="body")
    store.update_status(merged.id, status="merged")
    store.update_status(active.id, status="running")
    store.update_status(queued.id, status="queued")

    store._journal_base_advanced_for_active_cards(base_branch="main", merged_card_id=merged.id)

    entries = store.load_journal(limit=20)
    matches = [entry for entry in entries if entry.kind == "base_advanced"]
    assert len(matches) == 1
    assert matches[0].task_id == active.id
    assert matches[0].metadata == {"base_branch": "main", "status": "running", "merged_card_id": merged.id}


def test_base_advance_journals_notification(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    merged, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #90: Existing autopilot PR",
        body="open",
        source_ref="pr:90",
    )
    active, _ = store.enqueue_card(source_kind="manual_idea", title="Active follow-up", body="body")
    store.update_status(active.id, status="running")

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pull_base_branch",
        lambda self, *, base_branch: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._install_editable",
        lambda self: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(merged.id))
    entries = store.load_journal(limit=20)
    matches = [entry for entry in entries if entry.kind == "base_advanced" and entry.task_id == active.id]

    assert result.status == "merged"
    assert len(matches) == 1
    assert matches[0].metadata == {"base_branch": "main", "status": "running", "merged_card_id": merged.id}


def test_install_editable_runs_uv_sync_when_dependency_files_changed(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_command(command, *, cwd=None, timeout=None, shell=False, check=False):
        if command == ["git", "diff", "--name-only", "HEAD@{1}", "HEAD"]:
            assert cwd == repo
            assert timeout == 30
            return subprocess.CompletedProcess(command, 0, stdout="pyproject.toml\n", stderr="")
        calls.append((command, cwd, timeout, check))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_command", fake_run_command)

    store._install_editable()

    assert calls == [(["uv", "sync"], repo, 120, True)]


def test_install_editable_skips_uv_sync_when_dependency_files_unchanged(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_command(command, *, cwd=None, timeout=None, shell=False, check=False):
        if command == ["git", "diff", "--name-only", "HEAD@{1}", "HEAD"]:
            assert cwd == repo
            assert timeout == 30
            return subprocess.CompletedProcess(
                command, 0, stdout="src/openharness/autopilot/service.py\n", stderr=""
            )
        calls.append((command, cwd, timeout, check))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_command", fake_run_command)

    store._install_editable()

    assert calls == []


# ----------------------------------------------------------------------
# Main-checkout lock tests (P9.3)
# ----------------------------------------------------------------------


def _run_card_with_locked_pull(
    store: RepoAutopilotStore,
    monkeypatch,
    *,
    fake_lock_cls,
    pull_impl,
    install_impl,
):
    """Helper: drive run_card down the existing-PR auto-merge path that
    contains the main-checkout lock-protected _pull_base_branch and
    _install_editable call sites.
    """
    from openharness.autopilot import PreflightCheck

    # Mock preflight checks to pass (all non-fatal)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #500: Existing autopilot PR",
        body="open",
        source_ref="pr:500",
    )

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(
        self,
        card,
        pr_number,
        *,
        policies,
        model,
        base_branch="main",
        stream=None,
        checkpoint_attempt=1,
    ):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci",
        fake_wait_for_pr_ci,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pull_base_branch",
        pull_impl,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._install_editable",
        install_impl,
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoFileLock", fake_lock_cls)

    import asyncio

    return asyncio.run(store.run_card(card.id))


def test_pull_base_branch_acquires_lock(tmp_path: Path, monkeypatch) -> None:
    """The post-merge _pull_base_branch call site must acquire the main-checkout lock
    before pulling, and release it after."""
    from openharness.autopilot.locking import RepoFileLock as _OriginalLock

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    # Only track events for the main-checkout lock; delegate others to the real impl.
    main_events: list[tuple[str, object]] = []

    class RecordingLock:
        def __init__(self, lock_path, *, timeout=10.0):
            self._path = Path(lock_path)
            self._is_main = self._path.name == "main-checkout.lock"
            if self._is_main:
                main_events.append(("init", (self._path, timeout)))
            else:
                self._real = _OriginalLock(lock_path, timeout=timeout)

        def __enter__(self):
            if self._is_main:
                main_events.append(("enter", None))
                return self
            return self._real.__enter__()

        def __exit__(self, exc_type, exc, tb):
            if self._is_main:
                main_events.append(("exit", exc_type))
                return False
            return self._real.__exit__(exc_type, exc, tb)

    action_events: list[str] = []

    def fake_pull(self, *, base_branch):
        action_events.append("pull")

    def fake_install(self):
        action_events.append("install")

    result = _run_card_with_locked_pull(
        store,
        monkeypatch,
        fake_lock_cls=RecordingLock,
        pull_impl=fake_pull,
        install_impl=fake_install,
    )

    assert result.status == "merged"

    init_events = [e for e in main_events if e[0] == "init"]
    assert init_events, "RepoFileLock was never instantiated for main-checkout.lock"
    first_lock_path, first_timeout = init_events[0][1]
    assert first_lock_path.name == "main-checkout.lock"
    assert first_timeout == 60.0

    # We need to verify ordering: pull happens between enter/exit and install between enter/exit.
    # Since we can't easily interleave two event lists, rely on the invariant:
    # both pull and install must have happened, and there must be 2 enter/exit pairs.
    enters = [e for e in main_events if e[0] == "enter"]
    exits = [e for e in main_events if e[0] == "exit"]
    assert len(enters) == 2, (
        f"Expected 2 lock enters (one for pull, one for install), got {len(enters)}"
    )
    assert len(exits) == 2, f"Expected 2 lock exits, got {len(exits)}"
    assert action_events == ["pull", "install"], f"Expected pull then install, got {action_events}"


def test_pull_base_branch_releases_lock_on_error(tmp_path: Path, monkeypatch) -> None:
    """If _pull_base_branch raises, the main-checkout lock must still be released."""
    from openharness.autopilot.locking import RepoFileLock as _OriginalLock

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    enter_count = 0
    exit_count = 0
    saw_exception_in_exit = False

    class CheckingLock:
        def __init__(self, lock_path, *, timeout=10.0):
            self._path = Path(lock_path)
            self._is_main = self._path.name == "main-checkout.lock"
            if not self._is_main:
                self._real = _OriginalLock(lock_path, timeout=timeout)

        def __enter__(self):
            nonlocal enter_count
            if self._is_main:
                enter_count += 1
                return self
            return self._real.__enter__()

        def __exit__(self, exc_type, exc, tb):
            nonlocal exit_count, saw_exception_in_exit
            if self._is_main:
                exit_count += 1
                if exc_type is not None:
                    saw_exception_in_exit = True
                return False  # propagate exception
            return self._real.__exit__(exc_type, exc, tb)

    def fail_pull(self, *, base_branch):
        raise RuntimeError("not fast-forward")

    def fake_install(self):
        # Should not be called because pull failed.
        raise AssertionError("install_editable should not run when pull fails")

    result = _run_card_with_locked_pull(
        store,
        monkeypatch,
        fake_lock_cls=CheckingLock,
        pull_impl=fail_pull,
        install_impl=fake_install,
    )

    journal = (repo / ".openharness" / "autopilot" / "repo_journal.jsonl").read_text(
        encoding="utf-8"
    )

    assert result.status == "merged"
    assert "post-merge pull failed" in journal
    # Exactly one enter/exit pair around the failing pull (install was skipped).
    assert enter_count == 1
    assert exit_count == 1
    assert saw_exception_in_exit, "Lock __exit__ must observe the propagating exception"


def test_concurrent_pull_serialized(tmp_path: Path) -> None:
    """Two threads acquiring the production main-checkout lock must be serialized."""
    from openharness.autopilot.locking import RepoFileLock

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    active = threading.Lock()
    overlap_detected = False
    completion_order: list[int] = []

    def worker(worker_id: int) -> None:
        nonlocal overlap_detected
        with RepoFileLock(store._main_checkout_lock_path, timeout=60.0):
            if not active.acquire(blocking=False):
                overlap_detected = True
                return
            try:
                # Hold the lock long enough for the other thread to attempt acquire.
                time.sleep(0.1)
                completion_order.append(worker_id)
            finally:
                active.release()

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    started = time.monotonic()
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    elapsed = time.monotonic() - started

    assert not overlap_detected, "Two threads entered the critical section concurrently"
    assert sorted(completion_order) == [1, 2], f"Both workers must complete, got {completion_order}"
    # Two non-overlapping 0.1s holds should take at least ~0.18s in aggregate.
    assert elapsed >= 0.18, f"Lock did not actually serialize work (elapsed={elapsed:.3f}s)"


# ----------------------------------------------------------------------
# Per-card model field tests
# ----------------------------------------------------------------------


def test_card_model_default_none(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, created = store.enqueue_card(
        source_kind="manual_idea",
        title="Test card model default",
        body="body",
    )
    assert created is True
    assert card.model is None
    reloaded = store.get_card(card.id)
    assert reloaded is not None
    assert reloaded.model is None


def test_card_model_overrides_policy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Use haiku model",
        body="override test",
        model="claude-haiku-4-5",
    )
    assert card.model == "claude-haiku-4-5"

    reloaded = store.get_card(card.id)
    assert reloaded is not None
    assert reloaded.model == "claude-haiku-4-5"


def test_card_model_none_falls_back_to_policy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    # Override policy with a custom default_model
    from openharness.config.paths import get_project_autopilot_policy_path

    policy_path = get_project_autopilot_policy_path(repo)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        "execution:\n"
        '  default_model: "oc-default-model"\n'
        "  max_turns: 12\n"
        "  permission_mode: full_auto\n"
        "  host_mode: self_hosted\n"
        "  use_worktree: false\n"
        "  base_branch: main\n"
        "  max_attempts: 3\n",
        encoding="utf-8",
    )

    # Enqueue card without model
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Use policy default",
        body="fallback test",
    )
    assert card.model is None

    # Verify that when run_card is called, it falls back to policy default
    # We mock run_agent_prompt to capture the model argument
    used_models = []

    async def capture_model_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        used_models.append(model)
        return "done"

    store._run_agent_prompt = MethodType(capture_model_prompt, store)

    # Mock preflight model check so preflight passes (warn is transient -> pending)
    from openharness.autopilot import PreflightCheck

    store._check_cwd_exists = lambda: PreflightCheck(name="cwd_exists", status="ok", reason="ok")
    store._check_model_available = lambda m: PreflightCheck(name="model_available", status="ok", reason="ok")
    store._check_auth_status = lambda: PreflightCheck(name="auth_ok", status="ok", reason="ok")
    store._check_github_available = lambda: PreflightCheck(name="github_available", status="ok", reason="ok")

    def fake_verification(self, policies, *, cwd=None):
        return [
            RepoVerificationStep(
                command="uv run pytest -q",
                returncode=0,
                status="success",
                stdout="1 passed",
            )
        ]

    store._run_verification_steps = MethodType(fake_verification, store)

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    assert result.status == "completed"
    # The effective model should have fallen back to policy default
    assert used_models[0] == "oc-default-model"


def test_update_card_model(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Update model test",
        body="body",
    )
    assert card.model is None

    updated = store.update_card_model(card.id, "claude-haiku-4-5")
    assert updated.model == "claude-haiku-4-5"

    reloaded = store.get_card(card.id)
    assert reloaded is not None
    assert reloaded.model == "claude-haiku-4-5"

    updated2 = store.update_card_model(card.id, None)
    assert updated2.model is None


def test_registry_backward_compat_model_field(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    from openharness.config.paths import get_project_autopilot_registry_path

    registry_path = get_project_autopilot_registry_path(repo)
    registry_path.write_text(
        '{"version":1,"updated_at":0.0,"cards":[\n'
        "  {\n"
        '    "id":"ap-oldcard1",\n'
        '    "fingerprint":"f1","title":"Old card","body":"",\n'
        '    "source_kind":"manual_idea","source_ref":"","status":"queued",\n'
        '    "score":0,"score_reasons":[],"labels":[],"metadata":{},\n'
        '    "created_at":1000.0,"updated_at":1000.0\n'
        "  }\n"
        "]}",
        encoding="utf-8",
    )

    store = RepoAutopilotStore(repo)
    loaded = store._load_registry()
    assert len(loaded.cards) == 1
    old_card = loaded.cards[0]
    assert old_card.id == "ap-oldcard1"
    assert old_card.model is None

    new_card, created = store.enqueue_card(
        source_kind="manual_idea",
        title="New card after old registry",
        body="new",
        model="claude-sonnet",
    )
    assert created is True
    assert new_card.model == "claude-sonnet"


def test_card_model_precedes_policy_agent_model(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Use card model",
        body="override test",
        model="card-model",
    )
    used_models: list[str | None] = []

    async def fake_run_agent_prompt(
        self, prompt, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        used_models.append(model)
        return "Implemented the change and ran targeted checks."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        return [
            RepoVerificationStep(
                command="uv run pytest -q",
                returncode=0,
                status="success",
                stdout="1 passed",
            )
        ]

    # Mock preflight checks to pass
    monkeypatch.setattr(RepoAutopilotStore, "_check_cwd_exists", lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"))
    monkeypatch.setattr(RepoAutopilotStore, "_check_model_available", lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"))
    monkeypatch.setattr(RepoAutopilotStore, "_check_auth_status", lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"))
    monkeypatch.setattr(RepoAutopilotStore, "_check_github_available", lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"))
    monkeypatch.setattr(RepoAutopilotStore, "_check_git_repo", lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"))
    monkeypatch.setattr(RepoAutopilotStore, "_run_agent_prompt", fake_run_agent_prompt)
    monkeypatch.setattr(RepoAutopilotStore, "_run_verification_steps", fake_run_verification_steps)

    import asyncio

    result = asyncio.run(store.run_card(card.id, model=None))
    assert result.status == "completed"
    assert used_models[0] == "card-model"


# ---------------------------------------------------------------------------
# Branch-sync tests
# ---------------------------------------------------------------------------

_FAKE_WORKTREE_SLUG = "wt"


def _fake_run_card_common_patches(monkeypatch, *, worktree: Path) -> None:
    """Patch the shared boilerplate needed for run_card to reach the push step."""

    async def fake_create_worktree(self, repo_path, slug, branch=None, agent_id=None):
        return SimpleNamespace(path=worktree)

    async def fake_remove_worktree(self, slug):
        return True

    async def fake_run_agent_prompt(
        self, prompt, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        return "Implemented changes."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        return [RepoVerificationStep(command="uv run pytest -q", returncode=0, status="success")]

    # Mock preflight checks to pass
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        fake_run_verification_steps,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_commit_all",
        lambda self, cwd, message: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )


def test_branch_sync_runs_before_push(tmp_path: Path, monkeypatch) -> None:
    """_push_pr_branch_with_sync must be called before _upsert_pull_request."""
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Sync before push", body="")

    call_order: list[str] = []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        lambda self, cwd, *, base_branch, head_branch, policies, card_id=None: (
            call_order.append("sync") or (True, "branch_push_done", f"Pushed {head_branch}.")
        ),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: (
            call_order.append("upsert") or {"number": 1, "url": "https://example/pr/1"}
        ),
    )

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        return (
            "success",
            "ok",
            {"url": "https://example/pr/1", "labels": [], "isDraft": False},
            [],
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    _fake_run_card_common_patches(monkeypatch, worktree=worktree)

    result = asyncio.run(store.run_card(card.id))
    assert result.status == "completed"
    assert call_order == ["sync", "upsert"], f"unexpected order: {call_order}"


def test_branch_sync_non_fast_forward_retry_succeeds_without_rebase_when_branch_is_current(
    tmp_path: Path, monkeypatch
) -> None:
    """If push is rejected with non-fast-forward, sync retries without rebasing an already-current branch."""
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="NFF retry", body="")

    fetch_calls: list[str] = []
    push_calls: list[int] = []
    remote_rebases: list[str] = []

    def fake_run_git(self, args, *, cwd=None, check=False):
        import subprocess as sp

        result = sp.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ["push", "-u"]:
            push_calls.append(1)
            if len(push_calls) == 1:
                result = sp.CompletedProcess(args, 1, stdout="", stderr="non-fast-forward")
                if check:
                    raise RuntimeError("non-fast-forward")
        elif args[0] == "fetch":
            fetch_calls.append(args[-1])
        return result

    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git)

    # Use real _push_pr_branch_with_sync / _sync_pr_branch_before_push but mock rebase
    def fake_rebase(self, cwd, *, base_branch, card_id=None):
        return True

    def fake_remote_rebase(self, cwd, *, remote_branch, card_id=None):
        remote_rebases.append(remote_branch)
        return True

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_base", fake_rebase
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_remote_branch",
        fake_remote_rebase,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 5,
            "url": "https://example/pr/5",
        },
    )

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        return (
            "success",
            "ok",
            {"url": "https://example/pr/5", "labels": [], "isDraft": False},
            [],
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    _fake_run_card_common_patches(monkeypatch, worktree=worktree)
    # Override _sync_worktree_to_base to be a no-op AND _run_git above handles fetch/push.
    # _push_pr_branch_with_sync calls _git_push_branch which calls _run_git.
    # The second _run_git push call must succeed (returncode 0).

    result = asyncio.run(store.run_card(card.id))
    assert result.status == "completed"
    assert len(push_calls) >= 2, f"expected at least 2 push attempts, got {push_calls}"
    assert fetch_calls.count("main") >= 2
    assert fetch_calls.count(f"autopilot/{card.id}") >= 2
    assert remote_rebases == []


def test_branch_sync_conflict_continues_repair_loop(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Conflict repair", body="")

    agent_runs = 0
    push_attempts = 0

    async def fake_run_agent_prompt(
        self, prompt, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        nonlocal agent_runs
        agent_runs += 1
        return "Implemented changes."

    def fake_push(self, cwd, *, base_branch, head_branch, policies, card_id=None):
        nonlocal push_attempts
        push_attempts += 1
        if push_attempts == 1:
            return False, "branch_sync_conflict", (
                f"Could not rebase {head_branch} onto origin/{base_branch}."
            )
        return True, "branch_push_done", f"Pushed {head_branch}."

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        fake_push,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt",
        fake_run_agent_prompt,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 1,
            "url": "https://example/pr/1",
        },
    )

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        return (
            "success",
            "ok",
            {"url": "https://example/pr/1", "labels": [], "isDraft": False},
            [],
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    _fake_run_card_common_patches(monkeypatch, worktree=worktree)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt",
        fake_run_agent_prompt,
    )

    result = asyncio.run(store.run_card(card.id))
    assert result.status == "completed"
    assert agent_runs == 2
    assert push_attempts == 2
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.metadata.get("manual_intervention_required") is False
    assert updated.metadata.get("last_failure_stage") == "branch_sync_conflict"


# ---------------------------------------------------------------------------
# Cherry-pick reset tests
# ---------------------------------------------------------------------------


def test_cherry_pick_reset_triggers_after_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    """_sync_pr_branch_before_push calls _cherry_pick_reset_pr_branch once repeated_failure_count >= 2."""
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = tmp_path / "wt"
    cwd.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Cherry reset", body="")
    head_branch = f"autopilot/{card.id}"
    expected_summary = f"Could not rebase {head_branch} onto origin/main."
    store.update_status(
        card.id,
        status="queued",
        note="prior conflict",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 99,
            "repeated_failure_key": f"branch_sync_conflict:{expected_summary}",
            "repeated_failure_count": 2,
        },
    )

    cherry_pick_called: list[bool] = []

    def fake_cherry_pick_reset(self, cwd, *, base_branch, head_branch, card_id=None):
        cherry_pick_called.append(True)
        return True, "branch_sync_done", f"cherry-pick reset done for {head_branch}"

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._cherry_pick_reset_pr_branch",
        fake_cherry_pick_reset,
    )

    def fake_run_git(self, args, *, cwd=None, check=False):
        if args and args[0] == "rebase":
            result = sp.CompletedProcess(args, 1, stdout="", stderr="conflict")
            if check:
                raise RuntimeError("conflict")
            return result
        if args and args[0] == "rev-list" and "--count" in args:
            # Make base branch appear advanced so rebase is triggered
            return sp.CompletedProcess(args, 0, stdout="1", stderr="")
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git
    )

    policies: dict = {}
    ok, stage, _ = store._sync_pr_branch_before_push(
        cwd,
        base_branch="main",
        head_branch=head_branch,
        policies=policies,
        card_id=card.id,
    )

    assert ok is True
    assert stage == "branch_sync_done"
    assert cherry_pick_called


def _make_cherry_pick_reset_store(
    tmp_path: Path,
) -> "tuple[RepoAutopilotStore, RepoTaskCard]":
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="CPR card", body="")
    store.update_status(
        card.id,
        status="queued",
        note="",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 7,
            "repeated_failure_key": "branch_sync_conflict:Could not rebase autopilot/CPR card onto origin/main.",
            "repeated_failure_count": 2,
        },
    )
    return store, store.get_card(card.id)  # type: ignore[return-value]


def _fake_run_git_cherry_pick(
    commits: list[str],
    *,
    fail_sha: str | None = None,
    log_rc: int = 0,
    pushes: list[str] | None = None,
):
    import subprocess as sp

    if pushes is None:
        pushes = []

    def _fake(self, args, *, cwd=None, check=False):
        if args[0] == "log":
            stdout = "\n".join(commits) if commits else ""
            return sp.CompletedProcess(args, log_rc, stdout=stdout, stderr="")
        if args[0] == "reset":
            return sp.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "cherry-pick" and args[1] != "--abort":
            sha = args[1]
            if sha == fail_sha:
                return sp.CompletedProcess(args, 1, stdout="", stderr="conflict")
            return sp.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "cherry-pick" and args[1] == "--abort":
            return sp.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ["push", "-u"]:
            pushes.append(str(args))
            if check:
                return None
            return sp.CompletedProcess(args, 0, stdout="", stderr="")
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    return _fake


def test_cherry_pick_reset_success_journals_done(tmp_path: Path, monkeypatch) -> None:
    """_cherry_pick_reset_pr_branch returns branch_sync_done and journals cherry_pick_reset_done."""
    store, card = _make_cherry_pick_reset_store(tmp_path)
    pushes: list[str] = []
    commits = ["aaa111", "bbb222"]

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_git",
        _fake_run_git_cherry_pick(commits, pushes=pushes),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch",
        lambda self, cwd, branch, *, force_with_lease=False: pushes.append(f"push:{force_with_lease}"),
    )

    cwd = tmp_path / "wt"
    cwd.mkdir()
    ok, stage, summary = store._cherry_pick_reset_pr_branch(
        cwd, base_branch="main", head_branch="autopilot/cpr", card_id=card.id
    )

    assert ok is True
    assert stage == "branch_sync_done"
    assert "cherry-pick reset" in summary
    assert pushes == ["push:True"]

    journals = [
        e for e in store.load_journal(limit=50)
        if e.kind == "cherry_pick_reset_done" and e.task_id == card.id
    ]
    assert journals, "expected cherry_pick_reset_done journal entry"


def test_cherry_pick_reset_conflict_returns_branch_sync_failed(
    tmp_path: Path, monkeypatch
) -> None:
    """When cherry-pick conflicts, returns (False, 'branch_sync_failed', ...) — no further loop."""
    store, card = _make_cherry_pick_reset_store(tmp_path)
    commits = ["aaa111", "bbb222"]

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_git",
        _fake_run_git_cherry_pick(commits, fail_sha="aaa111"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch",
        lambda self, cwd, branch, *, force_with_lease=False: None,
    )

    cwd = tmp_path / "wt"
    cwd.mkdir()
    ok, stage, summary = store._cherry_pick_reset_pr_branch(
        cwd, base_branch="main", head_branch="autopilot/cpr", card_id=card.id
    )

    assert ok is False
    assert stage == "branch_sync_failed"
    assert "manual repair" in summary

    journals = [
        e for e in store.load_journal(limit=50)
        if e.kind == "cherry_pick_reset_failed" and e.task_id == card.id
    ]
    assert journals


def test_cherry_pick_reset_not_triggered_below_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    """With repeated_failure_count=1, threshold=2 — cherry-pick NOT triggered."""
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = tmp_path / "wt"
    cwd.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Below threshold", body="")
    head_branch = f"autopilot/{card.id}"
    expected_summary = f"Could not rebase {head_branch} onto origin/main."
    store.update_status(
        card.id,
        status="queued",
        note="",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 5,
            "repeated_failure_key": f"branch_sync_conflict:{expected_summary}",
            "repeated_failure_count": 0,  # first failure → computed count=1, below threshold=2
        },
    )

    cherry_called: list[bool] = []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._cherry_pick_reset_pr_branch",
        lambda self, *a, **kw: cherry_called.append(True) or (True, "branch_sync_done", ""),
    )

    def fake_run_git(self, args, *, cwd=None, check=False):
        if args and args[0] == "rebase":
            result = sp.CompletedProcess(args, 1, stdout="", stderr="conflict")
            if check:
                raise RuntimeError("conflict")
            return result
        if args and args[0] == "rev-list" and "--count" in args:
            return sp.CompletedProcess(args, 0, stdout="1", stderr="")
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git
    )

    ok, stage, _ = store._sync_pr_branch_before_push(
        cwd,
        base_branch="main",
        head_branch=head_branch,
        policies={},
        card_id=card.id,
    )

    assert ok is False
    assert stage == "branch_sync_conflict"
    assert not cherry_called


def test_cherry_pick_reset_not_triggered_for_non_managed_card(
    tmp_path: Path, monkeypatch
) -> None:
    """Non-autopilot-managed card: cherry-pick reset never triggered."""
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = tmp_path / "wt"
    cwd.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Unmanaged", body="")
    store.update_status(
        card.id,
        status="queued",
        note="",
        metadata_updates={"repeated_failure_count": 5},
    )

    cherry_called: list[bool] = []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._cherry_pick_reset_pr_branch",
        lambda self, *a, **kw: cherry_called.append(True) or (True, "branch_sync_done", ""),
    )

    def fake_run_git(self, args, *, cwd=None, check=False):
        if args and args[0] == "rebase":
            result = sp.CompletedProcess(args, 1, stdout="", stderr="conflict")
            if check:
                raise RuntimeError("conflict")
            return result
        if args and args[0] == "rev-list" and "--count" in args:
            return sp.CompletedProcess(args, 0, stdout="1", stderr="")
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git
    )

    ok, stage, _ = store._sync_pr_branch_before_push(
        cwd,
        base_branch="main",
        head_branch=f"autopilot/{card.id}",
        policies={},
        card_id=card.id,
    )

    assert ok is False
    assert stage == "branch_sync_conflict"
    assert not cherry_called


def test_cherry_pick_reset_empty_commits_resets_and_force_pushes(
    tmp_path: Path, monkeypatch
) -> None:
    """With no unique commits, _cherry_pick_reset_pr_branch resets to base and force-pushes."""
    store, card = _make_cherry_pick_reset_store(tmp_path)
    pushes: list[str] = []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_git",
        _fake_run_git_cherry_pick([], pushes=pushes),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch",
        lambda self, cwd, branch, *, force_with_lease=False: pushes.append(f"push:{force_with_lease}"),
    )

    cwd = tmp_path / "wt"
    cwd.mkdir()
    ok, stage, summary = store._cherry_pick_reset_pr_branch(
        cwd, base_branch="main", head_branch="autopilot/cpr", card_id=card.id
    )

    assert ok is True
    assert stage == "branch_sync_done"
    assert pushes == ["push:True"]


def test_branch_sync_skips_rebase_when_remote_branch_and_base_are_current(
    tmp_path: Path, monkeypatch
) -> None:
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    worktree = tmp_path / "wt"
    worktree.mkdir()

    remote_rebases: list[str] = []
    base_rebases: list[str] = []

    def fake_run_git(self, args, *, cwd=None, check=False):
        command = tuple(args)
        if command[:2] == ("checkout", "autopilot/ap-test"):
            return sp.CompletedProcess(args, 0, stdout="", stderr="")
        if command[:3] == ("fetch", "origin", "main"):
            return sp.CompletedProcess(args, 0, stdout="", stderr="")
        if command[:3] == ("fetch", "origin", "autopilot/ap-test"):
            return sp.CompletedProcess(args, 0, stdout="", stderr="")
        if command[:3] == ("rev-list", "--count", "origin/autopilot/ap-test..HEAD"):
            return sp.CompletedProcess(args, 0, stdout="0\n", stderr="")
        if command[:3] == ("rev-list", "--count", "HEAD..origin/autopilot/ap-test"):
            return sp.CompletedProcess(args, 0, stdout="0\n", stderr="")
        if command[:3] == ("rev-list", "--count", "HEAD..origin/main"):
            return sp.CompletedProcess(args, 0, stdout="0\n", stderr="")
        raise AssertionError(f"unexpected git command: {args}")

    def fake_remote_rebase(self, cwd, *, remote_branch, card_id=None):
        remote_rebases.append(remote_branch)
        return True

    def fake_base_rebase(self, cwd, *, base_branch, card_id=None):
        base_rebases.append(base_branch)
        return True

    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_remote_branch",
        fake_remote_rebase,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_base",
        fake_base_rebase,
    )

    ok, stage, summary = store._sync_pr_branch_before_push(
        worktree,
        base_branch="main",
        head_branch="autopilot/ap-test",
        policies=store.load_policies(),
        card_id=None,
    )

    assert ok is True
    assert stage == "branch_sync_done"
    assert summary == "Synced autopilot/ap-test onto origin/main."
    assert remote_rebases == []
    assert base_rebases == []


def test_branch_sync_no_force_push_by_default(tmp_path: Path, monkeypatch) -> None:
    """With default policy, --force and --force-with-lease are never used in _git_push_branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    force_used: list[bool] = []

    def fake_git_push_branch(self, cwd, branch, *, force_with_lease: bool = False):
        force_used.append(force_with_lease)

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch", fake_git_push_branch
    )

    # Verify the default policy has allow_force_push_pr_branch == False
    policies = store.load_policies()
    assert store._allow_force_push_pr_branch(policies) is False

    # Simulate push_pr_branch_with_sync with successful sync so no force path is taken
    def fake_rebase(self, cwd, *, base_branch, card_id=None):
        return True

    def fake_run_git(self, args, *, cwd=None, check=False):
        import subprocess as sp

        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_base", fake_rebase
    )

    worktree = tmp_path / "wt"
    worktree.mkdir()
    ok, stage, summary = store._push_pr_branch_with_sync(
        worktree,
        base_branch="main",
        head_branch="autopilot/ap-test",
        policies=policies,
        card_id=None,
    )
    assert ok is True
    assert all(not f for f in force_used), f"force_with_lease was used: {force_used}"


def test_branch_sync_force_with_lease_when_policy_allows(tmp_path: Path, monkeypatch) -> None:
    """With allow_force_push_pr_branch=True, --force-with-lease is used after retry failure."""
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    force_used: list[bool] = []
    push_attempt: list[int] = []

    def fake_git_push_branch(self, cwd, branch, *, force_with_lease: bool = False):
        force_used.append(force_with_lease)
        push_attempt.append(1)
        if len(push_attempt) <= 2:
            raise RuntimeError("non-fast-forward")

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch", fake_git_push_branch
    )

    def fake_rebase(self, cwd, *, base_branch, card_id=None):
        return True

    def fake_run_git(self, args, *, cwd=None, check=False):
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_base", fake_rebase
    )

    policies = store.load_policies()
    policies["autopilot"]["execution"]["allow_force_push_pr_branch"] = True

    worktree = tmp_path / "wt"
    worktree.mkdir()
    ok, stage, summary = store._push_pr_branch_with_sync(
        worktree,
        base_branch="main",
        head_branch="autopilot/ap-force",
        policies=policies,
        card_id=None,
    )
    assert ok is True
    assert stage == "branch_force_push_done"
    assert any(f for f in force_used), "expected --force-with-lease to have been used"


def test_branch_sync_force_with_lease_for_autopilot_managed_pr_branch(
    tmp_path: Path, monkeypatch
) -> None:
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Managed PR", body="")
    store.update_status(
        card.id,
        status="repairing",
        metadata_updates={"autopilot_managed": True, "linked_pr_number": 97},
    )

    force_used: list[bool] = []
    push_attempt: list[int] = []

    def fake_git_push_branch(self, cwd, branch, *, force_with_lease: bool = False):
        force_used.append(force_with_lease)
        push_attempt.append(1)
        if len(push_attempt) <= 2:
            raise RuntimeError("non-fast-forward")

    def fake_run_git(self, args, *, cwd=None, check=False):
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_rebase(self, cwd, *, base_branch, card_id=None):
        return True

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch", fake_git_push_branch
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_base", fake_rebase
    )

    worktree = tmp_path / "wt"
    worktree.mkdir()
    ok, stage, summary = store._push_pr_branch_with_sync(
        worktree,
        base_branch="main",
        head_branch=f"autopilot/{card.id}",
        policies=store.load_policies(),
        card_id=card.id,
    )

    assert ok is True
    assert stage == "branch_force_push_done"
    assert force_used == [False, False, True]


def test_branch_sync_does_not_force_for_unmanaged_branch(tmp_path: Path, monkeypatch) -> None:
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Unmanaged PR", body="")
    store.update_status(
        card.id,
        status="repairing",
        metadata_updates={"autopilot_managed": False, "linked_pr_number": 97},
    )

    force_used: list[bool] = []
    push_attempt: list[int] = []

    def fake_git_push_branch(self, cwd, branch, *, force_with_lease: bool = False):
        force_used.append(force_with_lease)
        push_attempt.append(1)
        raise RuntimeError("non-fast-forward")

    def fake_run_git(self, args, *, cwd=None, check=False):
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_rebase(self, cwd, *, base_branch, card_id=None):
        return True

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch", fake_git_push_branch
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_base", fake_rebase
    )

    worktree = tmp_path / "wt"
    worktree.mkdir()
    ok, stage, summary = store._push_pr_branch_with_sync(
        worktree,
        base_branch="main",
        head_branch=f"autopilot/{card.id}",
        policies=store.load_policies(),
        card_id=card.id,
    )

    assert ok is False
    assert stage == "branch_push_rejected"
    assert force_used == [False, False]


def test_branch_sync_force_policy_does_not_force_on_other_retry_errors(
    tmp_path: Path, monkeypatch
) -> None:
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    force_used: list[bool] = []
    push_attempt: list[int] = []

    def fake_git_push_branch(self, cwd, branch, *, force_with_lease: bool = False):
        force_used.append(force_with_lease)
        push_attempt.append(1)
        if len(push_attempt) == 1:
            raise RuntimeError("non-fast-forward")
        raise RuntimeError("remote hook declined")

    def fake_rebase(self, cwd, *, base_branch, card_id=None):
        return True

    def fake_run_git(self, args, *, cwd=None, check=False):
        return sp.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch", fake_git_push_branch
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_git", fake_run_git)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._rebase_head_onto_base", fake_rebase
    )

    policies = store.load_policies()
    policies["autopilot"]["execution"]["allow_force_push_pr_branch"] = True

    worktree = tmp_path / "wt"
    worktree.mkdir()
    ok, stage, summary = store._push_pr_branch_with_sync(
        worktree,
        base_branch="main",
        head_branch="autopilot/ap-force",
        policies=policies,
        card_id=None,
    )
    assert ok is False
    assert stage == "branch_push_failed"
    assert "remote hook declined" in summary
    assert all(not force for force in force_used)


def test_existing_pr_card_conflicting_branch_passes_through_ci(tmp_path: Path, monkeypatch) -> None:
    """_process_existing_pr_card with a green CI moves to completed with human_gate_pending."""
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    sync_cwd = tmp_path / "worktrees" / "card-42"
    sync_cwd.mkdir(parents=True)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #42: existing PR",
        body="",
        source_ref="pr:42",
        metadata={
            "linked_pr_number": 42,
            "head_branch": "autopilot/pr-42",
            "worktree_path": str(sync_cwd),
        },
    )
    call_order: list[str] = []

    def fake_push_pr_branch_with_sync(
        self, cwd, *, base_branch, head_branch, policies, card_id=None
    ):
        call_order.append("sync")
        assert cwd == sync_cwd
        assert base_branch == "main"
        assert head_branch == "autopilot/pr-42"
        assert card_id == card.id
        return True, "branch_push_done", "Pushed autopilot/pr-42."

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        call_order.append("ci")
        return (
            "success",
            "All remote checks passed.",
            {"url": "https://example/pr/42", "labels": [], "isDraft": False},
            [],
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_same_git_common_dir",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        fake_push_pr_branch_with_sync,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    # Mock _check_github_available to return ok status
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="GitHub CLI authenticated"),
    )

    result = asyncio.run(store.run_card(card.id))
    assert result.status == "completed"
    assert result.pr_number == 42
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.metadata.get("human_gate_pending") is True
    assert call_order == ["sync", "ci"]


def test_repair_exhausted_managed_pr_card_passes_through_ci(
    tmp_path: Path, monkeypatch
) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    sync_cwd = tmp_path / "worktrees" / "card-42"
    sync_cwd.mkdir(parents=True)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="Managed PR repair exhausted",
        body="",
        source_ref="pr:42",
        metadata={
            "autopilot_managed": True,
            "last_failure_stage": "repair_exhausted",
            "attempt_count": 3,
            "linked_pr_number": 42,
            "head_branch": "autopilot/card-42",
            "worktree_path": str(sync_cwd),
        },
    )
    store.update_status(card.id, status="failed", note="repair rounds exhausted")
    call_order: list[str] = []

    def fake_push_pr_branch_with_sync(
        self, cwd, *, base_branch, head_branch, policies, card_id=None
    ):
        call_order.append("sync")
        assert cwd == sync_cwd
        assert head_branch == "autopilot/card-42"
        assert card_id == card.id
        return True, "branch_push_done", "Pushed autopilot/card-42."

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        call_order.append("ci")
        return (
            "success",
            "All remote checks passed.",
            {"url": "https://example/pr/42", "labels": [], "isDraft": False},
            [],
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_same_git_common_dir",
        lambda self, cwd: True,
    )

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        fake_push_pr_branch_with_sync,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {"state": "OPEN", "url": "https://example/pr/42"},
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    # Mock _current_repo_full_name to avoid real git/gh calls
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._current_repo_full_name",
        lambda self: "test-owner/test-repo",
    )

    # Mock _pr_status_snapshot to return a green PR
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {
            "state": "open",
            "url": "https://example/pr/42",
            "labels": [],
            "isDraft": False,
        },
    )

    # Mock _run_verification_steps to avoid git worktree add in baseline check
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        lambda self, *args, **kwargs: [],
    )

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "completed"
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.metadata.get("human_gate_pending") is True
    assert call_order == ["sync", "ci"]


def test_repeated_failure_metadata_increments_for_same_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Repeat", body="")

    first = store._failure_repeat_metadata(
        card, stage="no_changes", summary="Agent produced no code changes to commit."
    )
    store.update_status(card.id, status="repairing", metadata_updates=first)
    updated = store.get_card(card.id)
    assert updated is not None

    second = store._failure_repeat_metadata(
        updated, stage="no_changes", summary="Agent produced no code changes to commit."
    )

    assert first["repeated_failure_count"] == 1
    assert second["repeated_failure_count"] == 2


def test_repeated_failure_metadata_resets_for_different_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Repeat",
        body="",
        metadata={
            "repeated_failure_key": "remote_ci_failed:test/check=failure",
            "repeated_failure_count": 2,
        },
    )

    repeat_meta = store._failure_repeat_metadata(
        card, stage="no_changes", summary="Agent produced no code changes to commit."
    )

    assert repeat_meta["repeated_failure_count"] == 1


def test_local_verification_failure_repeat_metadata_increments(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    summary = "agent:code-reviewer (diff vs main) rc=1"
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Repeat", body="")

    first = store._failure_repeat_metadata(
        card, stage="local_verification_failed", summary=summary
    )
    store.update_status(card.id, status="repairing", metadata_updates=first)
    updated = store.get_card(card.id)
    assert updated is not None

    second = store._failure_repeat_metadata(
        updated, stage="local_verification_failed", summary=summary
    )

    assert first["repeated_failure_count"] == 1
    assert second["repeated_failure_count"] == 2


def test_local_verification_failure_repeat_metadata_resets_for_new_summary(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Repeat",
        body="",
        metadata={
            "repeated_failure_key": "local_verification_failed:agent:code-reviewer rc=1",
            "repeated_failure_count": 2,
        },
    )

    repeat_meta = store._failure_repeat_metadata(
        card,
        stage="local_verification_failed",
        summary="agent:code-reviewer (diff vs main) rc=2",
    )

    assert repeat_meta["repeated_failure_count"] == 1


def test_max_attempts_clamps_unlimited_policy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    attempts = store._max_attempts(
        {"autopilot": {"execution": {"max_attempts": 0}, "repair": {"max_rounds": 0}}}
    )

    assert attempts == 50


def test_existing_pr_card_ci_fail_retries_when_repair_rounds_unlimited(
    tmp_path: Path, monkeypatch
) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    sync_cwd = tmp_path / "worktrees" / "card-42"
    sync_cwd.mkdir(parents=True)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #42: existing PR",
        body="",
        source_ref="pr:42",
        metadata={
            "attempt_count": 1,
            "linked_pr_number": 42,
            "head_branch": "autopilot/pr-42",
            "worktree_path": str(sync_cwd),
        },
    )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_same_git_common_dir",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        lambda self, cwd, *, base_branch, head_branch, policies, card_id=None: (
            True,
            "branch_push_done",
            "Pushed.",
        ),
    )

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        return "failed", "same check failed", {"url": "https://example/pr/42"}, []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )

    result = asyncio.run(
        store._process_existing_pr_card(
            card,
            42,
            _remote_review_policy(
                repair={"max_rounds": 0, "max_repeated_failure_attempts": 3}
            ),
        )
    )

    assert result.status == "queued"
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "queued"
    assert updated.metadata.get("repeated_failure_count") == 1


def test_existing_pr_card_ci_fail_stops_after_repeated_same_failure(
    tmp_path: Path, monkeypatch
) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    sync_cwd = tmp_path / "worktrees" / "card-42"
    sync_cwd.mkdir(parents=True)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #42: existing PR",
        body="",
        source_ref="pr:42",
        metadata={
            "attempt_count": 99,
            "linked_pr_number": 42,
            "head_branch": "autopilot/pr-42",
            "worktree_path": str(sync_cwd),
            "repeated_failure_key": "remote_ci_failed:same check failed",
            "repeated_failure_count": 2,
        },
    )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_same_git_common_dir",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        lambda self, cwd, *, base_branch, head_branch, policies, card_id=None: (
            True,
            "branch_push_done",
            "Pushed.",
        ),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        return "failed", "same check failed", {"url": "https://example/pr/42"}, []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )

    result = asyncio.run(
        store._process_existing_pr_card(
            card,
            42,
            _remote_review_policy(
                repair={"max_rounds": 0, "max_repeated_failure_attempts": 3}
            ),
        )
    )

    assert result.status == "failed"
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.metadata.get("repeated_failure_count") == 3


def test_existing_pr_card_branch_sync_failure_marks_failed(
    tmp_path: Path, monkeypatch
) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    sync_cwd = tmp_path / "worktrees" / "card-42"
    sync_cwd.mkdir(parents=True)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #42: existing PR",
        body="",
        source_ref="pr:42",
        metadata={
            "linked_pr_number": 42,
            "head_branch": "autopilot/pr-42",
            "worktree_path": str(sync_cwd),
        },
    )
    call_order: list[str] = []

    def fake_push_pr_branch_with_sync(
        self, cwd, *, base_branch, head_branch, policies, card_id=None
    ):
        call_order.append("sync")
        return False, "branch_push_failed", "remote rejected push"

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        call_order.append("ci")
        return "success", "All remote checks passed.", {"labels": [], "isDraft": False}, []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_same_git_common_dir",
        lambda self, cwd: True,
    )

    # Mock preflight checks to pass (all non-fatal)
    from openharness.autopilot import PreflightCheck

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        fake_push_pr_branch_with_sync,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "failed"
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.metadata.get("last_failure_stage") == "branch_push_failed"
    assert updated.metadata.get("last_failure_summary") == "remote rejected push"
    assert call_order == ["sync"]


def test_existing_pr_card_skips_branch_sync_for_foreign_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    sync_cwd = tmp_path / "foreign" / "card-42"
    sync_cwd.mkdir(parents=True)
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #42: existing PR",
        body="",
        source_ref="pr:42",
        metadata={"linked_pr_number": 42, "worktree_path": str(sync_cwd)},
    )
    call_order: list[str] = []

    def fake_push_pr_branch_with_sync(
        self, cwd, *, base_branch, head_branch, policies, card_id=None
    ):
        call_order.append("sync")
        return True, "branch_push_done", "Pushed."

    async def fake_wait_for_pr_ci(self, pr_number, policies):
        call_order.append("ci")
        return (
            "success",
            "All remote checks passed.",
            {"url": "https://example/pr/42", "labels": [], "isDraft": False},
            [],
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_same_git_common_dir",
        lambda self, cwd: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        fake_push_pr_branch_with_sync,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: False,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "completed"
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.metadata.get("base_branch") == "main"
    assert call_order == ["ci"]


def test_reap_dead_worker_cards_resets_orphaned_cards(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    import os

    # Card with a dead worker PID
    card_dead, _ = store.enqueue_card(
        source_kind="manual_idea", title="dead worker card", body="fix orphan"
    )
    store.update_status(
        card_dead.id,
        status="running",
        note="running",
        metadata_updates={"worker_id": "pid-999999999-deadbeef"},
    )

    # Card with a live worker PID (current process)
    card_live, _ = store.enqueue_card(
        source_kind="manual_idea", title="live worker card", body="still running"
    )
    store.update_status(
        card_live.id,
        status="running",
        note="running",
        metadata_updates={"worker_id": f"pid-{os.getpid()}-livetoken"},
    )

    # Card in waiting_ci — must NOT be reaped even if worker_id looks dead
    card_waiting, _ = store.enqueue_card(
        source_kind="manual_idea", title="waiting ci card", body="ci check"
    )
    store.update_status(
        card_waiting.id,
        status="waiting_ci",
        note="ci",
        metadata_updates={"worker_id": "pid-999999999-deadci"},
    )

    reaped = store._reap_dead_worker_cards()

    assert card_dead.id in reaped
    assert card_live.id not in reaped
    assert card_waiting.id not in reaped

    assert store.get_card(card_dead.id).status == "queued"
    assert store.get_card(card_live.id).status == "running"
    assert store.get_card(card_waiting.id).status == "waiting_ci"


# ---------------------------------------------------------------------------
# P13.9: autopilot_managed PR auto-merge when CI passes
# ---------------------------------------------------------------------------


def test_autopilot_managed_card_merged_when_ci_pass(tmp_path: Path, monkeypatch) -> None:
    """run_card() with autopilot_managed=True, linked PR, CI pass → merges directly."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Managed PR auto-merge test",
        body="autopilot managed card, CI will pass",
    )
    store.update_status(
        card.id,
        status="queued",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 77,
            "head_branch": f"autopilot/{card.id}",
        },
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        assert pr_number == 77
        return (
            "success",
            "All reported remote checks passed.",
            {"url": "https://example/pr/77", "labels": ["autopilot:merge"], "isDraft": False},
            [],
        )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore.run_preflight",
        lambda self, card: PreflightResult(passed=True, checks=[], fatal=[], transient=[]),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {"state": "OPEN", "url": "https://example/pr/77"},
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    assert result.status == "merged"
    assert result.pr_number == 77
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "merged"


def test_autopilot_managed_card_stays_waiting_when_ci_pending(tmp_path: Path, monkeypatch) -> None:
    """run_card() with autopilot_managed=True, linked PR, CI pending → falls through to worktree path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Managed PR CI pending",
        body="autopilot managed card, CI still running",
    )
    store.update_status(
        card.id,
        status="queued",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 88,
            "head_branch": f"autopilot/{card.id}",
        },
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        assert pr_number == 88
        return ("pending", "Remote CI is still running.", {}, [])

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore.run_preflight",
        lambda self, card: PreflightResult(passed=True, checks=[], fatal=[], transient=[]),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {"state": "OPEN", "url": "https://example/pr/88"},
    )

    async def fake_run_agent_prompt(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        return "done"

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree",
        lambda self, repo_path, slug, branch=None, agent_id=None: AsyncMock(return_value=SimpleNamespace(path=worktree))(),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree",
        lambda self, slug: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        lambda self, policies, *, cwd=None: [
            RepoVerificationStep(command="echo ok", returncode=0, status="success")
        ],
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base",
        lambda self, cwd, **kwargs: None,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_commit_all",
        lambda self, cwd, message: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._push_pr_branch_with_sync",
        lambda self, cwd, *, base_branch, head_branch, policies, card_id=None: (
            True,
            "branch_push_done",
            f"Pushed {head_branch}.",
        ),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 88,
            "url": "https://example/pr/88",
        },
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    asyncio.run(store.run_card(card.id))
    # CI pending → card stays in waiting_ci (don't re-run worktree)
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "waiting_ci"


def test_autopilot_managed_card_repairs_when_ci_fail(tmp_path: Path, monkeypatch) -> None:
    """run_card() with autopilot_managed=True, linked PR, CI fail → queues repair."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Managed PR CI fail test",
        body="autopilot managed card, CI will fail",
    )
    store.update_status(
        card.id,
        status="queued",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 99,
            "head_branch": f"autopilot/{card.id}",
        },
    )

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        assert pr_number == 99
        return ("failed", "test/check=failure", {"url": "https://example/pr/99"}, [])

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore.run_preflight",
        lambda self, card: PreflightResult(passed=True, checks=[], fatal=[], transient=[]),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {"state": "OPEN", "url": "https://example/pr/99"},
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    assert result.status == "queued"
    assert result.pr_number == 99
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "queued"
    assert updated.metadata.get("last_failure_stage") == "remote_ci_failed"
    assert updated.metadata.get("repeated_failure_count") == 1


def test_manual_retry_managed_pr_bypasses_ci_monitor(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Managed PR manual retry",
        body="autopilot managed card should run repair",
    )
    store.update_status(
        card.id,
        status="queued",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 99,
            "head_branch": f"autopilot/{card.id}",
            "manual_retry": True,
        },
    )

    async def fail_if_called(self, pr_number: int, policies):
        raise AssertionError("manual retry should bypass CI monitor")

    async def fake_create_worktree(self, repo_path, slug, branch=None):
        return WorktreeInfo(path=repo, branch=branch or "main", name=slug)

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore.run_preflight",
        lambda self, card: PreflightResult(passed=True, checks=[], fatal=[], transient=[]),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {"state": "OPEN", "url": "https://example/pr/99"},
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fail_if_called
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", lambda self, path: None
    )

    async def fake_run_agent(*args, **kwargs):
        return "manual retry repair ran"

    store._run_agent_prompt = MethodType(fake_run_agent, store)
    store._run_verification_steps = MethodType(lambda self, policies, *, cwd=None: [], store)
    monkeypatch.setattr(
        store,
        "_upsert_pull_request",
        lambda *args, **kwargs: {"number": 99, "url": "https://example/pr/99"},
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status in {"pr_open", "completed"}
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.metadata.get("attempt_count") == 1


def test_manual_retry_managed_pr_with_prior_ci_success_runs_repair(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Managed PR manual retry after CI success",
        body="manual retry must repair instead of reusing stale CI success",
    )
    store.update_status(
        card.id,
        status="queued",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 99,
            "head_branch": f"autopilot/{card.id}",
            "last_ci_conclusion": "success",
            "manual_retry": True,
            "retry_requested": True,
        },
    )

    merge_calls: list[int] = []
    agent_ran = False

    async def fake_create_worktree(self, repo_path, slug, branch=None):
        return WorktreeInfo(path=repo, branch=branch or "main", name=slug)

    async def fake_run_agent(*args, **kwargs):
        nonlocal agent_ran
        agent_ran = True
        return "manual retry repair ran"

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore.run_preflight",
        lambda self, card: PreflightResult(passed=True, checks=[], fatal=[], transient=[]),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {"state": "OPEN", "url": "https://example/pr/99"},
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: merge_calls.append(pr_number),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", lambda self, path: None
    )

    store._run_agent_prompt = MethodType(fake_run_agent, store)
    store._run_verification_steps = MethodType(lambda self, policies, *, cwd=None: [], store)
    monkeypatch.setattr(
        store,
        "_upsert_pull_request",
        lambda *args, **kwargs: {"number": 99, "url": "https://example/pr/99"},
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert merge_calls == []
    assert agent_ran is True
    assert result.status in {"pr_open", "completed"}


def test_manual_retry_flag_cleared_when_agent_loop_starts(tmp_path: Path, monkeypatch) -> None:
    """manual_retry should be cleared from metadata once the agent loop begins."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Managed PR manual retry clear test",
        body="manual_retry flag must be cleared before agent runs",
    )
    store.update_status(
        card.id,
        status="queued",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 42,
            "head_branch": f"autopilot/{card.id}",
            "manual_retry": True,
            "retry_requested": True,
            "retry_by": "user",
        },
    )

    observed_metadata: dict = {}

    async def fake_create_worktree(self, repo_path, slug, branch=None):
        return WorktreeInfo(path=repo, branch=branch or "main", name=slug)

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore.run_preflight",
        lambda self, card: PreflightResult(passed=True, checks=[], fatal=[], transient=[]),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {"state": "OPEN", "url": "https://example/pr/42"},
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.WorktreeManager.remove_worktree", lambda self, path: None
    )

    async def fake_run_agent(self, *args, **kwargs):
        # Capture metadata at the point the agent is invoked
        current = store.get_card(card.id)
        observed_metadata.update(current.metadata)
        return "agent ran"

    store._run_agent_prompt = MethodType(fake_run_agent, store)
    store._run_verification_steps = MethodType(lambda self, policies, *, cwd=None: [], store)
    monkeypatch.setattr(
        store,
        "_upsert_pull_request",
        lambda *args, **kwargs: {"number": 42, "url": "https://example/pr/42"},
    )

    async def fake_wait_ci(self, pr_number, policies):
        return "passed", "", {"state": "OPEN", "url": "https://example/pr/42"}, []

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_ci
    )

    import asyncio

    asyncio.run(store.run_card(card.id))

    # manual_retry and related keys must be cleared by the time the agent runs
    assert observed_metadata.get("manual_retry") is None
    assert observed_metadata.get("retry_requested") is None
    assert observed_metadata.get("retry_by") is None


def test_check_and_merge_managed_prs_merges_when_ci_pass_in_tick(
    tmp_path: Path, monkeypatch
) -> None:
    """_check_and_merge_managed_prs called in tick() merges waiting_ci autopilot_managed card."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Tick CI pass merge test",
        body="autopilot managed card in waiting_ci",
    )
    store.update_status(
        card.id,
        status="waiting_ci",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 55,
            "head_branch": f"autopilot/{card.id}",
        },
    )

    merge_calls: list[int] = []

    def fake_pr_status_snapshot(self, pr_number: int) -> dict[str, Any]:
        return {
            "state": "OPEN",
            "url": f"https://example/pr/{pr_number}",
            "labels": ["autopilot:merge"],
            "isDraft": False,
            "statusCheckRollup": [
                {"name": "test", "status": "COMPLETED", "conclusion": "SUCCESS"}
            ],
        }

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        fake_pr_status_snapshot,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._ci_rollup",
        lambda self, pr_snapshot: ("success", "All passed", []),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._automerge_eligible",
        lambda self, pr_snapshot, policies: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: merge_calls.append(pr_number),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    policies = store.load_policies()
    merged = asyncio.run(store._check_and_merge_managed_prs(policies))

    assert card.id in merged
    assert 55 in merge_calls
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "merged"


def test_check_and_merge_managed_prs_skips_pending_ci(tmp_path: Path, monkeypatch) -> None:
    """_check_and_merge_managed_prs skips card when CI is still pending."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Tick CI pending skip test",
        body="autopilot managed card in waiting_ci",
    )
    store.update_status(
        card.id,
        status="waiting_ci",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 66,
            "head_branch": f"autopilot/{card.id}",
        },
    )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {
            "state": "OPEN",
            "url": f"https://example/pr/{pr_number}",
            "labels": [],
            "isDraft": False,
            "statusCheckRollup": [],
        },
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._ci_rollup",
        lambda self, pr_snapshot: ("pending", "Remote CI is still running.", []),
    )

    import asyncio

    policies = store.load_policies()
    merged = asyncio.run(store._check_and_merge_managed_prs(policies))

    assert card.id not in merged
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "waiting_ci"


def test_check_and_merge_managed_prs_syncs_externally_merged(tmp_path: Path, monkeypatch) -> None:
    """_check_and_merge_managed_prs syncs card status when PR was merged externally."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="External merge sync test",
        body="autopilot managed card in waiting_ci",
    )
    store.update_status(
        card.id,
        status="waiting_ci",
        metadata_updates={
            "autopilot_managed": True,
            "linked_pr_number": 44,
            "head_branch": f"autopilot/{card.id}",
        },
    )

    merge_calls: list[int] = []

    def fake_pr_status_snapshot(self, pr_number: int) -> dict[str, Any]:
        return {
            "state": "MERGED",
            "url": f"https://example/pr/{pr_number}",
            "labels": [],
            "isDraft": False,
            "statusCheckRollup": [],
        }

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        fake_pr_status_snapshot,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._ci_rollup",
        lambda self, pr_snapshot: ("pending", "No checks.", []),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._merge_pull_request",
        lambda self, pr_number: merge_calls.append(pr_number),
    )

    import asyncio

    policies = store.load_policies()
    merged = asyncio.run(store._check_and_merge_managed_prs(policies))

    assert card.id in merged
    assert 44 not in merge_calls
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "merged"


def test_run_card_with_already_merged_pr_short_circuits(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    sync_cwd = tmp_path / "worktrees" / "card-42"
    sync_cwd.mkdir(parents=True)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Managed PR already merged",
        body="",
        metadata={
            "autopilot_managed": True,
            "last_failure_stage": "no_changes",
            "linked_pr_number": 42,
            "head_branch": "autopilot/card-42",
            "worktree_path": str(sync_cwd),
        },
    )
    store.update_status(card.id, status="repairing", note="retrying")
    claimed_by = "pid-test-1234"
    store.update_status(
        card.id,
        status="repairing",
        metadata_updates={"worker_id": claimed_by},
    )

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._pr_status_snapshot",
        lambda self, pr_number: {
            "state": "MERGED",
            "url": "https://example/pr/42",
        },
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_git_repo",
        lambda self: PreflightCheck(name="git_repo", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )

    result = asyncio.run(store.run_card(card.id, _claimed_by=claimed_by))

    assert result.status == "merged"
    assert result.pr_number == 42
    assert result.pr_url == "https://example/pr/42"
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "merged"
    assert updated.metadata.get("human_gate_pending") is False
    assert updated.metadata.get("linked_pr_url") == "https://example/pr/42"


def test_repair_prompt_injects_reviewer_feedback_on_code_review_failure(tmp_path: Path) -> None:
    """Test that code reviewer feedback is injected into repair prompt after code_review failure."""
    repo = tmp_path / "repo"
    repo.mkdir()
    runs_dir = repo / ".openharness" / "autopilot" / "runs"
    runs_dir.mkdir(parents=True)

    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Test card",
        body="Original task description",
    )

    # Create a fake verification report with CRITICAL issues
    verification_report = runs_dir / f"{card.id}-attempt-01-verification.md"
    verification_report.write_text(
        """# Verification Report: test-card

## FAILED :: agent:code-reviewer (diff vs main)

Return code: 1

### stdout
```text
Severity: CRITICAL
Findings:
  - src/example.py:42 security SQL injection vulnerability in query construction
  - src/example.py:89 correctness Missing input validation on user-provided path
Summary: Critical security issues found that must be fixed before merge.
```

### stderr
```text
severity=critical
```
""",
        encoding="utf-8",
    )

    # Prepare repair prompt with code_review failure
    policies = store.load_policies()
    prompt = store._prepare_repair_prompt(
        card,
        policies,
        attempt_count=2,
        prior_summary="Previous attempt summary",
        failure_stage="code_review",
        failure_summary="Code review failed with CRITICAL issues",
    )

    # Assert that the prompt contains the reviewer feedback
    assert "Previous attempt #1 failed code review" in prompt
    assert "Severity: CRITICAL" in prompt
    assert "SQL injection vulnerability" in prompt
    assert "Missing input validation" in prompt
    assert "End of reviewer constraints" in prompt


def test_repair_prompt_injects_reviewer_feedback_on_local_verification_failure(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runs_dir = repo / ".openharness" / "autopilot" / "runs"
    runs_dir.mkdir(parents=True)

    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Test card",
        body="Original task description",
    )
    verification_report = runs_dir / f"{card.id}-attempt-01-verification.md"
    verification_report.write_text(
        """# Verification Report: test-card

## FAILED :: agent:code-reviewer (diff vs main)

### stdout
```text
Severity: CRITICAL
Findings:
  - src/pipeline.py:10 correctness Missing implement_agent model lookup
  - src/pipeline.py:20 correctness repo_ok reports true for non-git cwd
```
""",
        encoding="utf-8",
    )

    prompt = store._prepare_repair_prompt(
        card,
        store.load_policies(),
        attempt_count=2,
        prior_summary="Previous attempt summary",
        failure_stage="local_verification_failed",
        failure_summary="agent:code-reviewer (diff vs main) rc=1",
    )

    assert "Previous attempt #1 failed code review" in prompt
    assert "Severity: CRITICAL" in prompt
    assert "Missing implement_agent model lookup" in prompt
    assert "repo_ok reports true" in prompt


def test_repair_prompt_no_feedback_injection_on_first_attempt(tmp_path: Path) -> None:
    """Test that feedback is not injected on first attempt (attempt_count=1)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    runs_dir = repo / ".openharness" / "autopilot" / "runs"
    runs_dir.mkdir(parents=True)

    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Test card",
        body="Original task description",
    )

    # Create verification report (should be ignored on first attempt)
    verification_report = runs_dir / f"{card.id}-attempt-01-verification.md"
    verification_report.write_text(
        """# Verification Report

Severity: CRITICAL
Findings:
  - src/example.py:42 security Issue found
""",
        encoding="utf-8",
    )

    policies = store.load_policies()
    prompt = store._prepare_repair_prompt(
        card,
        policies,
        attempt_count=1,
        prior_summary=None,
        failure_stage="code_review",
        failure_summary="Failed",
    )

    # Should return base prompt without repair context
    assert "Repair context:" not in prompt
    assert "Previous attempt" not in prompt
    assert "Severity: CRITICAL" not in prompt


def test_repair_prompt_no_feedback_injection_on_non_review_failure(tmp_path: Path) -> None:
    """Test that feedback is not injected when failure stage is not code_review or verifying."""
    repo = tmp_path / "repo"
    repo.mkdir()
    runs_dir = repo / ".openharness" / "autopilot" / "runs"
    runs_dir.mkdir(parents=True)

    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Test card",
        body="Original task description",
    )

    # Create verification report
    verification_report = runs_dir / f"{card.id}-attempt-01-verification.md"
    verification_report.write_text(
        """# Verification Report

Severity: CRITICAL
Findings:
  - src/example.py:42 security Issue found
""",
        encoding="utf-8",
    )

    policies = store.load_policies()
    prompt = store._prepare_repair_prompt(
        card,
        policies,
        attempt_count=2,
        prior_summary="Previous summary",
        failure_stage="running",  # Not code_review or verifying
        failure_summary="Agent failed",
    )

    # Should have repair context but no reviewer feedback
    assert "Repair context:" in prompt
    assert "Previous failure stage: running" in prompt
    assert "Severity: CRITICAL" not in prompt
    assert "SQL injection" not in prompt


def test_extract_reviewer_feedback_handles_missing_file(tmp_path: Path) -> None:
    """Test that _extract_reviewer_feedback returns empty string when file doesn't exist."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    feedback = store._extract_reviewer_feedback("nonexistent-card-id")

    assert feedback == ""


def test_extract_reviewer_feedback_handles_high_severity(tmp_path: Path) -> None:
    """Test that _extract_reviewer_feedback extracts HIGH severity issues."""
    repo = tmp_path / "repo"
    repo.mkdir()
    runs_dir = repo / ".openharness" / "autopilot" / "runs"
    runs_dir.mkdir(parents=True)

    store = RepoAutopilotStore(repo)
    card_id = "test-card-high"

    verification_report = runs_dir / f"{card_id}-attempt-01-verification.md"
    verification_report.write_text(
        """# Verification Report

## FAILED :: agent:code-reviewer (diff vs main)

### stdout
```text
Severity: HIGH
Findings:
  - src/utils.py:10 performance N+1 query detected in loop
  - src/utils.py:25 maintainability Large function should be split
Summary: High priority issues found.
```
""",
        encoding="utf-8",
    )

    feedback = store._extract_reviewer_feedback(card_id)

    assert "Severity: HIGH" in feedback
    assert "N+1 query detected" in feedback
    assert "Large function should be split" in feedback


# -----------------------------------------------------------------------
# Preflight tests
# -----------------------------------------------------------------------


def test_preflight_success_all_checks_pass(tmp_path: Path) -> None:
    """All preflight checks pass when environment is properly configured."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Test card", body="body")

    def fake_check_cwd(self):
        return PreflightCheck(name="cwd_exists", status="ok", reason="ok")

    def fake_check_git(self):
        return PreflightCheck(name="git_repo", status="ok", reason="ok")

    def fake_check_model(self, model):
        return PreflightCheck(name="model_available", status="ok", reason="ok")

    def fake_check_auth(self):
        return PreflightCheck(name="auth_ok", status="ok", reason="ok")

    def fake_check_github(self):
        return PreflightCheck(name="github_available", status="ok", reason="ok")

    store._check_cwd_exists = lambda: fake_check_cwd(store)
    store._check_git_repo = lambda: fake_check_git(store)
    store._check_model_available = lambda m: fake_check_model(store, m)
    store._check_auth_status = lambda: fake_check_auth(store)
    store._check_github_available = lambda: fake_check_github(store)

    result = store.run_preflight(card)

    assert result.passed is True
    assert len(result.fatal) == 0
    assert len(result.transient) == 0
    assert len(result.checks) >= 5


def test_preflight_skips_git_repo_when_worktree_disabled(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="No worktree card", body="body")
    (repo / ".openharness" / "autopilot" / "autopilot_policy.yaml").write_text(
        "execution:\n  use_worktree: false\n",
        encoding="utf-8",
    )
    git_checked = {"value": False}

    def check_git_repo(self):
        git_checked["value"] = True
        return PreflightCheck(name="git_repo", status="fail", reason="not a git repo")

    monkeypatch.setattr(RepoAutopilotStore, "_check_cwd_exists", lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"))
    monkeypatch.setattr(RepoAutopilotStore, "_check_git_repo", check_git_repo)
    monkeypatch.setattr(RepoAutopilotStore, "_check_model_available", lambda self, model: PreflightCheck(name="model_available", status="ok", reason="ok"))
    monkeypatch.setattr(RepoAutopilotStore, "_check_auth_status", lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"))

    result = store.run_preflight(card)

    git_check = next(check for check in result.checks if check.name == "git_repo")
    assert result.passed is True
    assert git_checked["value"] is False
    assert git_check.status == "ok"
    assert git_check.reason == "worktree not required"


def test_preflight_auth_failure_moves_to_pending(tmp_path: Path, monkeypatch) -> None:
    """Auth failure during preflight causes card to move to pending (transient)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Auth fail card", body="body")

    # Mock git repo check to pass
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_auth_status",
        lambda self: {"anthropic": {"configured": False, "source": "missing"}},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.list_profiles",
        lambda self: {"claude-api": type("P", (), {"allowed_models": []})()},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_profile",
        lambda self: "claude-api",
    )

    async def fake_run(*args, **kwargs):
        return type("R", (), {"status": "ok", "summary": ""})()

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt",
        fake_run,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        lambda self, *args, **kwargs: [],
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "pending"
    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "pending"
    assert "pending_reason" in refreshed.metadata
    assert refreshed.metadata["pending_reason"] == "preflight_transient"


def test_preflight_github_failure_moves_to_pending(tmp_path: Path, monkeypatch) -> None:
    """GitHub unavailability during preflight causes card to move to pending (transient)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="github_issue", title="PR flow card", body="body", source_ref="issue:42"
    )

    # Mock git repo check to pass
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )

    # Mock auth to pass
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_provider",
        lambda self: "anthropic",
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_auth_status",
        lambda self: {"anthropic": {"configured": True, "source": "env"}},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.list_profiles",
        lambda self: {"claude-api": type("P", (), {"allowed_models": []})()},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_profile",
        lambda self: "claude-api",
    )

    # Mock GitHub check to fail
    def fake_gh_json(cmd, **kwargs):
        raise RuntimeError("gh: command not found")

    store._run_gh_json = fake_gh_json

    async def fake_run(*args, **kwargs):
        return type("R", (), {"status": "ok", "summary": ""})()

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt",
        fake_run,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        lambda self, *args, **kwargs: [],
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "pending"
    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "pending"
    # Should have transient checks from github check
    assert len(refreshed.metadata.get("preflight_transient_reasons", [])) > 0


def test_preflight_non_git_repo_fails_fatally(tmp_path: Path, monkeypatch) -> None:
    """Non-git repo with worktree policy causes fatal preflight failure for GitHub flows."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    # Use a GitHub flow card so git_repo failure is fatal
    card, _ = store.enqueue_card(
        source_kind="github_issue", title="Git required", body="body", source_ref="issue:42"
    )

    # Mock _is_git_repo to return False
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: False,
    )
    # Mock GitHub check to fail (so it becomes a fatal failure for GitHub flow)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="error", reason="GitHub not available"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_cwd_exists",
        lambda self: PreflightCheck(name="cwd_exists", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, m: PreflightCheck(name="model_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_auth_status",
        lambda self: PreflightCheck(name="auth_ok", status="ok", reason="ok"),
    )

    async def fake_run(*args, **kwargs):
        return type("R", (), {"status": "ok", "summary": ""})()

    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt",
        fake_run,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_verification_steps",
        lambda self, *args, **kwargs: [],
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "failed"
    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    # GitHub flows with GitHub unavailable = fatal preflight failure
    assert refreshed.metadata.get("last_failure_stage") == "preflight_fatal"


def test_preflight_checks_recorded_in_metadata(tmp_path: Path) -> None:
    """Preflight results are stored in card metadata."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Check metadata", body="body")

    # Patch all checks to ok
    store._check_cwd_exists = lambda: PreflightCheck(name="cwd_exists", status="ok", reason="ok")
    store._check_git_repo = lambda: PreflightCheck(name="git_repo", status="ok", reason="ok")
    store._check_model_available = lambda m: PreflightCheck(name="model_available", status="ok", reason="ok")
    store._check_auth_status = lambda: PreflightCheck(name="auth_ok", status="ok", reason="ok")
    store._check_github_available = lambda: PreflightCheck(name="github_available", status="ok", reason="ok")

    result = store.run_preflight(card)

    assert result.passed is True
    assert len(result.checks) >= 5
    # Verify each check has expected fields
    for check in result.checks:
        assert hasattr(check, "name")
        assert hasattr(check, "status")
        assert hasattr(check, "reason")


def test_preflight_model_resolve_chain(tmp_path: Path, monkeypatch) -> None:
    """Model is resolved in priority order: card.model > metadata.execution_model > agent_models > default_model."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    # Set default model via policy
    policy_dir = repo / ".openharness" / "autopilot"
    policy_dir.mkdir(parents=True, exist_ok=True)
    (policy_dir / "autopilot_policy.yaml").write_text(
        "execution:\n  default_model: fallback-model\n  implement_agent: test-agent\n",
        encoding="utf-8",
    )

    execution = {"default_model": "fallback", "implement_agent": "test"}

    # Test 1: card.model takes precedence
    card1, _ = store.enqueue_card(source_kind="manual_idea", title="Test 1")
    # Directly set the model on the card object (simulating what update_card_model does)
    card1.model = "priority-model"
    resolved1 = store._resolve_model_for_card(card1, execution)
    assert resolved1 == "priority-model", f"Expected priority-model, got {resolved1}"

    # Test 2: metadata.execution_model is used when card.model is None
    card2, _ = store.enqueue_card(source_kind="manual_idea", title="Test 2")
    card2.metadata["execution_model"] = "meta-model"
    card2.model = None  # Explicitly clear card.model
    resolved2 = store._resolve_model_for_card(card2, execution)
    assert resolved2 == "meta-model", f"Expected meta-model, got {resolved2}"

    # Test 3: default_model is used when no card.model or metadata
    card3, _ = store.enqueue_card(source_kind="manual_idea", title="Test 3")
    # card3.model is already None (no override set)
    resolved3 = store._resolve_model_for_card(card3, execution)
    assert resolved3 == "fallback", f"Expected fallback, got {resolved3}"


def test_preflight_permanent_vs_transient_classification(tmp_path: Path, monkeypatch) -> None:
    """Permanent failures (model not in agent_models) → fatal.
    Transient failures (model not in allowed_models) → pending."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    original_card, _ = store.enqueue_card(source_kind="manual_idea", title="Classification test")
    store.update_card_model(original_card.id, "unknown-model")
    # Re-fetch card after model update
    card = store.get_card(original_card.id)
    assert card is not None
    assert card.model == "unknown-model"

    # Mock _is_git_repo to pass
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    # Mock GitHub check to pass
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    # Mock auth check to pass
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_provider",
        lambda self: "anthropic",
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_auth_status",
        lambda self: {"anthropic": {"configured": True, "source": "env"}},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.list_profiles",
        lambda self: {"claude-api": type("P", (), {"allowed_models": ["test-model"]})()},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_profile",
        lambda self: "claude-api",
    )
    # Mock load_settings to return empty allowed_models
    from openharness.config.settings import ProviderProfile
    monkeypatch.setattr(
        "openharness.config.settings.load_settings",
        lambda: type("Settings", (), {"profiles": {"empty": ProviderProfile(
            label="Empty", provider="test", api_format="openai",
            auth_source="test", default_model="test-model", allowed_models=[]
        )}})(),
    )
    # Mock claude_bridge to return no agent_models
    monkeypatch.setattr(
        "openharness.config.claude_bridge.read_claude_settings",
        lambda: None,
    )

    result = store.run_preflight(card)

    # When all_agent_models is empty, the permanent fail check is skipped
    # and we fall through to the transient check (model not in allowed_models of profile)
    model_check = next((c for c in result.checks if c.name == "model_available"), None)
    assert model_check is not None, "model_available check not found"
    # With empty all_agent_models, the permanent fail is not triggered
    # Instead it falls through to the transient check (error because unknown-model not in profile's allowed_models)
    assert model_check.status == "error", f"Expected error (transient), got {model_check.status}: {model_check.reason}"
    assert model_check.transient is True


def test_preflight_permanent_model_not_in_settings(tmp_path: Path, monkeypatch) -> None:
    """When models ARE configured in settings but card model is not in the list → permanent fail."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    original_card, _ = store.enqueue_card(source_kind="manual_idea", title="Permanent fail test")
    store.update_card_model(original_card.id, "unknown-model")
    card = store.get_card(original_card.id)
    assert card is not None

    # Mock _is_git_repo to pass
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._is_git_repo",
        lambda self, cwd: True,
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_provider",
        lambda self: "anthropic",
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_auth_status",
        lambda self: {"anthropic": {"configured": True, "source": "env"}},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.list_profiles",
        lambda self: {"claude-api": type("P", (), {"allowed_models": ["test-model"]})()},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_profile",
        lambda self: "claude-api",
    )
    # Mock load_settings to have some models configured
    from openharness.config.settings import ProviderProfile
    monkeypatch.setattr(
        "openharness.config.settings.load_settings",
        lambda: type("Settings", (), {"profiles": {"test": ProviderProfile(
            label="Test", provider="test", api_format="openai",
            auth_source="test", default_model="test-model", allowed_models=["test-model", "other-model"]
        )}})(),
    )
    # Mock claude_bridge to return no agent_models
    monkeypatch.setattr(
        "openharness.config.claude_bridge.read_claude_settings",
        lambda: None,
    )

    result = store.run_preflight(card)

    model_check = next((c for c in result.checks if c.name == "model_available"), None)
    assert model_check is not None
    # "unknown-model" is not in settings.allowed_models → permanent fail
    assert model_check.status == "fail", f"Expected fail, got {model_check.status}: {model_check.reason}"
    assert model_check.transient is False


def test_preflight_transient_failure_moves_card_to_pending(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Transient preflight", body="body")

    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_github_available",
        lambda self: PreflightCheck(name="github_available", status="ok", reason="ok"),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._check_model_available",
        lambda self, model: PreflightCheck(
            name="model_available",
            status="error",
            reason="provider temporarily unavailable",
            transient=True,
        ),
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_provider",
        lambda self: "anthropic",
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_auth_status",
        lambda self: {"anthropic": {"configured": True, "source": "env"}},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.list_profiles",
        lambda self: {"claude-api": type("P", (), {"allowed_models": ["test-model"]})()},
    )
    monkeypatch.setattr(
        "openharness.auth.manager.AuthManager.get_active_profile",
        lambda self: "claude-api",
    )
    monkeypatch.setattr("openharness.config.claude_bridge.read_claude_settings", lambda: None)

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "pending"
    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "pending"
    assert refreshed.metadata["pending_reason"] == "preflight_transient"
    assert refreshed.metadata["retry_count"] == 1
    assert refreshed.metadata["next_retry_at"] > 0


def test_pending_card_is_reclaimed_when_due(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Due retry", body="body")
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={"pending_reason": "preflight_transient", "next_retry_at": 1.0, "retry_count": 1},
    )

    claimed = store.pick_and_claim_card("worker-1")

    assert claimed is not None
    assert claimed.id == card.id
    assert claimed.status == "preparing"
    assert claimed.metadata["resumed_from_pending"] is True


def test_pending_card_exhausted_retries_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Exhausted retry", body="body")
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={"pending_reason": "preflight_transient", "next_retry_at": 1.0, "retry_count": 7},
    )

    assert store.pick_and_claim_card("worker-1") is None
    refreshed = store.get_card(card.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.metadata["last_failure_stage"] == "retry_exhausted"


def test_retry_now_reclaims_pending_card_and_clears_pending_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Manual retry", body="body")
    store.update_status(
        card.id,
        status="pending",
        metadata_updates={
            "attempt_count": 3,
            "pending_reason": "preflight_transient",
            "next_retry_at": 9999999999.0,
            "retry_count": 3,
        },
    )

    claimed = store.pick_specific_card(card.id, "worker-manual")

    assert claimed is not None
    assert claimed.status == "preparing"
    assert claimed.metadata["manual_retry"] is True
    assert claimed.metadata["worker_id"] == "worker-manual"
    assert claimed.metadata["attempt_count"] == 0
    assert "pending_reason" not in claimed.metadata
    assert "next_retry_at" not in claimed.metadata
    assert "retry_count" not in claimed.metadata

    journal = store.load_journal(limit=10)
    assert any(entry.kind == "manual_retry" for entry in journal)


def test_manual_reset_failed_card_clears_terminal_retry_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Failed reset", body="body")
    store.update_status(
        card.id,
        status="failed",
        metadata_updates={
            "attempt_count": 3,
            "last_failure_stage": "local_verification_failed",
            "last_failure_summary": "tests failed",
            "verification_failed": True,
            "worker_id": "pid-1-deadbeef",
        },
    )

    reset = store.update_status(card.id, status="queued")

    assert reset.status == "queued"
    assert reset.metadata["manual_retry"] is True
    assert reset.metadata["attempt_count"] == 0
    assert "last_failure_stage" not in reset.metadata
    assert "last_failure_summary" not in reset.metadata
    assert "verification_failed" not in reset.metadata
    assert "worker_id" not in reset.metadata
