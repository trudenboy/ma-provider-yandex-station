"""Yandex Station Player Provider for Music Assistant.

Play music on Yandex Station smart speakers via local Glagol WebSocket protocol.
Adapted from AlexxIT/YandexStation (MIT license).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from music_assistant_models.errors import InvalidDataError, LoginFailed

from .auth import login_with_cookies, perform_device_auth, perform_qr_auth
from .constants import (
    CONF_ACTION_AUTH_COOKIES,
    CONF_ACTION_AUTH_DEVICE,
    CONF_ACTION_AUTH_QR,
    CONF_ACTION_CLEAR_AUTH,
    CONF_COOKIES,
    CONF_INTERCEPT_FEATURE_ENABLED,
    CONF_MUSIC_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_REMEMBER_SESSION,
    CONF_X_TOKEN,
)
from .provider import YandexStationProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """Return Config entries to setup this provider."""
    if values is None:
        values = {}

    # Handle Device Flow auth action (yields x_token + refresh_token,
    # so we get silent auto-refresh on music-token AND x_token expiry)
    if action == CONF_ACTION_AUTH_DEVICE:
        session_id = values.get("session_id")
        if not session_id:
            raise InvalidDataError("Missing session_id for device authentication")
        x_token, music_token, refresh_token = await perform_device_auth(mass, str(session_id))
        values[CONF_MUSIC_TOKEN] = music_token
        values[CONF_X_TOKEN] = x_token
        values[CONF_REFRESH_TOKEN] = refresh_token

    # Handle QR auth action (yields x_token + music_token, no refresh_token)
    if action == CONF_ACTION_AUTH_QR:
        session_id = values.get("session_id")
        if not session_id:
            raise InvalidDataError("Missing session_id for QR authentication")
        x_token, music_token = await perform_qr_auth(mass, str(session_id))
        values[CONF_MUSIC_TOKEN] = music_token
        values[CONF_X_TOKEN] = x_token
        values[CONF_REFRESH_TOKEN] = None  # QR flow does not yield a refresh_token

    # Handle cookies auth action (yields x_token + music_token, no refresh_token)
    if action == CONF_ACTION_AUTH_COOKIES:
        cookies_val = values.get(CONF_COOKIES)
        if not cookies_val:
            raise InvalidDataError("Cookies field is empty")
        x_token, music_token = await login_with_cookies(str(cookies_val))
        values[CONF_MUSIC_TOKEN] = music_token
        values[CONF_X_TOKEN] = x_token
        values[CONF_REFRESH_TOKEN] = None  # cookies flow does not yield a refresh_token
        values[CONF_COOKIES] = None  # don't persist raw cookies

    # Handle clear auth action
    if action == CONF_ACTION_CLEAR_AUTH:
        values[CONF_X_TOKEN] = None
        values[CONF_MUSIC_TOKEN] = None
        values[CONF_REFRESH_TOKEN] = None

    # If the user toggles Remember session off post-auth, drop the long-lived
    # tokens right away so silent refresh can no longer run.
    if values.get(CONF_REMEMBER_SESSION) is False:
        values[CONF_X_TOKEN] = None
        values[CONF_REFRESH_TOKEN] = None

    # Authenticated if we have *either* a music token or an x_token
    is_authenticated = bool(values.get(CONF_MUSIC_TOKEN) or values.get(CONF_X_TOKEN))

    # Dynamic label text
    if not is_authenticated:
        label_text = (
            "Open a verification URL on any device and enter the short code, "
            "or scan a QR code with the Yandex app on your phone.\n\n"
            "Alternatively, you can paste browser cookies in the advanced settings."
        )
    elif action in (CONF_ACTION_AUTH_DEVICE, CONF_ACTION_AUTH_QR, CONF_ACTION_AUTH_COOKIES):
        label_text = "Authenticated to Yandex. Don't forget to save to complete setup."
    else:
        label_text = "Authenticated to Yandex."

    return (
        # Status label
        ConfigEntry(
            key="label_text",
            type=ConfigEntryType.LABEL,
            label=label_text,
        ),
        # Device Flow authentication (primary)
        ConfigEntry(
            key=CONF_ACTION_AUTH_DEVICE,
            type=ConfigEntryType.ACTION,
            label="Login with device code",
            description="Open a verification URL on any device and enter the short code.",
            action=CONF_ACTION_AUTH_DEVICE,
            action_label="Login with device code",
            hidden=is_authenticated,
        ),
        # QR authentication (alternative)
        ConfigEntry(
            key=CONF_ACTION_AUTH_QR,
            type=ConfigEntryType.ACTION,
            label="Login with QR code",
            description="Opens a QR code page — scan it with the Yandex app on your phone.",
            action=CONF_ACTION_AUTH_QR,
            action_label="Login with QR code",
            hidden=is_authenticated,
        ),
        # Remember session toggle — stays visible after login so users can
        # opt out of long-lived tokens without resetting authentication first.
        ConfigEntry(
            key=CONF_REMEMBER_SESSION,
            type=ConfigEntryType.BOOLEAN,
            label="Remember session (auto-refresh token)",
            description=(
                "When enabled, stores a long-lived session token to automatically "
                "refresh your music token when it expires. When disabled, you must "
                "re-authenticate manually when the token expires — toggling this off "
                "after logging in immediately drops the stored long-lived tokens."
            ),
            default_value=True,
            advanced=True,
        ),
        # Experimental intercept feature — provider-level master switch.
        # When OFF, no per-player intercept setting takes effect.
        ConfigEntry(
            key=CONF_INTERCEPT_FEATURE_ENABLED,
            type=ConfigEntryType.BOOLEAN,
            label="Experimental: Enable intercept feature",
            description=(
                "Master switch for the intercept feature. When ON, individual "
                "stations can be configured (in their player settings) to "
                "redirect Alice-initiated playback to another Music Assistant "
                "player. When OFF, intercept is fully disabled regardless of "
                "per-player settings. Requires the 'yandex_music' music "
                "provider to be configured to actually resolve tracks."
            ),
            default_value=False,
            required=False,
        ),
        # Cookies authentication (advanced fallback)
        ConfigEntry(
            key=CONF_COOKIES,
            type=ConfigEntryType.SECURE_STRING,
            label="Browser Cookies",
            description=(
                "Open passport.yandex.ru/profile in your browser, "
                'use "Copy Cookies" extension to copy cookies, paste here. '
                "Supports JSON array or raw cookie string."
            ),
            required=False,
            hidden=is_authenticated,
            advanced=True,
            value="",
        ),
        ConfigEntry(
            key=CONF_ACTION_AUTH_COOKIES,
            type=ConfigEntryType.ACTION,
            label="Login with Cookies",
            description="Authenticate using browser cookies from passport.yandex.ru.",
            action=CONF_ACTION_AUTH_COOKIES,
            action_label="Login with Cookies",
            hidden=is_authenticated,
            advanced=True,
        ),
        # Clear auth
        ConfigEntry(
            key=CONF_ACTION_CLEAR_AUTH,
            type=ConfigEntryType.ACTION,
            label="Reset authentication",
            description="Clear the current authentication details.",
            action=CONF_ACTION_CLEAR_AUTH,
            action_label="Reset authentication",
            hidden=not is_authenticated,
        ),
        # x_token (internal storage, always hidden)
        ConfigEntry(
            key=CONF_X_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex X-Token",
            description="Long-lived session token. Auto-obtained via login flows.",
            required=False,
            hidden=True,
            advanced=True,
            value=cast("str", values.get(CONF_X_TOKEN)) if values else None,
        ),
        # music_token (internal storage, always hidden)
        ConfigEntry(
            key=CONF_MUSIC_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex Music Token",
            description="Auto-obtained from one of the login flows.",
            required=False,
            hidden=True,
            value=cast("str", values.get(CONF_MUSIC_TOKEN)) if values else None,
        ),
        # refresh_token (internal storage, always hidden — device flow only)
        ConfigEntry(
            key=CONF_REFRESH_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Refresh token",
            required=False,
            hidden=True,
            value=cast("str", values.get(CONF_REFRESH_TOKEN)) if values else None,
        ),
    )


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    music_token = config.get_value(CONF_MUSIC_TOKEN)
    x_token = config.get_value(CONF_X_TOKEN)
    if not music_token and not x_token:
        msg = "Authentication required. Please login with your Yandex credentials."
        raise LoginFailed(msg)
    return YandexStationProvider(mass, manifest, config, SUPPORTED_FEATURES)
