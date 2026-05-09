"""Project-level repo autopilot state, intake, and execution helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha1
from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from openharness.autopilot.locking import RepoFileLock
from openharness.autopilot.types import (
    RepoAutopilotRegistry,
    RepoJournalEntry,
    RepoRunResult,
    RepoTaskCard,
    RepoTaskSource,
    RepoTaskStatus,
    RepoVerificationStep,
)
from openharness.config import load_settings
from openharness.config.paths import (
    get_project_active_repo_context_path,
    get_project_autopilot_policy_path,
    get_project_autopilot_registry_path,
    get_project_autopilot_runs_dir,
    get_project_release_policy_path,
    get_project_repo_journal_path,
    get_project_verification_policy_path,
)
from openharness.autopilot.run_stream import (
    RunStreamWriter,
    collect_old_stream_files,
    get_or_create_writer,
    release_writer,
    set_registry_stale_seconds,
    summarize_tool_input,
    summarize_tool_output,
)
from openharness.autopilot.session_store import (
    clear_checkpoints,
    load_latest_checkpoint,
    restore_messages,
    save_checkpoint,
)
from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from openharness.swarm.worktree import WorktreeManager
from openharness.utils.fs import atomic_write_text

log = logging.getLogger(__name__)

_SOURCE_BASE_SCORES: dict[RepoTaskSource, int] = {
    "ohmo_request": 100,
    "manual_idea": 80,
    "github_issue": 75,
    "github_pr": 85,
    "claude_code_candidate": 45,
}
_BUG_HINTS = ("bug", "fix", "failure", "broken", "regression", "crash", "error", "issue")
_URGENT_HINTS = ("urgent", "p0", "p1", "high", "critical", "blocker")

_LIST_STATUS_PRIORITY = {
    "queued": 0,
    "accepted": 1,
    "preparing": 2,
    "running": 3,
    "verifying": 4,
    "pr_open": 5,
    "waiting_ci": 6,
    "repairing": 7,
    "completed": 8,
    "merged": 9,
    "failed": 10,
    "rejected": 11,
    "superseded": 12,
}

_DEFAULT_AUTOPILOT_POLICY = {
    "intake": {
        "mode": "unified_queue",
        "max_visible_candidates": 12,
        "dedupe_strategy": "source_ref_then_fingerprint",
    },
    "decision": {
        "default_human_gate": True,
        "prefer_small_safe_steps": True,
    },
    "execution": {
        "default_model": "",
        "implement_agent": "",
        "review_agent": "",
        "max_turns": 12,
        "max_parallel_runs": 2,
        "rebase_strategy": "on_conflict",
        "pr_branch_sync_strategy": "rebase",
        "max_branch_sync_attempts": 2,
        "allow_force_push_pr_branch": False,
        "permission_mode": "full_auto",
        "host_mode": "self_hosted",
        "use_worktree": True,
        "base_branch": "main",
        "max_attempts": 3,
    },
    "github": {
        "issue_comment_style": "bilingual",
        "pr_branch_prefix": "autopilot/",
        "ci_poll_interval_seconds": 20,
        "ci_timeout_seconds": 1800,
        "no_checks_grace_seconds": 60,
        "checks_settle_seconds": 20,
        "auto_merge": {
            "mode": "label_gated",
            "required_label": "autopilot:merge",
        },
        "remote_code_review": {
            "enabled": True,
            "block_on": ["critical"],
            "max_turns": 0,
            "max_diff_chars": 80000,
        },
    },
    "repair": {
        "max_rounds": 2,
        "retry_on": ["local_verification_failed", "remote_ci_failed"],
        "stop_on": ["agent_runtime_error", "git_error", "permission_error", "merge_conflict"],
    },
}
_DEFAULT_VERIFICATION_POLICY = {
    "gates": [
        "fast_gate",
        "repo_gate",
        "harness_gate",
    ],
    "commands": [
        "uv run pytest -q",
        "uv run ruff check src tests scripts",
        {
            "command": (
                "cd frontend/webui && "
                "([ -x ./node_modules/.bin/tsc ] || npm ci --no-audit --no-fund) && "
                "./node_modules/.bin/tsc --noEmit"
            ),
            "shell": True,
        },
    ],
    "require_tests_before_merge": True,
    "ignore_preexisting_failures": True,
    "code_review": {
        "enabled": True,
        "agent": "code-reviewer",
        "block_on": ["critical"],
        "diff_against": "base_branch",
        "max_diff_chars": 80000,
        "max_turns": 6,
    },
}
_DEFAULT_RELEASE_POLICY = {
    "merge_requires_human": True,
    "release_requires_human": True,
    "auto_revert_on_failed_verification": False,
}


def _shorten(text: str, *, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _resolve_agent_model(agent_key: str) -> str | None:
    try:
        from openharness.config.claude_bridge import read_claude_settings

        claude = read_claude_settings()
    except Exception:
        return None
    if claude is None:
        return None
    model_config = claude.agent_models.get(agent_key)
    if isinstance(model_config, str):
        return model_config or None
    if isinstance(model_config, list) and model_config:
        model = model_config[0]
        return model if isinstance(model, str) and model else None
    return None


def _parse_review_severity(text: str) -> str:
    """Extract the highest severity tag from a code-reviewer agent response.

    Returns one of: critical, high, medium, low, none.
    Prefers an explicit ``Severity: <LEVEL>`` line so that prose like
    "No CRITICAL issues" does not falsely elevate the result.
    Returns none when no explicit line is found.
    """
    if not text:
        return "none"
    explicit = re.search(
        r"^\s*Severity:\s*(CRITICAL|HIGH|MEDIUM|LOW|NONE)\s*$", text, re.IGNORECASE | re.MULTILINE
    )
    if explicit:
        return explicit.group(1).lower()
    return "none"


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    return str(value)


_SHELL_METACHARS = frozenset(";&|`$<>\n\r")
_VERIFICATION_ENV_CWD_KEYS = frozenset({"PWD", "OLDPWD", "INIT_CWD", "PROJECT_CWD"})


def _verification_subprocess_env(cwd: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _VERIFICATION_ENV_CWD_KEYS}
    env["PWD"] = str(cwd)
    return env


@dataclass(frozen=True)
class _VerificationCommand:
    """Parsed verification-policy entry.

    When ``shell`` is false, ``argv`` is executed with ``shell=False``.
    When ``shell`` is true, ``raw`` is handed to the shell (explicit opt-in).
    ``error`` signals a policy entry that must not be executed; callers emit
    an error step so the verification gate fails loudly.
    """

    raw: str
    argv: tuple[str, ...]
    shell: bool
    error: str | None = None


def _parse_verification_entry(entry: object) -> _VerificationCommand:
    if isinstance(entry, dict):
        raw = str(entry.get("command", "")).strip()
        if not raw:
            return _VerificationCommand(raw=str(entry), argv=(), shell=False, error="empty command")
        if bool(entry.get("shell", False)):
            return _VerificationCommand(raw=raw, argv=(), shell=True)
        # fall through and validate as an argv-form command
    elif isinstance(entry, str):
        raw = entry.strip()
        if not raw:
            return _VerificationCommand(raw=entry, argv=(), shell=False, error="empty command")
    else:
        return _VerificationCommand(
            raw=str(entry),
            argv=(),
            shell=False,
            error="entry must be a string or a mapping with a 'command' key",
        )

    if any(ch in _SHELL_METACHARS for ch in raw):
        return _VerificationCommand(
            raw=raw,
            argv=(),
            shell=False,
            error=(
                "command contains shell metacharacters; use the mapping form "
                "{command: '...', shell: true} in verification_policy.yaml to opt in"
            ),
        )
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        return _VerificationCommand(
            raw=raw,
            argv=(),
            shell=False,
            error=f"could not tokenize command: {exc}",
        )
    if not argv:
        return _VerificationCommand(raw=raw, argv=(), shell=False, error="empty command")
    return _VerificationCommand(raw=raw, argv=tuple(argv), shell=False)


def _looks_available(command: str, cwd: Path) -> bool:
    import re as _re

    lowered = command.lower()
    if lowered.startswith("uv "):
        return (cwd / "pyproject.toml").exists()
    if "ruff check" in lowered:
        return (cwd / "pyproject.toml").exists()
    if "pytest" in lowered:
        return (cwd / "tests").exists()
    m = _re.search(r"\bcd\s+([\w./\-]+)", command)
    if m:
        return (cwd / m.group(1)).exists()
    if "tsc" in lowered:
        return (cwd / "frontend" / "webui" / "package.json").exists()
    return True


def _source_ref_number(source_ref: str, prefix: str) -> int | None:
    normalized = source_ref.strip()
    if not normalized.startswith(f"{prefix}:"):
        return None
    try:
        return int(normalized.split(":", 1)[1])
    except ValueError:
        return None


def _bilingual_lines(zh: str, en: str) -> str:
    return f"{zh}\n{en}".strip()


class RepoAutopilotStore:
    """Persist and query project-level autopilot state."""

    def __init__(self, cwd: str | Path) -> None:
        self._cwd = Path(cwd).resolve()
        self._registry_path = get_project_autopilot_registry_path(self._cwd)
        self._journal_path = get_project_repo_journal_path(self._cwd)
        self._context_path = get_project_active_repo_context_path(self._cwd)
        self._runs_dir = get_project_autopilot_runs_dir(self._cwd)
        # Lock files live next to the artefacts they protect so a single
        # autopilot directory mkdir already provisions them.
        self._registry_lock_path = self._registry_path.parent / "registry.lock"
        self._journal_lock_path = self._journal_path.parent / "journal.lock"
        self._main_checkout_lock_path = self._registry_path.parent / "main-checkout.lock"
        self._repo_full_name: str | None = None
        self._ensure_layout()
        self._startup_cleanup_task: asyncio.Task[list[str]] | None = None
        self._start_startup_cleanup()

    @property
    def registry_path(self) -> Path:
        return self._registry_path

    @property
    def journal_path(self) -> Path:
        return self._journal_path

    @property
    def context_path(self) -> Path:
        return self._context_path

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir

    def _lock_path(self) -> Path:
        return self._registry_path.parent / "registry.lock"

    def pick_and_claim_card(self, worker_id: str) -> "RepoTaskCard | None":
        """Atomically pick the highest-priority queued card and claim it for a worker.

        This avoids the race condition between pick_next_card() and update_status()
        by performing the read-modify-write under an exclusive file lock.

        Uses :class:`RepoFileLock` directly (the same primitive that
        ``_load_registry``/``_save_registry`` use internally) so the outer and
        inner critical sections share one open-file-description and don't
        deadlock against each other via two independent ``flock`` holders.
        """
        with RepoFileLock(self._registry_lock_path):
            if not self._registry_path.exists():
                return None
            try:
                payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            registry = RepoAutopilotRegistry.model_validate(payload)
            queued = [card for card in registry.cards if card.status in {"queued", "accepted"}]
            if not queued:
                return None
            chosen = sorted(
                queued, key=lambda card: (-card.score, card.created_at, card.title.lower())
            )[0]
            chosen.status = "preparing"
            chosen.updated_at = time.time()
            chosen.metadata["worker_id"] = worker_id
            registry.updated_at = time.time()
            atomic_write_text(
                self._registry_path,
                json.dumps(
                    registry.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    default=_json_default,
                )
                + "\n",
            )
            return chosen

    def list_cards(self, *, status: RepoTaskStatus | None = None) -> list[RepoTaskCard]:
        cards = self._load_registry().cards
        if status is not None:
            cards = [card for card in cards if card.status == status]
        return sorted(
            cards,
            key=lambda card: (
                _LIST_STATUS_PRIORITY.get(card.status, 8),
                -card.score,
                card.created_at,
                card.title.lower(),
            ),
        )

    _ACTIVE_STATUSES = frozenset(
        {"preparing", "running", "verifying", "repairing", "waiting_ci", "pr_open"}
    )

    def count_active_cards(self) -> int:
        """Return the number of cards currently in an active execution state."""
        return sum(
            1 for card in self._load_registry().cards if card.status in self._ACTIVE_STATUSES
        )

    _WORKER_OWNED_STATUSES = frozenset({"preparing", "running", "verifying"})

    def _reap_dead_worker_cards(self) -> list[str]:
        """Reset cards whose worker process has died back to queued.

        Only cards in preparing/running/verifying with a worker_id of the form
        'pid-<PID>-<token>' are eligible — waiting_ci/pr_open/repairing are managed
        by the CI-poll loop and must not be reset here.
        """
        reaped: list[str] = []
        registry = self._load_registry()
        changed = False
        for card in registry.cards:
            if card.status not in self._WORKER_OWNED_STATUSES:
                continue
            worker_id = _safe_text(card.metadata.get("worker_id"))
            if not worker_id:
                continue
            parts = worker_id.split("-")
            if len(parts) < 2 or parts[0] != "pid":
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            try:
                os.kill(pid, 0)  # signal 0: check existence only
            except ProcessLookupError:
                pass
            else:
                # PID exists — but for `preparing` cards that haven't created a
                # worktree yet, the PID may belong to a different process that
                # reused the slot after the original worker was killed.  If the
                # worktree_path is absent AND status is still `preparing`, treat
                # this as a stale claim regardless of PID liveness.
                if card.status == "preparing":
                    worktree_path = _safe_text(card.metadata.get("worktree_path"))
                    if not worktree_path or not Path(worktree_path).exists():
                        pass  # fall through to requeue
                    else:
                        continue  # worktree exists — real active worker
                else:
                    continue  # process alive — leave it alone
            # PID is gone: reset to queued so the next run_next picks it up
            card.status = "queued"
            card.updated_at = time.time()
            card.metadata["last_note"] = f"worker {worker_id} died; requeued"
            card.metadata.pop("worker_id", None)
            reaped.append(card.id)
            changed = True
            log.warning("Reaped dead-worker card %s (worker %s)", card.id, worker_id)
        if changed:
            registry.updated_at = time.time()
            atomic_write_text(
                self._registry_path,
                json.dumps(registry.model_dump(mode="json"), ensure_ascii=False, indent=2),
            )
            self.append_journal(
                kind="dead_worker_reaped",
                summary=f"reaped {len(reaped)} dead-worker card(s): {', '.join(reaped)}",
            )
        return reaped

    def has_capacity(self, policies: dict[str, Any]) -> bool:
        """Return True when fewer active cards are running than max_parallel_runs allows."""
        max_parallel = int(
            policies.get("autopilot", {})
            .get("execution", {})
            .get("max_parallel_runs", _DEFAULT_AUTOPILOT_POLICY["execution"]["max_parallel_runs"])
        )
        return self.count_active_cards() < max_parallel

    def get_card(self, card_id: str) -> RepoTaskCard | None:
        for card in self._load_registry().cards:
            if card.id == card_id:
                return card
        return None

    def update_card_model(self, card_id: str, model: str | None) -> RepoTaskCard:
        registry = self._load_registry()
        card = next((item for item in registry.cards if item.id == card_id), None)
        if card is None:
            raise ValueError(f"No autopilot card found with ID: {card_id}")
        card.model = _safe_text(model) or None
        card.updated_at = time.time()
        self._save_registry(registry)
        self.append_journal(
            kind="card_model_updated",
            summary=f"Updated model for card {card.id}: {card.model or 'none'}",
            task_id=card.id,
        )
        self.rebuild_active_context()
        return card

    def enqueue_card(
        self,
        *,
        source_kind: RepoTaskSource,
        title: str,
        body: str = "",
        source_ref: str = "",
        labels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> tuple[RepoTaskCard, bool]:
        registry = self._load_registry()
        now = time.time()
        normalized_title = title.strip()
        normalized_body = body.strip()
        normalized_ref = source_ref.strip()
        normalized_model = _safe_text(model) or None
        fingerprint = self._build_fingerprint(
            source_kind=source_kind,
            source_ref=normalized_ref,
            title=normalized_title,
            body=normalized_body,
        )
        existing = next((card for card in registry.cards if card.fingerprint == fingerprint), None)
        merged_labels = self._normalize_labels(labels)
        merged_metadata = dict(metadata or {})
        normalized_model = _safe_text(model) or None
        if existing is not None:
            if normalized_title:
                existing.title = normalized_title
            if normalized_body:
                existing.body = normalized_body
            if normalized_ref:
                existing.source_ref = normalized_ref
            existing.labels = self._merge_labels(existing.labels, merged_labels)
            existing.metadata.update(merged_metadata)
            if normalized_model is not None:
                existing.model = normalized_model
            existing.updated_at = now
            existing.score, existing.score_reasons = self._score_card(existing)
            self._save_registry(registry)
            self.append_journal(
                kind="intake_refresh",
                summary=f"Refreshed intake card {existing.id}: {existing.title}",
                task_id=existing.id,
                metadata={"source_kind": existing.source_kind, "source_ref": existing.source_ref},
            )
            self.rebuild_active_context()
            return existing, False

        card = RepoTaskCard(
            id=f"ap-{uuid4().hex[:8]}",
            fingerprint=fingerprint,
            title=normalized_title or "Untitled intake item",
            body=normalized_body,
            source_kind=source_kind,
            source_ref=normalized_ref,
            labels=merged_labels,
            metadata=merged_metadata,
            model=normalized_model,
            created_at=now,
            updated_at=now,
        )
        card.score, card.score_reasons = self._score_card(card)
        registry.cards.append(card)
        self._save_registry(registry)
        self.append_journal(
            kind="intake_added",
            summary=f"Queued {card.source_kind}: {card.title}",
            task_id=card.id,
            metadata={"source_ref": card.source_ref, "score": card.score},
        )
        self.rebuild_active_context()
        return card, True

    def pick_next_card(self) -> RepoTaskCard | None:
        queued = [
            card for card in self._load_registry().cards if card.status in {"queued", "accepted"}
        ]
        if not queued:
            return None
        return sorted(queued, key=lambda card: (-card.score, card.created_at, card.title.lower()))[
            0
        ]

    def pick_specific_card(self, card_id: str, worker_id: str) -> RepoTaskCard | None:
        """Claim a specific card by ID for a worker (used for direct card control).

        Returns None if the card does not exist or is not in a claimable state.
        """
        with RepoFileLock(self._registry_lock_path):
            if not self._registry_path.exists():
                return None
            try:
                payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            registry = RepoAutopilotRegistry.model_validate(payload)
            chosen = next((c for c in registry.cards if c.id == card_id), None)
            if chosen is None:
                return None
            if chosen.status not in {"queued", "accepted"}:
                return None
            chosen.status = "preparing"
            chosen.updated_at = time.time()
            chosen.metadata["worker_id"] = worker_id
            registry.updated_at = time.time()
            atomic_write_text(
                self._registry_path,
                json.dumps(
                    registry.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    default=_json_default,
                )
                + "\n",
            )
            return chosen

    def update_status(
        self,
        card_id: str,
        *,
        status: RepoTaskStatus,
        note: str | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> RepoTaskCard:
        registry = self._load_registry()
        card = next((item for item in registry.cards if item.id == card_id), None)
        if card is None:
            raise ValueError(f"No autopilot card found with ID: {card_id}")
        card.status = status
        card.updated_at = time.time()
        if note:
            card.metadata["last_note"] = note.strip()
        if metadata_updates:
            card.metadata.update(metadata_updates)
        card.score, card.score_reasons = self._score_card(card)
        self._save_registry(registry)
        summary = f"{status}: {card.title}"
        if note:
            summary = f"{summary} ({_shorten(note, limit=80)})"
        self.append_journal(kind=f"status_{status}", summary=summary, task_id=card.id)
        self.rebuild_active_context()
        return card

    def load_journal(self, *, limit: int = 12) -> list[RepoJournalEntry]:
        if not self._journal_path.exists():
            return []
        entries: list[RepoJournalEntry] = []
        for line in self._journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(RepoJournalEntry.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
        return entries[-limit:]

    def append_journal(
        self,
        *,
        kind: str,
        summary: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RepoJournalEntry:
        entry = RepoJournalEntry(
            timestamp=time.time(),
            kind=kind,
            summary=summary.strip(),
            task_id=task_id,
            metadata=metadata or {},
        )
        with RepoFileLock(self._journal_lock_path):
            with self._journal_path.open("a", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json() + "\n")
        return entry

    def load_active_context(self) -> str:
        if not self._context_path.exists():
            return ""
        return self._context_path.read_text(encoding="utf-8", errors="replace").strip()

    def rebuild_active_context(self) -> str:
        cards = self._load_registry().cards
        running = [
            card
            for card in cards
            if card.status in {"preparing", "running", "verifying", "waiting_ci", "repairing"}
        ]
        accepted = [card for card in cards if card.status in {"accepted", "pr_open"}]
        queued = [card for card in cards if card.status == "queued"]
        completed = [card for card in cards if card.status in {"completed", "merged"}]
        failed = [card for card in cards if card.status in {"failed", "rejected"}]
        focus = None
        for group in (running, accepted, queued):
            if group:
                focus = sorted(
                    group,
                    key=lambda card: (-card.score, card.created_at, card.title.lower()),
                )[0]
                break

        lines = [
            "# Active Repo Context",
            "",
            f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            "",
            "## Current Task Focus",
        ]
        if focus is None:
            lines.append("- No active repo task focus yet.")
        else:
            lines.append(
                f"- [{focus.status}] {focus.title} ({focus.source_kind}, score={focus.score})"
            )
            if focus.body:
                lines.append(f"- Detail: {_shorten(focus.body, limit=220)}")

        lines.extend(["", "## In Progress"])
        for card in sorted(running + accepted, key=lambda item: (-item.score, item.created_at))[:6]:
            lines.append(f"- [{card.status}] {card.id} {card.title} ({card.source_kind})")
        if not running and not accepted:
            lines.append("- None.")

        lines.extend(["", "## Next Up"])
        for card in sorted(queued, key=lambda item: (-item.score, item.created_at))[:8]:
            lines.append(f"- [{card.score}] {card.id} {card.title} ({card.source_kind})")
        if not queued:
            lines.append("- No queued items.")

        lines.extend(["", "## Recently Completed"])
        for card in sorted(completed, key=lambda item: item.updated_at, reverse=True)[:5]:
            lines.append(f"- {card.id} {card.title}")
        if not completed:
            lines.append("- None yet.")

        lines.extend(["", "## Recent Failures"])
        for card in sorted(failed, key=lambda item: item.updated_at, reverse=True)[:5]:
            lines.append(f"- [{card.status}] {card.id} {card.title}")
        if not failed:
            lines.append("- None.")

        lines.extend(["", "## Recent Repo Journal"])
        journal = self.load_journal(limit=8)
        if journal:
            for entry in journal:
                lines.append(
                    f"- {time.strftime('%m-%d %H:%M', time.gmtime(entry.timestamp))} "
                    f"{entry.kind}: {entry.summary}"
                )
        else:
            lines.append("- Journal is empty.")

        lines.extend(
            [
                "",
                "## Policies",
                f"- Autopilot: {get_project_autopilot_policy_path(self._cwd)}",
                f"- Verification: {get_project_verification_policy_path(self._cwd)}",
                f"- Release: {get_project_release_policy_path(self._cwd)}",
            ]
        )
        content = "\n".join(lines).strip() + "\n"
        atomic_write_text(self._context_path, content)
        self.export_dashboard()
        return content

    def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for card in self._load_registry().cards:
            counts[card.status] = counts.get(card.status, 0) + 1
        return counts

    def load_policies(self) -> dict[str, Any]:
        return {
            "autopilot": self._read_yaml(
                get_project_autopilot_policy_path(self._cwd), _DEFAULT_AUTOPILOT_POLICY
            ),
            "verification": self._read_yaml(
                get_project_verification_policy_path(self._cwd),
                _DEFAULT_VERIFICATION_POLICY,
            ),
            "release": self._read_yaml(
                get_project_release_policy_path(self._cwd), _DEFAULT_RELEASE_POLICY
            ),
        }

    def scan_github_issues(self, *, limit: int = 10) -> list[RepoTaskCard]:
        raw = self._run_gh_json(
            [
                "gh",
                "issue",
                "list",
                "--state",
                "open",
                "--limit",
                str(limit),
                "--json",
                "number,title,body,labels,updatedAt,url",
            ]
        )
        cards: list[RepoTaskCard] = []
        for item in raw:
            number = item.get("number")
            if number is None:
                continue
            labels = [str(label.get("name", "")).strip() for label in item.get("labels", [])]
            card, _ = self.enqueue_card(
                source_kind="github_issue",
                source_ref=f"issue:{number}",
                title=f"GitHub issue #{number}: {_safe_text(item.get('title'))}",
                body=_safe_text(item.get("body")),
                labels=[label for label in labels if label],
                metadata={
                    "url": _safe_text(item.get("url")),
                    "updated_at_remote": _safe_text(item.get("updatedAt")),
                },
            )
            cards.append(card)
        return cards

    def scan_github_prs(self, *, limit: int = 10) -> list[RepoTaskCard]:
        raw = self._run_gh_json(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                str(limit),
                "--json",
                "number,title,body,isDraft,reviewDecision,mergeStateStatus,updatedAt,url,labels,headRefName,baseRefName",
            ]
        )
        cards: list[RepoTaskCard] = []
        for item in raw:
            number = item.get("number")
            if number is None:
                continue
            labels = [str(label.get("name", "")).strip() for label in item.get("labels", [])]
            card, _ = self.enqueue_card(
                source_kind="github_pr",
                source_ref=f"pr:{number}",
                title=f"GitHub PR #{number}: {_safe_text(item.get('title'))}",
                body=_safe_text(item.get("body")),
                labels=[label for label in labels if label],
                metadata={
                    "url": _safe_text(item.get("url")),
                    "updated_at_remote": _safe_text(item.get("updatedAt")),
                    "is_draft": bool(item.get("isDraft")),
                    "review_decision": _safe_text(item.get("reviewDecision")),
                    "merge_state_status": _safe_text(item.get("mergeStateStatus")),
                    "head_ref_name": _safe_text(item.get("headRefName")),
                    "base_ref_name": _safe_text(item.get("baseRefName")),
                },
            )
            cards.append(card)
        return cards

    def scan_claude_code_candidates(
        self,
        *,
        limit: int = 10,
        root: str | Path | None = None,
    ) -> list[RepoTaskCard]:
        candidate_root = Path(root or Path.home() / "claude-code").expanduser().resolve()
        if not candidate_root.exists():
            raise ValueError(f"claude-code root not found: {candidate_root}")
        discovered: list[tuple[str, Path]] = []
        for dirname, label in (("commands", "command"), ("agents", "agent")):
            base = candidate_root / dirname
            if not base.exists():
                continue
            for path in sorted(base.iterdir(), key=lambda item: item.name.lower()):
                if path.name.startswith("."):
                    continue
                discovered.append((label, path))
        cards: list[RepoTaskCard] = []
        for label, path in discovered[:limit]:
            name = path.stem if path.is_file() else path.name
            card, _ = self.enqueue_card(
                source_kind="claude_code_candidate",
                source_ref=f"{label}:{path}",
                title=f"Evaluate claude-code {label}: {name}",
                body=(
                    f"Borrow candidate from {path}. "
                    "Review whether this should be aligned, adapted, or ignored for OpenHarness."
                ),
                metadata={"path": str(path)},
            )
            cards.append(card)
        return cards

    def scan_all_sources(self, *, issue_limit: int = 10, pr_limit: int = 10) -> dict[str, int]:
        counts = {"github_issue": 0, "github_pr": 0, "claude_code_candidate": 0}
        # GitHub issue scan disabled — upstream issues are not actionable in this fork
        # try:
        #     counts["github_issue"] = len(self.scan_github_issues(limit=issue_limit))
        # except Exception as exc:
        #     self.append_journal(kind="scan_warning", summary=f"GitHub issue scan failed: {exc}")
        try:
            counts["github_pr"] = len(self.scan_github_prs(limit=pr_limit))
        except Exception as exc:
            self.append_journal(kind="scan_warning", summary=f"GitHub PR scan failed: {exc}")
        try:
            counts["claude_code_candidate"] = len(self.scan_claude_code_candidates(limit=8))
        except Exception as exc:
            self.append_journal(kind="scan_warning", summary=f"claude-code scan failed: {exc}")
        self.append_journal(kind="scan_all", summary=f"Scanned sources: {counts}")
        self.rebuild_active_context()
        return counts

    async def run_next(
        self,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
        card_id: str | None = None,
    ) -> RepoRunResult:
        self._reap_dead_worker_cards()
        policies = self.load_policies()
        if not self.has_capacity(policies):
            raise ValueError("Maximum parallel runs reached.")
        worker_id = f"pid-{os.getpid()}-{uuid4().hex[:8]}"
        card = self.pick_specific_card(card_id, worker_id) if card_id else self.pick_and_claim_card(worker_id)
        if card is None:
            raise ValueError("No queued autopilot cards." if card_id is None else f"No queued autopilot card found with ID: {card_id}")
        return await self.run_card(
            card.id,
            model=model,
            max_turns=max_turns,
            permission_mode=permission_mode,
            _claimed_by=worker_id,
        )

    async def run_card(
        self,
        card_id: str,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
        _claimed_by: str | None = None,
    ) -> RepoRunResult:
        card = self.get_card(card_id)
        if card is None:
            raise ValueError(f"No autopilot card found with ID: {card_id}")
        if card.status in {"preparing", "running", "verifying", "waiting_ci", "repairing"}:
            # Allow re-entry if we just claimed this card ourselves
            if not (_claimed_by and card.metadata.get("worker_id") == _claimed_by):
                raise ValueError(f"Autopilot card {card.id} is already active.")

        policies = self.load_policies()
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        _stale_ttl_hours = float(execution.get("stream_registry_stale_hours", 1))
        set_registry_stale_seconds(_stale_ttl_hours * 3600)
        _implement_agent = _safe_text(execution.get("implement_agent"))
        _review_agent = _safe_text(execution.get("review_agent"))
        effective_model = (
            model
            or card.model
            or (_implement_agent and _resolve_agent_model(_implement_agent))
            or _safe_text(execution.get("default_model"))
            or None
        )
        effective_review_model = (
            _review_agent and _resolve_agent_model(_review_agent)
        ) or effective_model
        if max_turns is not None:
            effective_max_turns = max_turns
        else:
            raw_max_turns = execution.get("max_turns", 12)
            effective_max_turns = None if raw_max_turns in (None, "", 0) else int(raw_max_turns)
        effective_permission_mode = permission_mode or _safe_text(
            execution.get("permission_mode", "full_auto")
        )
        max_attempts = self._max_attempts(policies)
        base_branch = self._base_branch(policies)
        head_branch = self._head_branch(card, policies)
        issue_number = self._issue_number_for_card(card)
        linked_pr_number = self._linked_pr_number(card)
        use_worktree = bool(execution.get("use_worktree", True)) and self._is_git_repo(self._cwd)

        if linked_pr_number is not None and (
            (card.source_kind == "github_pr" and not card.metadata.get("autopilot_managed"))
            or (
                card.metadata.get("last_failure_stage") == "repair_exhausted"
                and int(card.metadata.get("attempt_count", 0) or 0) >= max_attempts
            )
        ):
            return await self._process_existing_pr_card(card, linked_pr_number, policies)
        if linked_pr_number is not None:
            pr_snapshot = self._pr_status_snapshot(linked_pr_number)
            if _safe_text(pr_snapshot.get("state")).upper() == "MERGED":
                pr_url = _safe_text(pr_snapshot.get("url", ""))
                self.update_status(
                    card.id,
                    status="merged",
                    note=f"linked PR #{linked_pr_number} already merged",
                    metadata_updates={
                        "linked_pr_number": linked_pr_number,
                        "linked_pr_url": pr_url,
                        "human_gate_pending": False,
                    },
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="merged",
                    run_report_path=str(self._runs_dir / f"{card.id}-run.md"),
                    verification_report_path=str(self._runs_dir / f"{card.id}-verification.md"),
                    pr_number=linked_pr_number,
                    pr_url=pr_url,
                )

        if (
            linked_pr_number is not None
            and bool(card.metadata.get("autopilot_managed"))
            # Skip CI-monitor path when card is requeued for repair — let the main
            # repair loop run the agent to actually fix the failing tests.
            and card.metadata.get("last_failure_stage") != "remote_ci_failed"
        ):
            ci_state, ci_summary, pr_snapshot, _checks = await self._wait_for_pr_ci(
                linked_pr_number, policies
            )
            pr_url = _safe_text(pr_snapshot.get("url"))
            if ci_state == "success" and self._automerge_eligible(pr_snapshot, policies):
                self._merge_pull_request(linked_pr_number)
                self.update_status(
                    card.id,
                    status="merged",
                    note=f"autopilot managed PR #{linked_pr_number} CI passed, merged automatically",
                    metadata_updates={
                        "linked_pr_number": linked_pr_number,
                        "linked_pr_url": pr_url,
                    },
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="merged",
                    run_report_path="",
                    verification_report_path="",
                    pr_number=linked_pr_number,
                    pr_url=pr_url,
                )
            if ci_state != "success":
                if ci_state == "pending":
                    self.update_status(
                        card.id,
                        status="waiting_ci",
                        note=f"autopilot managed PR #{linked_pr_number} CI still running, waiting",
                        metadata_updates={
                            "linked_pr_number": linked_pr_number,
                            "linked_pr_url": pr_url,
                        },
                    )
                    return RepoRunResult(
                        card_id=card.id,
                        status="waiting_ci",
                        run_report_path="",
                        verification_report_path="",
                        pr_number=linked_pr_number,
                        pr_url=pr_url,
                    )
                repeat_meta = self._failure_repeat_metadata(
                    card, stage="remote_ci_failed", summary=ci_summary
                )
                ci_meta = {
                    "linked_pr_number": linked_pr_number,
                    "linked_pr_url": pr_url,
                    "last_failure_stage": "remote_ci_failed",
                    "last_failure_summary": ci_summary,
                    **repeat_meta,
                }
                if (
                    int(card.metadata.get("attempt_count", 0) or 0) < max_attempts
                    and repeat_meta["repeated_failure_count"]
                    < self._max_repeated_failure_attempts(policies)
                ):
                    self.update_status(
                        card.id,
                        status="queued",
                        note=f"autopilot managed PR #{linked_pr_number} CI failed; queued repair retry",
                        metadata_updates=ci_meta,
                    )
                    return RepoRunResult(
                        card_id=card.id,
                        status="queued",
                        run_report_path="",
                        verification_report_path="",
                        pr_number=linked_pr_number,
                        pr_url=pr_url,
                    )
                self.update_status(
                    card.id,
                    status="failed",
                    note=f"autopilot managed PR #{linked_pr_number} CI failed: {ci_summary}",
                    metadata_updates=ci_meta,
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    run_report_path="",
                    verification_report_path="",
                    pr_number=linked_pr_number,
                    pr_url=pr_url,
                )

        # autopilot_managed cards with linked PR + CI pass: merge directly, skip repair loop
        if (
            linked_pr_number is not None
            and bool(card.metadata.get("autopilot_managed"))
            and card.metadata.get("last_failure_stage") != "remote_ci_failed"
        ):
            ci_state, ci_summary, pr_snapshot, _checks = await self._wait_for_pr_ci(
                linked_pr_number, policies
            )
            pr_url = _safe_text(pr_snapshot.get("url"))
            if ci_state == "success" and self._automerge_eligible(pr_snapshot, policies):
                self._merge_pull_request(linked_pr_number)
                self.update_status(
                    card.id,
                    status="merged",
                    note=f"autopilot managed PR #{linked_pr_number} CI passed, merged automatically",
                    metadata_updates={
                        "linked_pr_number": linked_pr_number,
                        "linked_pr_url": pr_url,
                    },
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="merged",
                    run_report_path="",
                    verification_report_path="",
                    pr_number=linked_pr_number,
                    pr_url=pr_url,
                )
            # CI not yet passed or not eligible — stay in waiting_ci, don't re-run
            if ci_state != "success":
                # Pending CI: update status and return so tick can check later
                if ci_state == "pending":
                    self.update_status(
                        card.id,
                        status="waiting_ci",
                        note=f"autopilot managed PR #{linked_pr_number} CI still running, waiting",
                        metadata_updates={
                            "linked_pr_number": linked_pr_number,
                            "linked_pr_url": pr_url,
                        },
                    )
                    return RepoRunResult(
                        card_id=card.id,
                        status="waiting_ci",
                        run_report_path="",
                        verification_report_path="",
                        pr_number=linked_pr_number,
                        pr_url=pr_url,
                    )
                # Failed CI
                repeat_meta = self._failure_repeat_metadata(
                    card, stage="remote_ci_failed", summary=ci_summary
                )
                ci_meta = {
                    "linked_pr_number": linked_pr_number,
                    "linked_pr_url": pr_url,
                    "last_failure_stage": "remote_ci_failed",
                    "last_failure_summary": ci_summary,
                    **repeat_meta,
                }
                if (
                    int(card.metadata.get("attempt_count", 0) or 0) < max_attempts
                    and repeat_meta["repeated_failure_count"]
                    < self._max_repeated_failure_attempts(policies)
                ):
                    self.update_status(
                        card.id,
                        status="queued",
                        note=f"autopilot managed PR #{linked_pr_number} CI failed; queued repair retry",
                        metadata_updates=ci_meta,
                    )
                    return RepoRunResult(
                        card_id=card.id,
                        status="queued",
                        run_report_path="",
                        verification_report_path="",
                        pr_number=linked_pr_number,
                        pr_url=pr_url,
                    )
                self.update_status(
                    card.id,
                    status="failed",
                    note=f"autopilot managed PR #{linked_pr_number} CI failed: {ci_summary}",
                    metadata_updates=ci_meta,
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    run_report_path="",
                    verification_report_path="",
                    pr_number=linked_pr_number,
                    pr_url=pr_url,
                )

        worktree_manager = WorktreeManager()
        worktree_info = None
        working_cwd = self._cwd
        current_run_report = self._runs_dir / f"{card.id}-run.md"
        current_verification_report = self._runs_dir / f"{card.id}-verification.md"
        existing_attempts = int(card.metadata.get("attempt_count", 0) or 0)
        try:
            if use_worktree:
                worktree_info = await worktree_manager.create_worktree(
                    self._cwd,
                    self._worktree_slug(card),
                    branch=head_branch,
                )
                working_cwd = worktree_info.path
            self.update_status(
                card.id,
                status="preparing",
                note="preparing isolated worktree" if use_worktree else "preparing local execution",
                metadata_updates={
                    "run_started_at": time.time(),
                    "execution_model": effective_model or "",
                    "max_attempts": max_attempts,
                    "worktree_slug": self._worktree_slug(card),
                    "worktree_path": str(working_cwd),
                    "head_branch": head_branch,
                    "base_branch": base_branch,
                    "linked_issue_numbers": [issue_number] if issue_number is not None else [],
                    "linked_pr_number": linked_pr_number,
                },
            )

            if issue_number is not None and existing_attempts == 0:
                self._comment_on_issue(
                    issue_number, self._comment_started(card, existing_attempts + 1)
                )

            prior_summary = _safe_text(card.metadata.get("assistant_summary_preview"))
            prior_failure_stage = _safe_text(card.metadata.get("last_failure_stage"))
            prior_failure_summary = _safe_text(card.metadata.get("last_failure_summary"))
            stream_writer = get_or_create_writer(card.id, self._runs_dir)
            try:
                for attempt_count in range(existing_attempts + 1, max_attempts + 1):
                    attempt_run_report = (
                        self._runs_dir / f"{card.id}-attempt-{attempt_count:02d}-run.md"
                    )
                    attempt_verification_report = (
                        self._runs_dir / f"{card.id}-attempt-{attempt_count:02d}-verification.md"
                    )
                    is_first_attempt = attempt_count == 1 and existing_attempts == 0
                    if use_worktree:
                        try:
                            self._sync_worktree_to_base(
                                working_cwd,
                                base_branch=base_branch,
                                head_branch=head_branch,
                                reset=is_first_attempt,
                                rebase_strategy=self._rebase_strategy(policies),
                                card_id=card.id,
                            )
                        except Exception as exc:
                            summary = f"Failed to prepare worktree branch: {exc}"
                            self.update_status(
                                card.id,
                                status="failed",
                                note=summary,
                                metadata_updates={
                                    "last_failure_stage": "git_prepare_failed",
                                    "last_failure_summary": summary,
                                },
                            )
                            self.append_journal(kind="run_failed", summary=summary, task_id=card.id)
                            return RepoRunResult(
                                card_id=card.id,
                                status="failed",
                                run_report_path=str(current_run_report),
                                verification_report_path=str(current_verification_report),
                                attempt_count=attempt_count,
                                worktree_path=str(working_cwd),
                            )

                    self.update_status(
                        card.id,
                        status="repairing" if attempt_count > 1 else "running",
                        note="repairing failed run"
                        if attempt_count > 1
                        else "autopilot execution started",
                        metadata_updates={"attempt_count": attempt_count},
                    )
                    prompt = self._prepare_repair_prompt(
                        card,
                        policies,
                        attempt_count=attempt_count,
                        prior_summary=prior_summary,
                        failure_stage=prior_failure_stage,
                        failure_summary=prior_failure_summary,
                    )
                    resume_msgs: list[Any] | None = None
                    resume_requested = bool(card.metadata.get("resume_requested"))
                    if resume_requested:
                        ckpt = load_latest_checkpoint(self._runs_dir, card.id)
                        _resume_ttl_hours = float(
                            (policies.get("autopilot", {}).get("execution", {}) or {}).get(
                                "resume_ttl_hours", 24
                            )
                        )
                        _resume_ttl_secs = _resume_ttl_hours * 3600
                        if (
                            ckpt is not None
                            and ckpt.has_pending_continuation
                            and ckpt.phase == "implement"
                            and (time.time() - ckpt.saved_at) < _resume_ttl_secs
                        ):
                            resume_msgs = restore_messages(ckpt)
                            stream_writer.emit(
                                "resume_started",
                                {
                                    "phase": ckpt.phase,
                                    "attempt": attempt_count,
                                    "saved_at": ckpt.saved_at,
                                },
                            )
                    stream_writer.emit(
                        "phase_start",
                        {
                            "phase": "implement",
                            "attempt": attempt_count,
                            "resumed": resume_msgs is not None,
                        },
                    )
                    try:
                        assistant_summary = await self._run_agent_prompt(
                            prompt,
                            model=effective_model,
                            max_turns=effective_max_turns,
                            permission_mode=effective_permission_mode,
                            cwd=working_cwd,
                            stream=stream_writer,
                            phase="implement",
                            checkpoint_card_id=card.id,
                            checkpoint_phase="implement",
                            checkpoint_attempt=attempt_count,
                            resume_messages=resume_msgs,
                        )
                        if resume_requested:
                            self.update_status(
                                card.id,
                                status=card.status,
                                metadata_updates={
                                    "resume_requested": False,
                                    "resume_available": False,
                                    "resume_phase": "",
                                },
                            )
                    except Exception as exc:
                        stream_writer.emit(
                            "phase_end",
                            {"phase": "implement", "attempt": attempt_count, "ok": False},
                        )
                        import traceback as _tb

                        tb_text = _tb.format_exc()
                        failure_text = self._render_run_report(
                            card,
                            agent_summary=f"Autopilot execution failed: {exc}\n\nTraceback:\n```\n{tb_text}\n```",
                            verification_steps=[],
                            verification_status="not_started",
                        )
                        for path in (attempt_run_report, current_run_report):
                            atomic_write_text(path, failure_text)
                        summary = f"agent execution failed: {exc}"
                        ckpt_after_fail = load_latest_checkpoint(self._runs_dir, card.id)
                        resume_meta: dict[str, Any] = {
                            "execution_error": str(exc),
                            "last_failure_stage": "agent_runtime_error",
                            "last_failure_summary": summary,
                        }
                        if ckpt_after_fail and ckpt_after_fail.has_pending_continuation:
                            resume_meta["resume_available"] = True
                            resume_meta["resume_phase"] = ckpt_after_fail.phase
                        self.update_status(
                            card.id,
                            status="failed",
                            note=summary,
                            metadata_updates=resume_meta,
                        )
                        self.append_journal(
                            kind="run_failed",
                            summary=f"{card.title}: agent execution failed",
                            task_id=card.id,
                            metadata={"error": str(exc), "attempt_count": attempt_count},
                        )
                        if issue_number is not None:
                            self._comment_on_issue(
                                issue_number, self._comment_terminal_failure(summary)
                            )
                        return RepoRunResult(
                            card_id=card.id,
                            status="failed",
                            assistant_summary=failure_text.strip(),
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=[],
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                        )

                    stream_writer.emit(
                        "phase_end", {"phase": "implement", "attempt": attempt_count, "ok": True}
                    )

                    pending_report = self._render_run_report(
                        card,
                        agent_summary=assistant_summary,
                        verification_steps=[],
                        verification_status="pending",
                    )
                    for path in (attempt_run_report, current_run_report):
                        atomic_write_text(path, pending_report)
                    self.append_journal(
                        kind="run_finished",
                        summary=f"Agent run finished for {card.title}",
                        task_id=card.id,
                        metadata={
                            "run_report_path": str(attempt_run_report),
                            "attempt_count": attempt_count,
                        },
                    )

                    self.update_status(
                        card.id,
                        status="verifying",
                        note="running verification gates",
                        metadata_updates={
                            "assistant_summary_preview": _shorten(assistant_summary, limit=300)
                        },
                    )
                    stream_writer.emit("phase_start", {"phase": "verify", "attempt": attempt_count})
                    verification_steps = self._run_verification_steps(policies, cwd=working_cwd)
                    review_cfg = (policies.get("verification") or {}).get("code_review") or {}
                    if review_cfg.get("enabled", True):
                        stream_writer.emit(
                            "phase_start", {"phase": "local_review", "attempt": attempt_count}
                        )
                        review_step = await self._run_code_review_step(
                            card,
                            cwd=working_cwd,
                            base_branch=base_branch,
                            policies=policies,
                            model=effective_review_model,
                            stream=stream_writer,
                            checkpoint_attempt=attempt_count,
                        )
                        verification_steps.append(review_step)
                        stream_writer.emit(
                            "phase_end",
                            {
                                "phase": "local_review",
                                "attempt": attempt_count,
                                "ok": review_step.status not in {"failed", "error"},
                            },
                        )
                    stream_writer.emit(
                        "phase_end",
                        {
                            "phase": "verify",
                            "attempt": attempt_count,
                            "ok": not any(
                                s.status in {"failed", "error"} for s in verification_steps
                            ),
                        },
                    )
                    verification_text = self._render_verification_report(card, verification_steps)
                    for path in (attempt_verification_report, current_verification_report):
                        atomic_write_text(path, verification_text)

                    failing = [
                        step for step in verification_steps if step.status in {"failed", "error"}
                    ]
                    final_local_report = self._render_run_report(
                        card,
                        agent_summary=assistant_summary,
                        verification_steps=verification_steps,
                        verification_status="failed" if failing else "passed",
                    )
                    for path in (attempt_run_report, current_run_report):
                        atomic_write_text(path, final_local_report)
                    prior_summary = assistant_summary

                    if failing:
                        summary = "; ".join(
                            f"{step.command} rc={step.returncode}" for step in failing[:3]
                        )
                        metadata_updates = {
                            "verification_failed": True,
                            "verification_steps": [
                                step.model_dump(mode="json") for step in verification_steps
                            ],
                            "last_failure_stage": "local_verification_failed",
                            "last_failure_summary": summary,
                        }
                        if attempt_count < max_attempts:
                            self.update_status(
                                card.id,
                                status="repairing",
                                note="local verification failed; retrying",
                                metadata_updates=metadata_updates,
                            )
                            self.append_journal(
                                kind="verification_failed",
                                summary=f"{card.title}: local verification failed, retrying",
                                task_id=card.id,
                                metadata={"attempt_count": attempt_count},
                            )
                            if issue_number is not None:
                                self._comment_on_issue(
                                    issue_number, self._comment_local_failed(attempt_count, summary)
                                )
                            prior_failure_stage = "local_verification_failed"
                            prior_failure_summary = summary
                            continue

                        self.update_status(
                            card.id,
                            status="failed",
                            note=f"{len(failing)} verification gate(s) failed",
                            metadata_updates=metadata_updates,
                        )
                        self.append_journal(
                            kind="verification_failed",
                            summary=f"{card.title}: {len(failing)} verification gate(s) failed",
                            task_id=card.id,
                        )
                        if issue_number is not None:
                            self._comment_on_issue(
                                issue_number, self._comment_terminal_failure(summary)
                            )
                        return RepoRunResult(
                            card_id=card.id,
                            status="failed",
                            assistant_summary=assistant_summary,
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=verification_steps,
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                        )

                    if not self._is_git_repo(working_cwd):
                        self.update_status(
                            card.id,
                            status="completed",
                            note="local verification passed; repository is not a git repo so GitHub automation was skipped",
                            metadata_updates={
                                "verification_failed": False,
                                "verification_steps": [
                                    step.model_dump(mode="json") for step in verification_steps
                                ],
                                "human_gate_pending": True,
                            },
                        )
                        return RepoRunResult(
                            card_id=card.id,
                            status="completed",
                            assistant_summary=assistant_summary,
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=verification_steps,
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                        )

                    commit_created = self._git_commit_all(
                        working_cwd,
                        f"autopilot({card.id}): {card.title}",
                    )
                    branch_has_progress = commit_created or self._git_branch_has_progress(
                        working_cwd,
                        base_branch=base_branch,
                    )
                    if not branch_has_progress:
                        no_changes_summary = "Agent produced no code changes to commit."
                        repeat_meta = self._failure_repeat_metadata(
                            card, stage="no_changes", summary=no_changes_summary
                        )
                        if (
                            attempt_count < max_attempts
                            and repeat_meta["repeated_failure_count"]
                            < self._max_repeated_failure_attempts(policies)
                        ):
                            self.update_status(
                                card.id,
                                status="repairing",
                                note="agent produced no changes; retrying",
                                metadata_updates={
                                    "last_failure_stage": "no_changes",
                                    "last_failure_summary": no_changes_summary,
                                    **repeat_meta,
                                },
                            )
                            prior_failure_stage = "no_changes"
                            prior_failure_summary = no_changes_summary
                            continue
                        self.update_status(
                            card.id,
                            status="failed",
                            note=no_changes_summary,
                            metadata_updates={
                                "last_failure_stage": "no_changes",
                                "last_failure_summary": no_changes_summary,
                                **repeat_meta,
                            },
                        )
                        return RepoRunResult(
                            card_id=card.id,
                            status="failed",
                            assistant_summary=assistant_summary,
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=verification_steps,
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                        )
                    if not commit_created:
                        self.append_journal(
                            kind="existing_progress_detected",
                            summary=f"{card.title}: reusing existing local branch progress",
                            task_id=card.id,
                            metadata={"attempt_count": attempt_count, "head_branch": head_branch},
                        )

                    push_ok, push_stage, push_summary = self._push_pr_branch_with_sync(
                        working_cwd,
                        base_branch=base_branch,
                        head_branch=head_branch,
                        policies=policies,
                        card_id=card.id,
                    )
                    if not push_ok:
                        _repair_stages = {"branch_sync_conflict", "branch_push_rejected"}
                        is_repairable = push_stage in _repair_stages
                        metadata_updates = {
                            "last_failure_stage": push_stage,
                            "last_failure_summary": push_summary,
                            "manual_intervention_required": False,
                            "human_gate_pending": False,
                        }
                        self.update_status(
                            card.id,
                            status="repairing" if is_repairable else "failed",
                            note=push_summary,
                            metadata_updates=metadata_updates,
                        )
                        self.append_journal(
                            kind="branch_sync_failed",
                            summary=f"{card.title}: {push_summary}",
                            task_id=card.id,
                            metadata={
                                "stage": push_stage,
                                "base_branch": base_branch,
                                "head_branch": head_branch,
                                "attempt_count": attempt_count,
                            },
                        )
                        if is_repairable and attempt_count < max_attempts:
                            prior_failure_stage = push_stage
                            prior_failure_summary = push_summary
                            continue
                        if issue_number is not None:
                            self._comment_on_issue(
                                issue_number, self._comment_terminal_failure(push_summary)
                            )
                        return RepoRunResult(
                            card_id=card.id,
                            status="repairing" if is_repairable else "failed",
                            assistant_summary=assistant_summary,
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=verification_steps,
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                        )
                    try:
                        pr_info = self._upsert_pull_request(
                            card,
                            head_branch=head_branch,
                            base_branch=base_branch,
                            run_report_path=current_run_report,
                            verification_report_path=current_verification_report,
                        )
                    except Exception as exc:
                        summary = f"Failed to upsert PR: {exc}"
                        self.update_status(
                            card.id,
                            status="failed",
                            note=summary,
                            metadata_updates={
                                "last_failure_stage": "github_pr_open_failed",
                                "last_failure_summary": summary,
                            },
                        )
                        if issue_number is not None:
                            self._comment_on_issue(
                                issue_number, self._comment_terminal_failure(summary)
                            )
                        return RepoRunResult(
                            card_id=card.id,
                            status="failed",
                            assistant_summary=assistant_summary,
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=verification_steps,
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                        )

                    linked_pr_number = int(pr_info.get("number"))
                    pr_url = _safe_text(pr_info.get("url"))
                    self.update_status(
                        card.id,
                        status="waiting_ci",
                        note=f"waiting for remote CI on PR #{linked_pr_number}",
                        metadata_updates={
                            "linked_pr_number": linked_pr_number,
                            "linked_pr_url": pr_url,
                            "linked_issue_numbers": [issue_number]
                            if issue_number is not None
                            else [],
                            "autopilot_managed": True,
                            "verification_failed": False,
                            "verification_steps": [
                                step.model_dump(mode="json") for step in verification_steps
                            ],
                        },
                    )
                    self._comment_on_pr(
                        linked_pr_number, self._comment_pr_opened(linked_pr_number, pr_url)
                    )

                    ci_state, ci_summary, pr_snapshot, checks = await self._wait_for_pr_ci(
                        linked_pr_number, policies
                    )
                    self.update_status(
                        card.id,
                        status="waiting_ci" if ci_state == "pending" else "waiting_ci",
                        note=f"remote CI status: {ci_state}",
                        metadata_updates={
                            "last_ci_conclusion": ci_state,
                            "last_ci_summary": ci_summary,
                            "last_ci_checks": checks,
                            "linked_pr_number": linked_pr_number,
                            "linked_pr_url": _safe_text(pr_snapshot.get("url")) or pr_url,
                        },
                    )
                    if ci_state == "failed":
                        repeat_meta = self._failure_repeat_metadata(
                            card, stage="remote_ci_failed", summary=ci_summary
                        )
                        if (
                            attempt_count < max_attempts
                            and repeat_meta["repeated_failure_count"]
                            < self._max_repeated_failure_attempts(policies)
                        ):
                            self.update_status(
                                card.id,
                                status="repairing",
                                note="remote CI failed; retrying",
                                metadata_updates={
                                    "last_failure_stage": "remote_ci_failed",
                                    "last_failure_summary": ci_summary,
                                    **repeat_meta,
                                },
                            )
                            self.append_journal(
                                kind="ci_failed_retry",
                                summary=f"{card.title}: remote CI failed, retrying",
                                task_id=card.id,
                                metadata={
                                    "pr_number": linked_pr_number,
                                    "attempt_count": attempt_count,
                                },
                            )
                            self._comment_on_pr(
                                linked_pr_number, self._comment_ci_failed(attempt_count, ci_summary)
                            )
                            prior_failure_stage = "remote_ci_failed"
                            prior_failure_summary = ci_summary
                            continue

                        self.update_status(
                            card.id,
                            status="failed",
                            note=f"remote CI failed: {ci_summary}",
                            metadata_updates={
                                "last_failure_stage": "remote_ci_failed",
                                "last_failure_summary": ci_summary,
                                **repeat_meta,
                            },
                        )
                        self._comment_on_pr(
                            linked_pr_number, self._comment_terminal_failure(ci_summary)
                        )
                        if issue_number is not None:
                            self._comment_on_issue(
                                issue_number, self._comment_terminal_failure(ci_summary)
                            )
                        return RepoRunResult(
                            card_id=card.id,
                            status="failed",
                            assistant_summary=assistant_summary,
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=verification_steps,
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                            pr_number=linked_pr_number,
                            pr_url=pr_url,
                        )

                    if self._automerge_eligible(pr_snapshot, policies):
                        remote_review_step = await self._run_remote_code_review_step(
                            card,
                            linked_pr_number,
                            policies=policies,
                            model=effective_review_model,
                            base_branch=base_branch,
                            stream=stream_writer,
                            checkpoint_attempt=attempt_count,
                        )
                        verification_steps.append(remote_review_step)
                        verification_text = self._render_verification_report(
                            card, verification_steps
                        )
                        for path in (attempt_verification_report, current_verification_report):
                            atomic_write_text(path, verification_text)
                        if remote_review_step.status in {"failed", "error"}:
                            summary = (
                                remote_review_step.stderr
                                or remote_review_step.stdout
                                or "remote code review blocked merge"
                            )
                            remote_review_meta = {
                                "human_gate_pending": False,
                                "linked_pr_number": linked_pr_number,
                                "linked_pr_url": pr_url,
                                "remote_review_status": remote_review_step.status,
                                "last_failure_stage": "remote_review_failed",
                                "last_failure_summary": summary,
                            }
                            if attempt_count < max_attempts:
                                self.update_status(
                                    card.id,
                                    status="repairing",
                                    note="remote code review failed; retrying",
                                    metadata_updates=remote_review_meta,
                                )
                                self.append_journal(
                                    kind="remote_review_failed_retry",
                                    summary=f"{card.title}: remote review failed, retrying",
                                    task_id=card.id,
                                    metadata={
                                        "pr_number": linked_pr_number,
                                        "attempt_count": attempt_count,
                                    },
                                )
                                self._comment_on_pr(
                                    linked_pr_number,
                                    self._comment_ci_failed(attempt_count, summary),
                                )
                                prior_failure_stage = "remote_review_failed"
                                prior_failure_summary = summary
                                continue

                            self.update_status(
                                card.id,
                                status="completed",
                                note=f"PR #{linked_pr_number} requires human gate after remote review",
                                metadata_updates={
                                    **remote_review_meta,
                                    "human_gate_pending": True,
                                },
                            )
                            self.append_journal(
                                kind="human_gate_pending",
                                summary=f"{card.title}: remote review requires human gate for PR #{linked_pr_number}",
                                task_id=card.id,
                                metadata={
                                    "pr_number": linked_pr_number,
                                    "remote_review_status": remote_review_step.status,
                                },
                            )
                            self._comment_on_pr(
                                linked_pr_number, self._comment_terminal_failure(summary)
                            )
                            if issue_number is not None:
                                self._comment_on_issue(
                                    issue_number, self._comment_terminal_failure(summary)
                                )
                            return RepoRunResult(
                                card_id=card.id,
                                status="completed",
                                assistant_summary=assistant_summary,
                                run_report_path=str(current_run_report),
                                verification_report_path=str(current_verification_report),
                                verification_steps=verification_steps,
                                attempt_count=attempt_count,
                                worktree_path=str(working_cwd),
                                pr_number=linked_pr_number,
                                pr_url=pr_url,
                            )

                        self._merge_pull_request(linked_pr_number)
                        self.update_status(
                            card.id,
                            status="merged",
                            note=f"PR #{linked_pr_number} merged automatically",
                            metadata_updates={"human_gate_pending": False},
                        )
                        self.append_journal(
                            kind="merged",
                            summary=f"{card.title}: PR #{linked_pr_number} merged",
                            task_id=card.id,
                            metadata={"pr_number": linked_pr_number},
                        )
                        self._comment_on_pr(
                            linked_pr_number, self._comment_merged(linked_pr_number)
                        )
                        if issue_number is not None:
                            self._comment_on_issue(
                                issue_number, self._comment_merged(linked_pr_number)
                            )
                        try:
                            with RepoFileLock(self._main_checkout_lock_path, timeout=60.0):
                                self._pull_base_branch(base_branch=base_branch)
                            self.rebase_inflight_worktrees(
                                base_branch=base_branch,
                                merged_card_id=card.id,
                                rebase_strategy=self._rebase_strategy(policies),
                            )
                        except Exception as exc:
                            self.append_journal(
                                kind="merge_warning",
                                summary=f"post-merge pull failed: {exc}",
                                task_id=card.id,
                                metadata={"pr_number": linked_pr_number},
                            )
                        else:
                            try:
                                with RepoFileLock(self._main_checkout_lock_path, timeout=60.0):
                                    self._install_editable()
                            except Exception as exc:
                                self.append_journal(
                                    kind="merge_warning",
                                    summary=f"post-merge install failed: {exc}",
                                    task_id=card.id,
                                    metadata={"pr_number": linked_pr_number},
                                )
                        try:
                            self._journal_base_advanced_for_active_cards(base_branch=base_branch, merged_card_id=card.id)
                        except Exception as exc:
                            self.append_journal(
                                kind="base_advanced_warning",
                                summary=f"failed to journal base_advanced after merge: {exc}",
                                task_id=card.id,
                            )
                        return RepoRunResult(
                            card_id=card.id,
                            status="merged",
                            assistant_summary=assistant_summary,
                            run_report_path=str(current_run_report),
                            verification_report_path=str(current_verification_report),
                            verification_steps=verification_steps,
                            attempt_count=attempt_count,
                            worktree_path=str(working_cwd),
                            pr_number=linked_pr_number,
                            pr_url=pr_url,
                        )

                    self.update_status(
                        card.id,
                        status="completed",
                        note=f"PR #{linked_pr_number} is green; human gate pending",
                        metadata_updates={
                            "human_gate_pending": True,
                            "linked_pr_number": linked_pr_number,
                            "linked_pr_url": pr_url,
                        },
                    )
                    self.append_journal(
                        kind="human_gate_pending",
                        summary=f"{card.title}: PR #{linked_pr_number} is ready for human gate",
                        task_id=card.id,
                        metadata={"pr_number": linked_pr_number},
                    )
                    self._comment_on_pr(
                        linked_pr_number, self._comment_human_gate(linked_pr_number)
                    )
                    if issue_number is not None:
                        self._comment_on_issue(
                            issue_number, self._comment_human_gate(linked_pr_number)
                        )
                    return RepoRunResult(
                        card_id=card.id,
                        status="completed",
                        assistant_summary=assistant_summary,
                        run_report_path=str(current_run_report),
                        verification_report_path=str(current_verification_report),
                        verification_steps=verification_steps,
                        attempt_count=attempt_count,
                        worktree_path=str(working_cwd),
                        pr_number=linked_pr_number,
                        pr_url=pr_url,
                    )

                exhausted = "repair rounds exhausted"
                self.update_status(
                    card.id,
                    status="failed",
                    note=exhausted,
                    metadata_updates={
                        "last_failure_stage": "repair_exhausted",
                        "last_failure_summary": exhausted,
                    },
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    attempt_count=max_attempts,
                    worktree_path=str(working_cwd),
                )
            finally:
                pass

        except Exception as exc:
            summary = f"unexpected autopilot failure: {exc}"
            self.update_status(
                card.id,
                status="failed",
                note=summary,
                metadata_updates={
                    "last_failure_stage": "unexpected_error",
                    "last_failure_summary": summary,
                },
            )
            self.append_journal(
                kind="run_failed",
                summary=f"{card.title}: unexpected autopilot failure",
                task_id=card.id,
                metadata={"error": str(exc)},
            )
            if issue_number is not None:
                self._comment_on_issue(issue_number, self._comment_terminal_failure(summary))
            return RepoRunResult(
                card_id=card.id,
                status="failed",
                run_report_path=str(current_run_report),
                verification_report_path=str(current_verification_report),
                attempt_count=existing_attempts + 1,
                worktree_path=str(working_cwd),
            )
        finally:
            if use_worktree and worktree_info is not None:
                try:
                    await worktree_manager.remove_worktree(self._worktree_slug(card))
                except Exception as cleanup_exc:  # pragma: no cover - defensive
                    self.append_journal(
                        kind="cleanup_warning",
                        summary=f"Failed to remove worktree {self._worktree_slug(card)}: {cleanup_exc}",
                        task_id=card.id,
                        metadata={"worktree_slug": self._worktree_slug(card)},
                    )
            release_writer(card.id)
            _stream_retention_days = float(
                (policies.get("autopilot", {}).get("execution", {}) or {}).get(
                    "stream_retention_days", 7
                )
            )
            collect_old_stream_files(self._runs_dir, max_age_seconds=_stream_retention_days * 86400)

    STUCK_CARD_STALE_SECONDS = 1800
    """Active cards untouched longer than this are considered stuck and reset to queued."""

    def _recover_stuck_cards(self) -> list[str]:
        """Reset cards stuck in active status with no recent updates.

        Returns IDs of recovered cards. Stuck cards happen when the cron tick
        is killed mid-run (timeout, crash, kill -9) — leaving the registry in
        an active status with no live process to drive it.

        Cards in ``waiting_ci`` or ``pr_open`` with a linked PR are handled
        specially: the remote PR state is checked so the card can be advanced
        to ``merged`` (if already merged) or kept in ``waiting_ci`` (if still
        open) instead of blindly resetting to ``queued`` and losing context.
        """
        active_states = {"preparing", "running", "verifying", "waiting_ci", "repairing"}
        now = time.time()
        recovered: list[str] = []
        for card in self.list_cards():
            if card.status not in active_states:
                continue
            updated_at = float(card.updated_at or 0)
            if now - updated_at <= self.STUCK_CARD_STALE_SECONDS:
                continue
            stale_minutes = int((now - updated_at) / 60)
            try:
                target_status, note, extra_meta = self._resolve_stuck_card_recovery(
                    card, stale_minutes
                )
                ckpt = load_latest_checkpoint(self._runs_dir, card.id)
                metadata_updates: dict[str, Any] = {
                    "stuck_recovery": {
                        "from_status": card.status,
                        "stale_seconds": int(now - updated_at),
                        "recovered_at": now,
                    },
                }
                metadata_updates.update(extra_meta)
                if target_status == "queued" and ckpt is not None and ckpt.has_pending_continuation:
                    metadata_updates.update(
                        {
                            "resume_available": True,
                            "resume_phase": ckpt.phase,
                        }
                    )
                self.update_status(
                    card.id,
                    status=target_status,
                    note=note,
                    metadata_updates=metadata_updates,
                )
                self.append_journal(
                    kind="stuck_card_recovered",
                    summary=note,
                    task_id=card.id,
                )
                recovered.append(card.id)
            except Exception as exc:  # pragma: no cover - defensive
                self.append_journal(
                    kind="stuck_card_recovery_failed",
                    summary=f"failed to reset {card.id}: {exc}",
                    task_id=card.id,
                )
        return recovered

    def _resolve_stuck_card_recovery(
        self, card: RepoTaskCard, stale_minutes: int
    ) -> tuple[str, str, dict[str, Any]]:
        """Decide target status for a stuck card based on its PR state.

        Returns ``(target_status, note, extra_metadata_updates)``.
        """
        pr_linked_states = {"waiting_ci", "pr_open"}
        linked_pr = self._linked_pr_number(card)

        if card.status == "repairing" and bool(card.metadata.get("manual_intervention_required")):
            return (
                "failed",
                f"auto-recovered: manual repair required after {stale_minutes}m in repairing",
                {},
            )

        if card.status not in pr_linked_states or linked_pr is None:
            return (
                "queued",
                f"auto-recovered: status={card.status} stale for {stale_minutes}m",
                {},
            )

        try:
            snapshot = self._pr_status_snapshot(linked_pr)
        except Exception:
            return (
                "queued",
                f"auto-recovered: status={card.status} stale for {stale_minutes}m (PR #{linked_pr} unreachable)",
                {"linked_pr_number": None, "linked_pr_url": ""},
            )

        pr_state = _safe_text(snapshot.get("state")).upper()
        pr_head = _safe_text(snapshot.get("headRefName"))
        expected_head = _safe_text(card.metadata.get("head_branch"))

        if pr_head and expected_head and pr_head != expected_head:
            return (
                "queued",
                f"auto-recovered: PR #{linked_pr} branch mismatch ({pr_head} != {expected_head}), stale for {stale_minutes}m",
                {"linked_pr_number": None, "linked_pr_url": "", "human_gate_pending": False, "verification_failed": False},
            )

        if pr_state == "MERGED":
            return (
                "merged",
                f"auto-recovered: PR #{linked_pr} already merged (stale {stale_minutes}m in {card.status})",
                {"human_gate_pending": False},
            )

        if pr_state == "OPEN":
            return (
                "waiting_ci",
                f"auto-recovered: PR #{linked_pr} still open, resuming CI watch (stale {stale_minutes}m)",
                {},
            )

        return (
            "queued",
            f"auto-recovered: PR #{linked_pr} state={pr_state}, stale for {stale_minutes}m",
            {"linked_pr_number": None, "linked_pr_url": "", "human_gate_pending": False, "verification_failed": False},
        )

    async def _cleanup_stale_worktrees(self) -> list[str]:
        worktree_manager = WorktreeManager()
        terminal_statuses = {"completed", "merged", "failed", "rejected", "superseded", "killed", "pending", "paused"}
        removed: list[str] = []
        try:
            worktrees = await worktree_manager.list_worktrees()
        except Exception as exc:  # pragma: no cover - defensive
            self.append_journal(kind="cleanup_warning", summary=f"Failed to list worktrees: {exc}")
            return removed

        for info in worktrees:
            slug = info.slug
            if not slug.startswith("autopilot/"):
                continue
            card_id = slug.split("/", 1)[1]
            card = self.get_card(card_id)
            if card is None or card.status not in terminal_statuses:
                continue
            try:
                await worktree_manager.remove_worktree(slug)
                removed.append(slug)
                self.append_journal(
                    kind="worktree_cleanup",
                    summary=f"Removed stale worktree for terminal card {card_id}",
                    task_id=card_id,
                    metadata={"worktree_slug": slug},
                )
            except Exception as exc:  # pragma: no cover - defensive
                self.append_journal(
                    kind="cleanup_warning",
                    summary=f"Failed to remove stale worktree {slug}: {exc}",
                    task_id=card_id,
                    metadata={"worktree_slug": slug},
                )
        return removed

    async def _check_and_merge_managed_prs(self, policies: dict[str, Any]) -> list[str]:
        """Check autopilot_managed cards in waiting_ci with linked PRs — merge if CI passes.

        Cards that are autopilot_managed=True and in waiting_ci with a linked_pr_number
        should be auto-merged when CI is green and automerge is eligible. This prevents
        them from getting stuck in waiting_ci indefinitely.

        Returns list of card IDs that were merged.
        """
        merged: list[str] = []
        for card in self.list_cards():
            if card.status != "waiting_ci":
                continue
            if not bool(card.metadata.get("autopilot_managed")):
                continue
            linked_pr = self._linked_pr_number(card)
            if linked_pr is None:
                continue
            try:
                pr_snapshot = self._pr_status_snapshot(linked_pr)
                ci_state, ci_summary, _checks = self._ci_rollup(pr_snapshot)
                pr_url = _safe_text(pr_snapshot.get("url"))
                pr_state = _safe_text(pr_snapshot.get("state")).upper()
                if pr_state == "MERGED":
                    # Already merged externally — sync status
                    self.update_status(
                        card.id,
                        status="merged",
                        note=f"PR #{linked_pr} was merged externally",
                        metadata_updates={
                            "linked_pr_url": pr_url,
                            "human_gate_pending": False,
                        },
                    )
                    merged.append(card.id)
                    continue
                if ci_state != "success":
                    # Still running or failed — skip for now
                    continue
                if not self._automerge_eligible(pr_snapshot, policies):
                    continue
                self._merge_pull_request(linked_pr)
                self.update_status(
                    card.id,
                    status="merged",
                    note=f"autopilot managed PR #{linked_pr} CI passed, merged automatically",
                    metadata_updates={
                        "linked_pr_number": linked_pr,
                        "linked_pr_url": pr_url,
                    },
                )
                self._comment_on_pr(linked_pr, self._comment_merged(linked_pr))
                self.append_journal(
                    kind="autopilot_managed_merged",
                    summary=f"Auto-merged autopilot managed PR #{linked_pr} (CI passed)",
                    task_id=card.id,
                    metadata={"pr_number": linked_pr, "pr_url": pr_url},
                )
                merged.append(card.id)
            except Exception as exc:
                self.append_journal(
                    kind="autopilot_managed_merge_failed",
                    summary=f"Failed to check/merge managed PR #{linked_pr}: {exc}",
                    task_id=card.id,
                )
        return merged

    async def tick(
        self,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
        issue_limit: int = 10,
        pr_limit: int = 10,
    ) -> RepoRunResult | None:
        self.scan_all_sources(issue_limit=issue_limit, pr_limit=pr_limit)
        self._recover_stuck_cards()
        await self._cleanup_stale_worktrees()
        policies = self.load_policies()
        merged = await self._check_and_merge_managed_prs(policies)
        if merged:
            self.append_journal(
                kind="autopilot_managed_batch_merged",
                summary=f"Auto-merged {len(merged)} autopilot managed PR(s) after CI check",
                metadata={"card_ids": merged},
            )
        if not self.has_capacity(policies):
            self.append_journal(
                kind="tick_skip",
                summary="Skipped run-next because maximum parallel runs capacity was reached",
            )
            return None
        if self.pick_next_card() is None:
            self.append_journal(kind="tick_idle", summary="Tick completed with no queued work")
            return None
        return await self.run_next(
            model=model,
            max_turns=max_turns,
            permission_mode=permission_mode,
        )

    def install_default_cron(self) -> dict[str, Any]:
        """Install cron jobs using configured schedules and return a full report.

        Reads ``cron_schedule.scan_cron`` and ``cron_schedule.tick_cron`` from
        the global settings file.  Falls back to safe defaults if the settings
        are absent or corrupt, then logs the resolved values and what changed
        so the caller can display them to the user.
        """
        from openharness.services.cron import get_cron_job, upsert_cron_job

        settings = load_settings()
        cron_cfg = settings.cron_schedule

        log.info(
            "install_default_cron: enabled=%s scan_cron=%r tick_cron=%r",
            cron_cfg.enabled,
            cron_cfg.scan_cron,
            cron_cfg.tick_cron,
        )

        jobs = [
            {
                "name": "autopilot.scan",
                "schedule": cron_cfg.scan_cron,
                "command": f"oh autopilot scan all --cwd {self._cwd}",
                "cwd": str(self._cwd),
                "project_path": str(self._cwd),
            },
            {
                "name": "autopilot.tick",
                "schedule": cron_cfg.tick_cron,
                "command": f"oh autopilot tick --cwd {self._cwd}",
                "cwd": str(self._cwd),
                "project_path": str(self._cwd),
            },
        ]

        installed: list[dict[str, Any]] = []
        for job in jobs:
            prior = get_cron_job(job["name"])
            if prior is not None:
                if prior["schedule"] == job["schedule"] and prior["command"] == job["command"]:
                    log.info("install_cron: no change for %s (schedule=%r)", job["name"], job["schedule"])
                else:
                    log.info(
                        "install_cron: updating %s schedule=%r (was %r), command=%r",
                        job["name"],
                        job["schedule"],
                        prior.get("schedule"),
                        job["command"],
                    )
            else:
                log.info("install_cron: creating %s schedule=%r command=%r", job["name"], job["schedule"], job["command"])
            upsert_cron_job(job)
            installed.append(job)

        return {
            "installed": installed,
            "cron_lines": [f"{j['schedule']} oh autopilot {name} --cwd {self._cwd}"
                           for name, j in zip(("scan", "tick"), installed)],
        }

    def export_dashboard(self, output_dir: str | Path | None = None) -> Path:
        target_dir = (
            Path(output_dir) if output_dir is not None else self._cwd / "docs" / "autopilot"
        )
        target_dir = target_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot = self._build_dashboard_snapshot()
        atomic_write_text(
            target_dir / "snapshot.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        )
        atomic_write_text(target_dir / "index.html", self._render_dashboard_html(snapshot))
        atomic_write_text(target_dir / ".nojekyll", "")
        return target_dir

    def _max_attempts(self, policies: dict[str, Any]) -> int:
        import sys

        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        repair = dict(policies.get("autopilot", {}).get("repair", {}))
        if repair.get("max_rounds") == 0:
            return sys.maxsize
        raw_execution = int(execution.get("max_attempts", 3) or 3)
        execution_attempts = sys.maxsize if raw_execution == 0 else raw_execution
        repair_rounds = int(repair.get("max_rounds", 2) or 2)
        return max(execution_attempts, repair_rounds + 1, 1)

    def _max_repeated_failure_attempts(self, policies: dict[str, Any]) -> int:
        repair = dict(policies.get("autopilot", {}).get("repair", {}))
        return max(int(repair.get("max_repeated_failure_attempts", 3) or 3), 1)

    def _failure_repeat_metadata(
        self,
        card: RepoTaskCard,
        *,
        stage: str,
        summary: str,
    ) -> dict[str, Any]:
        failure_key = f"{stage}:{summary}"
        previous_key = _safe_text(card.metadata.get("repeated_failure_key"))
        previous_count = int(card.metadata.get("repeated_failure_count", 0) or 0)
        count = previous_count + 1 if previous_key == failure_key else 1
        return {
            "repeated_failure_key": failure_key,
            "repeated_failure_count": count,
        }

    def _base_branch(self, policies: dict[str, Any]) -> str:
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        return _safe_text(execution.get("base_branch")) or "main"

    def _rebase_strategy(self, policies: dict[str, Any]) -> str:
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        strategy = _safe_text(execution.get("rebase_strategy")) or "on_conflict"
        if strategy not in {"none", "on_advance", "on_conflict", "always"}:
            return "on_conflict"
        return strategy

    def _pr_branch_sync_strategy(self, policies: dict[str, Any]) -> str:
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        strategy = _safe_text(execution.get("pr_branch_sync_strategy")) or "rebase"
        if strategy not in {"none", "rebase"}:
            return "rebase"
        return strategy

    def _max_branch_sync_attempts(self, policies: dict[str, Any]) -> int:
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        return max(int(execution.get("max_branch_sync_attempts", 2) or 2), 1)

    def _allow_force_push_pr_branch(self, policies: dict[str, Any]) -> bool:
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        return bool(execution.get("allow_force_push_pr_branch", False))

    def _should_force_push_pr_branch(
        self,
        *,
        card_id: str | None,
        head_branch: str,
        policies: dict[str, Any],
    ) -> bool:
        if self._allow_force_push_pr_branch(policies):
            return True
        if not card_id:
            return False
        card = self.get_card(card_id)
        if card is None:
            return False
        if not bool(card.metadata.get("autopilot_managed")):
            return False
        if self._linked_pr_number(card) is None:
            return False
        return self._head_branch(card, policies) == head_branch

    def _head_branch(self, card: RepoTaskCard, policies: dict[str, Any]) -> str:
        github_policy = dict(policies.get("autopilot", {}).get("github", {}))
        prefix = _safe_text(github_policy.get("pr_branch_prefix")) or "autopilot/"
        return f"{prefix}{card.id}"

    def _worktree_slug(self, card: RepoTaskCard) -> str:
        return f"autopilot/{card.id}"

    def _run_command(
        self,
        command: str | list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
        shell: bool = False,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        import signal

        proc = subprocess.Popen(
            command,
            cwd=cwd or self._cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
            start_new_session=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""},
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise
        completed = subprocess.CompletedProcess(
            args=proc.args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        if check and completed.returncode != 0:
            output = (completed.stderr or completed.stdout).strip() or f"Command failed: {command}"
            raise RuntimeError(output)
        return completed

    def _run_git(
        self, args: list[str], *, cwd: Path | None = None, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return self._run_command(["git", *args], cwd=cwd, check=check)

    def _run_gh(
        self, args: list[str], *, cwd: Path | None = None, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return self._run_command(["gh", *args], cwd=cwd, check=check)

    def _gh_json(self, args: list[str], *, cwd: Path | None = None) -> Any:
        completed = self._run_gh(args, cwd=cwd, check=True)
        raw = (completed.stdout or "").strip()
        if not raw:
            return None
        return json.loads(raw)

    def _git_has_changes(self, cwd: Path) -> bool:
        completed = self._run_git(["status", "--porcelain"], cwd=cwd, check=True)
        return bool((completed.stdout or "").strip())

    def _is_git_repo(self, cwd: Path) -> bool:
        completed = self._run_git(["rev-parse", "--git-dir"], cwd=cwd)
        return completed.returncode == 0

    def _is_same_git_common_dir(self, cwd: Path) -> bool:
        repo_common_dir = self._run_git(["rev-parse", "--git-common-dir"], cwd=self._cwd)
        cwd_common_dir = self._run_git(["rev-parse", "--git-common-dir"], cwd=cwd)
        if repo_common_dir.returncode != 0 or cwd_common_dir.returncode != 0:
            return False
        repo_path = Path((repo_common_dir.stdout or "").strip())
        cwd_path = Path((cwd_common_dir.stdout or "").strip())
        if not repo_path.is_absolute():
            repo_path = self._cwd / repo_path
        if not cwd_path.is_absolute():
            cwd_path = cwd / cwd_path
        return repo_path.resolve() == cwd_path.resolve()

    def _git_commit_all(self, cwd: Path, message: str) -> bool:
        if not self._git_has_changes(cwd):
            return False
        self._run_git(["add", "-A"], cwd=cwd, check=True)
        self._run_git(["commit", "-m", message], cwd=cwd, check=True)
        return True

    def _git_push_branch(self, cwd: Path, branch: str, *, force_with_lease: bool = False) -> None:
        args = ["push", "-u"]
        if force_with_lease:
            args.append("--force-with-lease")
        self._run_git([*args, "origin", branch], cwd=cwd, check=True)

    def _is_non_fast_forward_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            phrase in text
            for phrase in (
                "non-fast-forward",
                "fetch first",
                "failed to push some refs",
                "[rejected]",
            )
        )

    def _pull_base_branch(self, *, base_branch: str, cwd: Path | None = None) -> None:
        target = cwd or self._cwd
        self._run_git(["fetch", "origin", base_branch], cwd=target, check=True)
        self._run_git(["pull", "--ff-only", "origin", base_branch], cwd=target, check=True)

    def _install_editable(self, *, cwd: Path | None = None) -> None:
        target = cwd or self._cwd
        self._run_command(["uv", "pip", "install", "-e", "."], cwd=target, timeout=120, check=True)

    def _journal_base_advanced_for_active_cards(self, *, base_branch: str, merged_card_id: str) -> None:
        registry = self._load_registry()
        for card in registry.cards:
            if card.id == merged_card_id or card.status not in self._ACTIVE_STATUSES:
                continue
            self.append_journal(
                kind="base_advanced",
                summary=f"Base branch {base_branch} advanced while card {card.id} is active",
                task_id=card.id,
                metadata={"base_branch": base_branch, "status": card.status, "merged_card_id": merged_card_id},
            )

    def _git_branch_has_progress(self, cwd: Path, *, base_branch: str) -> bool:
        completed = self._run_git(
            ["rev-list", "--count", f"origin/{base_branch}..HEAD"],
            cwd=cwd,
        )
        if completed.returncode != 0:
            return False
        try:
            return int((completed.stdout or "0").strip() or "0") > 0
        except ValueError:
            return False

    def _base_branch_has_advanced(self, cwd: Path, *, base_branch: str) -> bool:
        completed = self._run_git(
            ["rev-list", "--count", f"HEAD..origin/{base_branch}"],
            cwd=cwd,
        )
        if completed.returncode != 0:
            return False
        try:
            return int((completed.stdout or "0").strip() or "0") > 0
        except ValueError:
            return False

    def _fetch_remote_branch(self, cwd: Path, *, branch: str) -> bool:
        completed = self._run_git(["fetch", "origin", branch], cwd=cwd)
        return completed.returncode == 0

    def _branch_matches_remote(self, cwd: Path, *, branch: str) -> bool:
        ahead = self._run_git(["rev-list", "--count", f"origin/{branch}..HEAD"], cwd=cwd)
        behind = self._run_git(["rev-list", "--count", f"HEAD..origin/{branch}"], cwd=cwd)
        if ahead.returncode != 0 or behind.returncode != 0:
            return False
        try:
            ahead_count = int((ahead.stdout or "0").strip() or "0")
            behind_count = int((behind.stdout or "0").strip() or "0")
        except ValueError:
            return False
        return ahead_count == 0 and behind_count == 0

    def _rebase_head_onto_base(
        self, cwd: Path, *, base_branch: str, card_id: str | None = None
    ) -> bool:
        completed = self._run_git(["rebase", f"origin/{base_branch}"], cwd=cwd)
        if completed.returncode == 0:
            self.append_journal(
                kind="rebase_done",
                summary=f"Rebased worktree onto origin/{base_branch}",
                task_id=card_id,
                metadata={"base_branch": base_branch, "worktree_path": str(cwd)},
            )
            return True
        self._run_git(["rebase", "--abort"], cwd=cwd)
        message = (completed.stderr or completed.stdout or "git rebase failed").strip()
        self.append_journal(
            kind="rebase_conflict",
            summary=f"Rebase onto origin/{base_branch} failed; continuing without rebased worktree",
            task_id=card_id,
            metadata={
                "base_branch": base_branch,
                "worktree_path": str(cwd),
                "non_fatal": True,
                "message": message,
            },
        )
        return False

    def _rebase_head_onto_remote_branch(
        self, cwd: Path, *, remote_branch: str, card_id: str | None = None
    ) -> bool:
        completed = self._run_git(["rebase", remote_branch], cwd=cwd)
        if completed.returncode == 0:
            self.append_journal(
                kind="remote_branch_rebase_done",
                summary=f"Rebased worktree onto {remote_branch}",
                task_id=card_id,
                metadata={"remote_branch": remote_branch, "worktree_path": str(cwd)},
            )
            return True
        self._run_git(["rebase", "--abort"], cwd=cwd)
        message = (completed.stderr or completed.stdout or "git rebase failed").strip()
        self.append_journal(
            kind="remote_branch_rebase_conflict",
            summary=f"Rebase onto {remote_branch} failed; branch requires manual repair",
            task_id=card_id,
            metadata={
                "remote_branch": remote_branch,
                "worktree_path": str(cwd),
                "message": message,
            },
        )
        return False

    def _sync_worktree_to_base(
        self,
        cwd: Path,
        *,
        base_branch: str,
        head_branch: str,
        reset: bool,
        rebase_strategy: str = "on_conflict",
        card_id: str | None = None,
    ) -> None:
        self._run_git(["fetch", "origin", base_branch], cwd=cwd, check=True)
        if reset:
            start_ref = f"origin/{base_branch}"
            if self._fetch_remote_branch(cwd, branch=head_branch):
                start_ref = f"origin/{head_branch}"
            self._run_git(["checkout", "-B", head_branch, start_ref], cwd=cwd, check=True)
            return
        self._run_git(["checkout", head_branch], cwd=cwd, check=True)
        if rebase_strategy == "none":
            return
        has_advanced = self._base_branch_has_advanced(cwd, base_branch=base_branch)
        should_rebase = rebase_strategy == "always" or (
            has_advanced and rebase_strategy in {"on_advance", "on_conflict"}
        )
        if should_rebase:
            self._rebase_head_onto_base(cwd, base_branch=base_branch, card_id=card_id)

    def _sync_pr_branch_before_push(
        self,
        cwd: Path,
        *,
        base_branch: str,
        head_branch: str,
        policies: dict[str, Any],
        card_id: str | None = None,
    ) -> tuple[bool, str, str]:
        strategy = self._pr_branch_sync_strategy(policies)
        if strategy == "none":
            return True, "branch_sync_skipped", "PR branch sync disabled."
        self._run_git(["checkout", head_branch], cwd=cwd, check=True)
        for attempt in range(1, self._max_branch_sync_attempts(policies) + 1):
            self._run_git(["fetch", "origin", base_branch], cwd=cwd, check=True)
            remote_head = self._run_git(["fetch", "origin", head_branch], cwd=cwd)
            success = True
            if remote_head.returncode == 0 and not self._branch_matches_remote(cwd, branch=head_branch):
                success = self._rebase_head_onto_remote_branch(
                    cwd,
                    remote_branch=f"origin/{head_branch}",
                    card_id=card_id,
                )
            if success and self._base_branch_has_advanced(cwd, base_branch=base_branch):
                success = self._rebase_head_onto_base(
                    cwd,
                    base_branch=base_branch,
                    card_id=card_id,
                )
            if success:
                summary = f"Synced {head_branch} onto origin/{base_branch}."
                self.append_journal(
                    kind="branch_sync_done",
                    summary=summary,
                    task_id=card_id,
                    metadata={
                        "base_branch": base_branch,
                        "head_branch": head_branch,
                        "attempt_count": attempt,
                    },
                )
                return True, "branch_sync_done", summary
            if attempt < self._max_branch_sync_attempts(policies):
                self._run_git(["fetch", "origin", base_branch], cwd=cwd, check=True)
        summary = f"Could not rebase {head_branch} onto origin/{base_branch}."
        self.append_journal(
            kind="branch_sync_conflict",
            summary=summary,
            task_id=card_id,
            metadata={
                "base_branch": base_branch,
                "head_branch": head_branch,
                "attempt_count": self._max_branch_sync_attempts(policies),
            },
        )
        return False, "branch_sync_conflict", summary

    def _push_pr_branch_with_sync(
        self,
        cwd: Path,
        *,
        base_branch: str,
        head_branch: str,
        policies: dict[str, Any],
        card_id: str | None = None,
    ) -> tuple[bool, str, str]:
        ok, stage, summary = self._sync_pr_branch_before_push(
            cwd,
            base_branch=base_branch,
            head_branch=head_branch,
            policies=policies,
            card_id=card_id,
        )
        if not ok:
            return ok, stage, summary
        try:
            self._git_push_branch(cwd, head_branch)
            return True, "branch_push_done", f"Pushed {head_branch}."
        except Exception as exc:
            if not self._is_non_fast_forward_error(exc):
                return False, "branch_push_failed", str(exc)
            ok, stage, summary = self._sync_pr_branch_before_push(
                cwd,
                base_branch=base_branch,
                head_branch=head_branch,
                policies=policies,
                card_id=card_id,
            )
            if not ok:
                return ok, stage, summary
            try:
                self._git_push_branch(cwd, head_branch)
                return True, "branch_push_done", f"Pushed {head_branch} after sync."
            except Exception as retry_exc:
                if not self._is_non_fast_forward_error(retry_exc):
                    return False, "branch_push_failed", str(retry_exc)
                if self._should_force_push_pr_branch(
                    card_id=card_id,
                    head_branch=head_branch,
                    policies=policies,
                ):
                    self._git_push_branch(cwd, head_branch, force_with_lease=True)
                    return True, "branch_force_push_done", f"Force-with-lease pushed {head_branch}."
                return False, "branch_push_rejected", str(retry_exc)

    def rebase_inflight_worktrees(
        self,
        *,
        base_branch: str,
        merged_card_id: str | None = None,
        rebase_strategy: str = "auto",
    ) -> None:
        if rebase_strategy == "none":
            return
        registry = self._load_registry()
        for card in registry.cards:
            if card.id == merged_card_id or card.status not in self._ACTIVE_STATUSES:
                continue
            worktree_path = _safe_text(card.metadata.get("worktree_path"))
            if not worktree_path:
                continue
            cwd = Path(worktree_path)
            if not cwd.exists():
                continue
            self._run_git(["fetch", "origin", base_branch], cwd=cwd)
            success = self._rebase_head_onto_base(cwd, base_branch=base_branch, card_id=card.id)
            if not success:
                self.update_status(
                    card.id,
                    status="repairing",
                    note=f"Rebase conflict after base branch {base_branch} advanced",
                    metadata_updates={
                        "human_gate_pending": True,
                        "last_failure_stage": "rebase_conflict",
                    },
                )

    def _issue_number_for_card(self, card: RepoTaskCard) -> int | None:
        linked = card.metadata.get("linked_issue_numbers")
        if isinstance(linked, list) and linked:
            try:
                return int(linked[0])
            except (TypeError, ValueError):
                pass
        return _source_ref_number(card.source_ref, "issue")

    def _linked_pr_number(self, card: RepoTaskCard) -> int | None:
        linked = card.metadata.get("linked_pr_number")
        if linked is not None:
            try:
                return int(linked)
            except (TypeError, ValueError):
                return None
        return _source_ref_number(card.source_ref, "pr")

    def _current_repo_full_name(self) -> str:
        if self._repo_full_name:
            return self._repo_full_name
        completed = self._run_git(["remote", "get-url", "origin"], cwd=self._cwd)
        if completed.returncode == 0:
            url = (completed.stdout or "").strip()
            for pattern in (
                r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$",
                r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
            ):
                m = re.match(pattern, url)
                if m:
                    self._repo_full_name = m.group(1)
                    return self._repo_full_name

        info = self._gh_json(["repo", "view", "--json", "nameWithOwner"], cwd=self._cwd) or {}
        repo = _safe_text(info.get("nameWithOwner"))
        if not repo:
            raise RuntimeError(
                "Unable to resolve GitHub repository name from origin remote or `gh repo view`."
            )
        self._repo_full_name = repo
        return self._repo_full_name

    def _find_open_pr_for_branch(self, head_branch: str) -> dict[str, Any] | None:
        data = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self._current_repo_full_name(),
                "--state",
                "open",
                "--head",
                head_branch,
                "--json",
                "number,url,isDraft,labels,headRefName,baseRefName,mergeStateStatus,reviewDecision",
            ],
            cwd=self._cwd,
        )
        if isinstance(data, list) and data:
            return data[0]
        return None

    def _best_effort_add_labels(self, pr_number: int, labels: list[str]) -> None:
        normalized = [label for label in labels if label]
        if not normalized:
            return
        try:
            self._run_gh(
                [
                    "pr",
                    "edit",
                    str(pr_number),
                    "--repo",
                    self._current_repo_full_name(),
                    *sum([["--add-label", label] for label in normalized], []),
                ],
                cwd=self._cwd,
            )
        except Exception:
            self.append_journal(
                kind="github_warning",
                summary=f"Failed to add labels to PR #{pr_number}; continuing",
                metadata={"labels": normalized},
            )

    def _build_pr_body(
        self,
        card: RepoTaskCard,
        *,
        run_report_path: Path,
        verification_report_path: Path,
    ) -> str:
        issue_number = self._issue_number_for_card(card)
        body = [
            "## Autopilot Summary",
            "",
            f"- Task ID: `{card.id}`",
            f"- Source: `{card.source_kind}`",
            f"- Source ref: `{card.source_ref or '-'}`",
            "",
            "## Reports",
            "",
            f"- Run report: `{run_report_path}`",
            f"- Verification report: `{verification_report_path}`",
            "",
            "## Notes",
            "",
            "- Agent self-reported summary is not the source of truth.",
            "- Service-level local verification and remote CI status should be checked before merge.",
        ]
        if issue_number is not None:
            body.extend(["", f"Closes #{issue_number}"])
        return "\n".join(body).strip() + "\n"

    def _upsert_pull_request(
        self,
        card: RepoTaskCard,
        *,
        head_branch: str,
        base_branch: str,
        run_report_path: Path,
        verification_report_path: Path,
    ) -> dict[str, Any]:
        existing = self._find_open_pr_for_branch(head_branch)
        if existing is not None:
            self._best_effort_add_labels(existing.get("number"), ["autopilot"])
            return existing

        title = f"Autopilot: {card.title}"
        body = self._build_pr_body(
            card,
            run_report_path=run_report_path,
            verification_report_path=verification_report_path,
        )
        with tempfile.NamedTemporaryFile(
            "w", delete=False, encoding="utf-8", suffix=".md"
        ) as handle:
            handle.write(body)
            body_path = Path(handle.name)
        try:
            self._create_pull_request(
                head_branch=head_branch,
                base_branch=base_branch,
                title=title,
                body_path=body_path,
            )
        except Exception:
            created = self._find_open_pr_for_branch(head_branch)
            if created is None:
                raise
            self._best_effort_add_labels(created.get("number"), ["autopilot"])
            return created
        finally:
            body_path.unlink(missing_ok=True)

        created = self._find_open_pr_for_branch(head_branch)
        if created is None:
            raise RuntimeError(
                f"PR creation succeeded but PR for branch {head_branch} was not discoverable."
            )
        self._best_effort_add_labels(created.get("number"), ["autopilot"])
        return created

    def _create_pull_request(
        self,
        *,
        head_branch: str,
        base_branch: str,
        title: str,
        body_path: Path,
    ) -> None:
        """Create a GitHub PR, retrying with explicit --repo and owner-qualified head on resolution errors."""
        result = self._run_gh(
            [
                "pr",
                "create",
                "--title",
                title,
                "--body-file",
                str(body_path),
                "--base",
                base_branch,
                "--head",
                head_branch,
            ],
            cwd=self._cwd,
        )
        if result.returncode == 0:
            return

        stderr = (result.stderr or "").lower()
        _resolution_errors = (
            "head sha can't be blank",
            "base sha can't be blank",
            "no commits between",
            "head ref must be a branch",
        )
        if not any(phrase in stderr for phrase in _resolution_errors):
            raise subprocess.CalledProcessError(
                result.returncode, "gh pr create", result.stdout, result.stderr
            )

        log.warning(
            "gh pr create failed with head/base resolution error; retrying with explicit --repo and owner-qualified head: %s",
            (result.stderr or "").strip(),
        )
        try:
            repo_full = self._current_repo_full_name()
        except RuntimeError as exc:
            raise RuntimeError(
                f"gh pr create failed and could not resolve repo name for fallback: {exc}",
            ) from exc

        owner = repo_full.split("/")[0]
        qualified_head = f"{owner}:{head_branch}"
        self._run_gh(
            [
                "pr",
                "create",
                "--repo",
                repo_full,
                "--title",
                title,
                "--body-file",
                str(body_path),
                "--base",
                base_branch,
                "--head",
                qualified_head,
            ],
            cwd=self._cwd,
            check=True,
        )

    def _comment_on_issue(self, issue_number: int, comment: str) -> None:
        try:
            self._run_gh(
                ["issue", "comment", str(issue_number), "--body", comment],
                cwd=self._cwd,
                check=True,
            )
        except Exception as exc:
            self.append_journal(
                kind="github_warning",
                summary=f"Failed to comment on issue #{issue_number}: {exc}",
                metadata={"issue": issue_number},
            )

    def _comment_on_pr(self, pr_number: int, comment: str) -> None:
        try:
            self._run_gh(
                [
                    "pr",
                    "comment",
                    str(pr_number),
                    "--repo",
                    self._current_repo_full_name(),
                    "--body",
                    comment,
                ],
                cwd=self._cwd,
                check=True,
            )
        except Exception as exc:
            self.append_journal(
                kind="github_warning",
                summary=f"Failed to comment on PR #{pr_number}: {exc}",
                metadata={"pr": pr_number},
            )

    def _comment_started(self, card: RepoTaskCard, attempt_count: int) -> str:
        return _bilingual_lines(
            f"OpenHarness autopilot 已开始处理 `{card.id}`，当前第 {attempt_count} 轮执行。",
            f"OpenHarness autopilot started processing `{card.id}`. Attempt {attempt_count} is now running.",
        )

    def _comment_pr_opened(self, pr_number: int, pr_url: str) -> str:
        return _bilingual_lines(
            f"已创建或更新 PR #{pr_number}: {pr_url}",
            f"Created or updated PR #{pr_number}: {pr_url}",
        )

    def _comment_ci_failed(self, attempt_count: int, summary: str) -> str:
        return _bilingual_lines(
            f"远端 CI 失败，准备进入第 {attempt_count + 1} 轮自动修复。摘要：{summary}",
            f"Remote CI failed. Preparing repair round {attempt_count + 1}. Summary: {summary}",
        )

    def _comment_local_failed(self, attempt_count: int, summary: str) -> str:
        return _bilingual_lines(
            f"本地 verification 失败，准备进入第 {attempt_count + 1} 轮自动修复。摘要：{summary}",
            f"Local verification failed. Preparing repair round {attempt_count + 1}. Summary: {summary}",
        )

    def _comment_merged(self, pr_number: int) -> str:
        return _bilingual_lines(
            f"PR #{pr_number} 已自动合并，任务闭环完成。",
            f"PR #{pr_number} was auto-merged. The autopilot loop has completed.",
        )

    def _comment_human_gate(self, pr_number: int) -> str:
        return _bilingual_lines(
            f"PR #{pr_number} 的本地验证和远端 CI 都已通过，但仍需人工 gate 或 merge label。",
            f"PR #{pr_number} passed local verification and remote CI, but still requires a human gate or merge label.",
        )

    def _comment_terminal_failure(self, summary: str) -> str:
        return _bilingual_lines(
            f"自动化流程已停止。失败原因：{summary}",
            f"The automated loop has stopped. Failure reason: {summary}",
        )

    def _pr_status_snapshot(self, pr_number: int) -> dict[str, Any]:
        payload = (
            self._gh_json(
                [
                    "pr",
                    "view",
                    str(pr_number),
                    "--repo",
                    self._current_repo_full_name(),
                    "--json",
                    "state,number,url,isDraft,labels,headRefName,baseRefName,mergeStateStatus,reviewDecision,statusCheckRollup",
                ],
                cwd=self._cwd,
            )
            or {}
        )
        payload["labels"] = [
            _safe_text(label.get("name"))
            for label in payload.get("labels", [])
            if isinstance(label, dict) and _safe_text(label.get("name"))
        ]
        return payload

    def _ci_rollup(self, pr_snapshot: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
        checks = pr_snapshot.get("statusCheckRollup") or []
        normalized: list[dict[str, Any]] = []
        if not isinstance(checks, list):
            checks = []
        for item in checks:
            if not isinstance(item, dict):
                continue
            name = _safe_text(
                item.get("name") or item.get("context") or item.get("__typename") or "check"
            )
            status = _safe_text(item.get("status")).upper()
            conclusion = _safe_text(item.get("conclusion")).upper()
            details_url = _safe_text(item.get("detailsUrl") or item.get("targetUrl"))
            normalized.append(
                {
                    "name": name,
                    "status": status,
                    "conclusion": conclusion,
                    "details_url": details_url,
                }
            )
        if not normalized:
            return "pending", "Remote CI checks have not appeared yet.", normalized
        if any(
            item["status"] in {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING"}
            or (not item["conclusion"] and item["status"] != "COMPLETED")
            for item in normalized
        ):
            return "pending", "Remote CI is still running.", normalized
        failing = [
            item
            for item in normalized
            if item["conclusion"] and item["conclusion"] not in {"SUCCESS", "SKIPPED", "NEUTRAL"}
        ]
        if failing:
            summary = "; ".join(f"{item['name']}={item['conclusion']}" for item in failing[:4])
            return "failed", summary, normalized
        return "success", "All reported remote checks passed.", normalized

    async def _wait_for_pr_ci(
        self, pr_number: int, policies: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any], list[dict[str, Any]]]:
        github_policy = dict(policies.get("autopilot", {}).get("github", {}))
        timeout_seconds = int(github_policy.get("ci_timeout_seconds", 1800) or 1800)
        poll_interval = int(github_policy.get("ci_poll_interval_seconds", 20) or 20)
        no_checks_grace_seconds = int(github_policy.get("no_checks_grace_seconds", 60) or 60)
        checks_settle_seconds = int(github_policy.get("checks_settle_seconds", 20) or 20)
        deadline = time.time() + max(timeout_seconds, 30)
        no_checks_deadline = time.time() + max(no_checks_grace_seconds, poll_interval, 5)
        checks_seen_at: float | None = None
        while True:
            snapshot = self._pr_status_snapshot(pr_number)
            state, summary, checks = self._ci_rollup(snapshot)
            now = time.time()
            if checks and checks_seen_at is None:
                checks_seen_at = now
            if not checks and time.time() >= no_checks_deadline:
                return (
                    "success",
                    "No remote checks were reported after the grace period.",
                    snapshot,
                    checks,
                )
            if (
                state == "success"
                and checks
                and checks_seen_at is not None
                and now < checks_seen_at + max(checks_settle_seconds, 0)
            ):
                await asyncio.sleep(max(poll_interval, 5))
                continue
            if state in {"success", "failed"}:
                return state, summary, snapshot, checks
            if now >= deadline:
                return "failed", "Remote CI timed out.", snapshot, checks
            await asyncio.sleep(max(poll_interval, 5))

    def _automerge_eligible(self, pr_snapshot: dict[str, Any], policies: dict[str, Any]) -> bool:
        github_policy = dict(policies.get("autopilot", {}).get("github", {}))
        auto_merge = dict(github_policy.get("auto_merge", {}))
        mode = _safe_text(auto_merge.get("mode")) or "label_gated"
        required_label = _safe_text(auto_merge.get("required_label")) or "autopilot:merge"
        labels = {str(label).lower() for label in pr_snapshot.get("labels", [])}
        if bool(pr_snapshot.get("isDraft")):
            return False
        if mode == "pr_only":
            return False
        if mode in {"always", "fully_auto"}:
            return True
        return required_label.lower() in labels

    def _merge_pull_request(self, pr_number: int) -> None:
        self._run_gh(
            ["pr", "merge", str(pr_number), "--repo", self._current_repo_full_name(), "--squash"],
            cwd=self._cwd,
            check=True,
        )

    def _extract_reviewer_feedback(self, card_id: str) -> str:
        """Extract CRITICAL/HIGH issues from verification report.

        Returns formatted feedback string, or empty string if no issues found.
        """
        # Find most recent attempt verification file
        attempt_files = sorted(
            self._runs_dir.glob(f"{card_id}-attempt-*-verification.md"),
            reverse=True
        )
        if attempt_files:
            verification_file = attempt_files[0]
        else:
            verification_file = self._runs_dir / f"{card_id}-verification.md"

        if not verification_file.exists():
            return ""

        try:
            content = verification_file.read_text(encoding="utf-8")
        except Exception:
            return ""

        # Look for code-reviewer section with CRITICAL or HIGH severity
        issues = []
        lines = content.split("\n")
        in_reviewer_section = False
        in_findings = False
        current_severity = None

        for line in lines:
            # Detect code-reviewer section
            if "agent:code-reviewer" in line.lower():
                in_reviewer_section = True
                continue

            # Exit reviewer section on next major heading
            if in_reviewer_section and line.startswith("## ") and "code-reviewer" not in line.lower():
                break

            if not in_reviewer_section:
                continue

            # Parse severity
            if line.strip().startswith("Severity:"):
                severity_text = line.split(":", 1)[1].strip().upper()
                if severity_text in ("CRITICAL", "HIGH"):
                    current_severity = severity_text

            # Parse findings section
            if "Findings:" in line:
                in_findings = True
                continue

            # Collect finding bullets
            if in_findings and line.strip().startswith("-"):
                issues.append(line.strip())

            # Stop at summary or next section
            if in_findings and (line.strip().startswith("Summary:") or line.startswith("##")):
                in_findings = False

        if not issues or not current_severity:
            return ""

        return "\n".join([f"Severity: {current_severity}"] + issues)

    def _prepare_repair_prompt(
        self,
        card: RepoTaskCard,
        policies: dict[str, Any],
        *,
        attempt_count: int,
        prior_summary: str | None,
        failure_stage: str | None,
        failure_summary: str | None,
    ) -> str:
        prompt = self._build_execution_prompt(card, policies)
        if attempt_count <= 1 or not failure_stage:
            return prompt
        extras = [
            "",
            "Repair context:",
            f"- Attempt: {attempt_count}",
            f"- Previous failure stage: {failure_stage}",
            f"- Previous failure summary: {failure_summary or '(none)'}",
        ]
        if prior_summary:
            extras.append(f"- Previous agent summary: {_shorten(prior_summary, limit=600)}")

        # Inject code reviewer feedback if previous failure was in code_review or verifying stage
        if failure_stage in ("code_review", "verifying"):
            reviewer_feedback = self._extract_reviewer_feedback(card.id)
            if reviewer_feedback:
                extras.extend(
                    [
                        "",
                        f"[Previous attempt #{attempt_count - 1} failed code review. "
                        "Code reviewer identified these issues that MUST be fixed:]",
                        "",
                        reviewer_feedback,
                        "",
                        "[End of reviewer constraints — address ALL of the above in your implementation.]",
                    ]
                )

        extras.extend(
            [
                "",
                "Repair instructions:",
                "- Make the smallest patch that fixes the reported failure.",
                "- Do not restart the task from scratch if the existing branch already contains valid progress.",
                "- Re-run the relevant verification commands after the fix.",
            ]
        )
        return prompt + "\n" + "\n".join(extras).strip() + "\n"

    async def _process_existing_pr_card(
        self,
        card: RepoTaskCard,
        pr_number: int,
        policies: dict[str, Any],
    ) -> RepoRunResult:
        current_run_report = self._runs_dir / f"{card.id}-run.md"
        current_verification_report = self._runs_dir / f"{card.id}-verification.md"
        stream_writer = get_or_create_writer(card.id, self._runs_dir)
        attempt_count = int(card.metadata.get("attempt_count", 1) or 1)
        try:
            return await self._process_existing_pr_card_with_stream(
                card,
                pr_number,
                policies,
                current_run_report=current_run_report,
                current_verification_report=current_verification_report,
                stream_writer=stream_writer,
                attempt_count=attempt_count,
            )
        finally:
            release_writer(card.id)
            _stream_retention_days = float(
                (policies.get("autopilot", {}).get("execution", {}) or {}).get(
                    "stream_retention_days", 7
                )
            )
            collect_old_stream_files(self._runs_dir, max_age_seconds=_stream_retention_days * 86400)

    async def _process_existing_pr_card_with_stream(
        self,
        card: RepoTaskCard,
        pr_number: int,
        policies: dict[str, Any],
        *,
        current_run_report: Path,
        current_verification_report: Path,
        stream_writer: RunStreamWriter,
        attempt_count: int,
    ) -> RepoRunResult:
        base_branch = self._base_branch(policies)
        head_branch = _safe_text(card.metadata.get("head_branch")) or self._head_branch(
            card, policies
        )
        worktree_path = _safe_text(card.metadata.get("worktree_path"))
        worktree_candidate = Path(worktree_path).expanduser() if worktree_path else None
        sync_cwd: Path | None = None
        if worktree_candidate is not None and ".." not in worktree_candidate.parts:
            sync_cwd = worktree_candidate.resolve()
        push_ok, push_stage, push_summary = True, "branch_sync_skipped", ""
        if (
            sync_cwd is not None
            and sync_cwd.exists()
            and self._is_git_repo(sync_cwd)
            and self._is_same_git_common_dir(sync_cwd)
        ):
            push_ok, push_stage, push_summary = self._push_pr_branch_with_sync(
                sync_cwd,
                base_branch=base_branch,
                head_branch=head_branch,
                policies=policies,
                card_id=card.id,
            )
        if not push_ok:
            self.update_status(
                card.id,
                status="failed",
                note=push_summary,
                metadata_updates={
                    "linked_pr_number": pr_number,
                    "last_failure_stage": push_stage,
                    "last_failure_summary": push_summary,
                },
            )
            return RepoRunResult(
                card_id=card.id,
                status="failed",
                run_report_path=str(current_run_report),
                verification_report_path=str(current_verification_report),
                pr_number=pr_number,
            )
        self.update_status(
            card.id,
            status="waiting_ci",
            note=f"monitoring existing PR #{pr_number}",
            metadata_updates={
                "linked_pr_number": pr_number,
                "head_branch": head_branch,
                "base_branch": base_branch,
            },
        )
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        _review_agent = _safe_text(execution.get("review_agent"))
        effective_review_model = (
            (_review_agent and _resolve_agent_model(_review_agent))
            or _safe_text(execution.get("default_model"))
            or None
        )
        ci_state, ci_summary, pr_snapshot, _checks = await self._wait_for_pr_ci(pr_number, policies)
        pr_url = _safe_text(pr_snapshot.get("url"))
        if ci_state == "failed":
            repeat_meta = self._failure_repeat_metadata(
                card, stage="remote_ci_failed", summary=ci_summary
            )
            ci_meta = {
                "linked_pr_number": pr_number,
                "linked_pr_url": pr_url,
                "last_failure_stage": "remote_ci_failed",
                "last_failure_summary": ci_summary,
                "last_ci_conclusion": "failed",
                "last_ci_summary": ci_summary,
                **repeat_meta,
            }
            max_attempts = self._max_attempts(policies)
            if (
                attempt_count < max_attempts
                and repeat_meta["repeated_failure_count"]
                < self._max_repeated_failure_attempts(policies)
            ):
                self.update_status(
                    card.id,
                    status="queued",
                    note=f"existing PR CI failed; queued repair retry (attempt {attempt_count})",
                    metadata_updates={**ci_meta, "attempt_count": attempt_count},
                )
                self.append_journal(
                    kind="ci_failed",
                    summary=f"{card.title}: remote CI failed, retrying",
                    task_id=card.id,
                    metadata={"attempt_count": attempt_count},
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="queued",
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    pr_number=pr_number,
                    pr_url=pr_url,
                )
            self.update_status(
                card.id,
                status="failed",
                note=f"existing PR CI failed: {ci_summary}",
                metadata_updates=ci_meta,
            )
            self._comment_on_pr(pr_number, self._comment_terminal_failure(ci_summary))
            return RepoRunResult(
                card_id=card.id,
                status="failed",
                run_report_path=str(current_run_report),
                verification_report_path=str(current_verification_report),
                pr_number=pr_number,
                pr_url=pr_url,
            )
        if self._automerge_eligible(pr_snapshot, policies):
            stream_writer.emit("phase_start", {"phase": "remote_review", "attempt": attempt_count})
            remote_review_step = await self._run_remote_code_review_step(
                card,
                pr_number,
                policies=policies,
                model=effective_review_model,
                base_branch=self._base_branch(policies),
                stream=stream_writer,
                checkpoint_attempt=attempt_count,
            )
            stream_writer.emit(
                "phase_end",
                {
                    "phase": "remote_review",
                    "attempt": attempt_count,
                    "ok": remote_review_step.status not in {"failed", "error"},
                },
            )
            atomic_write_text(
                current_verification_report,
                self._render_verification_report(card, [remote_review_step]),
            )
            if remote_review_step.status in {"failed", "error"}:
                summary = (
                    remote_review_step.stderr
                    or remote_review_step.stdout
                    or "remote code review blocked merge"
                )
                remote_review_meta = {
                    "linked_pr_number": pr_number,
                    "linked_pr_url": pr_url,
                    "human_gate_pending": False,
                    "remote_review_status": remote_review_step.status,
                    "last_failure_stage": "remote_review_failed",
                    "last_failure_summary": summary,
                }
                max_attempts = self._max_attempts(policies)
                if attempt_count < max_attempts:
                    self.update_status(
                        card.id,
                        status="queued",
                        note="existing PR remote review failed; queued repair retry",
                        metadata_updates={
                            **remote_review_meta,
                            "autopilot_managed": True,
                            "attempt_count": attempt_count,
                        },
                    )
                    self.append_journal(
                        kind="remote_review_failed_retry",
                        summary=f"{card.title}: existing PR remote review failed, queued repair retry",
                        task_id=card.id,
                        metadata={"pr_number": pr_number, "attempt_count": attempt_count},
                    )
                    self._comment_on_pr(pr_number, self._comment_ci_failed(attempt_count, summary))
                    return RepoRunResult(
                        card_id=card.id,
                        status="queued",
                        run_report_path=str(current_run_report),
                        verification_report_path=str(current_verification_report),
                        verification_steps=[remote_review_step],
                        pr_number=pr_number,
                        pr_url=pr_url,
                    )

                self.update_status(
                    card.id,
                    status="completed",
                    note=f"existing PR #{pr_number} requires human gate after remote review",
                    metadata_updates={
                        **remote_review_meta,
                        "human_gate_pending": True,
                    },
                )
                self._comment_on_pr(pr_number, self._comment_terminal_failure(summary))
                return RepoRunResult(
                    card_id=card.id,
                    status="completed",
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=[remote_review_step],
                    pr_number=pr_number,
                    pr_url=pr_url,
                )

            self._merge_pull_request(pr_number)
            self.update_status(
                card.id,
                status="merged",
                note=f"existing PR #{pr_number} merged automatically",
                metadata_updates={"linked_pr_number": pr_number, "linked_pr_url": pr_url},
            )
            self._comment_on_pr(pr_number, self._comment_merged(pr_number))
            try:
                with RepoFileLock(self._main_checkout_lock_path, timeout=60.0):
                    self._pull_base_branch(base_branch=self._base_branch(policies))
            except Exception as exc:
                self.append_journal(
                    kind="merge_warning",
                    summary=f"post-merge pull failed: {exc}",
                    task_id=card.id,
                    metadata={"pr_number": pr_number},
                )
            else:
                try:
                    with RepoFileLock(self._main_checkout_lock_path, timeout=60.0):
                        self._install_editable()
                except Exception as exc:
                    self.append_journal(
                        kind="merge_warning",
                        summary=f"post-merge install failed: {exc}",
                        task_id=card.id,
                        metadata={"pr_number": pr_number},
                    )
            try:
                self._journal_base_advanced_for_active_cards(base_branch=self._base_branch(policies), merged_card_id=card.id)
            except Exception as exc:
                self.append_journal(
                    kind="base_advanced_warning",
                    summary=f"failed to journal base_advanced after merge: {exc}",
                    task_id=card.id,
                )
            return RepoRunResult(
                card_id=card.id,
                status="merged",
                run_report_path=str(current_run_report),
                verification_report_path=str(current_verification_report),
                verification_steps=[remote_review_step],
                pr_number=pr_number,
                pr_url=pr_url,
            )
        self.update_status(
            card.id,
            status="completed",
            note=f"existing PR #{pr_number} is green; human gate pending",
            metadata_updates={
                "linked_pr_number": pr_number,
                "linked_pr_url": pr_url,
                "human_gate_pending": True,
            },
        )
        self._comment_on_pr(pr_number, self._comment_human_gate(pr_number))
        return RepoRunResult(
            card_id=card.id,
            status="completed",
            run_report_path=str(current_run_report),
            verification_report_path=str(current_verification_report),
            pr_number=pr_number,
            pr_url=pr_url,
        )

    def _build_dashboard_snapshot(self) -> dict[str, Any]:
        registry = self._load_registry()
        cards = sorted(
            registry.cards,
            key=lambda card: (
                self._status_sort_key(card.status),
                -card.score,
                card.created_at,
                card.title.lower(),
            ),
        )
        status_order = [
            "queued",
            "accepted",
            "preparing",
            "running",
            "verifying",
            "pr_open",
            "waiting_ci",
            "repairing",
            "completed",
            "merged",
            "failed",
            "rejected",
            "superseded",
        ]
        columns = {status: [] for status in status_order}
        counts = {status: 0 for status in status_order}
        for card in cards:
            counts[card.status] = counts.get(card.status, 0) + 1
            columns.setdefault(card.status, []).append(self._serialize_card(card))

        focus = None
        for status in (
            "repairing",
            "waiting_ci",
            "running",
            "verifying",
            "preparing",
            "accepted",
            "queued",
        ):
            bucket = columns.get(status) or []
            if bucket:
                focus = bucket[0]
                break

        return {
            "generated_at": time.time(),
            "repo_name": self._cwd.name,
            "repo_path": str(self._cwd),
            "focus": focus,
            "counts": counts,
            "status_order": status_order,
            "columns": columns,
            "cards": [self._serialize_card(card) for card in cards],
            "journal": [
                {
                    "timestamp": entry.timestamp,
                    "kind": entry.kind,
                    "summary": entry.summary,
                    "task_id": entry.task_id,
                    "metadata": entry.metadata,
                }
                for entry in self.load_journal(limit=30)
            ],
            "policies": {
                "autopilot": str(get_project_autopilot_policy_path(self._cwd)),
                "verification": str(get_project_verification_policy_path(self._cwd)),
                "release": str(get_project_release_policy_path(self._cwd)),
            },
            "active_context": self.load_active_context(),
        }

    def _serialize_card(self, card: RepoTaskCard) -> dict[str, Any]:
        verification_steps = []
        for step in card.metadata.get("verification_steps", []) or []:
            if isinstance(step, dict):
                verification_steps.append(
                    {
                        "command": _safe_text(step.get("command")),
                        "status": _safe_text(step.get("status")),
                        "returncode": step.get("returncode"),
                    }
                )
        return {
            "id": card.id,
            "title": card.title,
            "body": card.body,
            "status": card.status,
            "source_kind": card.source_kind,
            "source_ref": card.source_ref,
            "score": card.score,
            "score_reasons": list(card.score_reasons),
            "labels": list(card.labels),
            "created_at": card.created_at,
            "updated_at": card.updated_at,
            "metadata": {
                "last_note": _safe_text(card.metadata.get("last_note")),
                "url": _safe_text(card.metadata.get("url")),
                "execution_model": _safe_text(card.metadata.get("execution_model")),
                "assistant_summary_preview": _safe_text(
                    card.metadata.get("assistant_summary_preview")
                ),
                "human_gate_pending": bool(card.metadata.get("human_gate_pending")),
                "verification_failed": bool(card.metadata.get("verification_failed")),
                "attempt_count": int(card.metadata.get("attempt_count", 0) or 0),
                "max_attempts": int(card.metadata.get("max_attempts", 0) or 0),
                "linked_pr_number": card.metadata.get("linked_pr_number"),
                "linked_pr_url": _safe_text(card.metadata.get("linked_pr_url")),
                "head_branch": _safe_text(card.metadata.get("head_branch")),
                "last_ci_conclusion": _safe_text(card.metadata.get("last_ci_conclusion")),
                "last_ci_summary": _safe_text(card.metadata.get("last_ci_summary")),
                "last_failure_stage": _safe_text(card.metadata.get("last_failure_stage")),
                "last_failure_summary": _safe_text(card.metadata.get("last_failure_summary")),
                "verification_steps": verification_steps,
            },
        }

    def _status_sort_key(self, status: str) -> int:
        order = {
            "repairing": 0,
            "waiting_ci": 1,
            "code_review": 2,
            "running": 3,
            "verifying": 4,
            "preparing": 5,
            "accepted": 6,
            "pr_open": 7,
            "queued": 8,
            "completed": 9,
            "merged": 10,
            "failed": 11,
            "rejected": 12,
            "killed": 13,
            "superseded": 14,
        }
        return order.get(status, 99)

    def _render_dashboard_html(self, snapshot: dict[str, Any]) -> str:
        """Return a minimal fallback HTML page.

        The primary dashboard is now a React + Vite app built from
        ``autopilot-dashboard/``.  This fallback is only written when
        no pre-built ``index.html`` already exists in the output
        directory, so local ``snapshot.json`` generation still works
        without a Node.js toolchain.
        """
        repo_name = escape(_safe_text(snapshot.get("repo_name")) or "OpenHarness")
        generated = time.strftime(
            "%Y-%m-%d %H:%M:%S UTC",
            time.gmtime(float(snapshot.get("generated_at") or time.time())),
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{repo_name} Autopilot Kanban</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg: #0a0a0a; --bg-elevated: #1a1a1a; --ink: #fff;
      --accent: #00d4aa; --muted: #666; --line: #222;
      --mono: "JetBrains Mono", ui-monospace, monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--ink); font-family: var(--mono); font-size: 13px; }}
    .shell {{ max-width: 960px; margin: 80px auto; padding: 0 20px; text-align: center; }}
    h1 {{ font-size: 32px; letter-spacing: 2px; margin-bottom: 16px; }}
    h1 span {{ color: var(--accent); }}
    .sub {{ color: var(--muted); font-size: 12px; line-height: 1.8; margin-bottom: 32px; }}
    .info {{ background: var(--bg-elevated); border: 1px solid var(--line); border-radius: 6px; padding: 24px; text-align: left; }}
    .info p {{ color: #888; font-size: 12px; line-height: 1.7; margin-bottom: 12px; }}
    .info code {{ color: var(--accent); }}
    .ts {{ color: var(--muted); font-size: 10px; letter-spacing: 1px; margin-top: 20px; }}
  </style>
</head>
<body>
  <div class="shell">
    <h1>{repo_name} <span>AUTOPILOT</span></h1>
    <p class="sub">
      This is a fallback page. The full React dashboard is built via CI
      from <code>autopilot-dashboard/</code>.
    </p>
    <div class="info">
      <p>To view the full dashboard locally, build the React app:</p>
      <p><code>cd autopilot-dashboard &amp;&amp; npm install &amp;&amp; npm run build</code></p>
      <p>Then open <code>docs/autopilot/index.html</code> in a browser.</p>
      <p>Snapshot data: <code>snapshot.json</code> (generated {escape(generated)})</p>
    </div>
    <div class="ts">Generated at {escape(generated)}</div>
  </div>
</body>
</html>
"""

    def _ensure_layout(self) -> None:
        for path, payload in (
            (get_project_autopilot_policy_path(self._cwd), _DEFAULT_AUTOPILOT_POLICY),
            (get_project_verification_policy_path(self._cwd), _DEFAULT_VERIFICATION_POLICY),
            (get_project_release_policy_path(self._cwd), _DEFAULT_RELEASE_POLICY),
        ):
            if not path.exists():
                atomic_write_text(path, yaml.safe_dump(payload, sort_keys=False))
        if not self._registry_path.exists():
            self._save_registry(RepoAutopilotRegistry(updated_at=time.time(), cards=[]))
        if not self._context_path.exists():
            self.rebuild_active_context()

    def _start_startup_cleanup(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._cleanup_stale_worktrees())
            return
        self._startup_cleanup_task = loop.create_task(self._cleanup_stale_worktrees())

    def _load_registry(self) -> RepoAutopilotRegistry:
        with RepoFileLock(self._registry_lock_path):
            if not self._registry_path.exists():
                return RepoAutopilotRegistry(updated_at=time.time(), cards=[])
            try:
                payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return RepoAutopilotRegistry(updated_at=time.time(), cards=[])
            return RepoAutopilotRegistry.model_validate(payload)

    def _save_registry(self, registry: RepoAutopilotRegistry) -> None:
        with RepoFileLock(self._registry_lock_path):
            registry.updated_at = time.time()
            atomic_write_text(
                self._registry_path,
                json.dumps(
                    registry.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    default=_json_default,
                )
                + "\n",
            )

    def _build_fingerprint(
        self,
        *,
        source_kind: RepoTaskSource,
        source_ref: str,
        title: str,
        body: str,
    ) -> str:
        basis = source_ref.strip() or f"{title.strip()}\n{body.strip()}"
        digest = sha1(basis.encode("utf-8")).hexdigest()[:16]
        return f"{source_kind}:{digest}"

    def _score_card(self, card: RepoTaskCard) -> tuple[int, list[str]]:
        score = _SOURCE_BASE_SCORES.get(card.source_kind, 50)
        reasons = [f"source={card.source_kind}"]
        text = f"{card.title}\n{card.body}".lower()
        labels = {label.lower() for label in card.labels}
        if card.source_kind == "github_issue":
            if labels.intersection({"bug", "regression", "failure"}):
                score += 25
                reasons.append("bug-labelled issue")
            if any(hint in text for hint in _BUG_HINTS):
                score += 15
                reasons.append("issue looks like a bug/regression")
        if card.source_kind == "github_pr":
            if bool(card.metadata.get("is_draft")):
                score -= 30
                reasons.append("draft pr")
            if str(card.metadata.get("merge_state_status", "")).upper() == "CLEAN":
                score += 20
                reasons.append("clean merge state")
            if str(card.metadata.get("review_decision", "")).upper() == "APPROVED":
                score += 20
                reasons.append("approved review state")
        if card.source_kind in {"ohmo_request", "manual_idea"}:
            score += 10
            reasons.append("direct user-driven input")
        if any(hint in text for hint in _URGENT_HINTS) or labels.intersection(
            {"urgent", "p0", "p1", "high", "critical", "blocker"}
        ):
            score += 20
            reasons.append("urgent signals")
        age_days = max(0.0, (time.time() - card.updated_at) / 86400.0)
        freshness_bonus = max(0, 10 - int(age_days))
        if freshness_bonus:
            score += freshness_bonus
            reasons.append("recently updated")
        return score, reasons

    def _normalize_labels(self, labels: list[str] | None) -> list[str]:
        if not labels:
            return []
        return sorted({label.strip() for label in labels if label and label.strip()})

    def _merge_labels(self, existing: list[str], incoming: list[str]) -> list[str]:
        return sorted({*existing, *incoming})

    def _run_gh_json(self, command: list[str]) -> list[dict[str, Any]]:
        try:
            completed = subprocess.run(
                command,
                cwd=self._cwd,
                capture_output=True,
                text=True,
                check=False,
                start_new_session=True,
                timeout=60,
            )
        except FileNotFoundError as exc:
            raise ValueError("gh CLI is not installed.") from exc
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout).strip() or "gh command failed"
            raise ValueError(error)
        raw = (completed.stdout or "").strip()
        if not raw:
            return []
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Expected gh JSON array output.")
        return [item for item in payload if isinstance(item, dict)]

    def _read_yaml(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return dict(default)
        if not isinstance(payload, dict):
            return dict(default)
        return payload

    def _build_execution_prompt(self, card: RepoTaskCard, policies: dict[str, Any]) -> str:
        autopilot_policy = yaml.safe_dump(policies["autopilot"], sort_keys=False).strip()
        verification_policy = yaml.safe_dump(policies["verification"], sort_keys=False).strip()
        release_policy = yaml.safe_dump(policies["release"], sort_keys=False).strip()
        return (
            "You are executing one repo-autopilot task for the current repository.\n\n"
            "Goal:\n"
            "- Make the smallest coherent implementation that resolves the task.\n"
            "- Run the relevant verification commands yourself before stopping.\n"
            "- Do not merge, release, or perform irreversible external actions.\n"
            "- Leave the repository in a reviewable state and summarize what changed.\n\n"
            f"Task ID: {card.id}\n"
            f"Source: {card.source_kind}\n"
            f"Source ref: {card.source_ref or '-'}\n"
            f"Title: {card.title}\n"
            f"Body:\n{card.body or '(none)'}\n\n"
            "Autopilot policy:\n"
            f"{autopilot_policy}\n\n"
            "Verification policy:\n"
            f"{verification_policy}\n\n"
            "Release policy:\n"
            f"{release_policy}\n\n"
            "Expected output:\n"
            "1. What you changed.\n"
            "2. What you verified.\n"
            "3. Any remaining risk or human follow-up.\n"
        )

    async def _run_agent_prompt(
        self,
        prompt: str,
        *,
        model: str | None,
        max_turns: int | None,
        permission_mode: str,
        cwd: Path | None = None,
        stream: RunStreamWriter | None = None,
        phase: str | None = None,
        checkpoint_card_id: str | None = None,
        checkpoint_phase: str | None = None,
        checkpoint_attempt: int = 1,
        resume_messages: list[Any] | None = None,
    ) -> str:
        from openharness.ui.runtime import build_runtime, close_runtime, start_runtime

        async def _allow(_tool_name: str, _reason: str) -> bool:
            return True

        async def _ask(_question: str) -> str:
            return ""

        bundle = None
        collected: list[str] = []
        agent_failed = False
        try:
            bundle = await build_runtime(
                cwd=str(cwd or self._cwd),
                model=model,
                max_turns=max_turns,
                permission_prompt=_allow,
                ask_user_prompt=_ask,
                permission_mode=permission_mode,
            )
            await start_runtime(bundle)
            if resume_messages:
                from openharness.engine.messages import sanitize_conversation_messages

                bundle.engine.load_messages(sanitize_conversation_messages(list(resume_messages)))
                event_iter = bundle.engine.continue_pending(max_turns=max_turns)
            else:
                event_iter = bundle.engine.submit_message(prompt)
            async for event in event_iter:
                if isinstance(event, AssistantTextDelta):
                    collected.append(event.text)
                    if stream is not None:
                        stream.emit("text_delta", {"text": event.text, "phase": phase})
                elif isinstance(event, ToolExecutionStarted):
                    if stream is not None:
                        stream.emit(
                            "tool_call",
                            {
                                "name": event.tool_name,
                                "input_summary": summarize_tool_input(event.tool_input),
                                "phase": phase,
                            },
                        )
                elif isinstance(event, ToolExecutionCompleted):
                    if stream is not None:
                        stream.emit(
                            "tool_result",
                            {
                                "name": event.tool_name,
                                "is_error": bool(event.is_error),
                                "summary": summarize_tool_output(event.output),
                                "phase": phase,
                            },
                        )
                elif isinstance(event, AssistantTurnComplete):
                    text = event.message.text.strip()
                    if text and not "".join(collected).strip():
                        collected.append(text)
                elif isinstance(event, ErrorEvent):
                    if stream is not None:
                        stream.emit("error", {"message": event.message, "phase": phase})
                    agent_failed = True
                    raise RuntimeError(event.message)
        except BaseException:
            agent_failed = True
            raise
        finally:
            # Snapshot engine state BEFORE close_runtime — close may invalidate
            # the engine. Save unconditionally on failure (any exception path),
            # not just when the agent loop raised, so build/start failures still
            # leave a checkpoint when partial messages exist.
            if checkpoint_card_id and checkpoint_phase and bundle is not None:
                engine_messages: list[Any] = []
                has_pending = False
                try:
                    engine_messages = list(getattr(bundle.engine, "_messages", []) or [])
                    has_pending = bool(bundle.engine.has_pending_continuation())
                except Exception as snap_exc:
                    log.warning("Could not snapshot engine state: %s", snap_exc)
                try:
                    if agent_failed and engine_messages:
                        ckpt_path = save_checkpoint(
                            self._runs_dir,
                            card_id=checkpoint_card_id,
                            phase=checkpoint_phase,
                            attempt=checkpoint_attempt,
                            model=model,
                            permission_mode=permission_mode,
                            cwd=str(cwd or self._cwd),
                            messages=engine_messages,
                            has_pending_continuation=has_pending,
                        )
                        if stream is not None:
                            stream.emit(
                                "checkpoint_saved",
                                {"phase": checkpoint_phase, "file": ckpt_path.name},
                            )
                    elif not agent_failed:
                        clear_checkpoints(self._runs_dir, checkpoint_card_id)
                except Exception as ckpt_exc:
                    log.warning("Checkpoint save/clear failed: %s", ckpt_exc)
            if bundle is not None:
                try:
                    await close_runtime(bundle)
                except Exception as close_exc:
                    log.warning("close_runtime failed: %s", close_exc)
        return "".join(collected).strip()

    async def _run_remote_code_review_step(
        self,
        card: RepoTaskCard,
        pr_number: int,
        *,
        policies: dict[str, Any],
        model: str | None,
        base_branch: str = "main",
        stream: RunStreamWriter | None = None,
        checkpoint_attempt: int = 1,
    ) -> RepoVerificationStep:
        review_cfg = (policies.get("autopilot", {}).get("github", {}) or {}).get(
            "remote_code_review", {}
        ) or {}
        if not review_cfg.get("enabled", True):
            return RepoVerificationStep(
                command=f"agent:code-reviewer (PR #{pr_number} diff vs {base_branch})",
                returncode=0,
                status="skipped",
                stdout="Remote PR code review disabled by policy.",
                stderr="",
            )

        max_chars = int(review_cfg.get("max_diff_chars", 80000))
        block_on = {str(s).lower() for s in review_cfg.get("block_on", ["critical"])}
        _raw_turns = review_cfg.get("max_turns", 0)
        max_turns: int | None = None if _raw_turns in (None, "", 0) else int(_raw_turns)
        command = f"agent:code-reviewer (PR #{pr_number} diff vs {base_branch})"

        diff_result = self._run_gh(
            ["pr", "diff", str(pr_number), "--repo", self._current_repo_full_name()],
            cwd=self._cwd,
        )
        if diff_result.returncode != 0:
            return RepoVerificationStep(
                command=command,
                returncode=diff_result.returncode,
                status="error",
                stdout=diff_result.stdout or "",
                stderr=(diff_result.stderr or "gh pr diff failed").strip(),
            )

        diff_text = diff_result.stdout or ""
        if not diff_text.strip():
            return RepoVerificationStep(
                command=command,
                returncode=0,
                status="skipped",
                stdout="No PR diff detected.",
                stderr="",
            )
        if re.search(
            r"^diff --git a/\.venv(?:/[^\s]+)? b/\.venv(?:/[^\s]+)?$", diff_text, re.MULTILINE
        ):
            return RepoVerificationStep(
                command=command,
                returncode=1,
                status="failed",
                stdout="Severity: CRITICAL\nFindings:\n  - .venv: tracked virtualenv artifact must not be committed\nSummary: repository-local virtualenv artifacts are machine-specific and break uv/npm tooling.",
                stderr="severity=critical",
            )

        truncated = False
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars]
            truncated = True

        prompt = (
            f"Review GitHub PR #{pr_number} for task `{card.id}` ({card.title}) against `{base_branch}`.\n\n"
            "Output format (verbatim):\n"
            "  Severity: <CRITICAL|HIGH|MEDIUM|LOW|NONE>\n"
            "  Findings:\n"
            "    - <file:line> <category> <description>\n"
            "  Summary: <one paragraph>\n\n"
            "Apply the rules in `~/.claude/rules/common/code-review.md`. "
            "Also verify the implementation satisfies the task requirement, not just that the diff is syntactically safe. "
            "Treat committed virtualenvs, machine-local absolute paths, and missing behavior for named configuration options as CRITICAL. "
            "Block on CRITICAL only.\n\n"
            f"PR diff{' (truncated)' if truncated else ''}:\n```\n{diff_text}\n```\n"
        )

        try:
            output = await self._run_agent_prompt(
                prompt,
                model=model,
                max_turns=max_turns,
                permission_mode="full_auto",
                cwd=self._cwd,
                stream=stream,
                checkpoint_card_id=card.id,
                checkpoint_phase="remote_review",
                checkpoint_attempt=checkpoint_attempt,
            )
        except Exception as exc:
            return RepoVerificationStep(
                command=command,
                returncode=0,
                status="skipped",
                stdout="",
                stderr=f"remote code-reviewer agent failed (skipped): {exc}",
            )

        severity = _parse_review_severity(output)
        is_blocking = severity in block_on
        return RepoVerificationStep(
            command=command,
            returncode=1 if is_blocking else 0,
            status="failed" if is_blocking else "success",
            stdout=output,
            stderr=f"severity={severity}" if is_blocking else "",
        )

    async def _run_code_review_step(
        self,
        card: RepoTaskCard,
        *,
        cwd: Path,
        base_branch: str,
        policies: dict[str, Any],
        model: str | None,
        stream: RunStreamWriter | None = None,
        checkpoint_attempt: int = 1,
    ) -> RepoVerificationStep:
        """Spawn the code-reviewer agent on the worktree diff and turn its severity into a step."""
        review_cfg = (policies.get("verification") or {}).get("code_review") or {}
        max_chars = int(review_cfg.get("max_diff_chars", 80000))
        block_on = {str(s).lower() for s in review_cfg.get("block_on", ["critical"])}
        raw_turns = review_cfg.get("max_turns", 0)
        max_turns: int | None = None if raw_turns in (None, "", 0) else int(raw_turns)

        try:
            diff_text = (
                self._run_git(
                    ["diff", f"origin/{base_branch}...HEAD"],
                    cwd=cwd,
                    check=False,
                ).stdout
                or ""
            )
        except Exception as exc:  # git absent / no remote
            return RepoVerificationStep(
                command=f"agent:code-reviewer (diff vs {base_branch})",
                returncode=0,
                status="skipped",
                stdout="",
                stderr=f"could not collect diff: {exc}",
            )

        if not diff_text.strip():
            return RepoVerificationStep(
                command=f"agent:code-reviewer (diff vs {base_branch})",
                returncode=0,
                status="skipped",
                stdout="No changes detected vs base branch.",
                stderr="",
            )

        truncated = False
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars]
            truncated = True

        prompt = (
            f"Review the following diff for task `{card.id}` ({card.title}).\n\n"
            "Output format (verbatim):\n"
            "  Severity: <CRITICAL|HIGH|MEDIUM|LOW|NONE>\n"
            "  Findings:\n"
            "    - <file:line> <category> <description>\n"
            "  Summary: <one paragraph>\n\n"
            "Apply the rules in `~/.claude/rules/common/code-review.md`. "
            "Also verify the implementation satisfies the task requirement, not just that the diff is syntactically safe. "
            "Treat committed virtualenvs, machine-local absolute paths, and missing behavior for named configuration options as CRITICAL. "
            "Block on CRITICAL only.\n\n"
            f"Diff{' (truncated)' if truncated else ''}:\n```\n{diff_text}\n```\n"
        )

        try:
            output = await self._run_agent_prompt(
                prompt,
                model=model,
                max_turns=max_turns,
                permission_mode="full_auto",
                cwd=cwd,
                stream=stream,
                checkpoint_card_id=card.id,
                checkpoint_phase="local_review",
                checkpoint_attempt=checkpoint_attempt,
            )
        except Exception as exc:
            return RepoVerificationStep(
                command=f"agent:code-reviewer (diff vs {base_branch})",
                returncode=0,
                status="skipped",
                stdout="",
                stderr=f"code-reviewer agent failed (skipped): {exc}",
            )

        severity = _parse_review_severity(output)
        is_blocking = severity in block_on
        return RepoVerificationStep(
            command=f"agent:code-reviewer (diff vs {base_branch})",
            returncode=1 if is_blocking else 0,
            status="failed" if is_blocking else "success",
            stdout=output,
            stderr=f"severity={severity}" if is_blocking else "",
        )

    def _verification_commands(
        self, policies: dict[str, Any], *, cwd: Path | None = None
    ) -> list[_VerificationCommand]:
        configured = policies.get("verification", {}).get("commands", [])
        parsed = [_parse_verification_entry(entry) for entry in configured]
        check_cwd = cwd or self._cwd
        selected: list[_VerificationCommand] = []
        for cmd in parsed:
            if cmd.error is not None:
                selected.append(cmd)
                continue
            if _looks_available(cmd.raw, check_cwd):
                selected.append(cmd)
        return selected

    def _run_verification_steps(
        self, policies: dict[str, Any], *, cwd: Path | None = None
    ) -> list[RepoVerificationStep]:
        steps: list[RepoVerificationStep] = []
        baseline_cache: dict[str, RepoVerificationStep] = {}
        verification_policy = policies.get("verification") or {}
        ignore_preexisting = bool(verification_policy.get("ignore_preexisting_failures", True))
        base_branch = self._base_branch(policies)
        active_cwd = cwd or self._cwd
        for cmd in self._verification_commands(policies, cwd=active_cwd):
            if cmd.error is not None:
                steps.append(
                    RepoVerificationStep(
                        command=cmd.raw,
                        returncode=-1,
                        status="error",
                        stderr=f"verification policy error: {cmd.error}",
                    )
                )
                continue
            step = self._run_verification_command(cmd, cwd=active_cwd)
            if ignore_preexisting and step.status in {"failed", "error"}:
                baseline_step = self._run_baseline_verification_command(
                    cmd,
                    base_branch=base_branch,
                    cache=baseline_cache,
                )
                if baseline_step is not None and baseline_step.status in {"failed", "error"}:
                    step = step.model_copy(
                        update={
                            "status": "skipped",
                            "stderr": (
                                (step.stderr or "")
                                + "\nSkipped: verification command also fails on the base branch."
                            ).strip(),
                        }
                    )
            steps.append(step)
        return steps

    def _run_verification_command(
        self, cmd: _VerificationCommand, *, cwd: Path
    ) -> RepoVerificationStep:
        import signal

        target: str | list[str] = cmd.raw if cmd.shell else list(cmd.argv)
        proc = None
        try:
            proc = subprocess.Popen(
                target,
                cwd=cwd,
                env=_verification_subprocess_env(cwd),
                shell=cmd.shell,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(timeout=1800)
            return RepoVerificationStep(
                command=cmd.raw,
                returncode=proc.returncode,
                status="success" if proc.returncode == 0 else "failed",
                stdout=(stdout or "")[-4000:],
                stderr=(stderr or "")[-4000:],
            )
        except FileNotFoundError as exc:
            return RepoVerificationStep(
                command=cmd.raw,
                returncode=-1,
                status="error",
                stderr=f"executable not found: {exc}",
            )
        except subprocess.TimeoutExpired as exc:
            if proc is not None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            return RepoVerificationStep(
                command=cmd.raw,
                returncode=-1,
                status="error",
                stdout=_safe_text(getattr(exc, "stdout", ""))[-4000:],
                stderr=f"Timed out after {exc.timeout}s",
            )
        except Exception as exc:  # pragma: no cover - defensive
            return RepoVerificationStep(
                command=cmd.raw,
                returncode=-1,
                status="error",
                stderr=str(exc),
            )

    def _run_baseline_verification_command(
        self,
        cmd: _VerificationCommand,
        *,
        base_branch: str,
        cache: dict[str, RepoVerificationStep],
    ) -> RepoVerificationStep | None:
        if cmd.raw in cache:
            return cache[cmd.raw]
        try:
            is_git = self._is_git_repo(self._cwd)
        except Exception:
            is_git = False
        if not is_git:
            return None
        with tempfile.TemporaryDirectory(prefix="openharness-baseline-") as tmp:
            baseline_cwd = Path(tmp) / "repo"
            try:
                self._run_git(
                    ["worktree", "add", "--detach", str(baseline_cwd), f"origin/{base_branch}"],
                    check=True,
                )
                step = self._run_verification_command(cmd, cwd=baseline_cwd)
            except Exception as exc:
                log.warning("Skipping baseline verification for %r: %s", cmd.raw, exc)
                return None
            finally:
                if baseline_cwd.exists():
                    self._run_git(["worktree", "remove", "--force", str(baseline_cwd)])
        cache[cmd.raw] = step
        return step

    def _render_verification_report(
        self,
        card: RepoTaskCard,
        steps: list[RepoVerificationStep],
    ) -> str:
        lines = [
            f"# Verification Report: {card.id}",
            "",
            f"Title: {card.title}",
            "",
        ]
        if not steps:
            lines.append("No verification commands were applicable.")
            return "\n".join(lines).strip() + "\n"
        for step in steps:
            lines.extend(
                [
                    f"## {step.status.upper()} :: {step.command}",
                    "",
                    f"Return code: {step.returncode}",
                    "",
                ]
            )
            if step.stdout:
                lines.extend(["### stdout", "```text", step.stdout, "```", ""])
            if step.stderr:
                lines.extend(["### stderr", "```text", step.stderr, "```", ""])
        return "\n".join(lines).strip() + "\n"

    def _render_run_report(
        self,
        card: RepoTaskCard,
        *,
        agent_summary: str,
        verification_steps: list[RepoVerificationStep],
        verification_status: str,
    ) -> str:
        lines = [
            f"# Autopilot Run Report: {card.id}",
            "",
            f"Title: {card.title}",
            f"Source: {card.source_kind}",
            f"Source ref: {card.source_ref or '-'}",
            "",
            "## Agent Self-Reported Summary",
            "",
            agent_summary.strip() or "(empty agent summary)",
            "",
            "## Service-Level Ground Truth",
            "",
            (
                "The section above is the model's own summary. "
                "Treat it as untrusted until the service-level verification results below finish."
            ),
            "",
        ]

        if verification_status == "not_started":
            lines.extend(
                [
                    "- Verification status: not started.",
                    "- The agent run itself failed before service-level verification could begin.",
                ]
            )
        elif verification_status == "pending":
            lines.extend(
                [
                    "- Verification status: pending.",
                    "- Service-level verification has not finished yet.",
                ]
            )
        else:
            overall = "passed" if verification_status == "passed" else "failed"
            lines.append(f"- Verification status: {overall}.")
            if verification_steps:
                for step in verification_steps:
                    lines.append(f"- [{step.status}] `{step.command}` (rc={step.returncode})")
            else:
                lines.append("- No verification commands were applicable.")

        return "\n".join(lines).strip() + "\n"
