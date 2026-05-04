"""Per-user persistent WebSocket client for Paperclip's live-events endpoint.

One instance owns one WS to ``/api/companies/{companyId}/events/ws``
authenticated with a Better-Auth session cookie. Reconnects with capped
exponential backoff. Emits each parsed event to a caller-supplied async
callback, plus a synthetic ``{type: "stream.resumed"}`` event after
every successful reconnect so the broker can flush downstream caches
(Paperclip has no replay cursor — see spec § Reconnect semantics).

Lifecycle: explicit ``start()`` opens the loop; ``close()`` stops it.
Owner (the broker) is responsible for calling ``close()`` when the
last subscriber leaves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Awaitable, Callable

import websockets
from websockets.exceptions import WebSocketException

logger = logging.getLogger(__name__)


# Backoff schedule: 1s, 2s, 4s, 8s, 16s, 30s (cap), with ±20% jitter.
# Matches the OpenClaw gateway client to keep operator mental model uniform.
_MAX_BACKOFF_SECONDS = 30.0
_MAX_RECONNECT_ATTEMPTS = 30  # ≈ 15 minutes of trying before giving up


class PaperclipEventClient:
    """Single backing connection from the backend to Paperclip's WS.

    Args:
        url: full ``ws://`` or ``wss://`` URL for the events endpoint.
        cookie: value of the ``Cookie:`` header (Better-Auth session).
        on_event: async callback invoked once per parsed event.
        reconnect_initial_delay: first-attempt backoff base (seconds).
            Tests override this to keep the suite fast.
    """

    def __init__(
        self,
        *,
        url: str,
        cookie: str,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        reconnect_initial_delay: float = 1.0,
    ) -> None:
        self._url = url
        self._cookie = cookie
        self._on_event = on_event
        self._initial_delay = reconnect_initial_delay
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Begin the connect-loop in the background."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        """Signal the connect-loop to stop and await its termination."""
        self._stop.set()
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run(self) -> None:
        """Connect/reconnect loop. Runs until ``close()`` or max attempts."""
        attempt = 0
        is_reconnect = False
        while not self._stop.is_set() and attempt < _MAX_RECONNECT_ATTEMPTS:
            try:
                async with websockets.connect(
                    self._url,
                    additional_headers={"Cookie": self._cookie},
                    open_timeout=10.0,
                    close_timeout=5.0,
                ) as ws:
                    self._connected = True
                    attempt = 0  # successful connect resets backoff
                    logger.info("paperclip event WS connected url=%s reconnect=%s", self._url, is_reconnect)
                    if is_reconnect:
                        # Synthetic event so the broker can flush downstream
                        # SWR caches (no upstream replay cursor exists).
                        try:
                            await self._on_event({"type": "stream.resumed"})
                        except Exception:
                            logger.exception("on_event raised on stream.resumed")
                    is_reconnect = True
                    await self._receive_loop(ws)
            except (WebSocketException, OSError) as e:
                logger.warning("paperclip event WS connect/recv error: %s", e)
            finally:
                self._connected = False

            if self._stop.is_set():
                return
            attempt += 1
            delay = self._backoff(attempt)
            logger.info("paperclip event WS reconnecting in %.1fs (attempt %d)", delay, attempt)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                return  # stop fired during sleep
            except asyncio.TimeoutError:
                continue
        if attempt >= _MAX_RECONNECT_ATTEMPTS:
            logger.error("paperclip event WS giving up after %d attempts url=%s", attempt, self._url)

    async def _receive_loop(self, ws) -> None:
        """Read frames until the connection drops."""
        async for raw in ws:
            if self._stop.is_set():
                return
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("paperclip event WS dropped malformed frame")
                continue
            try:
                await self._on_event(event)
            except Exception:
                logger.exception("on_event raised; continuing")

    def _backoff(self, attempt: int) -> float:
        """Capped exponential backoff with ±20% jitter."""
        base = min(self._initial_delay * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)
        jitter = base * 0.2 * (2 * random.random() - 1)
        return max(0.1, base + jitter)
