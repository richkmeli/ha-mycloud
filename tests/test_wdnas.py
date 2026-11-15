"""Tests for the vendored OS5 WD NAS protocol client."""

from __future__ import annotations

import base64
import http.cookies
import json
from xml.etree.ElementTree import ParseError

import aiohttp
import pytest

from custom_components.mycloud.wdnas import (
    ENDPOINTS,
    HTTPS_SCHEME,
    SCHEME,
    AccountLockedError,
    AdminSessionBusyError,
    InvalidLoginError,
    NotAdminError,
    PasswordExpiredError,
    RequestFailedError,
    WDNASClient,
    _json_keys,
    parse_uptime_text,
)

SYSTEM_INFO_XML = """
<config>
  <disks>
    <disk id="1">
      <name>sda</name>
      <connected>1</connected>
      <vendor>WD</vendor>
      <model>WDC WD40EFAX</model>
      <rev>83.00A83</rev>
      <sn>WD-DISK-SN</sn>
      <size>4000787030016</size>
      <failed>0</failed>
      <healthy>1</healthy>
      <removable>1</removable>
      <over_temp>0</over_temp>
      <temp>35</temp>
      <sleep>0</sleep>
    </disk>
    <disk id="2">
      <name>sdb</name>
      <connected></connected>
      <size>100</size>
      <temp></temp>
    </disk>
  </disks>
  <vols>
    <vol id="1">
      <name>Volume_1</name>
      <label>Data</label>
      <encrypted>0</encrypted>
      <unlocked>1</unlocked>
      <mounted>1</mounted>
      <size>3932701929472</size>
    </vol>
    <total_size>3893374910178</total_size>
    <total_used_size>515219877888</total_used_size>
    <total_unused_size>3378155032290</total_unused_size>
  </vols>
</config>
"""

SYSTEM_STATUS_XML = """
<root>
  <cpu>12%</cpu>
  <mem_total>1000</mem_total>
  <mem_free>400</mem_free>
  <mem2_total>400 / 1000 MB</mem2_total>
</root>
"""

NETWORK_XML = """
<info>
  <lan>
    <mac>00:11:22:33:44:55</mac>
    <speed>1000</speed>
    <dhcp_enable>0</dhcp_enable>
    <dns_manual>1</dns_manual>
    <ip>192.168.10.41</ip>
    <netmask>255.255.255.0</netmask>
    <gateway>192.168.10.1</gateway>
    <lan_speed>1000</lan_speed>
    <lan_status>1</lan_status>
    <dns1>192.168.10.1</dns1>
    <dns2></dns2>
    <dns3></dns3>
  </lan>
  <lan>
    <mac>No found.</mac>
    <ip>192.168.0.33</ip>
  </lan>
</info>
"""

DEVICE_INFO_XML = """
<device_info>
  <serial_number>WUBM31111111</serial_number>
  <name>MyCloudEX2Ultra</name>
  <description>2-Bay NAS</description>
</device_info>
"""

SYSTEM_VERSION_XML = """
<version>
  <fw>5.31.108</fw>
  <oled>1.06
</oled>
</version>
"""

ACCOUNTS_XML = """
<accounts>
  <item>
    <uid>500</uid>
    <name>admin</name>
    <email>admin@example.com</email>
    <pwd>1</pwd>
    <gid>1000</gid>
    <first_name>Admin</first_name>
    <last_name>One</last_name>
    <last_name>Two</last_name>
    <hint>hint</hint>
  </item>
  <item>
    <name>incomplete</name>
  </item>
  <item>
    <gid>1000</gid>
    <name>administrators</name>
    <user_cnt>2</user_cnt>
    <users>
      <user>admin</user>
      <user>guest</user>
    </users>
  </item>
  <item>
    <gid>1001</gid>
    <name>orphan</name>
  </item>
</accounts>
"""

ALERTS_XML = """
<roots>
  <alerts>
    <code>1022</code>
    <seq_num>1</seq_num>
    <level>1</level>
    <msg>Power supply failure</msg>
    <desc>Power supply 1 failed.</desc>
    <time>Mon, Oct 20, 2025 11:04:53 AM</time>
  </alerts>
  <alerts>
    <code>1002</code>
    <seq_num>2</seq_num>
    <level>2</level>
    <msg>Network lost</msg>
    <desc>The network connection is down.</desc>
    <time>Tue, Oct 21, 2025 12:04:53 PM</time>
  </alerts>
</roots>
"""

SHARE_NAMES_JSON = json.dumps(
    {
        "item": [{"share_name": "Public", "path": "/mnt/HD/Public"}],
        "success": True,
    }
)
CLOUD_ACCESS_JSON = json.dumps(
    {
        "enable": "1",
        "token": None,
        "network": {"proxyConnected": True, "key": ""},
        "indexing": 100,
        "activity": "idle",
        "hwTranscoding": False,
    }
)
USB_INFO_JSON = json.dumps({"success": False})
UPTIME_XML = "<root><uptime>1 day 2 hours 3 minutes</uptime></root>"


class _FakeCookie:
    """Minimal cookie morsel for the login response."""

    def __init__(self, value: str) -> None:
        self.value = value


class _FakeHeaders:
    """Minimal response headers with the aiohttp accessors used by login."""

    def __init__(
        self,
        set_cookies: list[str],
        content_type: str = "application/json",
    ) -> None:
        self._set_cookies = set_cookies
        self._content_type = content_type

    def getall(self, name: str, default: list[str] | None = None) -> list[str]:
        return self._set_cookies if name == "Set-Cookie" else (default or [])

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._content_type if name == "Content-Type" else default


class _FakeCookieJar:
    """Record the cookies added to the aiohttp session jar."""

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    def update_cookies(self, cookies: dict[str, str]) -> None:
        self.cookies.update(cookies)

    def filter_cookies(self, url: str) -> dict[str, _FakeCookie]:
        """Return the jar contents for a request, like aiohttp does."""
        del url
        return {key: _FakeCookie(value) for key, value in self.cookies.items()}


class _FakeResponse:
    """Minimal aiohttp response used by the protocol tests."""

    def __init__(
        self,
        status: int = 200,
        text: str = "",
        *,
        cookies: dict | None = None,
        set_cookies: list[str] | None = None,
        history: tuple[_FakeResponse, ...] | None = None,
        content_type: str = "application/json",
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self._text = text
        self.cookies = cookies or {}
        self.headers = _FakeHeaders(set_cookies or [], content_type)
        self.history = history or ()
        self._error = error

    async def text(self) -> str:
        if self._error is not None:
            raise self._error
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeSession:
    """Minimal aiohttp session that records requests in order."""

    def __init__(self, *responses: _FakeResponse, closed: bool = False) -> None:
        self.responses = list(responses)
        self.closed = closed
        self.cookie_jar = _FakeCookieJar()
        self.calls: list[tuple[str, str, dict]] = []

    def _request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._request("DELETE", url, **kwargs)


@pytest.fixture
def client() -> WDNASClient:
    """Return an OS5 client with a fake session."""
    nas = WDNASClient("Admin", "secret", "nas.local:8080")
    nas.session = _FakeSession()
    return nas


def test_client_is_os5_only_and_normalizes_the_username(client):
    """The vendored client has no OS2 branch and lowercases the username."""
    assert client.version == 5
    assert client.username == "admin"
    assert client.host == "nas.local:8080"
    assert client.phpsessid is None
    assert client.session is not None


def test_client_defaults_to_http():
    """Entries created before the HTTPS option keep using HTTP."""
    nas = WDNASClient("Admin", "secret", "nas.local:8543")

    assert nas.use_https is False
    assert nas.scheme == SCHEME
    assert nas._url("login") == "http://nas.local:8543/nas/v1/auth"


def test_client_builds_https_urls_when_requested():
    """The HTTPS option changes every API URL built by the client."""
    nas = WDNASClient("Admin", "secret", "nas.local:8543", use_https=True)

    assert nas.use_https is True
    assert nas.scheme == HTTPS_SCHEME
    assert nas._url("login") == "https://nas.local:8543/nas/v1/auth"
    assert nas._url("system_info") == "https://nas.local:8543/xml/sysinfo.xml"


def test_parse_uptime_text_supports_plural_and_short_forms():
    """The uptime parser accepts the formats returned by OS5 firmware."""
    assert parse_uptime_text("0 day 0 hour 50 minutes") == 3000
    assert parse_uptime_text("2 days 1 hour 1 minute") == 176_460
    assert parse_uptime_text("not an uptime") is None


def test_json_keys_describes_the_body_without_its_values():
    """The log helper summarises JSON shapes without printing secrets."""
    assert _json_keys('{"b": 2, "a": 1}') == "a, b"
    assert _json_keys("{}") == "none"
    assert _json_keys("plain text") == "non-JSON"
    assert _json_keys('["secret"]') == "non-object JSON"


def test_endpoints_cover_every_used_os5_operation():
    """Every operation called by the integration has a fixed OS5 path."""
    assert SCHEME == "http://"
    assert HTTPS_SCHEME == "https://"
    assert set(ENDPOINTS) == {
        "login",
        "logout",
        "system_info",
        "share_names",
        "system_status",
        "network_info",
        "device_info",
        "system_version",
        "accounts",
        "alerts",
        "cloud_access",
        "usb_info",
        "uptime",
    }


def test_request_error_exposes_status_and_message():
    """Exceptions keep the HTTP status used by the coordinator."""
    err = RequestFailedError(403)
    assert err.status_code == 403
    assert str(err) == "Request failed: 403"


async def test_login_posts_the_base64_password_and_stores_the_cookie(client):
    """Login uses the OS5 JSON payload and keeps the session cookie."""
    client.session = _FakeSession(
        _FakeResponse(
            cookies={"PHPSESSID": _FakeCookie("session-id")},
            set_cookies=["PHPSESSID=session-id; Path=/nas/v1/auth; HttpOnly"],
        )
    )

    await client.login()

    assert client.session.cookie_jar.cookies == {"PHPSESSID": "session-id"}
    method, url, kwargs = client.session.calls[0]
    assert method == "POST"
    assert url == "http://nas.local:8080/nas/v1/auth"
    assert kwargs["json"] == {
        "username": "admin",
        "password": base64.b64encode(b"secret").decode("utf-8"),
    }
    assert kwargs["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Host": "nas.local:8080",
        "Origin": "http://nas.local:8080",
        "Referer": "http://nas.local:8080/",
        "X-Requested-With": "XMLHttpRequest",
    }
    assert client.phpsessid == "session-id"


async def test_login_uses_the_https_origin_when_requested():
    """An HTTPS entry sends the matching Origin and Referer headers."""
    client = WDNASClient("Admin", "secret", "nas.local:8543", use_https=True)
    client.session = _FakeSession(
        _FakeResponse(set_cookies=["PHPSESSID=session-id; Path=/nas/v1/auth"])
    )

    await client.login()

    method, url, kwargs = client.session.calls[0]
    assert method == "POST"
    assert url == "https://nas.local:8543/nas/v1/auth"
    assert kwargs["headers"]["Origin"] == "https://nas.local:8543"
    assert kwargs["headers"]["Referer"] == "https://nas.local:8543/"
    assert client.phpsessid == "session-id"


@pytest.mark.parametrize("cookie_name", ["fe97238703cba", "ge41881ed8d9r"])
async def test_login_accepts_each_opaque_os5_cookie(client, cookie_name):
    """Newer OS5 firmware sets opaque cookies instead of PHPSESSID."""
    client.session = _FakeSession(
        _FakeResponse(
            set_cookies=[f"{cookie_name}=opaque-token; Path=/nas/v1/auth; HttpOnly"]
        )
    )

    await client.login()

    assert client.phpsessid == "opaque-token"
    assert client.session.cookie_jar.cookies == {cookie_name: "opaque-token"}


async def test_login_accepts_an_unknown_auth_cookie(client):
    """An unknown non-empty cookie is accepted for future firmware names."""
    client.session = _FakeSession(
        _FakeResponse(set_cookies=["new_cookie=new-token; Path=/nas/v1/auth"])
    )

    await client.login()

    assert client.phpsessid == "new-token"
    assert client.session.cookie_jar.cookies == {"new_cookie": "new-token"}


async def test_login_prefers_phpsessid_and_keeps_all_cookies(client):
    """Known cookie names produce a stable session id when several are set."""
    client.session = _FakeSession(
        _FakeResponse(
            set_cookies=[
                "ge41881ed8d9r=refresh-token; Path=/nas/v1/auth",
                "PHPSESSID=php-session; Path=/nas/v1/auth",
                "fe97238703cba=access-token; Path=/nas/v1/auth",
            ]
        )
    )

    await client.login()

    assert client.phpsessid == "php-session"
    assert client.session.cookie_jar.cookies == {
        "PHPSESSID": "php-session",
        "fe97238703cba": "access-token",
        "ge41881ed8d9r": "refresh-token",
    }


async def test_login_keeps_response_and_jar_cookies(client):
    """Cookies from the response and the jar are merged for the session."""
    client.session = _FakeSession(
        _FakeResponse(set_cookies=["fe97238703cba=access-token; Path=/nas/v1/auth"])
    )
    client.session.cookie_jar.cookies["ge41881ed8d9r"] = "refresh-token"

    await client.login()

    assert client.phpsessid == "access-token"
    assert client.session.cookie_jar.cookies == {
        "fe97238703cba": "access-token",
        "ge41881ed8d9r": "refresh-token",
    }


async def test_login_rejects_a_json_error_even_when_a_cookie_is_set(client):
    """An explicit OS5 error code wins over a cookie on HTTP 200."""
    client.session = _FakeSession(
        _FakeResponse(
            text='{"error": "5", "eula_status": "3"}',
            set_cookies=["fe97238703cba=access-token; Path=/nas/v1/auth"],
        )
    )

    with pytest.raises(AdminSessionBusyError):
        await client.login()


async def test_login_accepts_cookie_names_and_body_keys_without_values(client, caplog):
    """The debug log names cookies and JSON keys but never their values."""
    caplog.set_level("DEBUG", logger="custom_components.mycloud.wdnas")
    client.session = _FakeSession(
        _FakeResponse(
            text='{"eula_status": "1", "booting": false}',
            set_cookies=[
                "fe97238703cba=secret-access; Path=/nas/v1/auth",
                "ge41881ed8d9r=secret-refresh; Path=/nas/v1/auth",
            ],
        )
    )

    await client.login()

    assert "NAS login accepted" in caplog.text
    assert "cookies: fe97238703cba, ge41881ed8d9r" in caplog.text
    assert "body keys: booting, eula_status" in caplog.text
    assert "secret-access" not in caplog.text
    assert "secret-refresh" not in caplog.text


async def test_login_reports_http_errors(client):
    """A non-200 login response is reported with its status."""
    client.session = _FakeSession(_FakeResponse(401))

    with pytest.raises(RequestFailedError) as err:
        await client.login()

    assert err.value.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        '{"error": "ACCOUNT_IN_USE"}',
        "The user account entered is currently in use.",
        "L'account utente inserito è al momento in uso.",
    ],
)
async def test_login_detects_an_active_admin_session(client, body):
    """The single-admin-session response is not reported as bad credentials."""
    client.session = _FakeSession(_FakeResponse(403, text=body))

    with pytest.raises(AdminSessionBusyError) as err:
        await client.login()

    assert isinstance(err.value, InvalidLoginError)


async def test_login_detects_busy_session_without_the_cookie(client):
    """A busy response is recognised even when the NAS answers with 200."""
    client.session = _FakeSession(
        _FakeResponse(text="<html>The account is already in use.</html>")
    )

    with pytest.raises(AdminSessionBusyError):
        await client.login()


@pytest.mark.parametrize(
    "body",
    [
        "You are already logged in from another device.",
        "The account is already connected.",
        "Another administrator session is active.",
        "The session is already active.",
        "The session is already open.",
        "Maximum number of sessions reached.",
        "Session limit exceeded.",
        "logged in from other IP address",
        "max session time exceeded",
        "Sei già connesso con un'altra sessione.",
        "Sessione già attiva.",
        "C'è un'altra sessione aperta.",
    ],
)
async def test_login_detects_expanded_busy_messages(client, body):
    """Localised and firmware-specific busy phrases are still recognised."""
    client.session = _FakeSession(_FakeResponse(403, text=body))

    with pytest.raises(AdminSessionBusyError) as err:
        await client.login()

    assert isinstance(err.value, InvalidLoginError)


async def test_firmware_multilogin_401_is_a_busy_session(client):
    """The OS5 nasAdmin multi-login body is a busy session, not bad credentials."""
    client.session = _FakeSession(
        _FakeResponse(401, text="logged in from other IP address")
    )

    with pytest.raises(AdminSessionBusyError) as err:
        await client.login()

    assert isinstance(err.value, InvalidLoginError)


@pytest.mark.parametrize(
    "body",
    [
        "The account has been blocked after multiple consecutive login attempts.",
        "The user account is locked.",
        "Account locked out.",
        "Too many consecutive login attempts.",
        "Too many failed login attempts.",
        "L'account è stato bloccato.",
        "Troppi tentativi di accesso.",
    ],
)
@pytest.mark.parametrize("status", [200, 403])
async def test_login_detects_a_temporary_account_block(client, body, status):
    """A blocked account or IP is delayed instead of being reported as wrong."""
    client.session = _FakeSession(_FakeResponse(status, text=body))

    with pytest.raises(AccountLockedError) as err:
        await client.login()

    assert isinstance(err.value, InvalidLoginError)


async def test_account_block_wins_over_a_busy_session_hint(client):
    """A body that mentions both phrases is treated as a temporary block."""
    client.session = _FakeSession(
        _FakeResponse(
            403,
            text="The account is blocked because another session is active.",
        )
    )

    with pytest.raises(AccountLockedError):
        await client.login()


@pytest.mark.parametrize(
    "body",
    [
        '{"error": "-3", "eula_status": "0"}',
        '{"error": -3, "eula_status": "0"}',
        '{"error": " -3 "}',
    ],
)
@pytest.mark.parametrize("status", [200, 403])
async def test_login_detects_json_account_locked_code(client, body, status):
    """The OS5 ``-3`` error code is an account lock, not a wrong password."""
    client.session = _FakeSession(_FakeResponse(status, text=body))

    with pytest.raises(AccountLockedError) as err:
        await client.login()

    assert isinstance(err.value, InvalidLoginError)


@pytest.mark.parametrize(
    "body",
    [
        '{"error": "5", "eula_status": "3"}',
        '{"error": 5, "eula_status": "3"}',
    ],
)
@pytest.mark.parametrize("status", [200, 403])
async def test_login_detects_json_busy_code(client, body, status):
    """The OS5 ``5`` error code means another admin session is active."""
    client.session = _FakeSession(_FakeResponse(status, text=body))

    with pytest.raises(AdminSessionBusyError) as err:
        await client.login()

    assert isinstance(err.value, InvalidLoginError)


async def test_json_error_code_wins_over_text_matches(client):
    """A JSON error code is authoritative even if other fields echo words."""
    client.session = _FakeSession(
        _FakeResponse(
            403,
            text='{"error": "5", "eula_status": "account locked"}',
        )
    )

    with pytest.raises(AdminSessionBusyError):
        await client.login()


@pytest.mark.parametrize(
    ("body", "exception"),
    [
        ('{"error": "-1", "eula_status": "1"}', PasswordExpiredError),
        ('{"error": -1, "eula_status": "1"}', PasswordExpiredError),
        ('{"error": "-2", "eula_status": "1"}', NotAdminError),
        ('{"error": -2, "eula_status": "1"}', NotAdminError),
    ],
)
@pytest.mark.parametrize("status", [200, 403])
async def test_login_detects_json_account_state_codes(client, body, exception, status):
    """The OS5 ``-1`` and ``-2`` codes have dedicated login errors."""
    client.session = _FakeSession(_FakeResponse(status, text=body))

    with pytest.raises(exception) as err:
        await client.login()

    assert isinstance(err.value, InvalidLoginError)


@pytest.mark.parametrize(
    "body",
    [
        '["-3"]',
        '{"error": null}',
        '{"error": true}',
        '{"error": ""}',
        '{"error": 5.5}',
        '{"error": "0"}',
    ],
)
async def test_login_ignores_unsupported_json_error_values(client, body):
    """Unknown or non-numeric JSON error values are not misclassified."""
    client.session = _FakeSession(_FakeResponse(403, text=body))

    with pytest.raises(RequestFailedError) as err:
        await client.login()

    assert err.value.status_code == 403


async def test_login_recovers_a_cookie_set_on_a_redirect(client):
    """A cookie set by an intermediate redirect authenticates the session."""
    redirect = _FakeResponse(
        302,
        set_cookies=["PHPSESSID=redirected; Path=/nas/v1/auth; HttpOnly"],
    )
    final = _FakeResponse(history=(redirect,))
    client.session = _FakeSession(final)

    await client.login()

    assert client.phpsessid == "redirected"
    assert client.session.cookie_jar.cookies == {"PHPSESSID": "redirected"}


async def test_login_uses_a_cookie_already_in_the_jar(client):
    """An aiohttp cookie jar entry is accepted when no header repeats it."""
    client.session = _FakeSession(_FakeResponse())
    client.session.cookie_jar.cookies["PHPSESSID"] = "jar-session"

    await client.login()

    assert client.phpsessid == "jar-session"


async def test_login_replaces_an_empty_session_cookie_from_the_jar(client):
    """An empty session cookie header does not hide a valid cookie in the jar."""
    client.session = _FakeSession(
        _FakeResponse(set_cookies=["PHPSESSID=; Path=/nas/v1/auth"])
    )
    client.session.cookie_jar.cookies["PHPSESSID"] = "jar-session"

    await client.login()

    assert client.phpsessid == "jar-session"


async def test_login_ignores_a_malformed_set_cookie_header(client, monkeypatch):
    """A parser error in one cookie header does not abort the login."""
    original_load = http.cookies.SimpleCookie.load

    def broken_load(self, rawdata):
        if rawdata == "broken":
            raise http.cookies.CookieError("invalid cookie")
        return original_load(self, rawdata)

    monkeypatch.setattr(http.cookies.SimpleCookie, "load", broken_load)
    client.session = _FakeSession(
        _FakeResponse(
            set_cookies=["broken", "PHPSESSID=still-valid; Path=/nas/v1/auth"]
        )
    )

    await client.login()

    assert client.phpsessid == "still-valid"


async def test_login_failure_is_logged_without_the_password(client, caplog):
    """The debug log records the response details but never the password."""
    caplog.set_level("DEBUG", logger="custom_components.mycloud.wdnas")
    client.session = _FakeSession(
        _FakeResponse(
            401,
            text="Invalid username or password",
            content_type="text/html",
        )
    )

    with pytest.raises(RequestFailedError):
        await client.login()

    assert "HTTP 401" in caplog.text
    assert "0 redirect(s)" in caplog.text
    assert "text/html" in caplog.text
    assert "cookies: none" in caplog.text
    assert "body keys: non-JSON" in caplog.text
    assert "Invalid username or password" in caplog.text
    assert "secret" not in caplog.text


async def test_login_failure_log_names_cookies_and_json_keys(client, caplog):
    """A rejected login logs cookie names and JSON keys without their values."""
    caplog.set_level("DEBUG", logger="custom_components.mycloud.wdnas")
    client.session = _FakeSession(
        _FakeResponse(
            403,
            text='{"error": "-1", "eula_status": "1"}',
            set_cookies=["ge41881ed8d9r=secret-refresh; Path=/nas/v1/auth"],
        )
    )

    with pytest.raises(PasswordExpiredError):
        await client.login()

    assert "cookies: ge41881ed8d9r" in caplog.text
    assert "body keys: error, eula_status" in caplog.text
    assert "secret-refresh" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        "Invalid username or password",
        "Sign in user with your account",
    ],
)
async def test_login_keeps_bad_credentials_separate_from_busy(client, body):
    """A plain authentication failure is not mistaken for a busy session."""
    client.session = _FakeSession(_FakeResponse(401, text=body))

    with pytest.raises(RequestFailedError) as err:
        await client.login()

    assert not isinstance(err.value, AdminSessionBusyError)


async def test_login_rejects_an_empty_session_cookie(client):
    """A Set-Cookie header with an empty session cookie is not authenticated."""
    client.session = _FakeSession(
        _FakeResponse(set_cookies=["PHPSESSID=; Path=/nas/v1/auth"])
    )

    with pytest.raises(InvalidLoginError):
        await client.login()


async def test_login_requires_the_session_cookie(client):
    """A 200 response without an authentication cookie is not a session."""
    client.session = _FakeSession(_FakeResponse())

    with pytest.raises(InvalidLoginError):
        await client.login()


async def test_login_requires_an_open_session(client):
    """Every request refuses to run without an authenticated session."""
    client.session = None
    with pytest.raises(ValueError):
        await client.login()

    client.session = _FakeSession(closed=True)
    with pytest.raises(ValueError):
        await client.login()


async def test_logout_deletes_the_server_session(client):
    """Logout releases the OS5 admin session and clears the PHP session id."""
    client.phpsessid = "session-id"
    client.session = _FakeSession(_FakeResponse(204))

    await client.logout()

    method, url, kwargs = client.session.calls[0]
    assert method == "DELETE"
    assert url == "http://nas.local:8080/nas/v1/auth"
    assert kwargs["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Host": "nas.local:8080",
    }
    assert client.phpsessid is None


async def test_logout_reports_http_errors(client):
    """A rejected logout is reported and keeps the stored session id."""
    client.phpsessid = "session-id"
    client.session = _FakeSession(_FakeResponse(403))

    with pytest.raises(RequestFailedError) as err:
        await client.logout()

    assert err.value.status_code == 403
    assert client.phpsessid == "session-id"


async def test_logout_requires_an_open_session(client):
    """Logout cannot create a session or log in on its own."""
    client.session = None
    with pytest.raises(ValueError):
        await client.logout()


async def test_get_text_reports_http_errors(client):
    """GET requests surface the NAS status code."""
    client.session = _FakeSession(_FakeResponse(500))

    with pytest.raises(RequestFailedError) as err:
        await client._get_text("system_info")

    assert err.value.status_code == 500


async def test_endpoint_failure_logs_the_endpoint_and_body(client, caplog):
    """A rejected data request identifies the endpoint in the debug log."""
    caplog.set_level("DEBUG", logger="custom_components.mycloud.wdnas")
    client.session = _FakeSession(_FakeResponse(403, text="denied"))

    with pytest.raises(RequestFailedError):
        await client._get_text("system_info")

    assert "NAS system_info request failed: HTTP 403" in caplog.text
    assert "denied" in caplog.text


async def test_endpoint_failure_tolerates_an_unreadable_body(client, caplog):
    """A broken error body does not replace the HTTP status error."""
    caplog.set_level("DEBUG", logger="custom_components.mycloud.wdnas")
    client.session = _FakeSession(
        _FakeResponse(500, error=aiohttp.ClientPayloadError("broken"))
    )

    with pytest.raises(RequestFailedError) as err:
        await client._post_text("system_status", "cmd=resource", form=True)

    assert err.value.status_code == 500
    assert "<unreadable>" in caplog.text


async def test_successful_login_is_logged(client, caplog):
    """A successful login is distinguishable from a rejected one in the log."""
    caplog.set_level("DEBUG", logger="custom_components.mycloud.wdnas")
    client.session = _FakeSession(
        _FakeResponse(
            cookies={"PHPSESSID": _FakeCookie("session-id")},
            set_cookies=["PHPSESSID=session-id; Path=/nas/v1/auth"],
        )
    )

    await client.login()

    assert "NAS login accepted: HTTP 200" in caplog.text
    assert "cookies: PHPSESSID" in caplog.text
    assert "body keys: non-JSON" in caplog.text


async def test_post_text_reports_http_errors(client):
    """POST requests surface the NAS status code."""
    client.session = _FakeSession(_FakeResponse(500))

    with pytest.raises(RequestFailedError) as err:
        await client._post_text("device_info")

    assert err.value.status_code == 500


async def test_system_info_parses_disks_volumes_and_size(client):
    """System info returns the same shape as the upstream client."""
    client.session = _FakeSession(_FakeResponse(text=SYSTEM_INFO_XML))

    data = await client.system_info()

    assert data["disks"] == [
        {
            "id": "1",
            "name": "sda",
            "connected": True,
            "vendor": "WD",
            "model": "WDC WD40EFAX",
            "rev": "83.00A83",
            "sn": "WD-DISK-SN",
            "size": 4000787030016,
            "failed": False,
            "healthy": True,
            "removable": True,
            "over_temp": False,
            "temp": 35,
            "sleep": False,
        },
        {
            "id": "2",
            "name": "sdb",
            "connected": False,
            "vendor": None,
            "model": None,
            "rev": None,
            "sn": None,
            "size": 100,
            "failed": False,
            "healthy": False,
            "removable": False,
            "over_temp": False,
            "temp": 0,
            "sleep": False,
        },
    ]
    assert data["volumes"] == [
        {
            "id": "1",
            "name": "Volume_1",
            "label": "Data",
            "encrypted": False,
            "unlocked": True,
            "mounted": True,
            "size": 3932701929472,
        }
    ]
    assert data["size"] == {
        "total": 3893374910178,
        "used": 515219877888,
        "unused": 3378155032290,
    }
    assert client.session.calls[0][:2] == (
        "GET",
        "http://nas.local:8080/xml/sysinfo.xml",
    )


async def test_system_info_reports_malformed_xml(client):
    """Malformed XML is not silently accepted."""
    client.session = _FakeSession(_FakeResponse(text="<config>"))

    with pytest.raises(ParseError):
        await client.system_info()


async def test_system_info_tolerates_partial_disks_and_volumes(client):
    """Missing IDs and unusual flags do not discard the whole payload."""
    xml = """
    <config>
      <disks>
        <disk>
          <name>sda</name>
          <connected>true</connected>
          <healthy>yes</healthy>
          <failed>no</failed>
          <removable>2</removable>
          <over_temp>maybe</over_temp>
          <temp>not-a-number</temp>
          <sleep>ON</sleep>
        </disk>
      </disks>
      <vols>
        <vol>
          <name>Volume_1</name>
          <mounted>1</mounted>
          <size>42</size>
        </vol>
      </vols>
      <total_size>42</total_size>
    </config>
    """
    client.session = _FakeSession(_FakeResponse(text=xml))

    data = await client.system_info()

    assert data["disks"] == [
        {
            "id": None,
            "name": "sda",
            "connected": True,
            "vendor": None,
            "model": None,
            "rev": None,
            "sn": None,
            "size": 0,
            "failed": False,
            "healthy": True,
            "removable": True,
            "over_temp": False,
            "temp": 0,
            "sleep": True,
        }
    ]
    assert data["volumes"] == [
        {
            "id": None,
            "name": "Volume_1",
            "label": None,
            "encrypted": False,
            "unlocked": False,
            "mounted": True,
            "size": 42,
        }
    ]
    assert data["size"] == {"total": 42, "used": 0, "unused": 0}


async def test_share_names_returns_the_share_list(client):
    """The share endpoint returns the item list."""
    client.session = _FakeSession(_FakeResponse(text=SHARE_NAMES_JSON))

    shares = await client.share_names()

    assert shares == [{"share_name": "Public", "path": "/mnt/HD/Public"}]
    method, url, kwargs = client.session.calls[0]
    assert (method, url) == (
        "POST",
        "http://nas.local:8080/web/get_share_name_list.php",
    )
    assert kwargs["data"] is None
    assert kwargs["headers"] == {"Host": "nas.local:8080"}


async def test_share_names_rejects_unsuccessful_responses(client):
    """A success=false payload is reported as a failed request."""
    client.session = _FakeSession(_FakeResponse(text='{"success": false}'))

    with pytest.raises(RequestFailedError) as err:
        await client.share_names()

    assert err.value.status_code == "Share list unavailable"


async def test_share_names_tolerates_a_missing_item_list(client):
    """A successful response without items yields an empty share list."""
    client.session = _FakeSession(_FakeResponse(text='{"success": true}'))

    assert await client.share_names() == []


async def test_system_status_parses_cpu_and_memory(client):
    """System status strips the CPU percent sign and keeps raw memory fields."""
    client.session = _FakeSession(_FakeResponse(text=SYSTEM_STATUS_XML))

    data = await client.system_status()

    assert data == {
        "cpu": 12,
        "memory": {
            "total": 1000,
            "unused": 400,
            "simple": "400 / 1000 MB",
        },
    }
    assert client.session.calls[0][2]["data"] == "cmd=resource"


async def test_system_status_defaults_missing_fields(client):
    """A status response without optional values does not crash."""
    client.session = _FakeSession(_FakeResponse(text="<root/>"))

    data = await client.system_status()

    assert data == {
        "cpu": 0,
        "memory": {"total": 0, "unused": 0, "simple": None},
    }

    client.session = _FakeSession(
        _FakeResponse(text="<root><cpu></cpu><mem_total></mem_total></root>")
    )
    assert await client.system_status() == {
        "cpu": 0,
        "memory": {"total": 0, "unused": 0, "simple": None},
    }


async def test_network_info_skips_unused_interfaces(client):
    """Only interfaces with a real MAC address are returned."""
    client.session = _FakeSession(_FakeResponse(text=NETWORK_XML))

    data = await client.network_info()

    assert data == {
        "00:11:22:33:44:55": {
            "speed": "1000",
            "dhcp_enable": False,
            "dns_manual": True,
            "ip": "192.168.10.41",
            "netmask": "255.255.255.0",
            "gateway": "192.168.10.1",
            "lan_speed": "1000",
            "lan_enabled": True,
            "dns1": "192.168.10.1",
            "dns2": "",
            "dns3": "",
        }
    }


async def test_network_info_tolerates_a_missing_mac(client):
    """A malformed interface without a MAC is skipped."""
    client.session = _FakeSession(_FakeResponse(text="<info><lan/></info>"))

    assert await client.network_info() == {}


async def test_device_info_parses_the_identity_fields(client):
    """Device info returns serial number, name and description."""
    client.session = _FakeSession(_FakeResponse(text=DEVICE_INFO_XML))

    data = await client.device_info()

    assert data == {
        "serial_number": "WUBM31111111",
        "name": "MyCloudEX2Ultra",
        "description": "2-Bay NAS",
    }
    assert client.session.calls[0][2]["data"] == "cmd=cgi_get_device_info"


async def test_system_version_parses_firmware_and_oled(client):
    """System version strips the OLED line break."""
    client.session = _FakeSession(_FakeResponse(text=SYSTEM_VERSION_XML))

    data = await client.system_version()

    assert data == {"firmware": "5.31.108", "oled": "1.06"}
    assert client.session.calls[0][2]["data"] == "cmd=get_firm_v_xml"


async def test_system_version_allows_a_missing_oled(client):
    """Firmware without an OLED element is still usable."""
    client.session = _FakeSession(
        _FakeResponse(text="<version><fw>5.31.108</fw></version>")
    )

    assert await client.system_version() == {"firmware": "5.31.108", "oled": None}


async def test_accounts_separates_users_from_groups(client):
    """Users and groups are parsed from the same item list without mixing."""
    client.session = _FakeSession(_FakeResponse(text=ACCOUNTS_XML))

    data = await client.accounts()

    assert data["users"] == [
        {
            "uid": "500",
            "name": "admin",
            "email": "admin@example.com",
            "pwd": True,
            "gid": "1000",
            "first_name": "Admin",
            "last_name": ["One", "Two"],
            "hint": "hint",
        }
    ]
    assert data["groups"] == {
        "1000": {
            "name": "administrators",
            "user_cnt": "2",
            "users": ["admin", "guest"],
        }
    }


async def test_alerts_return_the_count_and_entries(client):
    """Alerts preserve order and expose the documented fields."""
    client.session = _FakeSession(_FakeResponse(text=ALERTS_XML))

    count, alerts = await client.alerts()

    assert count == 2
    assert alerts[0] == {
        "code": "1022",
        "seq_num": "1",
        "level": "1",
        "msg": "Power supply failure",
        "desc": "Power supply 1 failed.",
        "time": "Mon, Oct 20, 2025 11:04:53 AM",
    }
    assert alerts[1]["code"] == "1002"


async def test_alerts_returns_an_empty_list(client):
    """A NAS with no alerts returns a zero count and an empty list."""
    client.session = _FakeSession(_FakeResponse(text="<roots/>"))

    assert await client.alerts() == (0, [])


async def test_cloud_access_returns_the_json_payload(client):
    """The cloud-access payload is returned unchanged."""
    client.session = _FakeSession(_FakeResponse(text=CLOUD_ACCESS_JSON))

    data = await client.cloud_access()

    assert data["enable"] == "1"
    assert data["network"]["proxyConnected"] is True
    assert client.session.calls[0][2]["data"] == "cmd=getCloudAccess"


async def test_usb_info_returns_the_json_payload(client):
    """The USB payload is returned unchanged."""
    client.session = _FakeSession(_FakeResponse(text=USB_INFO_JSON))

    assert await client.usb_info() == {"success": False}


async def test_uptime_parses_the_status_response(client):
    """The dedicated uptime command returns seconds."""
    client.session = _FakeSession(_FakeResponse(text=UPTIME_XML))

    assert await client.uptime() == 93_780
    assert client.session.calls[0][2]["data"] == "cmd=cgi_get_uptime"


async def test_uptime_rejects_a_missing_element(client):
    """A response without an uptime element is a failed request."""
    client.session = _FakeSession(_FakeResponse(text="<root/>"))

    with pytest.raises(RequestFailedError) as err:
        await client.uptime()

    assert str(err.value) == "Request failed: Uptime not found in XML response"


async def test_uptime_rejects_an_unknown_format(client):
    """An uptime element with an unknown format is a failed request."""
    client.session = _FakeSession(
        _FakeResponse(text="<root><uptime>soon</uptime></root>")
    )

    with pytest.raises(RequestFailedError) as err:
        await client.uptime()

    assert str(err.value) == "Request failed: Unexpected uptime format: soon"


async def test_transport_errors_propagate_to_the_caller(client):
    """aiohttp errors are not wrapped, so the coordinator can classify them."""
    client.session = _FakeSession(_FakeResponse(error=aiohttp.ClientError("offline")))

    with pytest.raises(aiohttp.ClientError):
        await client.system_info()
