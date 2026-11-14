"""Tests for the WD NAS client wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock

import aiohttp
from wdnas_client.exceptions import RequestFailedError

from custom_components.mycloud.client import MyCloudClient, parse_uptime_text


class _FakeResponse:
    """Minimal aiohttp response for the uptime fallback."""

    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeSession:
    """Minimal aiohttp session that records the uptime request."""

    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def post(self, url, data=None, headers=None):
        self.calls.append((url, data))
        return self.response


def test_parse_uptime_text():
    """The NAS uptime text is converted to seconds."""
    assert parse_uptime_text("<uptime>0 day 0 hour 50 minutes</uptime>") == 3000
    assert parse_uptime_text("1 day 2 hours 3 minutes") == 93_780
    assert parse_uptime_text("2 days 0 hour 0 minutes") == 172_800
    assert parse_uptime_text("not an uptime") is None


async def test_async_uptime_falls_back_to_status():
    """A failing cgi_get_uptime is retried through cgi_get_status."""
    client = MyCloudClient("admin", "secret", "nas.local", 5)
    client.uptime = AsyncMock(side_effect=RequestFailedError(500))
    client._async_uptime_from_status = AsyncMock(return_value=3000)

    assert await client.async_uptime() == 3000
    client.uptime.assert_awaited_once()
    client._async_uptime_from_status.assert_awaited_once()


async def test_async_uptime_falls_back_on_connection_error():
    """A transport error while reading uptime also uses the status fallback."""
    client = MyCloudClient("admin", "secret", "nas.local", 5)
    client.uptime = AsyncMock(side_effect=aiohttp.ClientError("offline"))
    client._async_uptime_from_status = AsyncMock(return_value=3000)

    assert await client.async_uptime() == 3000
    client._async_uptime_from_status.assert_awaited_once()


async def test_async_uptime_is_v5_only():
    """V2 has no uptime endpoint and must not issue a request."""
    client = MyCloudClient("admin", "secret", "nas.local", 2)
    client.uptime = AsyncMock()

    assert await client.async_uptime() is None
    client.uptime.assert_not_awaited()


async def test_uptime_from_status_uses_configured_host():
    """The fallback only talks to the configured NAS host."""
    client = MyCloudClient("admin", "secret", "nas.local:8080", 5)
    session = _FakeSession(
        _FakeResponse(200, "<uptime>1 day 2 hours 3 minutes</uptime>")
    )
    client.session = session

    assert await client._async_uptime_from_status() == 93_780
    assert session.calls == [
        ("http://nas.local:8080/cgi-bin/status_mgr.cgi", "cmd=cgi_get_status")
    ]


async def test_uptime_from_status_returns_none_on_error():
    """A failed status request or missing uptime does not raise."""
    client = MyCloudClient("admin", "secret", "nas.local", 5)
    client.session = _FakeSession(_FakeResponse(500, ""))

    assert await client._async_uptime_from_status() is None

    client.session = _FakeSession(_FakeResponse(200, "no uptime here"))
    assert await client._async_uptime_from_status() is None
