"""
Borrow mode: the Station uses a linked Yandex Music instance's account.

Covers spec 0001 — account-source dropdown, borrow-mode session
bootstrap (read-only against the linked instance) and the 401 re-derive
path. Own-mode behavior is pinned by the existing cascade suite.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from music_assistant_models.enums import ProviderType
from music_assistant_models.errors import LoginFailed, ResourceTemporarilyUnavailable
from ya_passport_auth.ma import BORROW_SOURCE_OWN

from music_assistant.providers.yandex_station import setup
from music_assistant.providers.yandex_station.constants import (
    CONF_INTERCEPT_FEATURE_ENABLED,
    CONF_MUSIC_TOKEN,
    CONF_X_TOKEN,
    CONF_YM_INSTANCE,
)

from .test_provider_cascade import _make_provider, _updates

_MOD = "music_assistant.providers.yandex_station.provider"


def _ym_owner(token: str | None, x_token: str | None) -> mock.MagicMock:
    owner = mock.MagicMock()
    owner.domain = "yandex_music"
    owner.type = ProviderType.MUSIC
    owner.config.get_value = lambda key: {"token": token, "x_token": x_token}.get(key)
    return owner


def _borrow_provider(owner: mock.MagicMock | None) -> Any:
    provider = _make_provider(
        {
            CONF_YM_INSTANCE: "ym-1",
            CONF_MUSIC_TOKEN: None,
            CONF_X_TOKEN: None,
        }
    )
    provider.mass.get_provider = mock.MagicMock(  # type: ignore[method-assign]
        return_value=owner
    )
    return provider


class TestConfigEntries:
    """The account source and authentication actions live only in setup."""

    async def test_options_surface_contains_only_genuine_options(self) -> None:
        """Post-setup configuration exposes the intercept option, not login fields."""
        provider = _make_provider({})

        entries = await provider.get_config_entries()

        keys = {entry.key for entry in entries}
        assert CONF_YM_INSTANCE not in keys
        assert keys.isdisjoint({"auth_device", "auth_qr", "auth_cookies", "clear_auth"})
        assert CONF_INTERCEPT_FEATURE_ENABLED in keys


class TestSetup:
    """Credential gating reads the values collected by the setup flow."""

    async def test_setup_allows_borrow_without_own_tokens(self) -> None:
        """Borrow mode passes setup() with empty own-token config."""
        mass = mock.MagicMock()
        config = mock.MagicMock()
        config.get_value = lambda _key, default=None: default
        with mock.patch(
            "music_assistant.providers.yandex_station.YandexStationProvider"
        ) as provider_cls:
            provider_cls.return_value.get_setup_value = mock.MagicMock(
                side_effect=lambda key, default=None: "ym-1" if key == CONF_YM_INSTANCE else default
            )
            await setup(mass, mock.MagicMock(), config)
        provider_cls.assert_called_once()

    async def test_setup_rejects_own_without_tokens(self) -> None:
        """Own mode without music or x token fails fast."""
        mass = mock.MagicMock()
        config = mock.MagicMock()
        config.get_value = lambda _key, default=None: default
        with mock.patch(
            "music_assistant.providers.yandex_station.YandexStationProvider"
        ) as provider_cls:
            provider_cls.return_value.get_setup_value = mock.MagicMock(
                side_effect=lambda key, default=None: (
                    BORROW_SOURCE_OWN if key == CONF_YM_INSTANCE else default
                )
            )
            with pytest.raises(LoginFailed):
                await setup(mass, mock.MagicMock(), config)


async def test_borrow_source_comes_from_setup_data() -> None:
    """A linked account selected during setup drives the read-only credential source."""
    provider = _make_provider({CONF_YM_INSTANCE: BORROW_SOURCE_OWN})
    provider.config.setup_data[CONF_YM_INSTANCE] = "ym-1"

    source = provider._build_borrow_source()

    assert source is not None
    assert source.instance_id == "ym-1"


class TestBorrowInitSession:
    """Session bootstrap from the linked instance (read-only)."""

    async def test_builds_session_from_linked_tokens(self) -> None:
        """YandexSession gets the borrowed tokens; nothing is persisted."""
        provider = _borrow_provider(_ym_owner("test-music-ym", "test-x-ym"))
        with (
            mock.patch(f"{_MOD}.ClientSession") as http_cls,
            mock.patch(f"{_MOD}.PassportClient"),
            mock.patch(f"{_MOD}.YandexSession") as session_cls,
        ):
            http_cls.return_value = mock.MagicMock(closed=False, close=mock.AsyncMock())
            session_instance = mock.MagicMock()
            session_instance.login_token = mock.AsyncMock(return_value=True)
            session_cls.return_value = session_instance

            assert await provider._init_session() is True

        kwargs = session_cls.call_args.kwargs
        assert kwargs["x_token"].get_secret() == "test-x-ym"
        assert kwargs["music_token"].get_secret() == "test-music-ym"
        assert kwargs["refresh_token"] is None
        # Read-only: nothing persisted on either side.
        assert _updates(provider) == []

    async def test_ym_not_loaded_is_transient(self) -> None:
        """A not-yet-loaded linked instance is a retryable condition."""
        provider = _borrow_provider(None)
        with pytest.raises(ResourceTemporarilyUnavailable, match="not loaded"):
            await provider._init_session()
        assert _updates(provider) == []


class TestBorrowSilentReauth:
    """401 recovery re-derives cookies without rotation."""

    async def test_rereads_linked_tokens_and_refreshes_cookies(self) -> None:
        """Reauth re-reads owner tokens and refreshes cookies, never rotates."""
        provider = _borrow_provider(_ym_owner("test-music-ym", "test-x-ym"))
        provider._session = mock.MagicMock()
        provider._session.login_token = mock.AsyncMock(return_value=True)

        with mock.patch("ya_passport_auth.ma.cascade.refresh_credentials") as rotate:
            assert await provider._silent_reauth() is True

        rotate.assert_not_called()
        assert provider._session.x_token.get_secret() == "test-x-ym"
        assert provider._session.music_token.get_secret() == "test-music-ym"
        provider._session.login_token.assert_awaited()
        assert _updates(provider) == []
