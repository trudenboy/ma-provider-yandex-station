"""Yandex Station Player Provider for Music Assistant.

Play music on Yandex Station smart speakers via local Glagol WebSocket protocol.
Adapted from AlexxIT/YandexStation (MIT license).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from music_assistant_models.errors import LoginFailed

from .constants import (
    CONF_ACTION_AUTH_QR,
    CONF_ACTION_CLEAR_AUTH,
    CONF_MUSIC_TOKEN,
    CONF_X_TOKEN,
)
from .provider import YandexStationProvider
from .yandex_auth import perform_qr_auth

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

    # Handle QR auth action
    if action == CONF_ACTION_AUTH_QR:
        session_id = values.get("session_id")
        if not session_id:
            raise LoginFailed("Missing session_id for QR authentication")
        x_token, music_token = await perform_qr_auth(mass, str(session_id))
        values[CONF_X_TOKEN] = x_token
        values[CONF_MUSIC_TOKEN] = music_token

    # Handle clear auth action
    if action == CONF_ACTION_CLEAR_AUTH:
        values[CONF_X_TOKEN] = None
        values[CONF_MUSIC_TOKEN] = None

    is_authenticated = bool(values.get(CONF_X_TOKEN))

    # Dynamic label text
    if not is_authenticated:
        label_text = (
            "Scan a QR code with the Yandex app on your phone to authenticate.\n\n"
            "Alternatively, you can enter tokens manually in the advanced settings."
        )
    elif action == CONF_ACTION_AUTH_QR:
        label_text = "✅ Authenticated! Don't forget to save to complete setup."
    else:
        label_text = "✅ Authenticated to Yandex."

    return (
        # Status label
        ConfigEntry(
            key="label_text",
            type=ConfigEntryType.LABEL,
            label=label_text,
        ),
        # QR authentication (primary)
        ConfigEntry(
            key=CONF_ACTION_AUTH_QR,
            type=ConfigEntryType.ACTION,
            label="Login with QR code",
            description="Opens a QR code page — scan it with the Yandex app on your phone.",
            action=CONF_ACTION_AUTH_QR,
            action_label="Login with QR code",
            hidden=is_authenticated,
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
        # x_token (internal storage)
        ConfigEntry(
            key=CONF_X_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex X-Token",
            description="Long-lived auth token (~1 year). Auto-obtained via QR login.",
            required=True,
            hidden=is_authenticated,
            advanced=True,
            value=cast("str", values.get(CONF_X_TOKEN)) if values else None,
        ),
        # music_token (internal storage)
        ConfigEntry(
            key=CONF_MUSIC_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex Music Token",
            description="Auto-obtained from X-Token. No manual entry needed.",
            required=False,
            hidden=True,
            value=cast("str", values.get(CONF_MUSIC_TOKEN)) if values else None,
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
