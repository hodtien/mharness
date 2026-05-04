"""Tests for project repo autopilot state."""

from __future__ import annotations

import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MethodType, SimpleNamespace

from openharness.autopilot import RepoAutopilotStore, RepoVerificationStep
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
    low, _ = store.enqueue_card(source_kind="claude_code_candidate", title="Low priority", body="candidate")
    high, _ = store.enqueue_card(source_kind="ohmo_request", title="High priority", body="urgent bug")
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


def test_autopilot_run_card_marks_completed_after_verification(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Implement repo autopilot tick",
        body="run next queued task and verify it",
    )

    async def fake_run_agent_prompt(self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs):
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
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.status == "completed"
    assert Path(result.run_report_path).exists()
    assert Path(result.verification_report_path).exists()
    run_report = Path(result.run_report_path).read_text(encoding="utf-8")
    assert "## Agent Self-Reported Summary" in run_report
    assert "## Service-Level Ground Truth" in run_report
    assert "- Verification status: passed." in run_report


def test_autopilot_run_card_marks_failed_when_verification_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    card, _ = store.enqueue_card(
        source_kind="manual_idea",
        title="Ship broken change",
        body="this should fail verification",
    )

    async def fake_run_agent_prompt(self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs):
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
    run_report = Path(result.run_report_path).read_text(encoding="utf-8")
    assert "## Agent Self-Reported Summary" in run_report
    assert "## Service-Level Ground Truth" in run_report
    assert "- Verification status: failed." in run_report
    assert "[failed] `uv run pytest -q`" in run_report


def test_autopilot_tick_scans_then_runs_next(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store.enqueue_card(source_kind="manual_idea", title="Do queued work", body="body")

    def fake_scan_all_sources(self, *, issue_limit: int = 10, pr_limit: int = 10):
        return {"github_issue": 0, "github_pr": 0, "claude_code_candidate": 0}

    async def fake_run_next(self, *, model=None, max_turns=None, permission_mode=None):
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

    async def fake_run_next(self, *, model=None, max_turns=None, permission_mode=None):
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


def test_autopilot_install_default_cron_creates_jobs(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    recorded: list[dict[str, str]] = []

    monkeypatch.setattr(
        "openharness.services.cron.upsert_cron_job",
        lambda job: recorded.append(job),
    )

    names = store.install_default_cron()

    assert names == ["autopilot.scan", "autopilot.tick"]
    assert len(recorded) == 2
    assert recorded[0]["name"] == "autopilot.scan"


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

    async def fake_run_agent_prompt(self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs):
        assert cwd == worktree
        return "Implemented the requested feature."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        assert cwd == worktree
        return [RepoVerificationStep(command="uv run pytest -q", returncode=0, status="success")]

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return "success", "All reported remote checks passed.", {"url": "https://example/pr/17", "labels": [], "isDraft": False}, []

    monkeypatch.setattr("openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree)
    monkeypatch.setattr("openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_verification_steps", fake_run_verification_steps)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base", lambda self, cwd, *, base_branch, head_branch, reset: None)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._git_commit_all", lambda self, cwd, message: True)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._git_push_branch", lambda self, cwd, branch: None)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 17,
            "url": "https://example/pr/17",
        },
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._automerge_eligible", lambda self, pr_snapshot, policies: False)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._comment_on_pr", lambda self, pr_number, comment: None)

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "completed"
    assert result.pr_number == 17
    updated = store.get_card(card.id)
    assert updated is not None
    assert updated.metadata["linked_pr_number"] == 17
    assert updated.metadata["human_gate_pending"] is True


def test_autopilot_run_card_repairs_after_local_verification_failure(tmp_path: Path, monkeypatch) -> None:
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

    async def fake_run_agent_prompt(self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs):
        return f"attempt for {cwd}"

    def fake_run_verification_steps(self, policies, *, cwd=None):
        verification_calls["count"] += 1
        if verification_calls["count"] == 1:
            return [RepoVerificationStep(command="uv run pytest -q", returncode=1, status="failed", stderr="1 failed")]
        return [RepoVerificationStep(command="uv run pytest -q", returncode=0, status="success")]

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return "success", "All reported remote checks passed.", {"url": "https://example/pr/23", "labels": ["autopilot:merge"], "isDraft": False}, []

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    merged = {"called": False}

    monkeypatch.setattr("openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree)
    monkeypatch.setattr("openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_verification_steps", fake_run_verification_steps)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base", lambda self, cwd, *, base_branch, head_branch, reset: None)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._git_commit_all", lambda self, cwd, message: True)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._git_push_branch", lambda self, cwd, branch: None)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 23,
            "url": "https://example/pr/23",
        },
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._automerge_eligible", lambda self, pr_snapshot, policies: True)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._merge_pull_request", lambda self, pr_number: merged.__setitem__("called", True))
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._comment_on_pr", lambda self, pr_number, comment: None)

    import asyncio

    result = asyncio.run(store.run_card(card.id))

    assert result.status == "merged"
    assert result.attempt_count == 2
    assert merged["called"] is True
    assert verification_calls["count"] == 2


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

    async def fake_run_agent_prompt(self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs):
        return "A direct git commit already exists on the branch."

    def fake_run_verification_steps(self, policies, *, cwd=None):
        return [RepoVerificationStep(command="uv run pytest -q", returncode=0, status="success")]

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return "success", "All reported remote checks passed.", {"url": "https://example/pr/29", "labels": [], "isDraft": False}, []

    pushed = {"called": False}

    monkeypatch.setattr("openharness.autopilot.service.WorktreeManager.create_worktree", fake_create_worktree)
    monkeypatch.setattr("openharness.autopilot.service.WorktreeManager.remove_worktree", fake_remove_worktree)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._is_git_repo", lambda self, cwd: True)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_agent_prompt", fake_run_agent_prompt)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._run_verification_steps", fake_run_verification_steps)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._sync_worktree_to_base", lambda self, cwd, *, base_branch, head_branch, reset: None)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._git_commit_all", lambda self, cwd, message: False)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._git_branch_has_progress", lambda self, cwd, *, base_branch: True)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._git_push_branch",
        lambda self, cwd, branch: pushed.__setitem__("called", True),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._upsert_pull_request",
        lambda self, card, *, head_branch, base_branch, run_report_path, verification_report_path: {
            "number": 29,
            "url": "https://example/pr/29",
        },
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._automerge_eligible", lambda self, pr_snapshot, policies: False)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._comment_on_pr", lambda self, pr_number, comment: None)

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
        return "success", "All reported remote checks passed.", {"url": "https://example/pr/88", "labels": ["autopilot:merge"], "isDraft": False}, []

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
        return RepoVerificationStep(
            command="agent:code-reviewer",
            returncode=0,
            status="success",
            stdout="Severity: NONE",
        )

    merged = {"called": False}

    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._wait_for_pr_ci", fake_wait_for_pr_ci)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._automerge_eligible", lambda self, pr_snapshot, policies: True)
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._run_remote_code_review_step",
        fake_remote_review,
    )
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._merge_pull_request", lambda self, pr_number: merged.__setitem__("called", True))
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._pull_base_branch", lambda self, *, base_branch: None)
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._comment_on_pr", lambda self, pr_number, comment: None)

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


def test_wait_for_pr_ci_allows_repos_with_no_remote_checks_after_grace(tmp_path: Path, monkeypatch) -> None:
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
            {"autopilot": {"github": {"ci_poll_interval_seconds": 1, "ci_timeout_seconds": 30, "no_checks_grace_seconds": 5}}},
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
                {"name": "GitGuardian Security Checks", "status": "COMPLETED", "conclusion": "SUCCESS"}
            ],
        },
        {
            "url": "https://example/pr/33",
            "statusCheckRollup": [
                {"name": "GitGuardian Security Checks", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "Python tests (3.10)", "status": "IN_PROGRESS", "conclusion": ""},
            ],
        },
        {
            "url": "https://example/pr/33",
            "statusCheckRollup": [
                {"name": "GitGuardian Security Checks", "status": "COMPLETED", "conclusion": "SUCCESS"},
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
        lambda args, *, cwd=None, check=False: captured.update({"args": args, "cwd": cwd, "check": check}),
    )

    store._merge_pull_request(41)

    assert captured["args"] == ["pr", "merge", "41", "--repo", "hodtien/mharness", "--squash"]
    assert captured["check"] is True


def test_find_open_pr_for_branch_uses_repo_qualified_head_lookup(tmp_path: Path, monkeypatch) -> None:
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
        lambda args, *, cwd=None, check=False: captured.update({"args": args, "cwd": cwd, "check": check}),
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
        "number,url,isDraft,labels,headRefName,baseRefName,mergeStateStatus,reviewDecision,statusCheckRollup",
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
        lambda args, *, cwd=None, check=False: captured.update({"args": args, "cwd": cwd, "check": check}),
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


def test_create_pr_retries_with_explicit_repo_on_head_resolution_error(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    body_path = tmp_path / "body.md"
    body_path.write_text("body", encoding="utf-8")
    store = RepoAutopilotStore(repo)
    calls: list[list[str]] = []

    def fake_run_gh(args, *, cwd=None, check=False):
        calls.append(args)
        if args[:2] == ["repo", "view"]:
            return subprocess.CompletedProcess(["gh", *args], 0, '{"nameWithOwner":"hodtien/mharness"}', "")
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
    monkeypatch.setattr(store, "_gh_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("gh should not run")))

    assert store._current_repo_full_name() == "hodtien/mharness"


def test_current_repo_full_name_handles_ssh_origin_remote(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    def fake_run_git(args, *, cwd=None, check=False):
        return subprocess.CompletedProcess(["git", *args], 0, "git@github.com:hodtien/mharness.git\n", "")

    monkeypatch.setattr(store, "_run_git", fake_run_git)

    assert store._current_repo_full_name() == "hodtien/mharness"


def test_current_repo_full_name_falls_back_to_gh_when_origin_unavailable(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)

    def fake_run_git(args, *, cwd=None, check=False):
        return subprocess.CompletedProcess(["git", *args], 1, "", "no origin")

    monkeypatch.setattr(store, "_run_git", fake_run_git)
    monkeypatch.setattr(store, "_gh_json", lambda args, *, cwd=None: {"nameWithOwner": "fallback/repo"})

    assert store._current_repo_full_name() == "fallback/repo"


def _remote_review_policy(*, enabled: bool = True) -> dict:
    return {
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


def _green_pr_snapshot(pr_number: int) -> tuple[str, str, dict, list]:
    return (
        "success",
        "All reported remote checks passed.",
        {"url": f"https://example/pr/{pr_number}", "labels": ["autopilot:merge"], "isDraft": False},
        [],
    )


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
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Review virtualenv", body="review")
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


def test_remote_code_review_step_blocks_nested_virtualenv_artifact(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Review virtualenv", body="review")

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


def test_remote_code_review_prompt_requires_requirement_completeness(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    store._repo_full_name = "hodtien/mharness"
    card, _ = store.enqueue_card(source_kind="manual_idea", title="Configurable max_parallel_runs policy", body="review")

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

    async def fake_run_agent_prompt(prompt, *, model, max_turns, permission_mode, cwd=None, stream=None, checkpoint_card_id=None, checkpoint_phase=None, checkpoint_attempt=1, resume_messages=None, phase=None):
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

    async def fake_run_agent_prompt(prompt, *, model, max_turns, permission_mode, cwd=None, stream=None, checkpoint_card_id=None, checkpoint_phase=None, checkpoint_attempt=1, resume_messages=None, phase=None):
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

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
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

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
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


def test_existing_pr_remote_code_review_failure_repairs_when_attempts_remain(tmp_path: Path, monkeypatch) -> None:
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

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
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

    async def fake_wait_for_pr_ci(self, pr_number: int, policies):
        return _green_pr_snapshot(pr_number)

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
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

    async def fake_remote_review(self, card, pr_number, *, policies, model, base_branch="main", stream=None, checkpoint_attempt=1):
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
    monkeypatch.setattr("openharness.autopilot.service.RepoAutopilotStore._pull_base_branch", fail_pull)
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
    journal = (repo / ".openharness" / "autopilot" / "repo_journal.jsonl").read_text(encoding="utf-8")

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
        lambda self: (_ for _ in ()).throw(RuntimeError("uv failed")),
    )
    monkeypatch.setattr(
        "openharness.autopilot.service.RepoAutopilotStore._comment_on_pr",
        lambda self, pr_number, comment: None,
    )

    import asyncio

    result = asyncio.run(store.run_card(card.id))
    journal = (repo / ".openharness" / "autopilot" / "repo_journal.jsonl").read_text(encoding="utf-8")

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


def test_install_editable_runs_uv_pip_install(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = RepoAutopilotStore(repo)
    calls = []

    def fake_run_command(command, *, cwd=None, timeout=None, shell=False, check=False):
        calls.append((command, cwd, timeout, check))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(store, "_run_command", fake_run_command)

    store._install_editable()

    assert calls == [(["uv", "pip", "install", "-e", "."], repo, 120, True)]


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
    card, _ = store.enqueue_card(
        source_kind="github_pr",
        title="GitHub PR #500: Existing autopilot PR",
        body="open",
        source_ref="pr:500",
    )

    async def fake_wait_for_pr_ci(self, pr_number, policies):
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
    assert len(enters) == 2, f"Expected 2 lock enters (one for pull, one for install), got {len(enters)}"
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

    journal = (repo / ".openharness" / "autopilot" / "repo_journal.jsonl").read_text(encoding="utf-8")

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
        'execution:\n'
        '  default_model: "oc-default-model"\n'
        '  max_turns: 12\n'
        '  permission_mode: full_auto\n'
        '  host_mode: self_hosted\n'
        '  use_worktree: false\n'
        '  base_branch: main\n'
        '  max_attempts: 3\n',
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

    async def capture_model_prompt(self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs):
        used_models.append(model)
        return "done"

    store._run_agent_prompt = MethodType(capture_model_prompt, store)

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
        '  {\n'
        '    "id":"ap-oldcard1",\n'
        '    "fingerprint":"f1","title":"Old card","body":"",\n'
        '    "source_kind":"manual_idea","source_ref":"","status":"queued",\n'
        '    "score":0,"score_reasons":[],"labels":[],"metadata":{},\n'
        '    "created_at":1000.0,"updated_at":1000.0\n'
        '  }\n'
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

    async def fake_run_agent_prompt(self, prompt, *, model, max_turns, permission_mode, cwd=None, **kwargs):
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

    monkeypatch.setattr(RepoAutopilotStore, "_run_agent_prompt", fake_run_agent_prompt)
    monkeypatch.setattr(RepoAutopilotStore, "_run_verification_steps", fake_run_verification_steps)

    import asyncio

    result = asyncio.run(store.run_card(card.id, model=None))
    assert result.status == "completed"
    assert used_models[0] == "card-model"
