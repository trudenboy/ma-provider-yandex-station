"""Yandex Station Player Provider for Music Assistant.

Play music on Yandex Station smart speakers via local Glagol WebSocket protocol.
Adapted from AlexxIT/YandexStation (MIT license).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from aiohttp import ClientSession, web
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from music_assistant_models.errors import LoginFailed

from .constants import (
    CONF_ACTION_CLEAR_AUTH,
    CONF_ACTION_LOGIN,
    CONF_ACTION_QR_START,
    CONF_MUSIC_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_X_TOKEN,
    PASSPORT_URL,
)
from .provider import YandexStationProvider
from .session import YandexSession

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES: set[ProviderFeature] = set()

# QR auth polling interval and timeout
_QR_POLL_INTERVAL = 3
_QR_POLL_TIMEOUT = 300


async def _fetch_qr_svg(track_id: str) -> str:
    """Fetch QR code SVG directly from Yandex passport."""
    url = f"{PASSPORT_URL}/auth/magic/code/?track_id={track_id}"
    try:
        async with ClientSession() as session, session.get(url) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception:
        _LOGGER.exception("Error fetching QR SVG")
    return ""


def _build_qr_page(qr_svg: str, status_path: str, callback_path: str) -> str:
    """Build HTML page with QR code and auto-polling JavaScript.

    Uses relative paths so it works regardless of Docker networking.
    The browser resolves paths from window.location.origin.
    """
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yandex Station — Scan QR Code</title>
<style>
  body {{ font-family: -apple-system, sans-serif; text-align: center;
         padding: 40px 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ font-size: 1.5em; margin-bottom: 0.3em; }}
  p {{ color: #aaa; margin-bottom: 24px; }}
  .qr-container {{ display: inline-block; background: white; padding: 24px;
                   border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }}
  .qr-container svg {{ width: 280px; height: 280px; }}
  #status {{ margin-top: 24px; font-size: 1em; color: #888; }}
  .success {{ color: #4ade80 !important; font-weight: 600; }}
  .spinner {{ display: inline-block; width: 18px; height: 18px;
              border: 2px solid #555; border-top-color: #3b82f6;
              border-radius: 50%; animation: spin 0.8s linear infinite;
              vertical-align: middle; margin-right: 8px; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head><body>
<h1>📱 Scan with Yandex App</h1>
<p>Open the <b>Yandex</b> app → tap the QR scanner → scan this code</p>
<div class="qr-container">{qr_svg}</div>
<p id="status"><span class="spinner"></span> Waiting for scan...</p>
<script>
(function() {{
  let tries = 0;
  const maxTries = {_QR_POLL_TIMEOUT // _QR_POLL_INTERVAL};
  const statusUrl = window.location.origin + "{status_path}";
  const callbackUrl = window.location.origin + "{callback_path}";
  async function poll() {{
    tries++;
    try {{
      const r = await fetch(statusUrl);
      const d = await r.json();
      if (d.status === "ok") {{
        document.getElementById("status").className = "success";
        document.getElementById("status").textContent =
          "✅ Authenticated! Redirecting...";
        setTimeout(() => window.location.href =
          callbackUrl + "?result=ok", 500);
        return;
      }}
    }} catch(e) {{}}
    if (tries < maxTries) setTimeout(poll, {_QR_POLL_INTERVAL * 1000});
    else document.getElementById("status").textContent =
      "⏰ Timeout. Close and try again.";
  }}
  setTimeout(poll, {_QR_POLL_INTERVAL * 1000});
}})();
</script>
</body></html>"""


async def _create_qr_session() -> tuple[str, str, str, str] | None:
    """Create QR session and return (svg, csrf_token, track_id, session_id) or None."""
    async with ClientSession() as http_session:
        session = YandexSession(http_session)
        qr_url, csrf_token, track_id = await session.get_qr()

    if not qr_url or not track_id or not csrf_token:
        return None

    svg = await _fetch_qr_svg(track_id)
    if not svg or "<svg" not in svg:
        return None

    session_id = f"yandex_qr_{track_id[:16]}"
    return svg, csrf_token, track_id, session_id


async def _poll_qr_until_scanned(csrf_token: str, track_id: str, result: list[str]) -> None:
    """Poll Yandex for QR scan status until scanned or cancelled."""
    for _ in range(_QR_POLL_TIMEOUT // _QR_POLL_INTERVAL):
        await asyncio.sleep(_QR_POLL_INTERVAL)
        try:
            async with ClientSession() as poll_session:
                s = YandexSession(poll_session)
                resp = await s.login_qr(csrf_token, track_id)
            if resp.ok and resp.x_token:
                result.append(resp.x_token)
                return
        except Exception:
            _LOGGER.debug("QR poll error, retrying...")


async def _handle_qr_login(
    mass: MusicAssistant,
    values: dict[str, ConfigValueType],
) -> str | None:
    """Handle QR code login using AuthenticationHelper for popup flow."""
    from music_assistant.helpers.auth import AuthenticationHelper  # noqa: PLC0415

    try:
        qr_session = await _create_qr_session()
        if qr_session is None:
            return "Failed to generate QR code. Try again."

        svg, csrf_token, track_id, session_id = qr_session

        # Use frontend's session_id for AUTH_SESSION event matching
        fe_session_id = str(values.get("session_id", session_id))

        async with AuthenticationHelper(mass, fe_session_id) as auth_helper:
            qr_path = f"/yandex_station/qr/{session_id}"
            status_path = f"/yandex_station/qr/{session_id}/status"
            # Use just the path for the popup URL — the frontend resolves
            # it from the browser's origin (avoids Docker internal IP issue)
            qr_page_url = qr_path
            # Callback path (for JS redirect in QR page)
            cb_path = auth_helper._cb_path
            x_token_result: list[str] = []

            async def serve_qr(request: web.Request) -> web.Response:
                _ = request
                html = _build_qr_page(svg, status_path, cb_path)
                return web.Response(text=html, content_type="text/html")

            async def serve_status(request: web.Request) -> web.Response:
                _ = request
                if x_token_result:
                    return web.json_response({"status": "ok"})
                return web.json_response({"status": "waiting"})

            unregister_qr = mass.webserver.register_dynamic_route(qr_path, serve_qr, "GET")
            unregister_status = mass.webserver.register_dynamic_route(
                status_path, serve_status, "GET"
            )

            try:
                poll_task = asyncio.create_task(
                    _poll_qr_until_scanned(csrf_token, track_id, x_token_result)
                )
                try:
                    await auth_helper.authenticate(qr_page_url, _QR_POLL_TIMEOUT)
                except LoginFailed:
                    pass  # Timeout is handled below
                finally:
                    poll_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await poll_task
            finally:
                unregister_qr()
                unregister_status()

        if x_token_result:
            values[CONF_X_TOKEN] = x_token_result[0]
            return None

        return "QR code was not scanned in time. Please try again."

    except Exception:
        _LOGGER.exception("Error during QR auth")
        return "Unexpected error during QR auth. Check server logs."


async def _handle_password_login(values: dict[str, ConfigValueType]) -> str | None:
    """Login with username/password."""
    username = values.get(CONF_USERNAME)
    password = values.get(CONF_PASSWORD)
    if not username or not password:
        return "Username and password are required."

    try:
        async with ClientSession() as http_session:
            session = YandexSession(http_session)

            resp = await session.login_username(str(username))
            if not resp.ok and resp.errors:
                error = resp.errors[0]
                if error == "account.not_found":
                    return "Account not found. Check your username."
                return f"Login error: {error}"

            resp = await session.login_password(str(password))
            if not resp.ok:
                errors = resp.errors
                if "password.not_matched" in errors:
                    return "Wrong password."
                if "captcha.required" in errors:
                    return "Captcha required. Use QR code login instead."
                if "redirect.unsupported" in errors:
                    return "2FA redirect detected. Use QR code login instead."
                if "push.timeout" in errors:
                    return "Push not approved in time. Try QR code login instead."
                if "push.denied" in errors:
                    return "Push denied. Please try again."
                return f"Login failed: {', '.join(errors)}"

            values[CONF_X_TOKEN] = resp.x_token
            values[CONF_USERNAME] = None
            values[CONF_PASSWORD] = None
    except Exception:
        _LOGGER.exception("Unexpected error during Yandex login")
        return "Unexpected error during login. Check server logs."
    return None


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """Return Config entries to setup this provider."""
    auth_error: str | None = None

    if values is not None and action is not None:
        if action == CONF_ACTION_QR_START:
            auth_error = await _handle_qr_login(mass, values)
        elif action == CONF_ACTION_LOGIN:
            auth_error = await _handle_password_login(values)
        elif action == CONF_ACTION_CLEAR_AUTH:
            values[CONF_X_TOKEN] = None
            values[CONF_MUSIC_TOKEN] = None

    x_token = (values or {}).get(CONF_X_TOKEN)
    is_authenticated = x_token not in (None, "")

    # Build status label
    if auth_error:
        label_text = f"⚠️ {auth_error}"
    elif not is_authenticated:
        label_text = (
            "Authenticate with your Yandex account. "
            "QR code login is recommended (works with 2FA). "
            "Password login works for accounts without 2FA."
        )
    elif action in (CONF_ACTION_LOGIN, CONF_ACTION_QR_START):
        label_text = "✅ Authenticated successfully! Click Save to complete setup."
    else:
        label_text = "✅ Authenticated to Yandex. No further action required."

    return (
        # ── Status label ──
        ConfigEntry(
            key="auth_label",
            type=ConfigEntryType.LABEL,
            label=label_text,
        ),
        # ── QR code login (primary method) ──
        ConfigEntry(
            key=CONF_ACTION_QR_START,
            type=ConfigEntryType.ACTION,
            label="Login with QR Code",
            description="Opens a popup with a QR code. Scan with Yandex app to login.",
            action=CONF_ACTION_QR_START,
            hidden=is_authenticated,
        ),
        # ── Password login (fallback) ──
        ConfigEntry(
            key=CONF_USERNAME,
            type=ConfigEntryType.STRING,
            label="Yandex Username",
            description="Your Yandex login (email or phone). For accounts without 2FA.",
            required=False,
            hidden=is_authenticated,
            value=values.get(CONF_USERNAME, "") if values else "",
        ),
        ConfigEntry(
            key=CONF_PASSWORD,
            type=ConfigEntryType.SECURE_STRING,
            label="Password",
            description="Used once to obtain token. Not stored.",
            required=False,
            hidden=is_authenticated,
            value=values.get(CONF_PASSWORD, "") if values else "",
        ),
        ConfigEntry(
            key=CONF_ACTION_LOGIN,
            type=ConfigEntryType.ACTION,
            label="Login with Password",
            description="Authenticate with username and password.",
            action=CONF_ACTION_LOGIN,
            hidden=is_authenticated,
        ),
        # ── Authenticated state ──
        ConfigEntry(
            key=CONF_ACTION_CLEAR_AUTH,
            type=ConfigEntryType.ACTION,
            label="Clear authentication",
            description="Remove stored credentials and log out.",
            action=CONF_ACTION_CLEAR_AUTH,
            action_label="Clear authentication",
            required=False,
            hidden=not is_authenticated,
        ),
        # ── Token storage (advanced, managed automatically) ──
        ConfigEntry(
            key=CONF_X_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex X-Token",
            description="Long-lived auth token (~1 year). Auto-obtained via login.",
            required=True,
            value=values.get(CONF_X_TOKEN, "") if values else "",
            category="advanced",
            advanced=True,
        ),
        ConfigEntry(
            key=CONF_MUSIC_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex Music Token",
            required=False,
            description="Auto-obtained from X-Token. No manual entry needed.",
            value=values.get(CONF_MUSIC_TOKEN, "") if values else "",
            category="advanced",
            advanced=True,
        ),
    )


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    x_token = config.get_value(CONF_X_TOKEN)
    if not x_token:
        msg = "Authentication required. Please login with your Yandex credentials."
        raise LoginFailed(msg)
    return YandexStationProvider(mass, manifest, config, SUPPORTED_FEATURES)
