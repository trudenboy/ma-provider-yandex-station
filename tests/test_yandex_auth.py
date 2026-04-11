"""Unit tests for yandex_auth.py (ya-passport-auth based authentication)."""

from __future__ import annotations

import json
from unittest import mock

import pytest
from music_assistant_models.errors import LoginFailed
from ya_passport_auth import Credentials, QrSession, SecretStr
from ya_passport_auth.exceptions import (
    InvalidCredentialsError,
    QRTimeoutError,
    RateLimitedError,
)
from ya_passport_auth.exceptions import (
    NetworkError as PassportNetworkError,
)

# Import via the namespace set up by conftest.py (avoids relative-import issues)
from music_assistant.providers.yandex_station.yandex_auth import (
    login_with_cookies,
    perform_qr_auth,
    refresh_music_token,
    validate_x_token,
)

# mock target prefix: the module as seen in sys.modules
_MOD = "music_assistant.providers.yandex_station.yandex_auth"

# -- helpers -------------------------------------------------------------------


def _make_credentials(
    x_token: str = "test_x_token",  # noqa: S107
    music_token: str | None = "test_music_token",  # noqa: S107
) -> Credentials:
    """Build a Credentials dataclass for testing."""
    return Credentials(
        x_token=SecretStr(x_token),
        music_token=SecretStr(music_token) if music_token else None,
    )


def _make_qr_session() -> QrSession:
    """Build a QrSession for testing."""
    return QrSession(
        track_id="track123",
        csrf_token="csrf_abc",
        qr_url="https://passport.yandex.ru/auth/magic/code/?track_id=track123",
    )


# -- perform_qr_auth ----------------------------------------------------------


async def test_perform_qr_auth_success() -> None:
    """QR flow returns (x_token, music_token) as plain strings."""
    qr = _make_qr_session()
    creds = _make_credentials()
    mock_client = mock.AsyncMock()
    mock_client.start_qr_login.return_value = qr
    mock_client.poll_qr_until_confirmed.return_value = creds

    mock_mass = mock.MagicMock()
    mock_auth_helper = mock.AsyncMock()

    with (
        mock.patch(
            f"{_MOD}.PassportClient.create",
        ) as mock_create,
        mock.patch(
            f"{_MOD}.AuthenticationHelper",
            return_value=mock_auth_helper,
        ),
    ):
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        x_token, music_token = await perform_qr_auth(mock_mass, "session_1")

    assert x_token == "test_x_token"
    assert music_token == "test_music_token"
    mock_client.start_qr_login.assert_awaited_once()
    mock_client.poll_qr_until_confirmed.assert_awaited_once_with(qr)


async def test_perform_qr_auth_sends_qr_url() -> None:
    """QR URL is sent to the AuthenticationHelper."""
    qr = _make_qr_session()
    creds = _make_credentials()
    mock_client = mock.AsyncMock()
    mock_client.start_qr_login.return_value = qr
    mock_client.poll_qr_until_confirmed.return_value = creds

    mock_mass = mock.MagicMock()
    mock_auth_helper = mock.AsyncMock()

    with (
        mock.patch(
            f"{_MOD}.PassportClient.create",
        ) as mock_create,
        mock.patch(
            f"{_MOD}.AuthenticationHelper",
            return_value=mock_auth_helper,
        ),
    ):
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        await perform_qr_auth(mock_mass, "session_1")

    mock_auth_helper.__aenter__.return_value.send_url.assert_called_once_with(qr.qr_url)


async def test_perform_qr_auth_timeout_raises_login_failed() -> None:
    """QRTimeoutError from library is mapped to LoginFailed."""
    qr = _make_qr_session()
    mock_client = mock.AsyncMock()
    mock_client.start_qr_login.return_value = qr
    mock_client.poll_qr_until_confirmed.side_effect = QRTimeoutError("timed out")

    mock_mass = mock.MagicMock()
    mock_auth_helper = mock.AsyncMock()

    with (
        mock.patch(
            f"{_MOD}.PassportClient.create",
        ) as mock_create,
        mock.patch(
            f"{_MOD}.AuthenticationHelper",
            return_value=mock_auth_helper,
        ),
    ):
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with pytest.raises(LoginFailed, match="timed out"):
            await perform_qr_auth(mock_mass, "session_1")


async def test_perform_qr_auth_passport_error_raises_login_failed() -> None:
    """Generic YaPassportError is mapped to LoginFailed."""
    mock_client = mock.AsyncMock()
    mock_client.start_qr_login.side_effect = PassportNetworkError("connection lost")

    mock_mass = mock.MagicMock()
    mock_auth_helper = mock.AsyncMock()

    with (
        mock.patch(
            f"{_MOD}.PassportClient.create",
        ) as mock_create,
        mock.patch(
            f"{_MOD}.AuthenticationHelper",
            return_value=mock_auth_helper,
        ),
    ):
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with pytest.raises(LoginFailed, match="Yandex auth error"):
            await perform_qr_auth(mock_mass, "session_1")


async def test_perform_qr_auth_no_music_token_raises() -> None:
    """Credentials without music_token raises LoginFailed."""
    qr = _make_qr_session()
    creds = _make_credentials(music_token=None)
    mock_client = mock.AsyncMock()
    mock_client.start_qr_login.return_value = qr
    mock_client.poll_qr_until_confirmed.return_value = creds

    mock_mass = mock.MagicMock()
    mock_auth_helper = mock.AsyncMock()

    with (
        mock.patch(
            f"{_MOD}.PassportClient.create",
        ) as mock_create,
        mock.patch(
            f"{_MOD}.AuthenticationHelper",
            return_value=mock_auth_helper,
        ),
    ):
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with pytest.raises(LoginFailed, match="no music token"):
            await perform_qr_auth(mock_mass, "session_1")


# -- refresh_music_token -------------------------------------------------------


async def test_refresh_music_token_success() -> None:
    """Successful refresh returns a SecretStr."""
    mock_client = mock.AsyncMock()
    mock_client.refresh_music_token.return_value = SecretStr("new_music_token")

    with mock.patch(
        f"{_MOD}.PassportClient.create",
    ) as mock_create:
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        result = await refresh_music_token(SecretStr("my_x_token"))

    assert result.get_secret() == "new_music_token"
    mock_client.refresh_music_token.assert_awaited_once()


async def test_refresh_music_token_auth_error_raises_login_failed() -> None:
    """Auth failure during refresh is mapped to LoginFailed."""
    mock_client = mock.AsyncMock()
    mock_client.refresh_music_token.side_effect = InvalidCredentialsError("bad token")

    with mock.patch(
        f"{_MOD}.PassportClient.create",
    ) as mock_create:
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with pytest.raises(LoginFailed, match="Failed to refresh"):
            await refresh_music_token(SecretStr("bad_x_token"))


# -- validate_x_token ----------------------------------------------------------


async def test_validate_x_token_valid() -> None:
    """Valid x_token returns True."""
    mock_client = mock.AsyncMock()
    mock_client.validate_x_token.return_value = True

    with mock.patch(
        f"{_MOD}.PassportClient.create",
    ) as mock_create:
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        result = await validate_x_token(SecretStr("good_token"))

    assert result is True


async def test_validate_x_token_error_returns_false() -> None:
    """Any YaPassportError returns False (graceful degradation)."""
    mock_client = mock.AsyncMock()
    mock_client.validate_x_token.side_effect = RateLimitedError("429")

    with mock.patch(
        f"{_MOD}.PassportClient.create",
    ) as mock_create:
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        result = await validate_x_token(SecretStr("some_token"))

    assert result is False


# -- login_with_cookies --------------------------------------------------------


async def test_login_with_cookies_raw_string() -> None:
    """Raw cookie string auth returns (x_token, music_token)."""
    creds = _make_credentials(x_token="cookie_x_token", music_token="cookie_music_token")

    mock_client = mock.AsyncMock()
    mock_client.login_cookies.return_value = creds

    with mock.patch(f"{_MOD}.PassportClient.create") as mock_create:
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        x_token, music_token = await login_with_cookies("Session_id=abc123; yandexuid=456")

    assert x_token == "cookie_x_token"
    assert music_token == "cookie_music_token"
    mock_client.login_cookies.assert_awaited_once_with("Session_id=abc123; yandexuid=456")


async def test_login_with_cookies_json_format() -> None:
    """JSON cookie array is converted to semicolon string and passed to library."""
    cookies_json = json.dumps(
        [
            {"name": "Session_id", "value": "abc123", "domain": ".yandex.ru"},
            {"name": "yandexuid", "value": "456", "domain": ".yandex.ru"},
        ]
    )

    creds = _make_credentials(x_token="json_x_token", music_token="json_music_token")

    mock_client = mock.AsyncMock()
    mock_client.login_cookies.return_value = creds

    with mock.patch(f"{_MOD}.PassportClient.create") as mock_create:
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        x_token, music_token = await login_with_cookies(cookies_json)

    assert x_token == "json_x_token"
    assert music_token == "json_music_token"
    mock_client.login_cookies.assert_awaited_once_with("Session_id=abc123; yandexuid=456")


async def test_login_with_cookies_empty_raises() -> None:
    """Empty cookie string raises LoginFailed."""
    with pytest.raises(LoginFailed, match="Empty cookies"):
        await login_with_cookies("")


async def test_login_with_cookies_invalid_format_raises() -> None:
    """Cookie string without '=' raises LoginFailed."""
    with pytest.raises(LoginFailed, match="Invalid cookie format"):
        await login_with_cookies("no_equals_sign_here")


async def test_login_with_cookies_auth_error_raises_login_failed() -> None:
    """InvalidCredentialsError from library is mapped to LoginFailed."""
    mock_client = mock.AsyncMock()
    mock_client.login_cookies.side_effect = InvalidCredentialsError("bad cookies")

    with mock.patch(f"{_MOD}.PassportClient.create") as mock_create:
        mock_create.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_create.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with pytest.raises(LoginFailed, match="Cookie authentication failed"):
            await login_with_cookies("Session_id=expired; yandexuid=456")
