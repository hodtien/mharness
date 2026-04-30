"""Web UI configuration."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field


@dataclass
class WebUIConfig:
    """Configuration for the Web UI server."""

    host: str = "127.0.0.1"
    port: int = 8765
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    cwd: str | None = None
    # Forwarded to BackendHostConfig
    model: str | None = None
    api_key: str | None = None
    api_format: str | None = None
    base_url: str | None = None
    system_prompt: str | None = None
    permission_mode: str | None = None
    debug: bool = False
