"""Token-based authentication for the Web UI.

Single-user model: a random token is generated at start, then stored by the
SPA for authenticated fetch, SSE, and WebSocket transports.
"""

from __future__ import annotations

import secrets
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, WebSocket, status

from openharness.webui.server.config import WebUIConfig


def _extract_header_or_cookie_token(request: Request | WebSocket) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    cookie = request.cookies.get("oh_token")
    if cookie:
        return cookie
    return None


def _extract_http_token(request: Request) -> str | None:
    token = _extract_header_or_cookie_token(request)
    if token:
        return token
    return request.query_params.get("token")


def make_http_auth_dependency(config: WebUIConfig) -> Callable[[Request], Awaitable[None]]:
    async def _check(request: Request) -> None:
        token = _extract_http_token(request)
        if token is None or not secrets.compare_digest(token, config.token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing token",
            )

    return _check


def check_ws_token(ws: WebSocket, config: WebUIConfig) -> bool:
    token = _extract_header_or_cookie_token(ws)
    if token is None:
        return False
    return secrets.compare_digest(token, config.token)
