"""Tests for validate_worktree_slug edge cases and WorktreeManager helpers."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from openharness.swarm.worktree import (
    WorktreeManager,
    _flatten_slug,
    _worktree_branch,
    validate_worktree_slug,
)


# ---------------------------------------------------------------------------
# validate_worktree_slug — valid cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    [
        "simple",
        "with-dashes",
        "with_underscores",
        "alpha123",
        "a.b.c",
        "feature/my-task",
        "a/b/c",
        "A-Z_0-9.mixed",
        "x" * 64,  # exactly 64 chars
    ],
)
def test_validate_worktree_slug_valid(slug):
    assert validate_worktree_slug(slug) == slug


# ---------------------------------------------------------------------------
# validate_worktree_slug — invalid cases
# ---------------------------------------------------------------------------


def test_validate_empty_slug_raises():
    with pytest.raises(ValueError, match="empty"):
        validate_worktree_slug("")


def test_validate_too_long_slug_raises():
    with pytest.raises(ValueError, match="64"):
        validate_worktree_slug("x" * 65)


def test_validate_absolute_path_raises():
    with pytest.raises(ValueError, match="absolute"):
        validate_worktree_slug("/absolute/path")


def test_validate_backslash_absolute_raises():
    with pytest.raises(ValueError, match="absolute"):
        validate_worktree_slug("\\windows\\path")


def test_validate_dot_segment_raises():
    with pytest.raises(ValueError, match=r"\.|\.\."):
        validate_worktree_slug("a/./b")


def test_validate_dotdot_segment_raises():
    with pytest.raises(ValueError, match=r"\.|\.\."):
        validate_worktree_slug("a/../b")


def test_validate_invalid_chars_raises():
    with pytest.raises(ValueError):
        validate_worktree_slug("has space")


def test_validate_empty_segment_via_double_slash_raises():
    with pytest.raises(ValueError):
        validate_worktree_slug("a//b")


@pytest.mark.parametrize(
    "slug",
    [
        "has space",
        "has@symbol",
        "has!bang",
        "has$dollar",
        "has#hash",
        "has%percent",
    ],
)
def test_validate_various_invalid_chars(slug):
    with pytest.raises(ValueError):
        validate_worktree_slug(slug)


# ---------------------------------------------------------------------------
# _flatten_slug
# ---------------------------------------------------------------------------


def test_flatten_slug_replaces_slash_with_plus():
    assert _flatten_slug("feature/my-task") == "feature+my-task"


def test_flatten_slug_no_slash_unchanged():
    assert _flatten_slug("simple") == "simple"


def test_flatten_slug_multiple_slashes():
    assert _flatten_slug("a/b/c") == "a+b+c"


# ---------------------------------------------------------------------------
# _worktree_branch
# ---------------------------------------------------------------------------


def test_worktree_branch_simple():
    assert _worktree_branch("fix-bug") == "worktree-fix-bug"


def test_worktree_branch_with_slash():
    assert _worktree_branch("feature/foo") == "worktree-feature+foo"


def test_worktree_branch_prefix():
    branch = _worktree_branch("anything")
    assert branch.startswith("worktree-")


def _init_repo_with_webui_dist(repo):
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("test\n")
    dist = repo / "frontend" / "webui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return dist


def test_create_worktree_symlinks_webui_dist(tmp_path):
    repo = tmp_path / "repo"
    dist = _init_repo_with_webui_dist(repo)

    manager = WorktreeManager(base_dir=tmp_path / "worktrees")
    worktree = asyncio.run(manager.create_worktree(repo, "autopilot/ap-test"))

    linked_dist = worktree.path / "frontend" / "webui" / "dist"
    assert linked_dist.is_symlink()
    assert linked_dist.resolve() == dist.resolve()


def test_remove_worktree_uses_fallback_when_repo_root_remove_fails(tmp_path, monkeypatch):
    # Create worktree directory manually — avoids running real git worktree add
    # so the entire remove_worktree path is covered by the fake _run_git.
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    manager = WorktreeManager(base_dir=tmp_path / "worktrees")
    worktree_path = tmp_path / "worktrees" / "autopilot+ap-test"
    worktree_path.mkdir(parents=True)

    # Resolve once so comparisons work cross-platform (macOS /var → /private/var)
    fake_repo_r = fake_repo.resolve()
    base_dir_r = manager.base_dir.resolve()

    calls: list[tuple[tuple[str, ...], Path]] = []

    async def fake_run_git(*args: str, cwd: Path) -> tuple[int, str, str]:
        calls.append((args, cwd))
        if args[:2] == ("rev-parse", "--git-common-dir"):
            # Return resolved path so remove_worktree's Path(...).resolve().parent == fake_repo_r
            return 0, str(fake_repo_r / ".git"), ""
        cwd_r = Path(cwd).resolve()
        if args[:3] == ("worktree", "remove", "--force") and cwd_r == fake_repo_r:
            return 1, "", "busy"
        if args[:3] == ("worktree", "remove", "--force") and cwd_r == base_dir_r:
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr("openharness.swarm.worktree._run_git", fake_run_git)

    assert asyncio.run(manager.remove_worktree("autopilot/ap-test")) is True

    remove_calls = [(a, c) for a, c in calls if a[:3] == ("worktree", "remove", "--force")]
    assert len(remove_calls) >= 2, f"Expected ≥2 remove calls (repo + fallback), got {remove_calls}"
    # Last remove call must be the fallback (cwd=base_dir)
    last_args, last_cwd = remove_calls[-1]
    assert Path(last_cwd).resolve() == base_dir_r
    assert last_args[3] == str(worktree_path)
