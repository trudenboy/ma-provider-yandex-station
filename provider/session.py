"""Yandex Session — authentication and HTTP client.

Adapted from AlexxIT/YandexStation (MIT license).
Stripped of Home Assistant dependencies; uses pure aiohttp.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import pickle
import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import ClientResponse, ClientSession

from .constants import (
    API_REQUEST_INTERVAL,
    MUSIC_CLIENT_ID,
    MUSIC_CLIENT_SECRET,
    MUSIC_TOKEN_URL,
    PASSPORT_API_URL,
    PASSPORT_CLIENT_ID,
    PASSPORT_CLIENT_SECRET,
    PASSPORT_URL,
)

_LOGGER = logging.getLogger(__name__)


class LoginResponse:
    """Wrapper for Yandex Passport login responses."""

    def __init__(self, resp: dict[str, Any]) -> None:
        """Wrap a raw Yandex Passport response dict."""
        self.raw = resp

    @property
    def ok(self) -> bool:
        """Return True if login succeeded."""
        return self.raw.get("status") == "ok"

    @property
    def errors(self) -> list[str]:
        """Return list of error codes."""
        return list(self.raw.get("errors", []))

    @property
    def error(self) -> str:
        """Return first error code."""
        return str(self.raw["errors"][0])

    @property
    def x_token(self) -> str:
        """Return the X-Token from response."""
        return str(self.raw["x_token"])

    @property
    def error_captcha_required(self) -> bool:
        """Return True if captcha is required."""
        return "captcha.required" in self.errors


class YandexSession:
    """Yandex authentication session and HTTP client.

    Manages x_token (long-lived ~1 year), music_token (for Glagol API),
    cookies, and CSRF tokens for Quasar API.
    """

    csrf_token: str | None = None
    last_ts: float = 0

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

        # Restore cookies from base64-encoded pickle
        if cookie:
            try:
                raw = base64.b64decode(cookie)
                self._session.cookie_jar._cookies = pickle.loads(raw)  # type: ignore[attr-defined]  # noqa: S301
                self._session.cookie_jar.clear(lambda _x: False)
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
            "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
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

    # ── QR code login flow (magic_x_token → x_token) ───────────

    async def get_qr(self) -> tuple[str | None, str | None, str | None]:
        """Start QR code auth session. Returns (qr_url, csrf_token, track_id) or (None, None, None)."""
        _LOGGER.debug("Starting QR code auth")

        # Step 1: Get CSRF token
        async with self._session.get(f"{PASSPORT_URL}/am?app_platform=android") as r:
            raw = await r.text()
            m = re.search(r'"csrf_token"\s*value="([^"]+)"', raw)
            if not m:
                _LOGGER.error("Failed to get CSRF token for QR auth")
                return None, None, None

        # Step 2: Request QR code track_id
        async with self._session.post(
            f"{PASSPORT_URL}/registration-validations/auth/password/submit",
            data={
                "csrf_token": m[1],
                "retpath": "https://passport.yandex.ru/profile",
                "with_code": 1,
            },
        ) as r:
            resp = await r.json()

        if resp.get("status") != "ok":
            _LOGGER.error("Failed to create QR session: %s", resp)
            return None, None, None

        csrf_token = resp["csrf_token"]
        track_id = resp["track_id"]
        qr_url = f"{PASSPORT_URL}/auth/magic/code/?track_id={track_id}"
        _LOGGER.info("QR auth URL: %s", qr_url)
        return qr_url, csrf_token, track_id

    async def login_qr(self, csrf_token: str, track_id: str) -> LoginResponse:
        """Check if QR code was scanned and approved. Exchange for x_token if so."""
        _LOGGER.debug("Checking QR auth status")
        self._auth_payload = {"csrf_token": csrf_token, "track_id": track_id}

        async with self._session.post(
            f"{PASSPORT_URL}/auth/new/magic/status/",
            data=self._auth_payload,
        ) as r:
            resp = await r.json()

        if resp.get("status") != "ok":
            return LoginResponse({"status": "error", "errors": ["qr.not_scanned"]})

        # QR approved — exchange cookies for x_token
        return await self.login_cookies()

    # ── Passport login flow (username/password → x_token) ────────

    async def login_username(self, username: str) -> LoginResponse:
        """Start multi-step auth: get CSRF token, submit username, return track_id."""
        _LOGGER.debug("Starting passport login for %s", username)

        # Step 1: Get CSRF token from passport page
        async with self._session.get(f"{PASSPORT_URL}/am?app_platform=android") as r:
            raw = await r.text()
            m = re.search(r'"csrf_token"\s*value="([^"]+)"', raw)
            if not m:
                return LoginResponse({"status": "error", "errors": ["csrf_token.not_found"]})
            self._auth_payload: dict[str, str] = {"csrf_token": m[1]}

        # Step 2: Submit username
        async with self._session.post(
            f"{PASSPORT_URL}/registration-validations/auth/multi_step/start",
            data={**self._auth_payload, "login": username},
        ) as r:
            resp = await r.json()

        if resp.get("can_register") is True:
            return LoginResponse({"status": "error", "errors": ["account.not_found"]})

        if not resp.get("can_authorize"):
            return LoginResponse({"status": "error", "errors": ["auth.not_available"]})

        self._auth_payload["track_id"] = resp["track_id"]
        return LoginResponse(resp)

    async def login_password(self, password: str) -> LoginResponse:
        """Submit password in multi-step auth flow, then obtain x_token."""
        if not hasattr(self, "_auth_payload") or "track_id" not in self._auth_payload:
            return LoginResponse({"status": "error", "errors": ["auth.no_track_id"]})

        _LOGGER.debug("Submitting password for passport login")

        async with self._session.post(
            f"{PASSPORT_URL}/registration-validations/auth/multi_step/commit_password",
            data={
                **self._auth_payload,
                "password": password,
                "retpath": f"{PASSPORT_URL}/am/finish?status=ok&from=Login",
            },
        ) as r:
            resp = await r.json()

        if resp.get("status") != "ok":
            return LoginResponse(resp)

        # If Yandex returns a redirect (2FA challenge), password login can't complete
        if "redirect_url" in resp:
            _LOGGER.info("Password login returned redirect (2FA). Use QR login instead.")
            return LoginResponse({"status": "error", "errors": ["redirect.unsupported"]})

        # No redirect — exchange session cookies for x_token
        return await self.login_cookies()

    async def login_cookies(self) -> LoginResponse:
        """Exchange current session cookies for x_token."""
        cookies = "; ".join(
            f"{c.key}={c.value}"
            for c in self._session.cookie_jar
            if c["domain"].endswith("yandex.ru")
        )

        async with self._session.post(
            f"{PASSPORT_API_URL}/1/bundle/oauth/token_by_sessionid",
            data={
                "client_id": PASSPORT_CLIENT_ID,
                "client_secret": PASSPORT_CLIENT_SECRET,
            },
            headers={
                "Ya-Client-Host": "passport.yandex.ru",
                "Ya-Client-Cookie": cookies,
            },
        ) as r:
            resp = await r.json()

        _LOGGER.debug("token_by_sessionid response keys=%s", list(resp.keys()))
        if "access_token" not in resp:
            _LOGGER.warning("token_by_sessionid failed: %s", resp)
            return LoginResponse({"status": "error", "errors": ["token.exchange_failed"]})

        x_token = resp["access_token"]
        self.x_token = x_token

        # Validate token and get user info
        return await self.validate_token(x_token)

    async def validate_token(self, x_token: str) -> LoginResponse:
        """Validate x_token and return user info."""
        async with self._session.get(
            f"{PASSPORT_API_URL}/1/bundle/account/short_info/",
            params={"avatar_size": "islands-300"},
            headers={"Authorization": f"OAuth {x_token}"},
        ) as r:
            resp = await r.json()

        resp["x_token"] = x_token
        return LoginResponse(resp)

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
        async with self._session.get(url, headers=headers, **kwargs) as r:
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
        """Serialize cookies to base64 for persistent storage."""
        raw = pickle.dumps(self._session.cookie_jar._cookies, pickle.HIGHEST_PROTOCOL)  # type: ignore[attr-defined]
        return base64.b64encode(raw).decode()
