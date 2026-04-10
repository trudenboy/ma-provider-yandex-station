"""Yandex Passport authentication flows.

Delegates all Passport interactions to the ``ya-passport-auth`` library.
This module exposes helpers consumed by the provider:

* ``perform_qr_auth``  — full QR login (UI popup → tokens)
* ``refresh_music_token`` — x_token → fresh music token
* ``validate_x_token``  — quick liveness check for an x_token
* ``login_with_cookies`` — browser cookies → tokens (custom, not in library)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import aiohttp
from music_assistant_models.errors import LoginFailed
from ya_passport_auth import PassportClient, SecretStr
from ya_passport_auth.exceptions import QRTimeoutError, YaPassportError

from music_assistant.helpers.auth import AuthenticationHelper

from .constants import PASSPORT_API_URL

if TYPE_CHECKING:
    from music_assistant import MusicAssistant

_LOGGER = logging.getLogger(__name__)

# Yandex Passport OAuth credentials (public, from Yandex Music Android app)
# Used only for cookie→x_token exchange (not handled by the library)
_PASSPORT_CLIENT_ID = "c0ebe342af7d48fbbbfcf2d2eedb8f9e"
_PASSPORT_CLIENT_SECRET = "ad0a908f0aa341a182a37ecd75bc319e"


async def perform_qr_auth(mass: MusicAssistant, session_id: str) -> tuple[str, str]:
    """Perform full QR authentication flow.

    Opens a QR code popup via MA frontend, polls for scan confirmation,
    then returns tokens as plain strings for MA config storage.

    Returns (x_token, music_token).
    """
    try:
        async with PassportClient.create() as client:
            qr = await client.start_qr_login()

            async with AuthenticationHelper(mass, session_id) as auth_helper:
                auth_helper.send_url(qr.qr_url)
                creds = await client.poll_qr_until_confirmed(qr)

            x_token = creds.x_token.get_secret()
            music_token = creds.music_token
            if music_token is None:
                raise LoginFailed("QR auth succeeded but no music token was returned")

            _LOGGER.debug("QR auth complete, obtained both tokens")
            return x_token, music_token.get_secret()

    except QRTimeoutError as err:
        raise LoginFailed("QR authentication timed out. Please try again.") from err
    except YaPassportError as err:
        raise LoginFailed(f"Yandex auth error: {err}") from err


async def refresh_music_token(x_token: SecretStr) -> SecretStr:
    """Exchange an x_token for a fresh music-scoped OAuth token."""
    try:
        async with PassportClient.create() as client:
            return await client.refresh_music_token(x_token)
    except YaPassportError as err:
        raise LoginFailed(f"Failed to refresh music token: {err}") from err


async def validate_x_token(x_token: SecretStr) -> bool:
    """Return True if *x_token* is still accepted by Yandex Passport."""
    try:
        async with PassportClient.create() as client:
            return bool(await client.validate_x_token(x_token))
    except YaPassportError:
        return False


async def login_with_cookies(cookies_input: str) -> tuple[str, str]:
    """Authenticate using browser cookies from passport.yandex.ru.

    The library does not support cookie→x_token exchange, so we keep
    the custom POST here and delegate only x_token→music_token.

    Supports two formats:
    - JSON from "Copy Cookies" Chrome extension: [{"name":"...", "value":"...", "domain":"..."}]
    - Raw cookie string: "key1=value1; key2=value2"

    Returns (x_token, music_token).
    """
    cookies_input = cookies_input.strip()
    if not cookies_input:
        raise LoginFailed("Empty cookies string")

    host = "passport.yandex.ru"
    cookies = cookies_input

    if cookies_input.startswith("["):
        try:
            raw = json.loads(cookies_input)
        except json.JSONDecodeError as err:
            raise LoginFailed("Invalid JSON in cookies") from err

        if not isinstance(raw, list):
            raise LoginFailed("Invalid JSON cookies format. Expected an array of cookie objects.")

        validated_cookies: list[str] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise LoginFailed(
                    f"Invalid JSON cookies format. Cookie at index {idx} must be an object."
                )
            domain = str(item.get("domain", "")).strip().lstrip(".")
            if domain.startswith("passport.yandex."):
                host = domain
            elif domain.startswith("yandex."):
                host = f"passport.{domain}"
            if "name" not in item or "value" not in item:
                raise LoginFailed(
                    f"Invalid JSON cookies format. Cookie at index {idx} must contain "
                    "'name' and 'value'."
                )
            validated_cookies.append(f"{item['name']}={item['value']}")
        cookies = "; ".join(validated_cookies)

    if "=" not in cookies:
        raise LoginFailed("Invalid cookie format. Expected 'key=value; ...' or JSON array.")

    # Cookie → x_token (custom; not in library)
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{PASSPORT_API_URL}/1/bundle/oauth/token_by_sessionid",
                data={
                    "client_id": _PASSPORT_CLIENT_ID,
                    "client_secret": _PASSPORT_CLIENT_SECRET,
                },
                headers={
                    "Ya-Client-Host": host,
                    "Ya-Client-Cookie": cookies,
                },
            ) as resp,
        ):
            if resp.status != 200:
                raise LoginFailed(f"Yandex returned HTTP {resp.status} for cookie→token exchange")
            if resp.content_type != "application/json":
                raise LoginFailed(
                    f"Unexpected response content type for cookie auth: {resp.content_type}"
                )
            try:
                data = await resp.json()
            except (json.JSONDecodeError, ValueError) as err:
                raise LoginFailed("Invalid JSON in cookie auth response") from err
    except LoginFailed:
        raise
    except aiohttp.ClientError as err:
        raise LoginFailed(f"Network error during cookie auth: {type(err).__name__}") from err

    if "access_token" not in data:
        raise LoginFailed("Failed to exchange cookies for x_token. Are the cookies valid?")

    x_token = str(data["access_token"])

    # x_token → music_token (delegated to library)
    music_token = await refresh_music_token(SecretStr(x_token))

    _LOGGER.debug("Cookie auth complete, obtained both tokens")
    return x_token, music_token.get_secret()
