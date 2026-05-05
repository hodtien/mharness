from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import yaml

from openharness.autopilot import RepoAutopilotStore, RepoVerificationStep
from openharness.config.paths import (
    get_project_autopilot_policy_path,
    get_project_verification_policy_path,
)
from openharness.swarm.worktree import WorktreeManager


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""},
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def _write_policy(repo: Path) -> None:
    get_project_autopilot_policy_path(repo).write_text(
        yaml.safe_dump(
            {
                "execution": {
                    "max_parallel_runs": 2,
                    "max_attempts": 1,
                    "base_branch": "main",
                    "use_worktree": True,
                },
                "github": {
                    "auto_merge": {"mode": "label_gated", "required_label": "autopilot:merge"}
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    get_project_verification_policy_path(repo).write_text(
        yaml.safe_dump(
            {
                "commands": [
                    {
                        "command": "python -c \"from pathlib import Path; assert Path('artifact.txt').exists()\"",
                        "shell": True,
                    }
                ],
                "code_review": {"enabled": False},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _bootstrap_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-m", "seed")
    _git(tmp_path, "init", "--bare", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    _write_policy(repo)
    return repo, origin


def test_two_cards_claim_different_cards(tmp_path: Path) -> None:
    repo, _ = _bootstrap_repo(tmp_path)
    store = RepoAutopilotStore(repo)
    first, _ = store.enqueue_card(source_kind="manual_idea", title="First", body="idea")
    second, _ = store.enqueue_card(source_kind="manual_idea", title="Second", body="idea")
    third, _ = store.enqueue_card(source_kind="manual_idea", title="Third", body="idea")

    claimed_a = RepoAutopilotStore(repo).pick_and_claim_card("worker-1")
    claimed_b = RepoAutopilotStore(repo).pick_and_claim_card("worker-2")

    assert claimed_a is not None
    assert claimed_b is not None
    assert claimed_a.id != claimed_b.id
    assert {claimed_a.id, claimed_b.id}.issubset({first.id, second.id, third.id})


def test_two_cards_run_parallel_end_to_end_with_real_git_and_worktrees(
    tmp_path: Path, monkeypatch
) -> None:
    repo, origin = _bootstrap_repo(tmp_path)
    worktree_root = tmp_path / "worktrees"
    store = RepoAutopilotStore(repo)
    card_a, _ = store.enqueue_card(source_kind="manual_idea", title="Card A", body="a")
    card_b, _ = store.enqueue_card(source_kind="manual_idea", title="Card B", body="b")
    started = {card_a.id: asyncio.Event(), card_b.id: asyncio.Event()}
    release = asyncio.Event()
    pr_comments: list[int] = []
    merged_prs: list[int] = []

    original_init = WorktreeManager.__init__

    def init_with_temp_root(self, base_dir=None):
        original_init(self, worktree_root)

    async def fake_agent(
        self, prompt: str, *, model, max_turns, permission_mode, cwd=None, **kwargs
    ):
        assert cwd is not None
        card_id = card_a.id if "Card A" in prompt else card_b.id
        Path(cwd, "artifact.txt").write_text(f"artifact for {card_id}\n", encoding="utf-8")
        return f"implemented {card_id}"

    def fake_upsert(
        self, card, *, head_branch, base_branch, run_report_path, verification_report_path
    ):
        number = 101 if card.id == card_a.id else 102
        return {"number": number, "url": f"https://example.test/pr/{number}"}

    async def fake_wait(self, pr_number: int, policies):
        card_id = card_a.id if pr_number == 101 else card_b.id
        started[card_id].set()
        await release.wait()
        labels = ["autopilot:merge"] if pr_number == 101 else []
        return (
            "success",
            "ok",
            {"url": f"https://example.test/pr/{pr_number}", "labels": labels, "isDraft": False},
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
            command="agent:code-reviewer", returncode=0, status="success", stdout="Severity: NONE"
        )

    monkeypatch.setattr(WorktreeManager, "__init__", init_with_temp_root)
    monkeypatch.setattr(RepoAutopilotStore, "_run_agent_prompt", fake_agent)
    monkeypatch.setattr(RepoAutopilotStore, "_upsert_pull_request", fake_upsert)
    monkeypatch.setattr(RepoAutopilotStore, "_wait_for_pr_ci", fake_wait)
    monkeypatch.setattr(RepoAutopilotStore, "_run_remote_code_review_step", fake_remote_review)
    monkeypatch.setattr(
        RepoAutopilotStore,
        "_comment_on_pr",
        lambda self, pr_number, comment: pr_comments.append(pr_number),
    )
    monkeypatch.setattr(
        RepoAutopilotStore, "_comment_on_issue", lambda self, issue_number, comment: None
    )
    monkeypatch.setattr(
        RepoAutopilotStore,
        "_merge_pull_request",
        lambda self, pr_number: merged_prs.append(pr_number),
    )
    monkeypatch.setattr(RepoAutopilotStore, "_pull_base_branch", lambda self, *, base_branch: None)
    monkeypatch.setattr(RepoAutopilotStore, "_install_editable", lambda self: None)
    monkeypatch.setattr(
        RepoAutopilotStore,
        "rebase_inflight_worktrees",
        lambda self, *, base_branch, merged_card_id=None: None,
        raising=False,
    )

    async def runner():
        task_a = asyncio.create_task(store.run_card(card_a.id))
        task_b = asyncio.create_task(store.run_card(card_b.id))
        try:
            await asyncio.wait_for(
                asyncio.gather(started[card_a.id].wait(), started[card_b.id].wait()), timeout=10
            )
        except TimeoutError:
            task_a.cancel()
            task_b.cancel()
            reg_a = store.get_card(card_a.id)
            reg_b = store.get_card(card_b.id)
            raise AssertionError(f"cards did not both reach CI: {reg_a!r} {reg_b!r}")
        reg_a = store.get_card(card_a.id)
        reg_b = store.get_card(card_b.id)
        assert reg_a is not None and reg_a.status == "waiting_ci"
        assert reg_b is not None and reg_b.status == "waiting_ci"
        assert reg_a.metadata["worktree_path"] != reg_b.metadata["worktree_path"]
        assert (
            Path(reg_a.metadata["worktree_path"], "artifact.txt").read_text(encoding="utf-8")
            == f"artifact for {card_a.id}\n"
        )
        assert (
            Path(reg_b.metadata["worktree_path"], "artifact.txt").read_text(encoding="utf-8")
            == f"artifact for {card_b.id}\n"
        )
        release.set()
        return await asyncio.gather(task_a, task_b)

    result_a, result_b = asyncio.run(runner())

    assert result_a.status == "merged"
    assert result_b.status == "completed"
    assert merged_prs == [101]
    refs = _git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    assert f"autopilot/{card_a.id}" in refs
    assert f"autopilot/{card_b.id}" in refs
    final_a = store.get_card(card_a.id)
    final_b = store.get_card(card_b.id)
    assert final_a is not None and final_a.status == "merged"
    assert final_b is not None and final_b.status == "completed"
    assert final_a.metadata["linked_pr_number"] == 101
    assert final_b.metadata["linked_pr_number"] == 102
    assert pr_comments.count(101) >= 1
    assert pr_comments.count(102) >= 1
