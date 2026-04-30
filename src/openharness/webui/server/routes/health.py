"""Health-check and metadata endpoints.

These two endpoints are the only ones the SPA hits *before* it has an active
token in localStorage, so they have different auth expectations:

* ``GET /api/health`` is unauthenticated and returns a fixed ``{"ok": True}``
  payload — used by tunnels (Cloudflare/Tailscale) and uptime probes.
* ``GET /api/meta`` requires a valid bearer token and returns server-side
  defaults the SPA needs to bootstrap (cwd, model, permission mode, etc.).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from openharness.webui.server.state import WebUIState, get_state, require_token

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, bool]:
    """Liveness probe used by tunnels and the SPA."""
    return {"ok": True}


@router.get("/meta", dependencies=[Depends(require_token)])
def meta(state: WebUIState = Depends(get_state)) -> dict[str, object]:
    """Return SPA bootstrap metadata."""
    return {
        "cwd": str(state.cwd),
        "model": state.model,
        "api_format": state.api_format,
        "permission_mode": state.permission_mode,
        **state.extra_meta,
    }
