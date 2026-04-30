"""Fallback-aware API client wrapper.

Wraps a base ``SupportsStreamingMessages`` client and retries with alternate
models from a fallback chain when the primary model raises a terminal
``RequestFailure`` or ``RateLimitFailure`` (i.e. after the inner client's own
HTTP-level retries are exhausted).

``AuthenticationFailure`` is never retried — it propagates immediately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import AsyncIterator

from openharness.api.client import (
    ApiMessageRequest,
    ApiStreamEvent,
    SupportsStreamingMessages,
)
from openharness.api.errors import AuthenticationFailure, RateLimitFailure, RequestFailure

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSwitchEvent:
    """Emitted when the fallback wrapper switches to the next model in the chain."""

    failed_model: str
    next_model: str
    reason: str
    position: int
    chain_length: int


ApiStreamEventWithFallback = ApiStreamEvent | ModelSwitchEvent


class FallbackApiClient:
    """Wraps a base client and replays the request with alternate models on terminal failure.

    The inner client handles HTTP-level retries (429, 5xx, transient errors).
    This wrapper kicks in *only* when the inner client raises a terminal
    ``RequestFailure`` or ``RateLimitFailure`` — meaning all HTTP retries are
    exhausted.

    ``AuthenticationFailure`` always propagates immediately (wrong credentials
    won't be fixed by switching models).
    """

    def __init__(
        self,
        inner: SupportsStreamingMessages,
        model_chain: tuple[str, ...],
    ) -> None:
        self._inner = inner
        self._model_chain = model_chain

    @property
    def model_chain(self) -> tuple[str, ...]:
        return self._model_chain

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEventWithFallback]:
        """Stream with automatic model fallback on terminal failure."""
        if len(self._model_chain) <= 1:
            async for event in self._inner.stream_message(request):
                yield event
            return

        last_error: Exception | None = None
        for idx, model in enumerate(self._model_chain):
            patched = replace(request, model=model)
            try:
                async for event in self._inner.stream_message(patched):
                    yield event
                return
            except AuthenticationFailure:
                raise
            except (RequestFailure, RateLimitFailure) as exc:
                last_error = exc
                next_model = self._model_chain[idx + 1] if idx + 1 < len(self._model_chain) else None
                if next_model is None:
                    raise
                log.warning(
                    "Model %s failed terminally (%s), falling back to %s (%d/%d)",
                    model, exc, next_model, idx + 2, len(self._model_chain),
                )
                yield ModelSwitchEvent(
                    failed_model=model,
                    next_model=next_model,
                    reason=str(exc),
                    position=idx + 2,
                    chain_length=len(self._model_chain),
                )

        if last_error is not None:
            raise last_error
