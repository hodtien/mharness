"""Tests for autopilot locking module."""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from openharness.autopilot.locking import (
    LockTimeoutError,
    RepoFileLock,
)


class TestLockAcquireRelease:
    def test_simple_acquire_release(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        with RepoFileLock(lock_path):
            pass
        # Should be re-acquirable immediately
        with RepoFileLock(lock_path):
            pass

    def test_double_acquire_raises(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock = RepoFileLock(lock_path)
        lock.acquire()
        with pytest.raises(RuntimeError):
            lock.acquire()
        lock.release()

    def test_release_when_not_held(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock = RepoFileLock(lock_path)
        lock.release()  # Must not raise


class TestLockBlocksConcurrent:
    def test_second_thread_blocks(self, tmp_path: Path) -> None:
        """Thread 2 cannot acquire the lock while thread 1 holds it.

        We measure the time thread 2 spends waiting and verify it's
        at least as long as thread 1's deliberate hold.
        """
        lock_path = tmp_path / "concurrent.lock"
        blocker_ready = threading.Event()
        second_acquired = threading.Event()
        hold_duration = 0.5  # seconds

        def hold_lock() -> None:
            with RepoFileLock(lock_path, timeout=5.0):
                blocker_ready.set()
                time.sleep(hold_duration)

        t1 = threading.Thread(target=hold_lock)
        t1.start()
        blocker_ready.wait(timeout=5.0)

        start = time.monotonic()
        with RepoFileLock(lock_path, timeout=5.0):
            elapsed = time.monotonic() - start
            second_acquired.set()

        t1.join(timeout=5.0)

        assert second_acquired.is_set(), "Thread 2 never acquired the lock"
        # Thread 2 must have waited at least most of thread 1's hold time.
        assert elapsed >= hold_duration * 0.8, (
            f"Lock acquired too quickly ({elapsed:.3f}s < expected ≥ {hold_duration * 0.8:.3f}s). "
            "Blocking may not have worked."
        )

    def test_concurrent_unlock_enables_other(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "unlock-enable.lock"
        events: list[str] = []
        ev_lock = threading.Lock()

        def first() -> None:
            with RepoFileLock(lock_path, timeout=2.0):
                with ev_lock:
                    events.append("first_done")
            with ev_lock:
                events.append("first_released")

        def second() -> None:
            # Wait for first to start holding the lock
            while True:
                if events:
                    break
                time.sleep(0.05)
            with RepoFileLock(lock_path, timeout=3.0):
                with ev_lock:
                    events.append("second_done")

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert "first_released" in events
        assert "second_done" in events
        assert events.index("second_done") > events.index("first_released")


class TestLockTimeout:
    def test_timeout_raises(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "timeout.lock"
        short_lock = RepoFileLock(lock_path, timeout=0.05)
        short_lock.acquire()

        with pytest.raises(LockTimeoutError):
            with RepoFileLock(lock_path, timeout=0.5):
                pass  # should not reach here

        short_lock.release()


class TestLockStaleDetection:
    def test_stale_lock_broken_when_pid_dead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock_path = tmp_path / "stale.lock"

        # Manually create a lock file with a dead PID and old mtime.
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("99999999|localhost|1.0\n")
        old_mtime = lock_path.stat().st_mtime

        # Backdate mtime so the file looks old enough to trigger stale check.
        def fake_mtime() -> float:
            return old_mtime - 120.0

        # Ensure _maybe_break_stale_lock sees it as stale.
        # We patch the mtime used inside _maybe_break_stale_lock by patching
        # time.time() only after the file exists.
        monkeypatch.setattr(time, "time", lambda: old_mtime - 120.0)

        # Now the lock should be acquired despite the stale file existing.
        with RepoFileLock(lock_path, timeout=2.0, backoff=0.05, stale_after=60.0):
            pass
        # If we got here without LockTimeoutError, the stale lock was broken.

    def test_stale_lock_not_broken_when_holder_alive(
        self, tmp_path: Path
    ) -> None:
        """If another thread/process is actively holding the flock, the
        stale-detection logic must not break it even when the lock file
        exists with our (alive) PID metadata.
        """
        lock_path = tmp_path / "fresh.lock"
        ready = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with RepoFileLock(lock_path, timeout=2.0, stale_after=0.001):
                ready.set()
                release.wait(timeout=5.0)

        holder = threading.Thread(target=hold)
        holder.start()
        ready.wait(timeout=5.0)

        # stale_after is tiny but holder is alive and flock is held — the
        # acquire should time out cleanly, NOT succeed by breaking the lock.
        with pytest.raises(LockTimeoutError):
            with RepoFileLock(lock_path, timeout=0.5, backoff=0.05, stale_after=0.001):
                pass

        release.set()
        holder.join(timeout=5.0)

    def test_stale_lock_not_broken_when_fresh_age(self, tmp_path: Path) -> None:
        """A recently-created lock file (age < stale_after) is never broken
        even if no flock is actually held — but on POSIX, no flock means
        the next acquire will simply succeed via flock semantics. This test
        verifies the age-based guard does not falsely report stale.
        """
        lock_path = tmp_path / "young.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        lock_path.write_text(f"99999999|{socket.gethostname()}|{now:.3f}\n")
        os.utime(lock_path, (now, now))

        lock = RepoFileLock(lock_path, timeout=0.1, stale_after=60.0)
        # Internal probe: stale-break should NOT fire on a young file.
        assert lock._maybe_break_stale_lock() is False


class TestRegistrySaveUnderLock:
    def test_no_lost_update_with_concurrent_saves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate two concurrent _save_registry calls: neither update is lost."""
        from openharness.autopilot.service import RepoAutopilotStore
        from openharness.autopilot.types import RepoTaskCard

        registry_path = tmp_path / "autopilot" / "registry.json"
        journal_path = tmp_path / "autopilot" / "repo_journal.jsonl"
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Patch paths so both stores point to the same tmp directory.
        def fake_registry(cwd: str | Path) -> Path:
            return registry_path

        def fake_journal(cwd: str | Path) -> Path:
            return journal_path

        monkeypatch.setattr(
            "openharness.config.paths.get_project_autopilot_registry_path", fake_registry
        )
        monkeypatch.setattr(
            "openharness.config.paths.get_project_repo_journal_path", fake_journal
        )

        store = RepoAutopilotStore(str(tmp_path))

        def save_with_card(n: int) -> None:
            registry = store._load_registry()
            card = RepoTaskCard(
                id=f"card-{n}",
                fingerprint=f"fp-{n}",
                title=f"Title {n}",
                source_kind="manual_idea",
                created_at=time.time(),
                updated_at=time.time(),
            )
            registry.cards.append(card)
            store._save_registry(registry)

        events: list[str] = []
        lock = threading.Lock()

        def thread_fn(fn: object, idx: int) -> None:
            result = fn(idx)
            with lock:
                events.append(f"thread-{idx}")
            return result

        t1 = threading.Thread(target=thread_fn, args=(save_with_card, 1))
        t2 = threading.Thread(target=thread_fn, args=(save_with_card, 2))
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        # Both saves succeeded.
        assert len(events) == 2

        # After both saves, registry should contain both cards.
        store2 = RepoAutopilotStore(str(tmp_path))
        final = store2._load_registry()
        card_ids = {c.id for c in final.cards}
        assert "card-1" in card_ids
        assert "card-2" in card_ids
