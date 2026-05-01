"""Provider profile REST endpoints for the Web UI.

Exposes the merged provider profile catalog (built-ins from
:func:`default_provider_profiles` plus user-defined entries in settings)
alongside per-profile auth and active flags. Credential and active-profile
detection is delegated to :class:`openharness.auth.manager.AuthManager` so the
Web UI matches what the CLI and TUI display.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from openharness.config.settings import load_settings, save_settings
from openharness.webui.server.sessions import SessionManager
from openharness.webui.server.state import get_session_manager, require_token

router = APIRouter(
    prefix="/api/providers",
    tags=["providers"],
    dependencies=[Depends(require_token)],
)


def _active_session_settings(manager: SessionManager):
    """Return settings from the first running WebUI session, if any.

    Mirrors :mod:`openharness.webui.server.routes.modes`: an active session may
    carry CLI-style overrides (model/api_format/active_profile) that aren't on
    disk, so the active-profile flag must reflect *that* session — not just the
    persisted ``settings.json``.
    """
    for entry in manager.entries():
        if entry.task is None or entry.task.done():
            continue
        bundle = getattr(entry.host, "_bundle", None)
        if bundle is not None:
            return bundle.current_settings()
    return None


def _build_items(manager: SessionManager) -> list[dict[str, object]]:
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

    settings = _active_session_settings(manager)
    statuses = AuthManager(settings).get_profile_statuses() if settings else AuthManager().get_profile_statuses()

    items: list[dict[str, object]] = []
    for name, profile_status in statuses.items():
        items.append(
            {
                "id": name,
                "label": profile_status["label"],
                "provider": profile_status["provider"],
                "api_format": profile_status["api_format"],
                "default_model": profile_status["model"],
                "base_url": profile_status.get("base_url"),
                "has_credentials": bool(profile_status.get("configured")),
                "is_active": bool(profile_status.get("active")),
            }
        )
    return items


@router.get("")
def list_providers(
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Return the merged provider profile catalog with auth and active flags.

    Each item contains ``id``, ``label``, ``provider``, ``api_format``,
    ``default_model``, ``base_url``, ``has_credentials``, and ``is_active``.
    The active profile is the one resolved for the running WebUI session
    (if any), falling back to the persisted settings.
    """
    return {"providers": _build_items(manager)}


@router.get("/")
def list_providers_slash(
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Keep behavior stable for callers that include a trailing slash."""
    return list_providers(manager)


@router.post("/{name}/activate")
def activate_provider(
    name: str,
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Switch the active provider profile.

    Persists ``active_profile`` to ``settings.json`` and updates the WebUI
    :class:`SessionManager` config so subsequent ``POST /api/sessions`` calls
    pick up the new model / api_format / base_url. Existing live sessions
    keep their current ``BackendHostConfig`` until the next reconnect, per
    the task spec.
    """
    settings = load_settings()
    profiles = settings.merged_profiles()
    if name not in profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider profile: {name}",
        )

    # Persist the new active profile. ``save_settings`` runs
    # ``materialize_active_profile`` which projects the profile onto the
    # legacy flat ``model``/``api_format``/``base_url`` fields.
    updated = settings.model_copy(update={"active_profile": name})
    try:
        save_settings(updated)
    except Exception as exc:  # pragma: no cover - filesystem failure
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist settings: {exc}",
        ) from exc

    # Re-read so we get the materialized model the same way the CLI/TUI do.
    materialized = load_settings()
    profile = materialized.merged_profiles()[name]
    new_model = materialized.model or profile.default_model

    # Reload BackendHostConfig defaults for *new* sessions. Existing
    # sessions keep their config until reconnect.
    manager.update_provider_defaults(
        model=new_model,
        api_format=profile.api_format,
        base_url=profile.base_url,
    )

    return {"ok": True, "model": new_model}
