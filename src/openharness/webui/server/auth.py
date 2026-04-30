"""Token-based authentication for the Web UI.

Single-user model: a random token is generated at start, must be supplied
either via ``Authorization: Bearer <token>`` header, ``?token=`` query
parameter, or ``oh_token`` cookie. The user lands on the page through a
URL like ``http://127.0.0.1:8765/?token=<token>`` printed at startup; the
SPA stores the token in localStorage afterwards.
"""

from __future__ import annotations

import secrets
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, WebSocket, status

from openharness.webui.server.config import WebUIConfig


def _extract_token(request: Request | WebSocket) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = request.query_params.get("token")
    if token:
        return token
    cookie = request.cookies.get("oh_token")
    if cookie:
        return cookie
    return None


def make_http_auth_dependency(config: WebUIConfig) -> Callable[[Request], Awaitable[None]]:
    async def _check(request: Request) -> None:
        token = _extract_token(request)
        if token is None or not secrets.compare_digest(token, config.token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing token",
            )

    return _check


def check_ws_token(ws: WebSocket, config: WebUIConfig) -> bool:
    token = _extract_token(ws)
    if token is None:
        return False
    return secrets.compare_digest(token, config.token)
