"""Tests for the vendored OS5 WD NAS protocol client."""

from __future__ import annotations

import base64
import json
from xml.etree.ElementTree import ParseError

import aiohttp
import pytest

from custom_components.mycloud.wdnas import (
    ENDPOINTS,
    SCHEME,
    InvalidLoginError,
    RequestFailedError,
    WDNASClient,
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
    """Minimal response headers with the aiohttp getall method."""

    def __init__(self, set_cookies: list[str]) -> None:
        self._set_cookies = set_cookies

    def getall(self, name: str, default: list[str] | None = None) -> list[str]:
        return self._set_cookies if name == "Set-Cookie" else (default or [])


class _FakeCookieJar:
    """Record the cookies added to the aiohttp session jar."""

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}

    def update_cookies(self, cookies: dict[str, str]) -> None:
        self.cookies.update(cookies)


class _FakeResponse:
    """Minimal aiohttp response used by the protocol tests."""

    def __init__(
        self,
        status: int = 200,
        text: str = "",
        *,
        cookies: dict | None = None,
        set_cookies: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self._text = text
        self.cookies = cookies or {}
        self.headers = _FakeHeaders(set_cookies or [])
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


def test_parse_uptime_text_supports_plural_and_short_forms():
    """The uptime parser accepts the formats returned by OS5 firmware."""
    assert parse_uptime_text("0 day 0 hour 50 minutes") == 3000
    assert parse_uptime_text("2 days 1 hour 1 minute") == 176_460
    assert parse_uptime_text("not an uptime") is None


def test_endpoints_cover_every_used_os5_operation():
    """Every operation called by the integration has a fixed OS5 path."""
    assert SCHEME == "http://"
    assert set(ENDPOINTS) == {
        "login",
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
    """Login uses the OS5 JSON payload and keeps the PHP session id."""
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
    }
    assert client.phpsessid == "session-id"


async def test_login_reports_http_errors(client):
    """A non-200 login response is reported with its status."""
    client.session = _FakeSession(_FakeResponse(401))

    with pytest.raises(RequestFailedError) as err:
        await client.login()

    assert err.value.status_code == 401


async def test_login_requires_the_session_cookie(client):
    """A 200 response without PHPSESSID is not an authenticated session."""
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


async def test_get_text_reports_http_errors(client):
    """GET requests surface the NAS status code."""
    client.session = _FakeSession(_FakeResponse(500))

    with pytest.raises(RequestFailedError) as err:
        await client._get_text("system_info")

    assert err.value.status_code == 500


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
