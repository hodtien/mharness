"""GET /api/models — list available models grouped by provider profile.

Merges built-in models from each ``ProviderProfile`` (via
:func:`default_provider_profiles` / :meth:`Settings.merged_profiles`) with
the ``CLAUDE_MODEL_ALIAS_OPTIONS`` alias set for Anthropic-family providers,
and custom models from ``profile.allowed_models``. Each model entry carries
``id``, ``label``, ``context_window``, ``is_default``, and ``is_custom``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from openharness.config.settings import (
    CLAUDE_MODEL_ALIAS_OPTIONS,
    Settings,
    is_claude_family_provider,
    load_settings,
)
from openharness.webui.server.state import require_token

router = APIRouter(
    prefix="/api/models",
    tags=["models"],
    dependencies=[Depends(require_token)],
)


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
