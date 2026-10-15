"""Tests for YandexSession cookie validation."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from provider.session import YandexSession


class _FakeResponse:
    def __init__(self, status: int = 200, payload: Any = None) -> None:
        self.status = status
        self._payload = payload

    async def json(self, content_type: str | None = None) -> Any:
        return self._payload

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeHttp:
    """Records requested URLs and replays one response or error."""

    def __init__(self, result: _FakeResponse | Exception) -> None:
        self.result = result
        self.urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.urls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _make_session(http: _FakeHttp) -> tuple[YandexSession, AsyncMock]:
    session = YandexSession(http, MagicMock(), x_token=MagicMock())  # type: ignore[arg-type]
    login = AsyncMock(return_value=True)
    session.login_token = login  # type: ignore[method-assign]
    return session, login


async def test_refresh_cookies_uses_iot_storage_endpoint() -> None:
    """Valid cookies are confirmed via the IoT storage page without re-login."""
    http = _FakeHttp(_FakeResponse(payload={"storage": {"user": {"uid": "123"}}}))
    session, login = _make_session(http)

    assert await session.refresh_cookies() is True

    assert http.urls == ["https://yandex.ru/iot?storage=1"]
    login.assert_not_awaited()


async def test_refresh_cookies_without_uid_logs_in_again() -> None:
    """An anonymous storage payload means the cookies are stale."""
    http = _FakeHttp(_FakeResponse(payload={"storage": {"user": {"uid": ""}}}))
    session, login = _make_session(http)

    assert await session.refresh_cookies() is True

    login.assert_awaited_once()


async def test_refresh_cookies_connection_error_logs_in_again() -> None:
    """A dropped connection on the check falls back to x-token login instead of raising."""
    http = _FakeHttp(aiohttp.ServerDisconnectedError())
    session, login = _make_session(http)

    assert await session.refresh_cookies() is True

    login.assert_awaited_once()
