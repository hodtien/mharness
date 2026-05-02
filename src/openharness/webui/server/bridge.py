"""Glue between FastAPI WebSocket transport and the BackendHost."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from openharness.ui.backend_host import BackendHostConfig, ReactBackendHost

if TYPE_CHECKING:
    from fastapi import WebSocket

log = logging.getLogger(__name__)


class WebSocketBackendHost(ReactBackendHost):
    """ReactBackendHost variant that talks to a single WebSocket peer.

    The same dispatch / runtime logic is reused; only the transport hooks
    (``_read_raw_request`` / ``_write_event``) are replaced.
    """

    def __init__(self, config: BackendHostConfig) -> None:
        super().__init__(config)
        self._inbound: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._websocket: WebSocket | None = None
        self._send_lock = asyncio.Lock()
        self._closed = False

    def attach_websocket(self, ws: "WebSocket") -> None:
        # A browser may reconnect to the same session after an abnormal close.
        # Reset the transport state so stale disconnect sentinels from the
        # previous socket do not immediately shut down the new run loop.
        self._websocket = ws
        self._closed = False
        while True:
            try:
                self._inbound.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def push_inbound(self, payload: bytes) -> None:
        """Called by the WS reader task with one raw line per request."""
        await self._inbound.put(payload)

    async def signal_disconnect(self) -> None:
        self._closed = True
        await self._inbound.put(None)

    # ---- BackendHost transport overrides -------------------------------------------------

    async def _read_raw_request(self) -> bytes | None:
        if self._closed:
            return None
        return await self._inbound.get()

    async def _write_event(self, payload_bytes: bytes) -> None:
        ws = self._websocket
        if ws is None or self._closed:
            return
        # Send the trimmed JSON (drop "OHJSON:" prefix and trailing newline).
        # Browsers don't need the framing — the WS message boundary already does that.
        text = payload_bytes.decode("utf-8")
        if text.startswith("OHJSON:"):
            text = text[len("OHJSON:"):]
        text = text.rstrip("\n")
        async with self._send_lock:
            try:
                await ws.send_text(text)
            except Exception as exc:  # pragma: no cover - connection drops
                log.debug("websocket send failed: %s", exc)
                self._closed = True
