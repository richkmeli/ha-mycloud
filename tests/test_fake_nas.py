"""Contract tests against a fake OS5 NAS with a single admin session."""

from __future__ import annotations

import asyncio
import base64
import ssl
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from custom_components.mycloud.client import (
    AdminSessionBusyError,
    InvalidLoginError,
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


def _request_origin(request: web.Request) -> str | None:
    """Return the origin carried by an OS5 request, like nasAdmin does."""
    origin = request.headers.get("Origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("Referer")
    if not referer:
        return None
    return "/".join(referer.split("/")[:3])


class FakeNAS:
    """Minimal OS5 API that accepts one admin session at a time."""

    def __init__(self, cookie_name: str = "PHPSESSID") -> None:
        """Initialize the fake NAS state."""
        self.cookie_name = cookie_name
        self.active_session: str | None = None
        self.token_origin: str | None = None
        self.logins = 0
        self.logouts = 0
        self.logout_delay = 0.0
        self.host = ""
        self.auth_cookie = True
        self.login_error: str | None = None

    async def login(self, request: web.Request) -> web.Response:
        """Authenticate or report that another admin session is active."""
        body = await request.json()
        password = base64.b64encode(b"secret").decode()
        if body.get("username") != "admin" or body.get("password") != password:
            return web.json_response({"error": "invalid credentials"}, status=401)
        if self.login_error is not None:
            return web.json_response({"error": self.login_error})
        if self.active_session is not None:
            return web.json_response(
                {"error": "The user account entered is currently in use."},
                status=403,
            )

        self.active_session = "session-1"
        self.token_origin = _request_origin(request)
        self.logins += 1
        response = web.json_response({"ok": True})
        # OS5 scopes the cookie to the login path; the client must re-add it
        # without a path so the data endpoints receive it too.
        if self.auth_cookie:
            response.set_cookie(
                self.cookie_name, self.active_session, path="/nas/v1/auth"
            )
        return response

    async def logout(self, request: web.Request) -> web.Response:
        """Release the admin session when cookie and origin match."""
        if self.logout_delay:
            await asyncio.sleep(self.logout_delay)
        if _request_origin(request) != self.token_origin:
            return web.Response(status=401, text="request origin != token origin")
        if request.cookies.get(self.cookie_name) != self.active_session:
            return web.Response(status=403)
        self.active_session = None
        self.token_origin = None
        self.logouts += 1
        return web.Response(status=204)

    async def system_info(self, request: web.Request) -> web.Response:
        """Return a small system payload to authenticated clients."""
        if _request_origin(request) != self.token_origin:
            return web.Response(status=401, text="request origin != token origin")
        if request.cookies.get(self.cookie_name) != self.active_session:
            return web.Response(status=403)
        return web.Response(text=SYSTEM_INFO_XML)


@pytest.fixture(params=["PHPSESSID", "fe97238703cba", "ge41881ed8d9r"])
async def fake_nas(request):
    """Start the fake NAS with each OS5 authentication cookie name."""
    nas = FakeNAS(cookie_name=request.param)
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


def _self_signed_context(tmp_path) -> ssl.SSLContext:
    """Return a TLS server context with a throwaway self-signed certificate."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "wdmycloud.local")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


async def test_https_login_accepts_a_self_signed_nas_certificate(tmp_path):
    """The HTTPS option connects to an OS5 NAS with a self-signed certificate."""
    nas = FakeNAS()
    app = web.Application()
    app.router.add_post("/nas/v1/auth", nas.login)
    app.router.add_delete("/nas/v1/auth", nas.logout)
    app.router.add_get("/xml/sysinfo.xml", nas.system_info)

    server = TestServer(app)
    await server.start_server(ssl=_self_signed_context(tmp_path))
    nas.host = f"{server.host}:{server.port}"
    try:
        client = MyCloudClient("admin", "secret", nas.host, use_https=True)
        await client.async_connect()

        assert client.scheme == "https://"
        assert (await client.system_info())["size"]["total"] == 42
        assert nas.logins == 1

        await client.async_close()

        assert nas.logouts == 1
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


async def test_login_without_any_cookie_is_rejected(fake_nas):
    """A 200 login response without an authentication cookie is not usable."""
    fake_nas.auth_cookie = False
    client = MyCloudClient("admin", "secret", fake_nas.host)

    with pytest.raises(InvalidLoginError):
        await client.async_connect()

    assert client.session is None
    assert client.phpsessid is None


async def test_json_error_on_http_200_is_reported(fake_nas):
    """An OS5 JSON error is not hidden by the HTTP 200 status."""
    fake_nas.login_error = "5"
    client = MyCloudClient("admin", "secret", fake_nas.host)

    with pytest.raises(AdminSessionBusyError):
        await client.async_connect()

    assert client.session is None
    assert client.phpsessid is None
