"""Vendored OS5-only client for the WD My Cloud HTTP API.

This module is based on ``wdnas-client`` 0.9.4 by Joakim Sørensen
(@ludeeus) and contributors, distributed under the MIT License.  The OS2
code paths, the OS2-only ``latest_version`` endpoint and the version
selector were removed.  The integration owns this copy and only sends
requests to the host configured by the user.

See ``THIRD_PARTY_NOTICES.md`` in this directory for the upstream
provenance and the full MIT license text.
"""

from __future__ import annotations

import base64
import http.cookies
import json
import logging
import re
from typing import Any, cast
from xml.etree.ElementTree import Element, ParseError, fromstring

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

SCHEME = "http://"
HTTPS_SCHEME = "https://"

ENDPOINTS = {
    "login": "/nas/v1/auth",
    "logout": "/nas/v1/auth",
    "system_info": "/xml/sysinfo.xml",
    "share_names": "/web/get_share_name_list.php",
    "system_status": "/cgi-bin/status_mgr.cgi",
    "network_info": "/cgi-bin/network_mgr.cgi?cmd=cgi_get_lan_xml",
    "device_info": "/cgi-bin/system_mgr.cgi",
    "system_version": "/cgi-bin/system_mgr.cgi",
    "accounts": "/xml/account.xml",
    "alerts": "/cgi-bin/system_mgr.cgi",
    "cloud_access": "/web/restSDK/cloudAccess.php",
    "usb_info": "/web/get_usb_info.php",
    "uptime": "/cgi-bin/status_mgr.cgi",
}

_UPTIME_RE = re.compile(
    r"(\d+)\s*days?\s*(\d+)\s*hour[s]?\s*(\d+)\s*minute[s]?", re.IGNORECASE
)
_UPTIME_ELEMENT_RE = re.compile(r"<uptime>(.*?)</uptime>", re.IGNORECASE | re.DOTALL)

# Older OS5 firmware authenticates with the PHP session id. Newer firmware
# sets two opaque cookies instead; both names are used by the nasAdmin
# ``validateToken`` and ``logoutHandler`` functions. The order is only a
# preference, login accepts any non-empty cookie the NAS sets.
_PREFERRED_SESSION_COOKIES = (
    "PHPSESSID",
    "fe97238703cba",
    "ge41881ed8d9r",
)

# OS5 returns this instead of a plain 401 when the single admin session is
# already active. The firmware localizes the message, so match a few stable
# fragments rather than the full sentence.
_LOGIN_BUSY_RE = re.compile(
    r"account_in_use"
    r"|\bin use\b"
    r"|\bin uso\b"
    r"|\balready (?:logged|signed) in\b"
    r"|\balready connected\b"
    r"|\banother (?:admin(?:istrator)? )?session\b"
    r"|\bsession (?:is )?already (?:active|open)\b"
    r"|\bmaximum (?:number of )?sessions?\b"
    r"|\bsession limit\b"
    # Firmware nasAdmin answers a second admin login with a 401 and this
    # exact body. It is the same single-session limit, not a wrong password.
    r"|\blogged in from (?:an? )?(?:other|another|different) "
    r"(?:ip(?: address)?|device|client|host)\b"
    r"|\bmax(?:imum)? session time exceeded\b"
    r"|\bgià connesso\b"
    r"|\bsessione già attiva\b"
    r"|\bun'altra sessione\b",
    re.IGNORECASE,
)

# Repeated failed logins make the firmware block the account or the client IP
# for a while. This is not a wrong password either, so it gets its own error.
_LOGIN_LOCKED_RE = re.compile(
    r"\bblocked\b"
    r"|\blocked out\b"
    r"|\baccount (?:is )?locked\b"
    r"|\btoo many (?:consecutive |failed )?(?:login )?attempts\b"
    r"|\bbloccat[oaie]\b"
    r"|\btroppi tentativi\b",
    re.IGNORECASE,
)


class InvalidLoginError(Exception):
    """Raised when the NAS rejects the credentials or the login cookies."""


class AdminSessionBusyError(InvalidLoginError):
    """Raised when the NAS reports that another admin session is active.

    OS5 accepts a single admin session. This is not a credential problem, so
    callers should retry later instead of asking the user for the password.
    """


class AccountLockedError(InvalidLoginError):
    """Raised when the NAS temporarily blocks the account or the client IP.

    The firmware blocks repeated failed logins for a while. Retrying with the
    correct password during the block keeps the lock active, so callers must
    wait instead of asking for the password again.
    """


class PasswordExpiredError(InvalidLoginError):
    """Raised when the NAS reports that the admin password has expired."""


class NotAdminError(InvalidLoginError):
    """Raised when the NAS account is not an administrator."""


class RequestFailedError(Exception):
    """Raised when the NAS returns an unexpected response."""

    def __init__(self, status_code: int | str) -> None:
        """Initialize the error with the HTTP status or a description."""
        self.status_code = status_code
        super().__init__(f"Request failed: {status_code}")


def parse_uptime_text(text: str) -> int | None:
    """Parse the ``<uptime>`` text returned by the NAS into seconds."""
    match = _UPTIME_RE.search(text)
    if match is None:
        return None
    days, hours, minutes = (int(part) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60


def _is_admin_session_busy(body: str) -> bool:
    """Return True when a login response reports an active admin session."""
    return _LOGIN_BUSY_RE.search(body) is not None


def _is_account_locked(body: str) -> bool:
    """Return True when a login response reports a temporary account block."""
    return _LOGIN_LOCKED_RE.search(body) is not None


def _login_error_code(body: str) -> str | None:
    """Return the numeric ``error`` field from a JSON login response.

    OS5 normally answers a rejected login with
    ``{"error": "-3", "eula_status": "..."}`` instead of a textual message.
    The field is documented as a string but some firmware revisions send a
    number, so both forms are accepted.
    """
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    code = payload.get("error")
    if isinstance(code, bool) or not isinstance(code, (int, str)):
        return None
    return str(code).strip() or None


def _login_error(body: str) -> InvalidLoginError | None:
    """Return the specific login error described by a NAS response."""
    code = _login_error_code(body)
    if code == "-3":
        return AccountLockedError(_login_message(body))
    if code == "5":
        return AdminSessionBusyError(_login_message(body))
    if code == "-1":
        return PasswordExpiredError(_login_message(body))
    if code == "-2":
        return NotAdminError(_login_message(body))
    if _is_account_locked(body):
        return AccountLockedError(_login_message(body))
    if _is_admin_session_busy(body):
        return AdminSessionBusyError(_login_message(body))
    return None


def _login_message(body: str) -> str:
    """Return a short single-line description of the login response."""
    message = " ".join(body.split())[:200]
    return message or "The NAS rejected the login"


def _short_body(body: str) -> str:
    """Return a compact body for a debug log, without changing its meaning."""
    return " ".join(body.split())[:500]


def _response_cookies(
    response: aiohttp.ClientResponse,
) -> http.cookies.SimpleCookie:
    """Return every cookie set by a response and its redirect chain.

    A malformed ``Set-Cookie`` header is ignored instead of failing the whole
    login.
    """
    cookies = http.cookies.SimpleCookie()
    for item in (*response.history, response):
        for header in item.headers.getall("Set-Cookie", []):
            try:
                cookies.load(header)
            except http.cookies.CookieError:
                _LOGGER.debug("Ignoring a malformed NAS Set-Cookie header")
    return cookies


def _session_cookie(
    cookies: http.cookies.SimpleCookie,
) -> tuple[str, str] | None:
    """Return the first non-empty authentication cookie, if any.

    OS5 firmware may use ``PHPSESSID`` or two opaque cookie names. Known names
    are preferred for a stable choice, then any other cookie is accepted so a
    future firmware rename does not break login again.
    """
    for name in _PREFERRED_SESSION_COOKIES:
        morsel = cookies.get(name)
        if morsel is not None and morsel.value:
            return name, morsel.value
    for name in sorted(cookies):
        morsel = cookies[name]
        if morsel.value:
            return name, morsel.value
    return None


def _json_keys(body: str) -> str:
    """Return the JSON object keys for a debug log, never the values."""
    try:
        payload = json.loads(body)
    except ValueError:
        return "non-JSON"
    if not isinstance(payload, dict):
        return "non-object JSON"
    return ", ".join(sorted(payload)) or "none"


def _as_bool(value: str | None) -> bool:
    """Convert a NAS flag to a boolean without failing the whole payload.

    OS5 normally returns ``0`` or ``1``, but partially initialized disks can
    return an empty element and some firmware revisions use textual flags.
    """
    if value is None:
        return False
    normalized = value.strip().casefold()
    if normalized in ("", "0", "false", "no", "off"):
        return False
    if normalized in ("1", "true", "yes", "on"):
        return True
    try:
        return int(normalized) != 0
    except ValueError:
        _LOGGER.debug("Unexpected boolean value from the NAS: %r", value)
        return False


def _as_int(value: str | None, default: int = 0) -> int:
    """Convert a NAS numeric field, falling back to a default."""
    if value is None:
        return default
    normalized = value.strip()
    if not normalized:
        return default
    try:
        return int(normalized)
    except ValueError:
        _LOGGER.debug("Unexpected integer value from the NAS: %r", value)
        return default


def _field_text(root: Element, *names: str) -> str | None:
    """Return the first non-empty leaf text matching one of the tag names.

    The status endpoint is normally a flat XML document, but some firmware
    revisions nest the memory fields inside a container. Matching by tag name
    instead of a fixed path keeps the parser tolerant of both shapes.
    """
    wanted = set(names)
    for element in root.iter():
        if len(element):
            continue
        tag = element.tag.rsplit("}", 1)[-1].strip().lower()
        if tag not in wanted:
            continue
        text = (element.text or "").strip()
        if text:
            return text
    return None


def _optional_int(value: str | None) -> int | None:
    """Convert an optional NAS numeric field, returning None when absent."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        _LOGGER.debug("Unexpected integer value from the NAS: %r", value)
        return None


def _parse_xml(text: str) -> Element:
    """Parse XML returned by the configured NAS.

    The data comes from the local NAS and is never rendered or executed.
    Only numeric fields and fixed node names are read.  See SECURITY.md.
    """
    return fromstring(text)  # noqa: S314


class WDNASClient:
    """Async OS5 client for the WD My Cloud HTTP API."""

    # Kept for callers that used the upstream version attribute.  This copy
    # only implements the OS5 protocol.
    version = 5

    def __init__(
        self,
        username: str,
        password: str,
        host: str,
        *,
        use_https: bool = False,
    ) -> None:
        """Initialize an OS5 client for the configured NAS."""
        self.host = host
        self.username = username.lower()
        self.password = password
        self.use_https = use_https
        self.scheme = HTTPS_SCHEME if use_https else SCHEME
        self.session: aiohttp.ClientSession | None = None
        # Kept for compatibility with the vendored upstream API. It holds the
        # value of the cookie that authenticated the current session, which is
        # not necessarily PHPSESSID on newer OS5 firmware.
        self.phpsessid: str | None = None

    def _url(self, endpoint: str) -> str:
        """Build an API URL from the configured host and a fixed path."""
        return f"{self.scheme}{self.host}{ENDPOINTS[endpoint]}"

    def _require_session(self) -> aiohttp.ClientSession:
        """Return the authenticated session or raise a clear error."""
        if self.session is None or self.session.closed:
            raise ValueError("An authenticated NAS session is required")
        return self.session

    def _headers(self, *, form: bool = False, origin: bool = True) -> dict[str, str]:
        """Return the headers used by the NAS API.

        OS5 binds the authentication token to the origin of the login
        request. Every authenticated request must repeat the same ``Origin``
        and ``Referer``, otherwise ``nasAdmin`` rejects it with
        ``request origin != token origin`` even though the cookies are valid.

        The legacy CGI endpoints under ``/cgi-bin/`` (used by power actions)
        predate CORS and reject these headers, so callers can disable them
        with ``origin=False``.
        """
        headers = {"Host": self.host}
        if origin:
            origin_url = f"{self.scheme}{self.host}"
            headers["Origin"] = origin_url
            headers["Referer"] = f"{origin_url}/"
            headers["X-Requested-With"] = "XMLHttpRequest"
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        return headers

    async def _raise_for_status(
        self, endpoint: str, response: aiohttp.ClientResponse
    ) -> None:
        """Log a rejected request and raise its status code."""
        if response.status == 200:
            return
        try:
            body = await response.text()
        except (aiohttp.ClientError, TimeoutError, OSError, UnicodeDecodeError):
            body = "<unreadable>"
        _LOGGER.debug(
            "NAS %s request failed: HTTP %s, body: %s",
            endpoint,
            response.status,
            _short_body(body),
        )
        raise RequestFailedError(response.status)

    async def _get_text(self, endpoint: str, *, origin: bool = True) -> str:
        """Perform an authenticated GET and return the response body.

        Legacy CGI endpoints under ``/cgi-bin/`` predate CORS and reject the
        ``Origin``/``Referer``/``X-Requested-With`` headers, so callers can
        disable them with ``origin=False``.
        """
        session = self._require_session()
        async with session.get(
            self._url(endpoint), headers=self._headers(origin=origin)
        ) as response:
            await self._raise_for_status(endpoint, response)
            return await response.text()

    async def _post_text(
        self,
        endpoint: str,
        data: str | None = None,
        *,
        form: bool = False,
        origin: bool = True,
    ) -> str:
        """Perform an authenticated POST and return the response body.

        Legacy CGI endpoints under ``/cgi-bin/`` predate CORS and reject the
        ``Origin``/``Referer``/``X-Requested-With`` headers, so callers can
        disable them with ``origin=False``.
        """
        session = self._require_session()
        async with session.post(
            self._url(endpoint),
            data=data,
            headers=self._headers(form=form, origin=origin),
        ) as response:
            await self._raise_for_status(endpoint, response)
            return await response.text()

    async def login(self) -> None:
        """Authenticate against the OS5 API and keep the session cookie."""
        session = self._require_session()
        encoded_password = base64.b64encode(self.password.encode("utf-8")).decode(
            "utf-8"
        )
        # Match the NAS web interface. Some firmware revisions validate the
        # request origin or reject a request that does not look like the XHR
        # sent by the dashboard.
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"

        async with session.post(
            self._url("login"),
            json={"username": self.username, "password": encoded_password},
            headers=headers,
        ) as response:
            body = await response.text()
            error = _login_error(body)
            # A JSON error code is authoritative even on HTTP 200. The text
            # heuristics are only used when no cookie authenticates the
            # session, so a success body cannot be misread as a busy session.
            if error is not None and (
                response.status != 200 or _login_error_code(body) is not None
            ):
                self._log_login_failure(response, body)
                raise error
            if response.status != 200:
                self._log_login_failure(response, body)
                raise RequestFailedError(response.status)

            cookies = self._collect_login_cookies(response)
            session_cookie = _session_cookie(cookies)
            if session_cookie is None:
                self._log_login_failure(response, body)
                if error is not None:
                    raise error
                raise InvalidLoginError(
                    "Invalid Username/Password or missing session cookie"
                )

            # The NAS scopes some cookies to the login path. Re-add every
            # collected cookie with no path so the data endpoints receive it.
            for key, morsel in cookies.items():
                if morsel.value:
                    session.cookie_jar.update_cookies({key: morsel.value})
            self.phpsessid = session_cookie[1]
            _LOGGER.debug(
                "NAS login accepted: HTTP %s, %s redirect(s), cookies: %s, "
                "body keys: %s",
                response.status,
                len(response.history),
                ", ".join(sorted(cookies)) or "none",
                _json_keys(body),
            )

    def _collect_login_cookies(
        self, response: aiohttp.ClientResponse
    ) -> http.cookies.SimpleCookie:
        """Return the login cookies from the response, redirects and jar.

        Some firmware answers the login POST with a redirect and sets the
        authentication cookie on that intermediate response. OS5 may use
        ``PHPSESSID`` or two opaque cookie names. Non-empty response cookies
        take precedence over the jar; the jar fills in values that the response
        did not repeat.
        """
        cookies = _response_cookies(response)
        session = self._require_session()
        for key, morsel in session.cookie_jar.filter_cookies(
            URL(self._url("login"))
        ).items():
            if key not in cookies or not cookies[key].value:
                cookies[key] = morsel.value
        return cookies

    def _log_login_failure(self, response: aiohttp.ClientResponse, body: str) -> None:
        """Log a rejected login without logging the password or cookie values."""
        cookies = _response_cookies(response)
        _LOGGER.debug(
            "NAS login failed: HTTP %s, %s redirect(s), content-type %s, "
            "cookies: %s, body keys: %s, body: %s",
            response.status,
            len(response.history),
            response.headers.get("Content-Type", "unknown"),
            ", ".join(sorted(cookies)) or "none",
            _json_keys(body),
            _short_body(body),
        )

    async def logout(self) -> None:
        """End the NAS admin session without closing the local session.

        OS5 firmware allows only one admin session at a time. The WD web
        interface releases it with ``DELETE /nas/v1/auth``; calling this before
        a new login lets the integration reconfigure or re-authenticate
        without waiting for the old session to expire.
        """
        session = self._require_session()
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        async with session.delete(
            self._url("logout"),
            headers=headers,
        ) as response:
            if not 200 <= response.status < 300:
                raise RequestFailedError(response.status)
        self.phpsessid = None

    async def system_info(self) -> dict[str, Any]:
        """Return disks, volumes and the total storage size."""
        root = _parse_xml(await self._get_text("system_info"))
        data: dict[str, Any] = {"disks": [], "volumes": [], "size": {}}

        for disk in root.iter("disk"):
            data["disks"].append(
                {
                    "id": disk.attrib.get("id"),
                    "name": disk.findtext("name"),
                    "connected": _as_bool(disk.findtext("connected")),
                    "vendor": disk.findtext("vendor"),
                    "model": disk.findtext("model"),
                    "rev": disk.findtext("rev"),
                    "sn": disk.findtext("sn"),
                    "size": _as_int(disk.findtext("size")),
                    "failed": _as_bool(disk.findtext("failed")),
                    "healthy": _as_bool(disk.findtext("healthy")),
                    "removable": _as_bool(disk.findtext("removable")),
                    "over_temp": _as_bool(disk.findtext("over_temp")),
                    "temp": _as_int(disk.findtext("temp")),
                    "sleep": _as_bool(disk.findtext("sleep")),
                }
            )

        for volume in root.iter("vol"):
            data["volumes"].append(
                {
                    "id": volume.attrib.get("id"),
                    "name": volume.findtext("name"),
                    "label": volume.findtext("label"),
                    "encrypted": _as_bool(volume.findtext("encrypted")),
                    "unlocked": _as_bool(volume.findtext("unlocked")),
                    "mounted": _as_bool(volume.findtext("mounted")),
                    "size": _as_int(volume.findtext("size")),
                }
            )

        data["size"] = {
            "total": _as_int(root.findtext(".//total_size")),
            "used": _as_int(root.findtext(".//total_used_size")),
            "unused": _as_int(root.findtext(".//total_unused_size")),
        }
        return data

    async def share_names(self) -> list[dict[str, Any]]:
        """Return the shares configured on the NAS."""
        payload = json.loads(await self._post_text("share_names"))
        if not payload.get("success"):
            raise RequestFailedError("Share list unavailable")
        items = payload.get("item")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    async def system_status(self) -> dict[str, Any]:
        """Return CPU and memory usage.

        The status endpoint is a legacy CGI under ``/cgi-bin/``.  It sends the
        same ``Origin``/``Referer``/``X-Requested-With`` headers as the login;
        otherwise nasAdmin rejects the request with ``request origin != token
        origin`` (HTTP 403).
        """
        root = _parse_xml(
            await self._post_text(
                "system_status", "cmd=resource", form=True, origin=True
            )
        )
        cpu = root.findtext(".//cpu")
        memory: dict[str, Any] = {
            "total": _as_int(_field_text(root, "mem_total", "memtotal")),
            "unused": _as_int(_field_text(root, "mem_free", "memfree")),
            "simple": _field_text(root, "mem2_total", "mem2total"),
            "available": _optional_int(
                _field_text(
                    root,
                    "mem_available",
                    "memavailable",
                    "mem_avail",
                    "memavail",
                )
            ),
            "cached": _optional_int(
                _field_text(root, "mem_cached", "memcached", "cached")
            ),
            "buffers": _optional_int(
                _field_text(root, "mem_buffers", "membuffers", "buffers")
            ),
            "swap_total": _optional_int(_field_text(root, "swap_total", "swaptotal")),
            "swap_free": _optional_int(_field_text(root, "swap_free", "swapfree")),
        }
        if memory["swap_total"] is not None and memory["swap_free"] is not None:
            memory["swap_used"] = max(memory["swap_total"] - memory["swap_free"], 0)
        else:
            memory["swap_used"] = None
        return {
            "memory": memory,
            "cpu": _as_int(cpu.strip("%")) if cpu is not None else 0,
        }

    async def network_info(self) -> dict[str, Any]:
        """Return network interface information keyed by MAC address."""
        root = _parse_xml(await self._get_text("network_info"))
        data: dict[str, Any] = {}
        for lan in root.iter("lan"):
            mac = lan.findtext("mac")
            if mac is None or mac == "No found.":
                continue
            data[mac] = {
                "speed": lan.findtext("speed"),
                "dhcp_enable": _as_bool(lan.findtext("dhcp_enable")),
                "dns_manual": _as_bool(lan.findtext("dns_manual")),
                "ip": lan.findtext("ip"),
                "netmask": lan.findtext("netmask"),
                "gateway": lan.findtext("gateway"),
                "lan_speed": lan.findtext("lan_speed"),
                "lan_enabled": _as_bool(lan.findtext("lan_status")),
                "dns1": lan.findtext("dns1"),
                "dns2": lan.findtext("dns2"),
                "dns3": lan.findtext("dns3"),
            }
        return data

    async def device_info(self) -> dict[str, str | None]:
        """Return the NAS serial number, name and description."""
        root = _parse_xml(
            await self._post_text("device_info", "cmd=cgi_get_device_info", form=True)
        )
        return {
            "serial_number": root.findtext(".//serial_number"),
            "name": root.findtext(".//name"),
            "description": root.findtext(".//description"),
        }

    async def system_version(self) -> dict[str, str | None]:
        """Return the firmware version and the OLED text."""
        root = _parse_xml(
            await self._post_text("system_version", "cmd=get_firm_v_xml", form=True)
        )
        oled = root.findtext(".//oled")
        return {
            "firmware": root.findtext(".//fw"),
            "oled": oled.strip("\n") if oled is not None else None,
        }

    async def accounts(self) -> dict[str, Any]:
        """Return user and group information."""
        root = _parse_xml(await self._post_text("accounts"))
        data: dict[str, Any] = {"users": [], "groups": {}}
        items = list(root.iter("item"))

        for user in items:
            uid = user.findtext("uid")
            if uid is None:
                continue
            last_names = [node.text for node in user.iter("last_name")]
            data["users"].append(
                {
                    "uid": uid,
                    "name": user.findtext("name"),
                    "email": user.findtext("email"),
                    "pwd": _as_bool(user.findtext("pwd")),
                    "gid": user.findtext("gid"),
                    "first_name": user.findtext("first_name"),
                    "last_name": last_names,
                    "hint": user.findtext("hint"),
                }
            )

        for group in items:
            gid = group.findtext("gid")
            if gid is None or group.findtext("uid") is not None:
                continue
            if group.find("users") is None and group.find("user_cnt") is None:
                continue
            data["groups"][gid] = {
                "name": group.findtext("name"),
                "user_cnt": group.findtext("user_cnt"),
                "users": [node.text for node in group.iter("user")],
            }

        return data

    async def alerts(self) -> tuple[int, list[dict[str, Any]]]:
        """Return the alert count and the alert entries."""
        root = _parse_xml(
            await self._post_text("alerts", "cmd=cgi_get_alert", form=True)
        )
        alerts = [
            {
                "code": entry.findtext("code"),
                "seq_num": entry.findtext("seq_num"),
                "level": entry.findtext("level"),
                "msg": entry.findtext("msg"),
                "desc": entry.findtext("desc"),
                "time": entry.findtext("time"),
            }
            for entry in root.iter("alerts")
        ]
        return len(alerts), alerts

    async def cloud_access(self) -> dict[str, Any]:
        """Return the cloud-access payload."""
        payload = await self._post_text("cloud_access", "cmd=getCloudAccess", form=True)
        return cast(dict[str, Any], json.loads(payload))

    async def usb_info(self) -> dict[str, Any]:
        """Return the connected USB payload."""
        return cast(dict[str, Any], json.loads(await self._post_text("usb_info")))

    async def uptime(self) -> int:
        """Return the NAS uptime in seconds.

        The uptime endpoint is a legacy CGI under ``/cgi-bin/``.  It sends the
        same ``Origin``/``Referer``/``X-Requested-With`` headers as the login;
        otherwise nasAdmin rejects the request with ``request origin != token
        origin`` (HTTP 403).
        """
        text = await self._post_text(
            "uptime", "cmd=cgi_get_uptime", form=True, origin=True
        )
        match = _UPTIME_ELEMENT_RE.search(text)
        if match is None:
            raise RequestFailedError("Uptime not found in XML response")

        uptime = parse_uptime_text(match.group(1))
        if uptime is None:
            raise RequestFailedError(
                f"Unexpected uptime format: {match.group(1).strip()}"
            )
        return uptime


__all__ = [
    "ENDPOINTS",
    "HTTPS_SCHEME",
    "SCHEME",
    "AccountLockedError",
    "AdminSessionBusyError",
    "InvalidLoginError",
    "NotAdminError",
    "ParseError",
    "PasswordExpiredError",
    "RequestFailedError",
    "WDNASClient",
    "parse_uptime_text",
]
