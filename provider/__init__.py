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
    CONF_MUSIC_TOKEN,
    CONF_PASSWORD,
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

    if action == CONF_ACTION_LOGIN:
        username = values.get(CONF_USERNAME)
        password = values.get(CONF_PASSWORD)
        if not username or not password:
            return "Username and password are required."

        async with ClientSession() as http_session:
            session = YandexSession(http_session)

            # Step 1: Submit username
            resp = session.login_username(str(username))
            resp = await resp
            if not resp.ok and resp.errors:
                error = resp.errors[0]
                if error == "account.not_found":
                    return "Account not found. Check your username."
                return f"Login error: {error}"

            # Step 2: Submit password
            resp = await session.login_password(str(password))
            if not resp.ok:
                errors = resp.errors
                if "password.not_matched" in errors:
                    return "Wrong password."
                if "captcha.required" in errors:
                    return (
                        "Captcha required. Yandex blocked automated login. "
                        "Please obtain x_token manually (see documentation)."
                    )
                return f"Login failed: {', '.join(errors)}"

            # Success — store tokens
            values[CONF_X_TOKEN] = resp.x_token
            values[CONF_USERNAME] = None
            values[CONF_PASSWORD] = None

    elif action == CONF_ACTION_CLEAR_AUTH:
        values[CONF_X_TOKEN] = None
        values[CONF_MUSIC_TOKEN] = None

    return None


async def get_config_entries(
    mass: MusicAssistant,  # noqa: ARG001
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """Return Config entries to setup this provider."""
    # Handle auth actions
    auth_error = await _handle_auth_action(action, values)

    # Determine authentication state
    x_token = (values or {}).get(CONF_X_TOKEN)
    is_authenticated = x_token not in (None, "")

    # Build dynamic label text
    if auth_error:
        label_text = f"⚠️ {auth_error}"
    elif not is_authenticated:
        label_text = (
            "Enter your Yandex credentials to authenticate. "
            "Your password is used once to obtain a long-lived token and is not stored."
        )
    elif action == CONF_ACTION_LOGIN:
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
        # ── Login form (shown when not authenticated) ──
        ConfigEntry(
            key=CONF_USERNAME,
            type=ConfigEntryType.STRING,
            label="Yandex Username",
            description="Your Yandex login (email or phone number).",
            required=False,
            hidden=is_authenticated,
            value=values.get(CONF_USERNAME, "") if values else "",
        ),
        ConfigEntry(
            key=CONF_PASSWORD,
            type=ConfigEntryType.SECURE_STRING,
            label="Password",
            description="Used once to obtain x_token. Not stored.",
            required=False,
            hidden=is_authenticated,
            value=values.get(CONF_PASSWORD, "") if values else "",
        ),
        ConfigEntry(
            key=CONF_ACTION_LOGIN,
            type=ConfigEntryType.ACTION,
            label="Login to Yandex",
            description="Authenticate with your Yandex credentials.",
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
        # ── Token storage (hidden, managed automatically) ──
        ConfigEntry(
            key=CONF_X_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex X-Token",
            description=(
                "Long-lived authentication token (~1 year). "
                "Automatically obtained via login, or enter manually."
            ),
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
