"""Task data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


TaskType = Literal["local_bash", "local_agent", "remote_agent", "in_process_teammate"]
TaskStatus = Literal["pending", "running", "completed", "failed", "killed"]


@dataclass
class TaskRecord:
    """Runtime representation of a background task."""

    id: str
    type: TaskType
    status: TaskStatus
    description: str
    cwd: str
    output_file: Path
    command: str | None = None
    prompt: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    ended_at: float | None = None
    return_code: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    # Terminal tracking fields
    last_heartbeat_at: float | None = None
    terminal_at: float | None = None
    error_summary: str | None = None
    last_log_excerpt: str | None = None


# Default stale threshold: 15 minutes without heartbeat
DEFAULT_STALE_THRESHOLD_SECONDS = 15 * 60
