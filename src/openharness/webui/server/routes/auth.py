"""Authentication endpoints: login, refresh, logout, change-password, status.

These endpoints operate on the ``~/.harness/webui/auth.json`` store managed by
:mod:`openharness.webui.server.auth_store`.  They are intentionally **not**
protected by the legacy token middleware — callers use the raw bearer token
returned by the login endpoint.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from openharness.webui.server.auth_store import (
    change_password as _change_password,
    clear_tokens,
    create_tokens,
    get_token_pair,
    is_access_token_valid,
    is_default_password,
    refresh_tokens,
    store_tokens,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCESS_TOKEN_TTL = 3600  # 1 hour
REFRESH_TOKEN_TTL = 604800  # 7 days


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Request body for password login."""

    model_config = ConfigDict(extra="forbid")

    password: str


class LoginResponse(BaseModel):
    """Access + refresh token pair returned on successful login."""

    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int
    is_default_password: bool


class RefreshRequest(BaseModel):
    """Request body for token refresh."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = ""


class RefreshResponse(BaseModel):
    """New access + refresh token pair."""

    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int


class ChangePasswordRequest(BaseModel):
    """Request body for changing the password."""

    model_config = ConfigDict(extra="forbid")

    old_password: str
    new_password: str = Field(min_length=1)


class StatusResponse(BaseModel):
    """Auth status for the SPA bootstrap flow."""

    authenticated: bool
    is_default_password: bool
    access_expires_in: int | None = None
    refresh_expires_in: int | None = None


class OkResponse(BaseModel):
    """Simple success response."""

    ok: bool


class ChangePasswordResponse(OkResponse):
    """Password-change success response."""

    is_default_password: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
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
    return LoginResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_in=ACCESS_TOKEN_TTL,
        refresh_expires_in=REFRESH_TOKEN_TTL,
        is_default_password=is_default_password(),
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(request: RefreshRequest) -> RefreshResponse:
    """Exchange a valid refresh token for a new access + refresh token pair.

    This endpoint performs token rotation: the provided refresh token is
    consumed and a fresh pair is returned and persisted.

    If the refresh token is missing, expired, or revoked, returns 401.
    """
    pair = refresh_tokens(
        request.refresh_token,
        expires_in=ACCESS_TOKEN_TTL,
        refresh_expires_in=REFRESH_TOKEN_TTL,
    )
    if pair is None:
        clear_tokens()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    return RefreshResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_in=ACCESS_TOKEN_TTL,
        refresh_expires_in=REFRESH_TOKEN_TTL,
    )


@router.post("/logout", response_model=OkResponse)
def logout() -> OkResponse:
    """Revoke the stored token pair (all sessions are terminated)."""
    clear_tokens()
    return OkResponse(ok=True)


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(request: ChangePasswordRequest) -> ChangePasswordResponse:
    """Change the account password.

    Requires the current password as ``old_password`` and the desired new
    password as ``new_password``.  All existing tokens are revoked and the
    caller must log in again with the new password.
    """
    ok = _change_password(request.old_password, request.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid current password",
        )

    clear_tokens()
    return ChangePasswordResponse(ok=True, is_default_password=is_default_password())


@router.get("/status", response_model=StatusResponse)
def auth_status() -> StatusResponse:
    """Return auth state for the SPA bootstrap.

    This endpoint is intentionally **unauthenticated** — it is used by the SPA
    to decide whether to show the login screen or attempt token reuse without
    sending any sensitive data.  It does not expose the password hash or tokens.
    """
    pair = get_token_pair()
    if pair is None:
        return StatusResponse(
            authenticated=False,
            is_default_password=is_default_password(),
        )

    now = int(time.time())
    access_expires_in = max(0, pair.access_expires_at - now)
    refresh_expires_in = max(0, pair.refresh_expires_at - now)
    access_valid = access_expires_in > 0
    refresh_valid = refresh_expires_in > 0

    return StatusResponse(
        authenticated=access_valid or refresh_valid,
        is_default_password=is_default_password(),
        access_expires_in=access_expires_in,
        refresh_expires_in=refresh_expires_in,
    )


@router.get("/validate", response_model=OkResponse)
def validate_token(
    authorization: str | None = Header(default=None),
) -> OkResponse:
    """Lightweight token validation for use by middleware.

    This endpoint verifies the ``Authorization: Bearer <token>`` header and
    returns 200 on success or 401 on failure.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    prefix = "Bearer "
    if not authorization.lower().startswith(prefix.lower()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )

    token = authorization[len(prefix):].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty token")

    if not is_access_token_valid(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return OkResponse(ok=True)
