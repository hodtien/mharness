"""Provider profile REST endpoints for the Web UI.

Exposes the merged provider profile catalog (built-ins from
:func:`default_provider_profiles` plus user-defined entries in settings)
alongside per-profile auth and active flags. Credential and active-profile
detection is delegated to :class:`openharness.auth.manager.AuthManager` so the
Web UI matches what the CLI and TUI display.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from openharness.webui.server.state import require_token

router = APIRouter(
    prefix="/api/providers",
    tags=["providers"],
    dependencies=[Depends(require_token)],
)


def _build_items() -> list[dict[str, object]]:
    """Return the provider list payload using ``AuthManager.get_profile_statuses``.

    ``get_profile_statuses`` already merges built-ins with custom profiles
    (via ``Settings.merged_profiles``), resolves the active profile, and
    decides whether credentials are available — including env-var fallbacks
    and per-profile credential slots. Reusing it keeps the API consistent
    with the rest of OpenHarness.
    """
    # Local import: avoids loading the auth/config subsystems at module
    # import time (this router is included unconditionally by ``create_app``).
    from openharness.auth.manager import AuthManager

    statuses = AuthManager().get_profile_statuses()

    items: list[dict[str, object]] = []
    for name, status in statuses.items():
        items.append(
            {
                "id": name,
                "label": status["label"],
                "provider": status["provider"],
                "api_format": status["api_format"],
                "default_model": status["model"],
                "base_url": status.get("base_url"),
                "has_credentials": bool(status.get("configured")),
                "is_active": bool(status.get("active")),
            }
        )
    return items


@router.get("")
def list_providers() -> dict[str, object]:
    """Return the merged provider profile catalog with auth and active flags.

    Each item contains ``id``, ``label``, ``provider``, ``api_format``,
    ``default_model``, ``base_url``, ``has_credentials``, and ``is_active``.
    The active profile is the one resolved for the current process/session
    via :class:`AuthManager`.
    """
    return {"providers": _build_items()}


@router.get("/")
def list_providers_slash() -> dict[str, object]:
    """Keep behavior stable for callers that include a trailing slash."""
    return list_providers()
