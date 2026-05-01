"""Provider profile REST endpoints for the Web UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from openharness.auth.storage import load_credential
from openharness.config.settings import (
    ProviderProfile,
    auth_source_uses_api_key,
    credential_storage_provider_name,
    display_label_for_profile,
    display_model_setting,
)
from openharness.webui.server.state import require_token


router = APIRouter(
    prefix="/api/providers",
    tags=["providers"],
    dependencies=[Depends(require_token)],
)


def _has_credentials(name: str, profile: ProviderProfile) -> bool:
    """Return True when credentials are available for this profile.

    For API-key auth sources, check both the profile-specific credential slot
    (if any) and the provider-level storage namespace. Non-API-key auth sources
    (e.g. subscription-based) are treated as having credentials when the
    underlying provider has any stored credential at all.
    """
    storage = credential_storage_provider_name(name, profile)
    if load_credential(storage, "api_key"):
        return True
    # Subscription-based providers store oauth tokens under different keys; a
    # quick presence check via load_credential on common slot names.
    if not auth_source_uses_api_key(profile.auth_source):
        for key in ("access_token", "oauth_token", "session_token"):
            if load_credential(storage, key):
                return True
    return False


@router.get("")
def list_providers() -> dict[str, object]:
    """Return the merged provider profile catalog with auth and active flags.

    Each item contains: id, label, provider, api_format, default_model, base_url,
    has_credentials, is_active.
    """
    # Import here to avoid circular dependency at module load time.
    from openharness.config import load_settings

    settings = load_settings()
    profiles = settings.merged_profiles()
    active_profile = settings.active_profile

    items: list[dict[str, object]] = []
    for name, profile in profiles.items():
        items.append(
            {
                "id": name,
                "label": display_label_for_profile(name, profile),
                "provider": profile.provider,
                "api_format": profile.api_format,
                "default_model": display_model_setting(profile),
                "base_url": profile.base_url,
                "has_credentials": _has_credentials(name, profile),
                "is_active": name == active_profile,
            }
        )

    return {"providers": items}


@router.get("/")
def list_providers_slash() -> dict[str, object]:
    """Keep behavior stable for callers that include a trailing slash."""
    return list_providers()
