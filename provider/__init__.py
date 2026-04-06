"""Yandex Station Player Provider for Music Assistant.

Play music on Yandex Station smart speakers via local Glagol WebSocket protocol.
Adapted from AlexxIT/YandexStation (MIT license).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import ClientSession
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from music_assistant_models.errors import LoginFailed

from .constants import (
    CONF_ACTION_CLEAR_AUTH,
    CONF_ACTION_LOGIN,
    CONF_ACTION_QR_CHECK,
    CONF_ACTION_QR_START,
    CONF_MUSIC_TOKEN,
    CONF_PASSWORD,
    CONF_QR_CSRF,
    CONF_QR_TRACK_ID,
    CONF_USERNAME,
    CONF_X_TOKEN,
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


async def _handle_auth_action(
    action: str | None,
    values: dict[str, ConfigValueType] | None,
) -> str | None:
    """Handle login/logout actions. Returns error message or None on success."""
    if values is None or action is None:
        return None

    if action == CONF_ACTION_QR_START:
        return await _handle_qr_start(values)

    if action == CONF_ACTION_QR_CHECK:
        return await _handle_qr_check(values)

    if action == CONF_ACTION_LOGIN:
        return await _handle_password_login(values)

    if action == CONF_ACTION_CLEAR_AUTH:
        values[CONF_X_TOKEN] = None
        values[CONF_MUSIC_TOKEN] = None
        values[CONF_QR_CSRF] = None
        values[CONF_QR_TRACK_ID] = None

    return None


async def _handle_qr_start(values: dict[str, ConfigValueType]) -> str | None:
    """Start QR code auth — get QR URL from Yandex."""
    try:
        async with ClientSession() as http_session:
            session = YandexSession(http_session)
            qr_url, csrf_token, track_id = await session.get_qr()

        if not qr_url:
            return "Failed to generate QR code. Try again."

        # Store QR session state for the check step
        values[CONF_QR_CSRF] = csrf_token
        values[CONF_QR_TRACK_ID] = track_id
    except Exception:
        _LOGGER.exception("Error starting QR auth")
        return "Unexpected error generating QR code. Check server logs."
    return None


async def _handle_qr_check(values: dict[str, ConfigValueType]) -> str | None:
    """Check if QR code was scanned and exchange for x_token."""
    csrf = values.get(CONF_QR_CSRF)
    track_id = values.get(CONF_QR_TRACK_ID)
    if not csrf or not track_id:
        return "No active QR session. Click 'Get QR Code' first."

    try:
        async with ClientSession() as http_session:
            session = YandexSession(http_session)
            resp = await session.login_qr(str(csrf), str(track_id))

        if not resp.ok:
            errors = resp.errors
            if "qr.not_scanned" in errors:
                return "QR code not scanned yet. Open the link, scan with Yandex app, then try again."
            return f"QR auth failed: {', '.join(errors)}"

        # Success
        values[CONF_X_TOKEN] = resp.x_token
        values[CONF_QR_CSRF] = None
        values[CONF_QR_TRACK_ID] = None
    except Exception:
        _LOGGER.exception("Error checking QR auth status")
        return "Unexpected error during QR auth. Check server logs."
    return None


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
    mass: MusicAssistant,  # noqa: ARG001
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """Return Config entries to setup this provider."""
    auth_error = await _handle_auth_action(action, values)

    x_token = (values or {}).get(CONF_X_TOKEN)
    is_authenticated = x_token not in (None, "")

    # QR session state
    qr_track_id = (values or {}).get(CONF_QR_TRACK_ID)
    has_qr_session = qr_track_id not in (None, "")
    qr_url = ""
    if has_qr_session:
        qr_url = f"https://passport.yandex.ru/auth/magic/code/?track_id={qr_track_id}"

    # Build status label
    if auth_error:
        label_text = f"⚠️ {auth_error}"
    elif not is_authenticated and has_qr_session:
        label_text = (
            f"📱 Open this link and scan the QR code with your Yandex app: {qr_url} "
            "Then click 'Check QR Status' below."
        )
    elif not is_authenticated:
        label_text = (
            "Authenticate with your Yandex account. "
            "QR code login is recommended (works with 2FA). "
            "Password login works for accounts without 2FA."
        )
    elif action in (CONF_ACTION_LOGIN, CONF_ACTION_QR_CHECK):
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
        # ── QR code login (primary method, shown when not authenticated) ──
        ConfigEntry(
            key=CONF_ACTION_QR_START,
            type=ConfigEntryType.ACTION,
            label="Get QR Code",
            description="Generate a QR code link for login via Yandex app.",
            action=CONF_ACTION_QR_START,
            hidden=is_authenticated or has_qr_session,
        ),
        ConfigEntry(
            key=CONF_ACTION_QR_CHECK,
            type=ConfigEntryType.ACTION,
            label="Check QR Status",
            description="Check if QR code was scanned and approved.",
            action=CONF_ACTION_QR_CHECK,
            hidden=is_authenticated or not has_qr_session,
        ),
        # ── Password login (fallback, shown when not authenticated) ──
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
        # ── Hidden QR state fields ──
        ConfigEntry(
            key=CONF_QR_CSRF,
            type=ConfigEntryType.STRING,
            label="QR CSRF",
            required=False,
            hidden=True,
            value=values.get(CONF_QR_CSRF, "") if values else "",
        ),
        ConfigEntry(
            key=CONF_QR_TRACK_ID,
            type=ConfigEntryType.STRING,
            label="QR Track ID",
            required=False,
            hidden=True,
            value=values.get(CONF_QR_TRACK_ID, "") if values else "",
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
