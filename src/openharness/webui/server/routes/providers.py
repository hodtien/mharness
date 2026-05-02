"""Provider profile REST endpoints for the Web UI.

Exposes the merged provider profile catalog (built-ins from
:func:`default_provider_profiles` plus user-defined entries in settings)
alongside per-profile auth and active flags. Credential and active-profile
detection is delegated to :class:`openharness.auth.manager.AuthManager` so the
Web UI matches what the CLI and TUI display.
"""

from __future__ import annotations

from urllib.parse import urljoin

import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status

from openharness.auth.storage import load_credential, store_credential
from openharness.config.settings import (
    ProviderProfile,
    auth_source_uses_api_key,
    credential_storage_provider_name,
    load_settings,
    save_settings,
)
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


class _CredentialsBody(BaseModel):
    """Request body for ``POST /api/providers/{name}/credentials``."""

    api_key: str | None = None
    base_url: str | None = None


def _mask_api_key(api_key: str) -> str:
    """Return a masked representation of *api_key* exposing only the last 4 chars."""
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return "*" * (len(api_key) - 4) + api_key[-4:]


@router.post("/{name}/credentials")
def set_provider_credentials(
    name: str,
    body: _CredentialsBody,
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    """Save credentials and/or base_url override for a provider profile.

    - ``api_key`` is persisted via :func:`openharness.auth.storage.store_credential`
      under the profile's resolved storage namespace
      (:func:`credential_storage_provider_name`).
    - ``base_url`` is persisted on the provider profile in ``settings.json``
      so it overrides the built-in default for that profile.

    The response masks ``api_key`` to its last 4 characters; the raw key is
    never echoed back.
    """
    settings = load_settings()
    profiles = settings.merged_profiles()
    if name not in profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider profile: {name}",
        )

    profile = profiles[name]

    api_key = (body.api_key or "").strip() if body.api_key is not None else None
    base_url_provided = body.base_url is not None
    base_url_value = (body.base_url or "").strip() if base_url_provided else None

    if api_key is None and not base_url_provided:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of 'api_key' or 'base_url' must be provided.",
        )

    # Store the API key against the same namespace used by the rest of the
    # auth subsystem (env-var fallback and CLI both read from this key).
    if api_key is not None:
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'api_key' must not be empty.",
            )
        if not auth_source_uses_api_key(profile.auth_source):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Profile {name!r} uses auth_source {profile.auth_source!r} "
                    "which is not API-key based."
                ),
            )
        storage_provider = credential_storage_provider_name(name, profile)
        try:
            store_credential(storage_provider, "api_key", api_key)
        except Exception as exc:  # pragma: no cover - storage failure
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist credential: {exc}",
            ) from exc

    # Persist base_url override on the profile itself. Empty string clears
    # the override (back to the built-in default on next ``merged_profiles``).
    if base_url_provided:
        new_base_url: str | None = base_url_value or None
        updated_profile = profile.model_copy(update={"base_url": new_base_url})
        merged = settings.merged_profiles()
        merged[name] = updated_profile
        updated_settings = settings.model_copy(update={"profiles": merged})
        try:
            save_settings(updated_settings)
        except Exception as exc:  # pragma: no cover - filesystem failure
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist settings: {exc}",
            ) from exc

        # If we just updated the *active* profile's base_url, reload defaults
        # for new sessions so they pick up the override.
        materialized = load_settings()
        if materialized.active_profile == name:
            active_profile = materialized.merged_profiles()[name]
            new_model = materialized.model or active_profile.default_model
            manager.update_provider_defaults(
                model=new_model,
                api_format=active_profile.api_format,
                base_url=active_profile.base_url,
            )
        final_base_url = updated_profile.base_url
    else:
        final_base_url = profile.base_url

    response: dict[str, object] = {"ok": True, "base_url": final_base_url}
    if api_key is not None:
        response["api_key"] = _mask_api_key(api_key)
    return response


# ---------------------------------------------------------------------------
# Provider verify
# ---------------------------------------------------------------------------

_VERIFY_TIMEOUT_S = 10.0


class VerifyResult(BaseModel):
    """Response schema for ``POST /api/providers/{name}/verify``."""

    ok: bool
    error: str | None = None
    models: list[str] | None = None


async def _fetch_models_via_openai_client(
    base_url: str,
    api_key: str,
) -> tuple[bool, str | None, list[str]]:
    """Call GET {base_url}/models using the OpenAI client.

    Returns (ok, error, models).
    """
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=_VERIFY_TIMEOUT_S)
        try:
            models_data = await client.models.with_options(timeout=_VERIFY_TIMEOUT_S).list()
        finally:
            await client.close()
        model_ids = sorted(m.id for m in models_data.data)
        return (True, None, model_ids)
    except Exception as exc:  # pragma: no cover — network errors in tests are covered elsewhere
        return (False, str(exc), [])


async def _fetch_models_via_httpx(
    base_url: str,
    api_key: str,
) -> tuple[bool, str | None, list[str]]:
    """Call GET {base_url}/models using httpx as a fallback.

    Used when the provider does not speak OpenAI client format.
    Returns (ok, error, models).
    """
    url = urljoin(base_url.rstrip("/") + "/", "models")
    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT_S) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if not response.is_success:
                return (False, f"HTTP {response.status_code}: {response.text[:200]}", [])
            data = response.json()
            # OpenAI-compatible: { "object": "list", "data": [{ "id": "...", ... }, ...] }
            model_ids = sorted(item["id"] for item in data.get("data", []) if isinstance(item, dict))
            return (True, None, model_ids)
    except Exception as exc:
        return (False, str(exc), [])


async def _completion_probe(
    base_url: str,
    api_key: str,
    model: str,
) -> str | None:
    """Send a minimal completion probe (~10 tokens) and return the error message on failure."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=_VERIFY_TIMEOUT_S)
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "x"}],
                max_tokens=10,
                stream=True,
            )
            # Drain the stream to trigger the actual request.
            async for _ in stream:
                pass
            return None
        finally:
            await client.close()
    except Exception as exc:
        return str(exc)


def _default_base_url_for_profile(profile: ProviderProfile) -> str | None:
    """Return the default base_url for a profile's api_format / provider."""
    # Anthropic (claude-api / claude-subscription) uses a non-standard API.
    # We fall back to the completion probe for those.
    if profile.api_format == "anthropic":
        return None
    if profile.api_format == "copilot":
        return None
    # All other api_format="openai" profiles use an OpenAI-compatible base_url.
    if profile.base_url:
        return profile.base_url
    if profile.provider == "openai":
        return "https://api.openai.com/v1"
    # Use the profile's provider name to look up built-in defaults.
    from openharness.api.registry import find_by_name

    spec = find_by_name(profile.provider)
    if spec is not None and spec.default_base_url:
        return spec.default_base_url
    return None


async def _resolve_api_key(profile: ProviderProfile) -> str | None:
    """Resolve the API key for a profile, checking env / file store."""
    import os

    storage_provider = credential_storage_provider_name("", profile)
    auth_source = profile.auth_source

    # Env variable fallbacks
    env_map = {
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
        "dashscope_api_key": "DASHSCOPE_API_KEY",
        "moonshot_api_key": "MOONSHOT_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "minimax_api_key": "MINIMAX_API_KEY",
    }
    env_var = env_map.get(auth_source)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    if os.environ.get("OPENAI_API_KEY") and profile.api_format == "openai":
        return os.environ["OPENAI_API_KEY"]
    if os.environ.get("ANTHROPIC_API_KEY") and profile.api_format == "anthropic":
        return os.environ["ANTHROPIC_API_KEY"]

    # File store
    key = load_credential(storage_provider, "api_key")
    if key:
        return key

    # Session-level key (in-memory settings, not persisted)
    try:
        settings = load_settings()
        if getattr(settings, "api_key", None):
            return settings.api_key
    except Exception:
        pass

    return None


@router.post("/{name}/verify", response_model=VerifyResult)
async def verify_provider(name: str) -> VerifyResult:
    """Test connectivity to a provider profile.

    Strategy:
    1. If the profile uses an OpenAI-compatible API format, try ``GET /v1/models``
       (free, returns model list) via the OpenAI client first, then httpx fallback.
    2. If /v1/models is unavailable (404/405) or returns no models, fall back to a
       minimal completion probe (~10 tokens).
    3. Profiles without a known base_url (anthropic-format, copilot-format) skip
       /v1/models and go straight to the completion probe.

    Response:
      - ``ok``: True if the provider was reachable.
      - ``error``: Human-readable error message when ``ok`` is False.
      - ``models``: List of model IDs when /v1/models succeeded; absent otherwise.

    Timeout: 10 seconds total.
    """
    settings = load_settings()
    profiles = settings.merged_profiles()
    if name not in profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider profile: {name}",
        )

    profile = profiles[name]
    base_url = _default_base_url_for_profile(profile)
    api_key = await _resolve_api_key(profile)

    if profile.api_format == "anthropic":
        # No base_url for Anthropic API — skip /v1/models, go straight to probe.
        error = await _completion_probe(
            "https://api.anthropic.com/v1",
            api_key or "",
            profile.resolved_model,
        )
        if error:
            return VerifyResult(ok=False, error=error)
        return VerifyResult(ok=True)

    if profile.api_format == "copilot":
        # Copilot uses OAuth — we can't meaningfully probe it without OAuth tokens.
        return VerifyResult(ok=False, error="Copilot uses OAuth; connection probing is not supported.")

    if not base_url:
        # No base_url means we can't reach the provider at all.
        return VerifyResult(ok=False, error="No base_url configured for this provider.")

    if not api_key:
        return VerifyResult(ok=False, error="No API key available.")

    # Priority: OpenAI client → httpx fallback → completion probe
    models_found: list[str] = []
    models_error: str | None = None

    # Try OpenAI client first
    ok, models_error, models_found = await _fetch_models_via_openai_client(base_url, api_key)

    # Fall back to httpx if the OpenAI client got a non-successful response
    if not ok and models_error and ("404" in models_error or "405" in models_error):
        ok, models_error, models_found = await _fetch_models_via_httpx(base_url, api_key)

    if ok and models_found:
        return VerifyResult(ok=True, models=models_found)

    # If models fetch failed or returned no models, try a completion probe.
    completion_error = await _completion_probe(base_url, api_key, profile.resolved_model)

    if completion_error:
        combined = "; ".join(filter(None, [models_error, completion_error]))
        return VerifyResult(ok=False, error=combined or "Connection failed.")
    return VerifyResult(ok=True)
