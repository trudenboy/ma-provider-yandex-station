"""
Yandex Passport authentication flows.

Three user-facing login paths, all backed by ``ya-passport-auth``:

* **Device Flow** — :func:`perform_device_auth` serves a short user code on an
  MA-hosted intermediate page and polls Passport until confirmation. Yields
  the full ``(x_token, music_token, refresh_token)`` triple so the provider
  can silently refresh credentials when the music token (or x_token) expires.
* **QR flow** — :func:`perform_qr_auth` opens a QR popup via the MA frontend
  and polls Passport until the user scans/confirms. Yields
  ``(x_token, music_token)``.
* **Cookies fallback** — :func:`login_with_cookies` accepts a JSON array or
  raw cookie string exported from the browser. Yields
  ``(x_token, music_token)``.

Token maintenance helpers (:func:`refresh_music_token`,
:func:`refresh_credentials_via_passport`, :func:`validate_x_token`) live
alongside the login flows.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from typing import TYPE_CHECKING

from aiohttp import web
from music_assistant_models.errors import (
    InvalidDataError,
    LoginFailed,
    ProviderUnavailableError,
)
from ya_passport_auth import Credentials, PassportClient, SecretStr
from ya_passport_auth.exceptions import (
    DeviceCodeTimeoutError,
    NetworkError,
    QRTimeoutError,
    RateLimitedError,
    YaPassportError,
)

from music_assistant.helpers.auth import AuthenticationHelper

if TYPE_CHECKING:
    from music_assistant import MusicAssistant

_LOGGER = logging.getLogger(__name__)

_DEVICE_CODE_PAGE_PATH = "/yandex_station/device_code"
# Seconds to keep the status endpoint alive after the flow finishes so the
# intermediate page has a chance to poll once more and close itself.
_POST_AUTH_GRACE_SECONDS = 3
# session_id is embedded in a webserver route path — restrict it to a safe
# set so a crafted value can't register overlapping or escape-the-scope routes.
_SAFE_SESSION_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")


def _build_device_code_page(
    user_code: str,
    verification_url: str,
    status_url: str,
) -> str:
    """
    Render the HTML page shown to the user during Device Flow login.

    Yandex's verification page does not pre-fill the code from query params,
    and the MA frontend opens auth URLs in a new tab, so the user would
    otherwise have no signal that authorization succeeded. The page polls the
    status endpoint and closes itself (or shows a success message) when the
    backend signals completion.
    """
    safe_code = html.escape(user_code)
    safe_url = html.escape(verification_url, quote=True)
    # json.dumps emits a JS string literal, but `</script>` would still break
    # out of the surrounding <script> block. Escape the slash to be safe.
    safe_status_url = json.dumps(status_url).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Yandex Station — Device Code</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {{ color-scheme: light; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0; padding: 2rem 1rem;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; box-sizing: border-box;
            background: #f5f5f7; color: #1d1d1f;
        }}
        .card {{
            background: #ffffff; color: #1d1d1f;
            border-radius: 14px; padding: 2rem;
            max-width: 28rem; width: 100%;
            box-shadow: 0 4px 20px rgba(0,0,0,.08);
            text-align: center;
        }}
        h1 {{ margin: 0 0 .5rem; font-size: 1.25rem; color: #1d1d1f; }}
        p {{ margin: .5rem 0 1.25rem; color: #4a4a52; line-height: 1.45; }}
        #code {{
            display: inline-block;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 2rem; font-weight: 600; letter-spacing: .15em;
            padding: .75rem 1.25rem; border-radius: 10px;
            background: #f2f2f7; color: #1d1d1f;
            user-select: all;
        }}
        button, .btn {{
            display: inline-block; margin-top: 1.5rem; padding: .75rem 1.5rem;
            font-size: 1rem; font-weight: 600; text-decoration: none;
            border: none; border-radius: 10px; cursor: pointer;
            background: #ffcc00; color: #1d1d1f;
        }}
        button:hover, .btn:hover {{ background: #ffd633; }}
        #copy {{
            margin-top: .75rem; background: transparent; color: #1d1d1f;
            border: 1px solid #c8c8cd; padding: .4rem 1rem;
            font-size: .85rem; font-weight: 400;
        }}
        #copy:hover {{ background: #f2f2f7; }}
    </style>
</head>
<body>
    <div class="card" id="card">
        <h1>Login to Yandex Station</h1>
        <p>Open the link below and enter this code to authorize Music Assistant.</p>
        <div id="code">{safe_code}</div>
        <div>
            <button id="copy" type="button">Copy code</button>
        </div>
        <a class="btn" href="{safe_url}" target="_blank" rel="noopener">Continue to Yandex</a>
    </div>
    <script>
        const copyButton = document.getElementById('copy');
        const codeElement = document.getElementById('code');
        const card = document.getElementById('card');
        const statusUrl = {safe_status_url};

        function selectCodeForManualCopy() {{
            if (!codeElement) return;
            const selection = window.getSelection();
            if (!selection) return;
            const range = document.createRange();
            range.selectNodeContents(codeElement);
            selection.removeAllRanges();
            selection.addRange(range);
            if (copyButton) copyButton.textContent = 'Press Ctrl/Cmd+C';
        }}

        copyButton?.addEventListener('click', async function() {{
            const code = codeElement?.textContent?.trim();
            if (!code) return;
            if (!navigator.clipboard?.writeText) {{
                selectCodeForManualCopy();
                return;
            }}
            try {{
                await navigator.clipboard.writeText(code);
                this.textContent = 'Copied';
            }} catch {{
                selectCodeForManualCopy();
            }}
        }});

        function showResult(title, message) {{
            card.innerHTML =
                '<h1>' + title + '</h1><p>' + message + '</p>';
        }}

        async function pollStatus() {{
            try {{
                const r = await fetch(statusUrl, {{ cache: 'no-store' }});
                if (r.ok) {{
                    const data = await r.json();
                    if (data.state === 'done') {{
                        showResult(
                            'Authorization successful',
                            'You can close this window.'
                        );
                        setTimeout(() => {{ try {{ window.close(); }} catch (e) {{}} }}, 300);
                        return;
                    }}
                    if (data.state === 'failed') {{
                        showResult(
                            'Authorization failed',
                            'Please return to Music Assistant and try again.'
                        );
                        return;
                    }}
                }}
            }} catch (e) {{ /* network hiccup — retry */ }}
            setTimeout(pollStatus, 2000);
        }}
        setTimeout(pollStatus, 2000);
    </script>
</body>
</html>
"""


async def perform_device_auth(mass: MusicAssistant, session_id: str) -> tuple[str, str, str]:
    """
    Perform Yandex OAuth Device Flow and return credential tokens.

    Asks Yandex for a device code, presents it to the user via an intermediate
    HTML page served from MA's own webserver, then polls until the user
    confirms or the code expires.

    Returns (x_token, music_token, refresh_token) as plain strings for MA
    config storage.
    """
    if not _SAFE_SESSION_ID_RE.match(session_id):
        raise InvalidDataError("Invalid session_id for device authentication")
    try:
        async with PassportClient.create() as client:
            session = await client.start_device_login()

            _LOGGER.info(
                "Device flow started: open %s (expires in %ss)",
                session.verification_url,
                session.expires_in,
            )
            _LOGGER.debug("Device flow user_code issued")

            page_path = f"{_DEVICE_CODE_PAGE_PATH}/{session_id}"
            status_path = f"{page_path}/status"
            status_url = f"{mass.webserver.base_url}{status_path}"
            state = {"value": "pending"}

            page_html = _build_device_code_page(
                session.user_code, session.verification_url, status_url
            )

            async def _serve_page(_request: web.Request) -> web.Response:
                return web.Response(
                    text=page_html,
                    content_type="text/html",
                    charset="utf-8",
                    headers={
                        "Cache-Control": "no-store",
                        "Pragma": "no-cache",
                        "Expires": "0",
                    },
                )

            async def _serve_status(_request: web.Request) -> web.Response:
                return web.json_response(
                    {"state": state["value"]},
                    headers={"Cache-Control": "no-store"},
                )

            mass.webserver.register_dynamic_route(page_path, _serve_page, "GET")
            mass.webserver.register_dynamic_route(status_path, _serve_status, "GET")
            try:
                async with AuthenticationHelper(mass, session_id) as auth_helper:
                    auth_helper.send_url(f"{mass.webserver.base_url}{page_path}")
                    try:
                        creds = await client.poll_device_until_confirmed(session)
                    except asyncio.CancelledError:
                        # Don't mark cancellations as auth failures.
                        raise
                    except Exception:
                        state["value"] = "failed"
                        # Give the page one more poll to surface the failure
                        # message before we tear the status route down.
                        await asyncio.sleep(_POST_AUTH_GRACE_SECONDS)
                        raise
                    state["value"] = "done"
                    # Give the intermediate page one more poll to pick up "done"
                    # and close itself before we tear the status route down.
                    await asyncio.sleep(_POST_AUTH_GRACE_SECONDS)
            finally:
                mass.webserver.unregister_dynamic_route(page_path, "GET")
                mass.webserver.unregister_dynamic_route(status_path, "GET")

            music_token = creds.music_token
            if music_token is None:
                raise LoginFailed("Device auth succeeded but no music token was returned")
            refresh_token = creds.refresh_token
            if refresh_token is None:
                raise LoginFailed("Device auth succeeded but no refresh token was returned")

            _LOGGER.debug("Device flow complete, obtained full credential triple")
            return (
                creds.x_token.get_secret(),
                music_token.get_secret(),
                refresh_token.get_secret(),
            )

    except DeviceCodeTimeoutError as err:
        raise LoginFailed("Device authentication timed out. Please try again.") from err
    except YaPassportError as err:
        raise LoginFailed(f"Yandex device auth error: {err}") from err


async def perform_qr_auth(mass: MusicAssistant, session_id: str) -> tuple[str, str]:
    """
    Perform full QR authentication flow.

    Opens a QR code popup via MA frontend, polls for scan confirmation,
    then returns tokens as plain strings for MA config storage.

    Returns (x_token, music_token).
    """
    if not _SAFE_SESSION_ID_RE.match(session_id):
        raise InvalidDataError("Invalid session_id for QR authentication")
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
    """
    Exchange an x_token for a fresh music-scoped OAuth token.

    :param x_token: Long-lived Yandex Passport session token.
    :returns: A fresh music-scoped OAuth token.
    :raises ProviderUnavailableError: On transient failures (network,
        rate limit) — callers should retry later instead of clearing
        credentials.
    :raises LoginFailed: On real credential failures (x_token
        expired or rejected).
    """
    try:
        async with PassportClient.create() as client:
            return await client.refresh_music_token(x_token)
    except (NetworkError, RateLimitedError) as err:
        raise ProviderUnavailableError(f"Transient failure refreshing music token: {err}") from err
    except YaPassportError as err:
        raise LoginFailed(f"Failed to refresh music token: {err}") from err


async def refresh_credentials_via_passport(
    x_token: SecretStr, refresh_token: SecretStr
) -> Credentials:
    """
    Silently re-issue the full credential triple using a refresh token.

    Only available for accounts authenticated via the Device Flow (QR
    and cookies login do not yield a ``refresh_token``). Rotates both
    ``x_token`` and ``refresh_token`` server-side, so callers must
    persist the returned Credentials.

    :param x_token: Current long-lived Yandex Passport session token.
    :param refresh_token: Refresh token issued during Device Flow.
    :returns: New Credentials with rotated ``x_token`` and
        ``refresh_token``.
    :raises ProviderUnavailableError: On transient failures (network,
        rate limit) — callers should retry later instead of clearing
        credentials.
    :raises LoginFailed: On real credential failures (refresh_token
        rejected).
    """
    try:
        async with PassportClient.create() as client:
            return await client.refresh_credentials(
                Credentials(x_token=x_token, refresh_token=refresh_token)
            )
    except (NetworkError, RateLimitedError) as err:
        raise ProviderUnavailableError(f"Transient failure refreshing credentials: {err}") from err
    except YaPassportError as err:
        raise LoginFailed(f"Failed to refresh credentials: {err}") from err


async def validate_x_token(x_token: SecretStr) -> bool:
    """Return True if *x_token* is still accepted by Yandex Passport."""
    try:
        async with PassportClient.create() as client:
            return bool(await client.validate_x_token(x_token))
    except YaPassportError:
        return False


async def login_with_cookies(cookies_input: str) -> tuple[str, str]:
    """
    Authenticate using browser cookies from passport.yandex.ru.

    Supports two formats:
    - JSON from "Copy Cookies" Chrome extension: [{"name":"...", "value":"...", "domain":"..."}]
    - Raw cookie string: "key1=value1; key2=value2"

    Returns (x_token, music_token).
    """
    cookies_input = cookies_input.strip()
    if not cookies_input:
        raise InvalidDataError("Empty cookies string")

    cookies = cookies_input

    if cookies_input.startswith("["):
        try:
            raw = json.loads(cookies_input)
        except json.JSONDecodeError as err:
            raise InvalidDataError("Invalid JSON in cookies") from err

        if not isinstance(raw, list):
            raise InvalidDataError(
                "Invalid JSON cookies format. Expected an array of cookie objects."
            )

        validated_cookies: list[str] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise InvalidDataError(
                    f"Invalid JSON cookies format. Cookie at index {idx} must be an object."
                )
            if "name" not in item or "value" not in item:
                raise InvalidDataError(
                    f"Invalid JSON cookies format. Cookie at index {idx} must contain "
                    "'name' and 'value'."
                )
            validated_cookies.append(f"{item['name']}={item['value']}")
        cookies = "; ".join(validated_cookies)

    if "=" not in cookies:
        raise InvalidDataError("Invalid cookie format. Expected 'key=value; ...' or JSON array.")

    try:
        async with PassportClient.create() as client:
            creds = await client.login_cookies(cookies)
    except YaPassportError as err:
        raise LoginFailed(f"Cookie authentication failed: {err}") from err

    x_token = creds.x_token.get_secret()
    music_token = creds.music_token
    if music_token is None:
        raise LoginFailed("Cookie auth succeeded but no music token was returned")

    _LOGGER.debug("Cookie auth complete, obtained both tokens")
    return x_token, music_token.get_secret()
