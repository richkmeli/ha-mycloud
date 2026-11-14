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
import re
from typing import Any
from xml.etree.ElementTree import Element, ParseError, fromstring

import aiohttp

SCHEME = "http://"

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


class InvalidLoginError(Exception):
    """Raised when the NAS rejects the credentials or the login cookies."""


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


def _as_bool(value: str | None) -> bool:
    """Convert a NAS numeric flag to a boolean."""
    return bool(int(value)) if value not in (None, "") else False


def _as_int(value: str | None, default: int = 0) -> int:
    """Convert a NAS numeric field, falling back to a default."""
    return int(value) if value not in (None, "") else default


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

    def __init__(self, username: str, password: str, host: str) -> None:
        """Initialize an OS5 client for the configured NAS."""
        self.host = host
        self.username = username.lower()
        self.password = password
        self.session: aiohttp.ClientSession | None = None
        self.phpsessid: str | None = None

    def _url(self, endpoint: str) -> str:
        """Build an API URL from the configured host and a fixed path."""
        return f"{SCHEME}{self.host}{ENDPOINTS[endpoint]}"

    def _require_session(self) -> aiohttp.ClientSession:
        """Return the authenticated session or raise a clear error."""
        if self.session is None or self.session.closed:
            raise ValueError("An authenticated NAS session is required")
        return self.session

    def _headers(self, *, form: bool = False) -> dict[str, str]:
        """Return the headers used by the NAS API."""
        headers = {"Host": self.host}
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        return headers

    async def _get_text(self, endpoint: str) -> str:
        """Perform an authenticated GET and return the response body."""
        session = self._require_session()
        async with session.get(
            self._url(endpoint), headers=self._headers()
        ) as response:
            if response.status != 200:
                raise RequestFailedError(response.status)
            return await response.text()

    async def _post_text(
        self, endpoint: str, data: str | None = None, *, form: bool = False
    ) -> str:
        """Perform an authenticated POST and return the response body."""
        session = self._require_session()
        async with session.post(
            self._url(endpoint),
            data=data,
            headers=self._headers(form=form),
        ) as response:
            if response.status != 200:
                raise RequestFailedError(response.status)
            return await response.text()

    async def login(self) -> None:
        """Authenticate against the OS5 API and keep the session cookie."""
        session = self._require_session()
        encoded_password = base64.b64encode(self.password.encode("utf-8")).decode(
            "utf-8"
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Host": self.host,
        }

        async with session.post(
            self._url("login"),
            json={"username": self.username, "password": encoded_password},
            headers=headers,
        ) as response:
            if response.status != 200:
                raise RequestFailedError(response.status)

            # The NAS scopes some cookies to the login path. Add them to the
            # jar with no path so they are also sent to the data endpoints.
            for cookie_string in response.headers.getall("Set-Cookie", []):
                cookie = http.cookies.SimpleCookie(cookie_string)
                for key, morsel in cookie.items():
                    session.cookie_jar.update_cookies({key: morsel.value})

            cookies = response.cookies
            if "PHPSESSID" not in cookies:
                raise InvalidLoginError(
                    "Invalid Username/Password or missing session cookie"
                )
            self.phpsessid = cookies["PHPSESSID"].value

    async def logout(self) -> None:
        """End the NAS admin session without closing the local session.

        OS5 firmware allows only one admin session at a time. The WD web
        interface releases it with ``DELETE /nas/v1/auth``; calling this before
        a new login lets the integration reconfigure or re-authenticate
        without waiting for the old session to expire.
        """
        session = self._require_session()
        async with session.delete(
            self._url("logout"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Host": self.host,
            },
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
                    "id": disk.attrib["id"],
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
                    "id": volume.attrib["id"],
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
        return payload["item"]

    async def system_status(self) -> dict[str, Any]:
        """Return CPU and memory usage."""
        root = _parse_xml(
            await self._post_text("system_status", "cmd=resource", form=True)
        )
        cpu = root.findtext(".//cpu")
        return {
            "memory": {
                "total": _as_int(root.findtext(".//mem_total")),
                "unused": _as_int(root.findtext(".//mem_free")),
                "simple": root.findtext(".//mem2_total"),
            },
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
        return json.loads(
            await self._post_text("cloud_access", "cmd=getCloudAccess", form=True)
        )

    async def usb_info(self) -> dict[str, Any]:
        """Return the connected USB payload."""
        return json.loads(await self._post_text("usb_info"))

    async def uptime(self) -> int:
        """Return the NAS uptime in seconds."""
        text = await self._post_text("uptime", "cmd=cgi_get_uptime", form=True)
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
    "SCHEME",
    "InvalidLoginError",
    "ParseError",
    "RequestFailedError",
    "WDNASClient",
    "parse_uptime_text",
]
