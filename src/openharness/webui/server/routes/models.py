"""GET /api/models — list available models grouped by provider profile.

Merges built-in models from each ``ProviderProfile`` (via
:func:`default_provider_profiles` / :meth:`Settings.merged_profiles`) with
the ``CLAUDE_MODEL_ALIAS_OPTIONS`` alias set for Anthropic-family providers,
and custom models from ``profile.allowed_models``. Each model entry carries
``id``, ``label``, ``context_window``, ``is_default``, and ``is_custom``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from openharness.config.settings import (
    CLAUDE_MODEL_ALIAS_OPTIONS,
    Settings,
    is_claude_family_provider,
    load_settings,
    save_settings,
)
from openharness.webui.server.state import require_token

router = APIRouter(
    prefix="/api/models",
    tags=["models"],
    dependencies=[Depends(require_token)],
)


class _CustomModelBody(BaseModel):
    """Request body for ``POST /api/models``."""

    provider: str
    model_id: str
    label: str | None = None
    context_window: int | None = None


def _build_models_for_profile(profile_name: str, profile) -> dict[str, dict]:
    """Return a dict mapping model id -> model entry for a single profile."""

    # Collect candidates; use a dict for deduplication.
    candidates: dict[str, tuple[str, str | None, bool, bool]] = {}  # id -> (label, context_window, is_default, is_custom)

    def _add(id: str, label: str, context_window: int | None, is_default: bool, is_custom: bool) -> None:
        # Custom always wins; default only if not already present.
        if id in candidates:
            _, _, prev_is_default, prev_is_custom = candidates[id]
            if is_custom and not prev_is_custom:
                candidates[id] = (label, context_window, prev_is_default, True)
            elif is_default and not prev_is_default:
                candidates[id] = (label, context_window, True, prev_is_custom)
        else:
            candidates[id] = (label, context_window, is_default, is_custom)

    default_model = (profile.last_model or "").strip() or profile.default_model
    profile_context_window = profile.context_window_tokens

    # 1. Built-in default model.
    _add(
        default_model,
        default_model,
        profile_context_window,
        is_default=True,
        is_custom=False,
    )

    # 2. CLAUDE_MODEL_ALIAS_OPTIONS for Anthropic-family providers.
    if is_claude_family_provider(profile.provider):
        for value, label, _description in CLAUDE_MODEL_ALIAS_OPTIONS:
            _add(
                value,
                label,
                profile_context_window,
                is_default=value == default_model,
                is_custom=False,
            )

    # 3. Custom models from allowed_models.
    for custom_id in profile.allowed_models:
        # Deduplicate: don't add if already registered as default or built-in.
        if custom_id not in candidates:
            _add(
                custom_id,
                custom_id,
                profile_context_window,
                is_default=custom_id == default_model,
                is_custom=True,
            )

    return {
        id: {
            "id": id,
            "label": label,
            "context_window": context_window,
            "is_default": is_default,
            "is_custom": is_custom,
        }
        for id, (label, context_window, is_default, is_custom) in candidates.items()
    }


@router.get("")
def list_models() -> dict[str, list[dict]]:
    """Return all available models grouped by provider profile id.

    Each group is a list of model objects with ``id``, ``label``,
    ``context_window``, ``is_default``, and ``is_custom``.
    """
    settings: Settings = load_settings()
    profiles = settings.merged_profiles()

    result: dict[str, list[dict]] = {}
    for profile_name, profile in profiles.items():
        entries = _build_models_for_profile(profile_name, profile)
        # Sort: default first, then alphabetically.
        sorted_entries = sorted(
            entries.values(),
            key=lambda m: (0 if m["is_default"] else 1, m["id"]),
        )
        result[profile_name] = sorted_entries

    return result


@router.get("/")
def list_models_slash() -> dict[str, list[dict]]:
    """Keep behavior stable for callers that include a trailing slash."""
    return list_models()


@router.post("", status_code=201)
def add_custom_model(body: _CustomModelBody) -> dict[str, object]:
    """Add a custom model to the given provider profile.

    The ``model_id`` is appended to ``ProviderProfile.allowed_models`` for the
    profile whose key matches ``provider``. The profile settings currently store
    only custom model ids, so ``label`` and ``context_window`` are accepted for
    request compatibility but are not persisted.

    Returns ``{"ok": True, "provider": ..., "model_id": ...}`` on success.
    """
    settings: Settings = load_settings()
    profiles = settings.merged_profiles()

    provider_key = body.provider.strip()
    if not provider_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider must not be empty",
        )

    if provider_key not in profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider profile: {provider_key!r}",
        )

    model_id = body.model_id.strip()
    if not model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model_id must not be empty",
        )

    profile = profiles[provider_key]
    if model_id in profile.allowed_models:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Model {model_id!r} already exists in provider {provider_key!r}",
        )

    updated_allowed = list(profile.allowed_models) + [model_id]
    updated_profiles = dict(settings.profiles)
    updated_profiles[provider_key] = profile.model_copy(
        update={"allowed_models": updated_allowed}
    )
    updated_settings = settings.model_copy(update={"profiles": updated_profiles})
    save_settings(updated_settings)

    return {"ok": True, "provider": provider_key, "model_id": model_id}


@router.delete("/{provider}/{model_id}", status_code=200)
def remove_custom_model(provider: str, model_id: str) -> dict[str, object]:
    """Remove a custom model from the given provider profile.

    Only models that appear in ``ProviderProfile.allowed_models`` (i.e.
    ``is_custom=True``) may be deleted.  Attempting to delete a built-in model
    (the profile's ``default_model`` or a Claude alias) returns **400**.

    Returns ``{"ok": True, "provider": ..., "model_id": ...}`` on success.
    """
    settings: Settings = load_settings()
    profiles = settings.merged_profiles()

    provider_key = provider.strip()
    if provider_key not in profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider profile: {provider_key!r}",
        )

    profile = profiles[provider_key]

    # Identify built-in model ids for this profile.
    builtin_ids: set[str] = {profile.default_model}
    if is_claude_family_provider(profile.provider):
        for value, _label, _desc in CLAUDE_MODEL_ALIAS_OPTIONS:
            builtin_ids.add(value)

    target = model_id.strip()

    if target in builtin_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete built-in model {target!r}",
        )

    if target not in profile.allowed_models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Custom model {target!r} not found in provider {provider_key!r}",
        )

    updated_allowed = [m for m in profile.allowed_models if m != target]
    updated_profiles = dict(settings.profiles)
    updated_profiles[provider_key] = profile.model_copy(
        update={"allowed_models": updated_allowed}
    )
    updated_settings = settings.model_copy(update={"profiles": updated_profiles})
    save_settings(updated_settings)

    return {"ok": True, "provider": provider_key, "model_id": target}
