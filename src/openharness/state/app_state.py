"""Minimal application state model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppState:
    """Shared mutable UI/session state."""

    model: str
    permission_mode: str
    theme: str
    cwd: str = "."
    provider: str = "unknown"
    active_profile: str = ""
    auth_status: str = "missing"
    base_url: str = ""
    vim_enabled: bool = False
    voice_enabled: bool = False
    voice_available: bool = False
    voice_reason: str = ""
    fast_mode: bool = False
    effort: str = "medium"
    passes: int = 1
    notifications_enabled: bool = True
    auto_compact_threshold_tokens: int | None = None
    mcp_connected: int = 0
    mcp_failed: int = 0
    bridge_sessions: int = 0
    output_style: str = "default"
    keybindings: dict[str, str] = field(default_factory=dict)
