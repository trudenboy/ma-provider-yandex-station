"""Yandex Session — HTTP client with cookie/CSRF management.

Adapted from AlexxIT/YandexStation (MIT license).
Authentication flows moved to yandex_auth.py; this module handles
only HTTP requests with automatic cookie refresh and CSRF token management.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

import yarl

if TYPE_CHECKING:
    from aiohttp import ClientResponse, ClientSession

from .constants import (
    API_REQUEST_INTERVAL,
    MUSIC_CLIENT_ID,
    MUSIC_CLIENT_SECRET,
    MUSIC_TOKEN_URL,
    PASSPORT_API_URL,
)

_LOGGER = logging.getLogger(__name__)


class YandexSession:
    """Yandex HTTP client with cookie/CSRF management.

    Manages x_token (long-lived ~1 year), music_token (for Glagol API),
    cookies, and CSRF tokens for Quasar API.
    """

    def __init__(
        self,
        session: ClientSession,
        x_token: str | None = None,
        music_token: str | None = None,
        cookie: str | None = None,
    ) -> None:
        """Initialize with aiohttp session and optional credentials."""
        self._session = session
        self.x_token = x_token
        self.music_token = music_token
        self.csrf_token: str | None = None
        self.last_ts: float = 0

        # Restore cookies from JSON-serialized list
        if cookie:
            try:
                raw = base64.b64decode(cookie).decode()
                cookie_list: list[dict[str, str]] = json.loads(raw)
                for c in cookie_list:
                    self._session.cookie_jar.update_cookies(
                        {c["name"]: c["value"]},
                        response_url=yarl.URL(c.get("domain", "https://yandex.ru")),
                    )
            except Exception:
                _LOGGER.warning("Failed to restore cookies from saved state")

    # ── Token management ─────────────────────────────────────────

    async def get_music_token(self, x_token: str) -> str:
        """Get music token using x-token (for Glagol API auth)."""
        _LOGGER.debug("Requesting music token")
        payload = {
            "client_secret": MUSIC_CLIENT_SECRET,
            "client_id": MUSIC_CLIENT_ID,
            "grant_type": "x-token",
            "access_token": x_token,
        }
        async with self._session.post(MUSIC_TOKEN_URL, data=payload) as r:
            resp = await r.json()
            if "access_token" not in resp:
                msg = f"Failed to get music token: {resp}"
                raise RuntimeError(msg)
            return resp["access_token"]  # type: ignore[no-any-return]

    async def login_token(self, x_token: str) -> bool:
        """Login to Yandex with x-token to obtain session cookies."""
        _LOGGER.debug("Login with x-token")
        payload = {"type": "x-token", "retpath": "https://www.yandex.ru"}
        headers = {"Ya-Consumer-Authorization": f"OAuth {x_token}"}
        async with self._session.post(
            f"{PASSPORT_API_URL}/1/bundle/auth/x_token/",
            data=payload,
            headers=headers,
        ) as r:
            resp = await r.json()
            if resp.get("status") != "ok":
                _LOGGER.error("Login with token failed: %s", resp)
                return False
            host = resp["passport_host"]
            track_id = resp["track_id"]

        async with self._session.get(
            f"{host}/auth/session/",
            params={"track_id": track_id},
            allow_redirects=False,
        ) as r:
            return r.status == 302

    async def refresh_cookies(self) -> bool:
        """Check cookies and refresh if needed."""
        async with self._session.get("https://yandex.ru/quasar?storage=1") as r:
            resp = await r.json()
            if resp.get("storage", {}).get("user", {}).get("uid"):
                return True

        if not self.x_token:
            return False
        return await self.login_token(self.x_token)

    async def ensure_music_token(self) -> None:
        """Ensure music_token is available, fetching it if needed."""
        if not self.music_token and self.x_token:
            self.music_token = await self.get_music_token(self.x_token)

    # ── HTTP methods ─────────────────────────────────────────────

    async def get(self, url: str, **kwargs: Any) -> ClientResponse:
        """GET request with automatic auth for Glagol/Music API."""
        if url.startswith(("https://quasar.yandex.net/glagol/", "https://api.music.yandex.net/")):
            return await self._request_glagol(url, **kwargs)
        return await self._request("get", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> ClientResponse:
        """POST request with CSRF token management."""
        return await self._request("post", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> ClientResponse:
        """PUT request with CSRF token management."""
        return await self._request("put", url, **kwargs)

    async def ws_connect(self, url: str, **kwargs: Any) -> Any:
        """Create a WebSocket connection."""
        return await self._session.ws_connect(url, **kwargs)

    async def _request(
        self, method: str, url: str, retry: int = 2, **kwargs: Any
    ) -> ClientResponse:
        """Request with CSRF token and retry logic."""
        # DDoS protection
        while (delay := self.last_ts + API_REQUEST_INTERVAL - time.time()) > 0:
            await asyncio.sleep(delay)
        self.last_ts = time.time()

        # Non-GET requests need CSRF token for Quasar API
        if method != "get" and not url.startswith("https://rpc.alice.yandex.ru"):
            if self.csrf_token is None:
                _LOGGER.debug("Refreshing CSRF token")
                async with self._session.get("https://yandex.ru/quasar") as csrf_resp:
                    raw = await csrf_resp.text()
                    m = re.search('"csrfToken2":"(.+?)"', raw)
                    if not m:
                        msg = "Failed to obtain CSRF token"
                        raise RuntimeError(msg)
                    self.csrf_token = m[1]
            kwargs.setdefault("headers", {})["x-csrf-token"] = self.csrf_token

        r: ClientResponse = await getattr(self._session, method)(url, **kwargs)
        if r.status == 200:
            return r
        if r.status == 400:
            retry = 0
        elif r.status == 401:
            await self.refresh_cookies()
        elif r.status == 403:
            self.csrf_token = None

        if retry:
            _LOGGER.debug("Retry %s %s", method, url)
            return await self._request(method, url, retry - 1, **kwargs)

        msg = f"{url} returned {r.status}"
        raise RuntimeError(msg)

    async def _request_glagol(self, url: str, retry: int = 2, **kwargs: Any) -> ClientResponse:
        """Request to Glagol/Music API with music_token auth."""
        await self.ensure_music_token()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"OAuth {self.music_token}"
        r: ClientResponse = await self._session.get(url, headers=headers, **kwargs)
        if r.status == 200:
            return r
        if r.status == 403:
            self.music_token = None

        if retry:
            _LOGGER.debug("Retry Glagol request %s", url)
            return await self._request_glagol(url, retry - 1, **kwargs)

        msg = f"{url} returned error"
        raise RuntimeError(msg)

    # ── Serialization ────────────────────────────────────────────

    @property
    def cookie(self) -> str:
        """Serialize cookies to base64 JSON for persistent storage."""
        cookies: list[dict[str, str]] = []
        for cookie in self._session.cookie_jar:
            cookies.append(
                {
                    "name": cookie.key,
                    "value": cookie.value,
                    "domain": f"https://{cookie['domain']}" if cookie.get("domain") else "",
                }
            )
        raw = json.dumps(cookies).encode()
        return base64.b64encode(raw).decode()
