"""Contract tests against a fake OS5 NAS with a single admin session."""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.mycloud.client import (
    AdminSessionBusyError,
    MyCloudClient,
)

SYSTEM_INFO_XML = """
<config>
  <disks>
    <disk id="1">
      <name>sda</name>
      <connected>1</connected>
      <healthy>1</healthy>
    </disk>
  </disks>
  <vols>
    <vol id="1">
      <name>Volume_1</name>
      <mounted>1</mounted>
      <size>42</size>
    </vol>
  </vols>
  <total_size>42</total_size>
  <total_used_size>10</total_used_size>
  <total_unused_size>32</total_unused_size>
</config>
"""


class FakeNAS:
    """Minimal OS5 API that accepts one admin session at a time."""

    def __init__(self) -> None:
        """Initialize the fake NAS state."""
        self.active_session: str | None = None
        self.logins = 0
        self.logouts = 0
        self.logout_delay = 0.0
        self.host = ""

    async def login(self, request: web.Request) -> web.Response:
        """Authenticate or report that another admin session is active."""
        body = await request.json()
        password = base64.b64encode(b"secret").decode()
        if body.get("username") != "admin" or body.get("password") != password:
            return web.json_response({"error": "invalid credentials"}, status=401)
        if self.active_session is not None:
            return web.json_response(
                {"error": "The user account entered is currently in use."},
                status=403,
            )

        self.active_session = "session-1"
        self.logins += 1
        response = web.json_response({"ok": True})
        # OS5 scopes the cookie to the login path; the client must re-add it
        # without a path so the data endpoints receive it too.
        response.set_cookie("PHPSESSID", self.active_session, path="/nas/v1/auth")
        return response

    async def logout(self, request: web.Request) -> web.Response:
        """Release the admin session when the cookie matches."""
        if self.logout_delay:
            await asyncio.sleep(self.logout_delay)
        if request.cookies.get("PHPSESSID") != self.active_session:
            return web.Response(status=403)
        self.active_session = None
        self.logouts += 1
        return web.Response(status=204)

    async def system_info(self, request: web.Request) -> web.Response:
        """Return a small system payload to authenticated clients."""
        if request.cookies.get("PHPSESSID") != self.active_session:
            return web.Response(status=403)
        return web.Response(text=SYSTEM_INFO_XML)


@pytest.fixture
async def fake_nas():
    """Start the fake NAS on a local ephemeral port."""
    nas = FakeNAS()
    app = web.Application()
    app.router.add_post("/nas/v1/auth", nas.login)
    app.router.add_delete("/nas/v1/auth", nas.logout)
    app.router.add_get("/xml/sysinfo.xml", nas.system_info)

    server = TestServer(app)
    await server.start_server()
    nas.host = f"{server.host}:{server.port}"
    try:
        yield nas
    finally:
        await server.close()


async def test_single_admin_session_is_released_on_close(fake_nas):
    """A second login succeeds only after the first client logs out."""
    first = MyCloudClient("admin", "secret", fake_nas.host)
    await first.async_connect()

    assert fake_nas.active_session == "session-1"
    assert (await first.system_info())["size"]["total"] == 42

    second = MyCloudClient("admin", "secret", fake_nas.host)
    with pytest.raises(AdminSessionBusyError):
        await second.async_connect()

    await first.async_close()

    assert fake_nas.active_session is None
    assert fake_nas.logouts == 1
    assert first.session is None

    await second.async_connect()
    assert second.phpsessid == "session-1"

    await second.async_close()
    assert fake_nas.active_session is None
    assert fake_nas.logouts == 2


async def test_close_times_out_a_hanging_logout(fake_nas):
    """An unanswered logout cannot block an unload or reload."""
    fake_nas.logout_delay = 1.0
    client = MyCloudClient("admin", "secret", fake_nas.host)
    await client.async_connect()

    with patch("custom_components.mycloud.client._LOGOUT_TIMEOUT", 0.01):
        async with asyncio.timeout(0.5):
            await client.async_close()

    assert client.session is None
    assert client.phpsessid is None
