"""Authentication endpoints: login, refresh, logout, change-password, status.

These endpoints operate on the ``~/.harness/webui/auth.json`` store managed by
:mod:`openharness.webui.server.auth_store`.  They are intentionally **not**
protected by the legacy token middleware — callers use the raw bearer token
returned by the login endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from openharness.webui.server.auth_store import (
    clear_tokens,
    create_tokens,
    get_token_pair,
    is_access_token_valid,
    is_default_password,
    is_refresh_token_valid,
    refresh_tokens,
    store_tokens,
    verify_password,
    change_password as _change_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCESS_TOKEN_TTL = 3600  # 1 hour
REFRESH_TOKEN_TTL = 604800  # 7 days


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest:
    """Request body for password login."""
    def __init__(self, password: str) -> None:
        self.password = password


class LoginResponse:
    """Access + refresh token pair returned on successful login."""
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        access_expires_in: int,
        refresh_expires_in: int,
        is_default_password: bool,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.access_expires_in = access_expires_in
        self.refresh_expires_in = refresh_expires_in
        self.is_default_password = is_default_password


class RefreshRequest:
    """Request body for token refresh."""
    def __init__(self, refresh_token: str) -> None:
        self.refresh_token = refresh_token


class RefreshResponse:
    """New access + refresh token pair."""
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        access_expires_in: int,
        refresh_expires_in: int,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.access_expires_in = access_expires_in
        self.refresh_expires_in = refresh_expires_in


class ChangePasswordRequest:
    """Request body for changing the password."""
    def __init__(self, old_password: str, new_password: str) -> None:
        self.old_password = old_password
        self.new_password = new_password


class StatusResponse:
    """Auth status for the SPA bootstrap flow."""
    def __init__(
        self,
        authenticated: bool,
        is_default_password: bool,
        access_expires_in: int | None = None,
        refresh_expires_in: int | None = None,
    ) -> None:
        self.authenticated = authenticated
        self.is_default_password = is_default_password
        self.access_expires_in = access_expires_in
        self.refresh_expires_in = refresh_expires_in


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=dict)
def login(request: LoginRequest) -> dict:
    """Authenticate with password and return access + refresh tokens.

    On success the caller should store the returned ``access_token`` and
    ``refresh_token`` (e.g. in localStorage) and use ``access_token`` as the
    ``Authorization: Bearer`` value for subsequent API calls.

    The response body is a flat dict::

        {
            "access_token": "...",
            "refresh_token": "...",
            "access_expires_in": 3600,
            "refresh_expires_in": 604800,
            "is_default_password": true,
        }
    """
    if not verify_password(request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    pair = create_tokens(expires_in=ACCESS_TOKEN_TTL, refresh_expires_in=REFRESH_TOKEN_TTL)
    store_tokens(pair)
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "access_expires_in": ACCESS_TOKEN_TTL,
        "refresh_expires_in": REFRESH_TOKEN_TTL,
        "is_default_password": is_default_password(),
    }


@router.post("/refresh", response_model=dict)
def refresh(request: RefreshRequest) -> dict:
    """Exchange a valid refresh token for a new access + refresh token pair.

    This endpoint performs token rotation: the provided refresh token is
    consumed and a fresh pair is returned and persisted.

    If the refresh token is missing, expired, or revoked, returns 401.
    """
    if not is_refresh_token_valid(request.refresh_token):
        clear_tokens()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    pair = refresh_tokens()
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "access_expires_in": ACCESS_TOKEN_TTL,
        "refresh_expires_in": REFRESH_TOKEN_TTL,
    }


@router.post("/logout")
def logout() -> dict:
    """Revoke the stored token pair (all sessions are terminated)."""
    clear_tokens()
    return {"ok": True}


@router.post("/change-password", response_model=dict)
def change_password(request: ChangePasswordRequest) -> dict:
    """Change the account password.

    Requires the current password as ``old_password`` and the desired new
    password as ``new_password``.  All existing tokens are revoked and the
    caller must log in again with the new password.
    """
    if len(request.new_password) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be empty",
        )

    ok = _change_password(request.old_password, request.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid current password",
        )

    clear_tokens()
    return {
        "ok": True,
        "is_default_password": is_default_password(),
    }


@router.get("/status", response_model=dict)
def auth_status() -> dict:
    """Return auth state for the SPA bootstrap.

    This endpoint is intentionally **unauthenticated** — it is used by the SPA
    to decide whether to show the login screen or attempt token reuse without
    sending any sensitive data.  It does not expose the password hash or tokens.
    """
    pair = get_token_pair()
    if pair is None:
        return {
            "authenticated": False,
            "is_default_password": is_default_password(),
            "access_expires_in": None,
            "refresh_expires_in": None,
        }

    import time
    now = int(time.time())
    access_valid = pair.access_token and now < pair.access_expires_at
    refresh_valid = pair.refresh_token and now < pair.refresh_expires_at

    return {
        "authenticated": access_valid,
        "is_default_password": is_default_password(),
        "access_expires_in": max(0, pair.access_expires_at - now),
        "refresh_expires_in": max(0, pair.refresh_expires_at - now),
    }


@router.get("/validate")
def validate_token(
    authorization: str | None = None,
) -> dict:
    """Lightweight token validation for use by middleware.

    This endpoint verifies the ``Authorization: Bearer <token>`` header and
    returns 200 on success or 401 on failure.
    """
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header format")

    token = authorization[len(prefix):].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty token")

    if not is_access_token_valid(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    return {"ok": True}