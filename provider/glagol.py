"""Yandex Glagol — local WebSocket client for Yandex Station.

Adapted from AlexxIT/YandexStation (MIT license).
Stripped of Home Assistant dependencies; uses pure aiohttp + asyncio.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from aiohttp import ClientConnectorError, ClientWebSocketResponse, ServerTimeoutError

from .constants import (
    GLAGOL_TOKEN_URL,
    WS_COMMAND_TIMEOUT,
    WS_HEARTBEAT,
    WS_RECONNECT_BASE_DELAY,
    WS_RECONNECT_MAX_MULTIPLIER,
)

if TYPE_CHECKING:
    from .session import YandexSession

_LOGGER = logging.getLogger(__name__)


class YandexGlagol:
    """Local WebSocket client for Yandex Station via Glagol protocol."""

    device_token: str | None = None
    url: str | None = None
    ws: ClientWebSocketResponse | None = None

    update_handler: Callable[[dict[str, Any] | None], None] | None = None

    def __init__(self, session: YandexSession, device: dict[str, Any]) -> None:
        """Initialize Glagol client for a device."""
        self.session = session
        self.device = device
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._connect_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        """Return device display name."""
        return str(self.device.get("name", "Unknown"))

    @property
    def device_id(self) -> str:
        """Return Quasar device ID."""
        return str(self.device["quasar_info"]["device_id"])

    @property
    def platform(self) -> str:
        """Return device platform identifier."""
        return str(self.device["quasar_info"]["platform"])

    @property
    def connected(self) -> bool:
        """Return True if WebSocket is open."""
        return self.ws is not None and not self.ws.closed

    async def get_device_token(self) -> str:
        """Fetch a device token for WebSocket authentication."""
        _LOGGER.debug("[%s] Refreshing device token", self.name)
        payload = {
            "device_id": self.device_id,
            "platform": self.platform,
        }
        r = await self.session.get(GLAGOL_TOKEN_URL, params=payload)
        resp = json.loads(await r.text())
        if resp.get("status") != "ok":
            msg = f"Failed to get device token: {resp}"
            raise RuntimeError(msg)
        return resp["token"]  # type: ignore[no-any-return]

    async def start(self) -> None:
        """Start or restart the WebSocket connection."""
        host = self.device.get("host")
        port = self.device.get("port")
        if not host or not port:
            _LOGGER.warning("[%s] No host/port for device, cannot connect", self.name)
            return

        new_url = f"wss://{host}:{port}"

        if not self.url:
            # First connection
            self.url = new_url
            self._connect_task = asyncio.create_task(self._connect(0))
        elif host not in self.url:
            # IP changed
            _LOGGER.debug("[%s] IP address changed, reconnecting", self.name)
            self.url = new_url
            if self.ws:
                await self.ws.close()

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        _LOGGER.debug("[%s] Stopping local connection", self.name)
        self.url = None
        if self.ws:
            await self.ws.close()
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            self._connect_task = None

    async def _connect(self, fails: int) -> None:
        """Maintain persistent WebSocket connection with reconnect."""
        _LOGGER.debug("[%s] Connecting locally", self.name)
        fails += 1  # Will be reset on first message

        try:
            if not self.device_token:
                self.device_token = await self.get_device_token()

            self.ws = await self.session.ws_connect(
                self.url,  # type: ignore[arg-type]  # url checked in start()
                heartbeat=WS_HEARTBEAT,
                ssl=False,
            )
            await self._ping(command="softwareVersion")

            async for msg in self.ws:
                if isinstance(msg.data, ServerTimeoutError):
                    raise msg.data

                data = json.loads(msg.data)
                fails = 0  # Any message = reset fails

                # Handle response waiters
                request_id = data.get("requestId")
                if request_id in self._waiters:
                    result: dict[str, Any] = {"status": data.get("status", "unknown")}
                    self._waiters[request_id].set_result(result)

                # Dispatch state update
                if self.update_handler:
                    self.update_handler(data)

            # Connection closed normally — clear device token for next reconnect
            self.device_token = None

        except (ClientConnectorError, ConnectionResetError, ServerTimeoutError) as e:
            _LOGGER.debug("[%s] Connection error: %r", self.name, e)

        except (asyncio.CancelledError, RuntimeError) as e:
            if isinstance(e, RuntimeError) and e.args[0] != "Session is closed":
                raise
            _LOGGER.debug("[%s] Connection stopped: %r", self.name, e)
            if self.ws and not self.ws.closed:
                await self.ws.close()
            return

        except Exception:
            _LOGGER.exception("[%s] Unexpected error in local connection", self.name)

        # Notify handler that we're disconnected
        if self.update_handler:
            self.update_handler(None)

        # Stop reconnect attempts if stop() was called
        if not self.url:
            return

        if fails:
            delay = WS_RECONNECT_BASE_DELAY * min(fails - 1, WS_RECONNECT_MAX_MULTIPLIER)
            _LOGGER.debug("[%s] Reconnecting in %ds", self.name, delay)
            await asyncio.sleep(delay)

        self._connect_task = asyncio.create_task(self._connect(fails))

    async def _ping(self, command: str = "ping") -> None:
        """Send a ping/keepalive message."""
        if not self.ws or self.ws.closed:
            return
        with contextlib.suppress(Exception):
            await self.ws.send_json(
                {
                    "conversationToken": self.device_token,
                    "id": str(uuid.uuid4()),
                    "payload": {"command": command},
                    "sentTime": round(time.time() * 1000),
                }
            )

    async def send(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Send a command and wait for response."""
        if not self.ws or self.ws.closed:
            _LOGGER.warning("[%s] Cannot send: not connected", self.name)
            return {"error": "not_connected"}

        _LOGGER.debug("[%s] => local | %s", self.name, payload)

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()

        try:
            await self.ws.send_json(
                {
                    "conversationToken": self.device_token,
                    "id": request_id,
                    "payload": payload,
                    "sentTime": round(time.time() * 1000),
                }
            )

            future: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._waiters[request_id] = future
            await asyncio.wait_for(future, WS_COMMAND_TIMEOUT)
            return self._waiters.pop(request_id).result()

        except TimeoutError:
            self._waiters.pop(request_id, None)
            return {"error": "timeout"}

        except Exception as e:
            _LOGGER.error("[%s] Send error: %r", self.name, e)
            self._waiters.pop(request_id, None)
            return {"error": repr(e)}
