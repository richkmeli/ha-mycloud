"""Tests for the WD NAS client wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from xml.etree.ElementTree import ParseError

import aiohttp
import pytest

from custom_components.mycloud.client import (
    InvalidLoginError,
    MyCloudClient,
    PowerActionBlockedError,
    RequestFailedError,
    parse_uptime_text,
    status_code,
)


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
        self.closed = False

    def post(self, url, data=None, headers=None):
        self.calls.append((url, data))
        return self.response


def test_parse_uptime_text():
    """The NAS uptime text is converted to seconds."""
    assert parse_uptime_text("<uptime>0 day 0 hour 50 minutes</uptime>") == 3000
    assert parse_uptime_text("1 day 2 hours 3 minutes") == 93_780
    assert parse_uptime_text("2 days 0 hour 0 minutes") == 172_800
    assert parse_uptime_text("not an uptime") is None


def test_status_code_extracts_http_status():
    """The HTTP status is extracted from the client exception or message."""
    assert status_code(RequestFailedError(404)) == 404
    assert status_code(RequestFailedError("missing session")) is None
    assert status_code(Exception("Request failed: 502")) == 502
    assert status_code(Exception("not an HTTP error")) is None


async def test_connect_reconnect_and_close_use_the_session_lock():
    """The public lifecycle methods delegate to the locked helpers."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client._async_open = AsyncMock()
    client._async_close_locked = AsyncMock()

    await client.async_connect()
    await client.async_reconnect()
    await client.async_close()

    assert client._async_open.await_count == 2
    client._async_close_locked.assert_awaited_once()


async def test_async_open_creates_a_bounded_session_and_logs_in():
    """Opening the client replaces the session and authenticates."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    client.login = AsyncMock()

    with patch(
        "custom_components.mycloud.client.aiohttp.ClientSession",
        return_value=session,
    ) as session_cls:
        await client._async_open()

    session_cls.assert_called_once()
    client.login.assert_awaited_once()
    assert client.session is session


async def test_async_open_uses_a_default_connector_for_http():
    """HTTP stays on the aiohttp default, verified connector."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    client.login = AsyncMock()

    with (
        patch("custom_components.mycloud.client.aiohttp.TCPConnector") as connector_cls,
        patch(
            "custom_components.mycloud.client.aiohttp.ClientSession",
            return_value=session,
        ) as session_cls,
    ):
        await client._async_open()

    connector_cls.assert_not_called()
    assert session_cls.call_args.kwargs["connector"] is None


async def test_async_open_disables_certificate_verification_for_https(caplog):
    """The self-signed WD certificate is accepted for the configured host."""
    caplog.set_level("DEBUG", logger="custom_components.mycloud.client")
    client = MyCloudClient("admin", "secret", "nas.local:8543", use_https=True)
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    client.login = AsyncMock()

    with (
        patch("custom_components.mycloud.client.aiohttp.TCPConnector") as connector_cls,
        patch(
            "custom_components.mycloud.client.aiohttp.ClientSession",
            return_value=session,
        ) as session_cls,
    ):
        await client._async_open()

    connector_cls.assert_called_once_with(ssl=False)
    assert session_cls.call_args.kwargs["connector"] is connector_cls.return_value
    assert "certificate verification is disabled for nas.local:8543" in caplog.text


async def test_async_open_closes_the_session_when_login_fails():
    """A failed login does not leak the new aiohttp session."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    client.login = AsyncMock(side_effect=InvalidLoginError("bad"))

    with (
        patch(
            "custom_components.mycloud.client.aiohttp.ClientSession",
            return_value=session,
        ),
        pytest.raises(InvalidLoginError),
    ):
        await client._async_open()

    assert client.session is None
    session.close.assert_awaited_once()


async def test_close_locked_closes_only_open_sessions():
    """Closing an open session releases it and clears the reference."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    client.session = session

    await client._async_close_locked()

    session.close.assert_awaited_once()
    assert client.session is None


async def test_close_locked_skips_already_closed_sessions():
    """An already closed session is not closed twice."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = MagicMock()
    session.closed = True
    session.close = AsyncMock()
    client.session = session

    await client._async_close_locked()

    session.close.assert_not_awaited()
    assert client.session is None


async def test_close_releases_the_admin_session_before_closing():
    """Closing an authenticated client logs out on the NAS first."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _LogoutSession(_FakeResponse(204, ""))
    client.session = session
    client.phpsessid = "session-id"

    await client._async_close_locked()

    assert session.calls == [
        (
            "http://nas.local/nas/v1/auth",
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Host": "nas.local",
                "Origin": "http://nas.local",
                "Referer": "http://nas.local/",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
    ]
    assert session.closed
    assert client.session is None
    assert client.phpsessid is None


async def test_close_swallows_logout_failures():
    """An unreachable NAS still allows the local session to be released."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _LogoutSession(error=aiohttp.ClientError("offline"))
    client.session = session
    client.phpsessid = "session-id"

    await client._async_close_locked()

    assert len(session.calls) == 1
    assert session.closed
    assert client.session is None
    assert client.phpsessid is None


async def test_client_context_manager_opens_and_closes():
    """The async context manager exposes the client and closes it."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.async_connect = AsyncMock()
    client.async_close = AsyncMock()

    async with client as entered:
        assert entered is client

    client.async_connect.assert_awaited_once()
    client.async_close.assert_awaited_once()


async def test_async_uptime_falls_back_to_status():
    """A failing cgi_get_uptime is retried through cgi_get_status."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.uptime = AsyncMock(side_effect=RequestFailedError(500))
    client._async_uptime_from_status = AsyncMock(return_value=3000)

    assert await client.async_uptime() == 3000
    client.uptime.assert_awaited_once()
    client._async_uptime_from_status.assert_awaited_once()


async def test_async_uptime_falls_back_on_connection_error():
    """A transport error while reading uptime also uses the status fallback."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.uptime = AsyncMock(side_effect=aiohttp.ClientError("offline"))
    client._async_uptime_from_status = AsyncMock(return_value=3000)

    assert await client.async_uptime() == 3000
    client._async_uptime_from_status.assert_awaited_once()


def test_client_is_os5_only():
    """The wrapper always uses the OS5 API."""
    client = MyCloudClient("admin", "secret", "nas.local")

    assert client.version == 5


async def test_async_uptime_uses_the_primary_endpoint():
    """Uptime uses cgi_get_uptime when the NAS supports it."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.uptime = AsyncMock(return_value=3000)

    assert await client.async_uptime() == 3000
    client.uptime.assert_awaited_once()


async def test_uptime_from_status_uses_configured_host():
    """The fallback only talks to the configured NAS host."""
    client = MyCloudClient("admin", "secret", "nas.local:8080")
    session = _FakeSession(
        _FakeResponse(200, "<uptime>1 day 2 hours 3 minutes</uptime>")
    )
    client.session = session

    assert await client._async_uptime_from_status() == 93_780
    assert session.calls == [
        ("http://nas.local:8080/cgi-bin/status_mgr.cgi", "cmd=cgi_get_status")
    ]


async def test_uptime_from_status_omits_origin_headers():
    """The status fallback must not send Origin/Referer/X-Requested-With."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _RecordingSession(
        [_FakeResponse(200, "<uptime>1 day 2 hours 3 minutes</uptime>")]
    )
    client.session = session

    assert await client._async_uptime_from_status() == 93_780
    _, _, headers = session.calls[0]
    assert "Origin" not in headers
    assert "Referer" not in headers
    assert "X-Requested-With" not in headers


async def test_uptime_from_status_returns_none_on_error():
    """A failed status request or missing uptime does not raise."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.session = _FakeSession(_FakeResponse(500, ""))

    assert await client._async_uptime_from_status() is None

    client.session = _FakeSession(_FakeResponse(200, "no uptime here"))
    assert await client._async_uptime_from_status() is None


async def test_uptime_from_status_without_session_is_none():
    """The fallback is a no-op when the session is missing."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.session = None

    assert await client._async_uptime_from_status() is None


async def test_uptime_from_status_handles_transport_errors():
    """A transport error during the fallback does not propagate."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = MagicMock()
    session.closed = False
    session.post.side_effect = aiohttp.ClientError("offline")
    client.session = session

    assert await client._async_uptime_from_status() is None


class _LogoutSession:
    """Session that records the server-side logout request."""

    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def delete(self, url, headers=None):
        self.calls.append((url, headers))
        if self.error is not None:
            raise self.error
        return self.response

    async def close(self) -> None:
        self.closed = True


class _RecordingSession:
    """Session that returns prepared responses and records power requests."""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []
        self.closed = False

    def post(self, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        return self.responses.pop(0)


class _DisconnectResponse:
    """Response that simulates the NAS closing the connection."""

    async def __aenter__(self):
        raise aiohttp.ServerDisconnectedError()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


async def test_power_action_checks_safety_then_shuts_down():
    """Shutdown uses the authenticated session after the safety check."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _RecordingSession(
        [_FakeResponse(200, "<root><res>0</res></root>"), _FakeResponse(200, "")]
    )
    client.session = session

    await client.async_power_action("shutdown")

    assert [call[1] for call in session.calls] == [
        "cmd=cgi_Detect_Dangerous",
        "cmd=cgi_shutdown",
    ]
    assert session.calls[0][0] == "http://nas.local/cgi-bin/hd_config.cgi"
    assert session.calls[1][0] == "http://nas.local/cgi-bin/system_mgr.cgi"
    assert all(call[2]["Host"] == "nas.local" for call in session.calls)
    # Legacy CGI endpoints must not receive Origin/Referer/X-Requested-With.
    for _, _, headers in session.calls:
        assert "Origin" not in headers
        assert "Referer" not in headers
        assert "X-Requested-With" not in headers


async def test_power_action_uses_https_urls_when_requested():
    """Power actions follow the scheme selected for the entry."""
    client = MyCloudClient("admin", "secret", "nas.local:8543", use_https=True)
    session = _RecordingSession(
        [_FakeResponse(200, "<root><res>0</res></root>"), _FakeResponse(200, "")]
    )
    client.session = session

    await client.async_power_action("restart")

    assert session.calls[0][0] == "https://nas.local:8543/cgi-bin/hd_config.cgi"
    assert session.calls[1][0] == "https://nas.local:8543/cgi-bin/system_mgr.cgi"


async def test_power_action_restart_uses_restart_command():
    """Restart sends the cgi_restart command."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _RecordingSession(
        [_FakeResponse(200, "<root><res>0</res></root>"), _FakeResponse(200, "")]
    )
    client.session = session

    await client.async_power_action("restart")

    assert session.calls[1][1] == "cmd=cgi_restart"


async def test_power_action_is_blocked_when_safety_check_fails():
    """A non-zero safety code prevents the power action."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _RecordingSession([_FakeResponse(200, "<root><res>2</res></root>")])
    client.session = session

    with pytest.raises(PowerActionBlockedError) as err:
        await client.async_power_action("shutdown")

    assert err.value.code == 2
    assert len(session.calls) == 1


async def test_power_action_rejects_malformed_safety_response():
    """A missing or non-numeric safety result is not treated as safe."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _RecordingSession([_FakeResponse(200, "<root/>")])
    client.session = session

    with pytest.raises(ParseError):
        await client.async_power_action("shutdown")

    session.responses = [_FakeResponse(200, "<root><res>yes</res></root>")]
    with pytest.raises(ParseError):
        await client.async_power_action("shutdown")


async def test_power_action_reports_safety_http_error():
    """An HTTP error from the safety endpoint is reported."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.session = _RecordingSession([_FakeResponse(500, "")])

    with pytest.raises(RequestFailedError):
        await client.async_power_action("shutdown")


async def test_power_action_reports_action_http_error():
    """An HTTP error from the action endpoint is reported."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.session = _RecordingSession(
        [_FakeResponse(200, "<root><res>0</res></root>"), _FakeResponse(500, "")]
    )

    with pytest.raises(RequestFailedError):
        await client.async_power_action("shutdown")


async def test_power_action_treats_disconnect_as_success():
    """The NAS may close the connection while it powers off."""
    client = MyCloudClient("admin", "secret", "nas.local")
    session = _RecordingSession(
        [_FakeResponse(200, "<root><res>0</res></root>"), _DisconnectResponse()]
    )
    client.session = session

    await client.async_power_action("shutdown")

    assert len(session.calls) == 2


async def test_power_action_requires_a_session():
    """A missing session cannot issue power commands."""
    client = MyCloudClient("admin", "secret", "nas.local")
    with pytest.raises(ValueError):
        await client.async_power_action("shutdown")


async def test_power_action_rejects_unknown_action():
    """Only restart and shutdown are accepted."""
    client = MyCloudClient("admin", "secret", "nas.local")
    client.session = _RecordingSession([])

    with pytest.raises(ValueError):
        await client.async_power_action("halt")
