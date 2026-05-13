"""Repo autopilot data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from openharness.config.settings import CronScheduleConfig  # noqa: F401

RepoTaskStatus = Literal[
    "pending",
    "queued",
    "accepted",
    "preparing",
    "running",
    "verifying",
    "pr_open",
    "waiting_ci",
    "code_review",
    "repairing",
    "completed",
    "merged",
    "done",
    "failed",
    "rejected",
    "killed",
    "superseded",
    "paused",
]
RepoTaskSource = Literal[
    "ohmo_request",
    "manual_idea",
    "github_issue",
    "github_pr",
    "claude_code_candidate",
]


def _coerce_timestamp(v: Any) -> float:
    if isinstance(v, datetime):
        return v.timestamp()
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    return float(v)


class RepoTaskCard(BaseModel):
    """One normalized repo-level work item."""

    id: str
    fingerprint: str
    title: str
    body: str = ""
    source_kind: RepoTaskSource
    source_ref: str = ""
    status: RepoTaskStatus = "queued"
    score: int = 0
    score_reasons: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    created_at: float
    updated_at: float

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_ts(cls, v: Any) -> float:
        return _coerce_timestamp(v)


class RepoJournalEntry(BaseModel):
    """Append-only repo journal event."""

    timestamp: float
    kind: str
    summary: str
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepoAutopilotRegistry(BaseModel):
    """Full registry payload."""

    version: int = 1
    updated_at: float = 0.0
    cards: list[RepoTaskCard] = Field(default_factory=list)

    @field_validator("updated_at", mode="before")
    @classmethod
    def _coerce_ts(cls, v: Any) -> float:
        return _coerce_timestamp(v)


class RepoVerificationStep(BaseModel):
    """One verification command result."""

    command: str
    returncode: int
    status: Literal["success", "failed", "skipped", "error"]
    stdout: str = ""
    stderr: str = ""


class RepoRunResult(BaseModel):
    """Result of one autopilot execution attempt."""

    card_id: str
    status: RepoTaskStatus
    assistant_summary: str = ""
    run_report_path: str = ""
    verification_report_path: str = ""
    verification_steps: list[RepoVerificationStep] = Field(default_factory=list)
    attempt_count: int = 0
    worktree_path: str = ""
    pr_number: int | None = None
    pr_url: str = ""


class PreflightCheck(BaseModel):
    """Result of one individual preflight check."""

    name: str
    status: Literal["ok", "warn", "fail", "error"]
    reason: str = ""
    transient: bool = False
    detail: str = ""


class PreflightResult(BaseModel):
    """Aggregated result of all preflight checks before running a card."""

    passed: bool
    checks: list[PreflightCheck] = Field(default_factory=list)
    fatal: list[PreflightCheck] = Field(default_factory=list)
    transient: list[PreflightCheck] = Field(default_factory=list)


