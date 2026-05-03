"""Interprocess file lock for autopilot registry and journal.

Provides :class:`RepoFileLock`, a cross-platform context manager that
serialises read-modify-write sequences on shared autopilot artefacts
(``registry.json``, ``repo_journal.jsonl``) across multiple autopilot
processes running against the same project.

Design:
    * POSIX: ``fcntl.flock`` non-blocking, polled with backoff until the
      caller-supplied timeout elapses.
    * Windows: ``msvcrt.locking`` with ``LK_NBLCK`` polled the same way.
    * The on-disk lock file stores ``pid|hostname|acquired_ts`` so a dead
      holder can be detected and forcibly cleared after ``stale_after``
      seconds (default 60s) — this prevents a crashed process from
      wedging the queue forever.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
DEFAULT_BACKOFF = 0.1
DEFAULT_STALE_AFTER = 60.0


class LockTimeoutError(TimeoutError):
    """Raised when :class:`RepoFileLock` cannot acquire within the timeout."""


class RepoFileLock(AbstractContextManager["RepoFileLock"]):
    """Cross-platform interprocess lock for a single resource.

    Args:
        lock_path: Path to the on-disk lock file. The parent directory is
            created on demand.
        timeout: Maximum seconds to wait for the lock before raising
            :class:`LockTimeoutError`. Default 10s.
        backoff: Sleep interval between non-blocking acquire attempts.
            Default 0.1s.
        stale_after: If a lock file exists and its holder PID is dead OR
            its age exceeds this many seconds, the lock is considered
            stale and forcibly broken. Default 60s.
    """

    def __init__(
        self,
        lock_path: str | Path,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        backoff: float = DEFAULT_BACKOFF,
        stale_after: float = DEFAULT_STALE_AFTER,
    ) -> None:
        self._lock_path = Path(lock_path)
        self._timeout = float(timeout)
        self._backoff = max(float(backoff), 0.001)
        self._stale_after = float(stale_after)
        self._fd: int | None = None
        self._acquired = False

    # ------------------------------------------------------------------
    # Context-manager API
    # ------------------------------------------------------------------
    def __enter__(self) -> "RepoFileLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def acquire(self) -> None:
        """Acquire the lock, polling until ``timeout`` elapses."""
        if self._acquired:
            raise RuntimeError(f"RepoFileLock already acquired: {self._lock_path}")

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        attempts = 0

        while True:
            attempts += 1
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                if _try_lock(fd):
                    self._fd = fd
                    self._acquired = True
                    self._write_holder_metadata()
                    return
            except Exception:
                os.close(fd)
                raise
            os.close(fd)

            # Could not acquire — see if the holder is stale and reclaim.
            if self._maybe_break_stale_lock():
                continue

            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"Could not acquire {self._lock_path} within {self._timeout:.2f}s "
                    f"(attempts={attempts})"
                )
            time.sleep(self._backoff)

    def release(self) -> None:
        """Release the lock. Safe to call multiple times."""
        if not self._acquired or self._fd is None:
            return
        fd = self._fd
        self._fd = None
        self._acquired = False
        try:
            # Best-effort: clear the holder metadata before unlocking so a
            # subsequent stale-check sees an empty file rather than our PID.
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                os.ftruncate(fd, 0)
            except OSError:
                pass
            _unlock(fd)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _write_holder_metadata(self) -> None:
        if self._fd is None:
            return
        payload = f"{os.getpid()}|{socket.gethostname()}|{time.time():.3f}\n".encode(
            "utf-8"
        )
        try:
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.ftruncate(self._fd, 0)
            os.write(self._fd, payload)
        except OSError as exc:  # pragma: no cover - defensive
            log.debug("Failed to write lock holder metadata for %s: %s", self._lock_path, exc)

    def _maybe_break_stale_lock(self) -> bool:
        """Return True if a stale lock file was removed and a retry is warranted."""
        try:
            stat = self._lock_path.stat()
        except FileNotFoundError:
            return False
        except OSError:
            return False

        age = max(time.time() - stat.st_mtime, 0.0)
        try:
            text = self._lock_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            text = ""

        holder_pid: int | None = None
        holder_host: str = ""
        if text:
            parts = text.split("|")
            if parts and parts[0].isdigit():
                holder_pid = int(parts[0])
            if len(parts) >= 2:
                holder_host = parts[1]

        pid_dead = False
        if holder_pid is not None and holder_host == socket.gethostname():
            pid_dead = not _pid_alive(holder_pid)

        # Break only when both the file is older than stale_after AND
        # either the pid is dead or unknown. This avoids racing with a
        # freshly-acquired lock that has not yet written metadata.
        if age < self._stale_after:
            return False
        if holder_pid is None or pid_dead:
            log.warning(
                "Breaking stale autopilot lock %s (age=%.1fs, holder_pid=%s, host=%s)",
                self._lock_path,
                age,
                holder_pid,
                holder_host or "?",
            )
            try:
                self._lock_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.debug("Failed to remove stale lock %s: %s", self._lock_path, exc)
                return False
            return True
        return False


# ----------------------------------------------------------------------
# Platform helpers
# ----------------------------------------------------------------------
if os.name == "nt":  # pragma: no cover - exercised on Windows only
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            # Lock a single byte at offset 0 — file may be empty so seek+ensure.
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

    def _pid_alive(pid: int) -> bool:
        # Best-effort: assume alive on Windows (rely on age-based fallback).
        return True

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass

    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # The PID exists, we just can't signal it.
            return True
        except OSError:
            return False
        return True


__all__ = [
    "DEFAULT_BACKOFF",
    "DEFAULT_STALE_AFTER",
    "DEFAULT_TIMEOUT",
    "LockTimeoutError",
    "RepoFileLock",
]
