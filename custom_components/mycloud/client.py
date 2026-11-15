"""Client for the WD My Cloud OS5 API.

The protocol implementation is vendored in :mod:`custom_components.mycloud.wdnas`
and is based on the MIT-licensed ``wdnas-client`` library.  This wrapper adds
the Home Assistant lifecycle: a bounded aiohttp session, serialized session
handling, the uptime fallback and the guarded power actions.  It only sends
data to the host configured by the user.  See SECURITY.md for the threat model
and the known HTTP limitation of the WD API.
"""

from __future__ import annotations

import asyncio
import logging
import re
from xml.etree.ElementTree import ParseError, fromstring

import aiohttp

from .const import REQUEST_TIMEOUT
from .wdnas import (
    AccountLockedError,
    AdminSessionBusyError,
    InvalidLoginError,
    NotAdminError,
    PasswordExpiredError,
    RequestFailedError,
    WDNASClient,
    parse_uptime_text,
)

_LOGGER = logging.getLogger(__name__)

_STATUS_CODE_RE = re.compile(r"Request failed:\s*(\d{3})")
_LOGOUT_TIMEOUT = 5

_POWER_COMMANDS = {"restart": "cgi_restart", "shutdown": "cgi_shutdown"}
_POWER_SAFETY_COMMAND = "cmd=cgi_Detect_Dangerous"
_POWER_SAFETY_PATH = "/cgi-bin/hd_config.cgi"
_POWER_ACTION_PATH = "/cgi-bin/system_mgr.cgi"


class PowerActionBlockedError(Exception):
    """Raised when the NAS safety check refuses a power action."""

    def __init__(self, code: int) -> None:
        """Initialize the error with the NAS safety code."""
        self.code = code
        super().__init__(f"Power action blocked by the NAS (code {code})")


def status_code(err: Exception) -> int | None:
    """Extract the HTTP status code from a client exception."""
    code = getattr(err, "status_code", None)
    if isinstance(code, int):
        return code
    match = _STATUS_CODE_RE.search(str(err))
    return int(match.group(1)) if match else None


class MyCloudClient(WDNASClient):
    """A WD NAS client with bounded requests and clean session lifecycle."""

    def __init__(
        self,
        username: str,
        password: str,
        host: str,
        *,
        use_https: bool = False,
    ) -> None:
        """Initialize an OS5 client."""
        super().__init__(username, password, host, use_https=use_https)
        self._session_lock = asyncio.Lock()
        self._power_lock = asyncio.Lock()

    async def async_connect(self) -> None:
        """Open a session and authenticate."""
        async with self._session_lock:
            await self._async_open()

    async def async_reconnect(self) -> None:
        """Replace the session and authenticate again (e.g. after a 403)."""
        async with self._session_lock:
            await self._async_open()

    async def async_close(self) -> None:
        """Close the underlying aiohttp session."""
        async with self._session_lock:
            await self._async_close_locked()

    async def async_uptime(self) -> int | None:
        """Return the OS5 uptime in seconds.

        Some firmware (for example 5.33.103) answers ``cgi_get_uptime`` with an
        empty HTTP 500 even though the same ``<uptime>`` element is present in
        ``cgi_get_status``. Try the documented command first and fall back to
        the status response, as proposed upstream in wdnas_client#50.
        """
        try:
            return await self.uptime()
        except (RequestFailedError, aiohttp.ClientError, TimeoutError, OSError):
            return await self._async_uptime_from_status()

    async def _async_uptime_from_status(self) -> int | None:
        """Read uptime from ``cgi_get_status`` when the dedicated call fails."""
        try:
            text = await self._post_text("uptime", "cmd=cgi_get_status", form=True)
        except (
            RequestFailedError,
            aiohttp.ClientError,
            TimeoutError,
            OSError,
            ValueError,
        ):
            return None
        return parse_uptime_text(text)

    async def async_power_action(self, action: str) -> None:
        """Restart or shut down the OS5 NAS over the authenticated session.

        The WD dashboard checks ``cgi_Detect_Dangerous`` before restarting or
        shutting down. A non-zero result means the NAS is busy (for example a
        RAID operation or a firmware update) and the action must not be sent.
        The action is sent exactly once: no retry or method fallback is used,
        because an unanswered request may already have powered the device off.
        """
        try:
            command = _POWER_COMMANDS[action]
        except KeyError as err:
            raise ValueError(f"Unsupported power action: {action}") from err

        session = self._require_session()
        headers = self._headers(form=True)

        async with self._power_lock:
            safety_url = f"{self.scheme}{self.host}{_POWER_SAFETY_PATH}"
            async with session.post(
                safety_url, data=_POWER_SAFETY_COMMAND, headers=headers
            ) as response:
                if response.status != 200:
                    raise RequestFailedError(response.status)
                # The payload comes from the NAS configured by the user and
                # only its numeric res field is read. See SECURITY.md.
                root = fromstring(await response.text())  # noqa: S314

            result = root.findtext(".//res")
            try:
                code = int(result) if result is not None else None
            except ValueError as err:
                raise ParseError("Unexpected power safety response") from err
            if code is None:
                raise ParseError("Missing power safety result")
            if code != 0:
                raise PowerActionBlockedError(code)

            action_url = f"{self.scheme}{self.host}{_POWER_ACTION_PATH}"
            try:
                async with session.post(
                    action_url, data=f"cmd={command}", headers=headers
                ) as response:
                    if response.status != 200:
                        raise RequestFailedError(response.status)
                    await response.text()
            except aiohttp.ServerDisconnectedError:
                # The NAS may close the HTTP connection while it powers off.
                return

    async def _async_open(self) -> None:
        """Create a fresh session and log in."""
        await self._async_close_locked()
        # The WD firmware uses a self-signed certificate, so certificate
        # verification cannot be used for the local HTTPS endpoint. The
        # integration only talks to the host configured by the user.
        connector = aiohttp.TCPConnector(ssl=False) if self.use_https else None
        if connector is not None:
            _LOGGER.debug(
                "HTTPS certificate verification is disabled for %s", self.host
            )
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            connector=connector,
        )
        try:
            await self.login()
        except Exception:
            await self._async_close_locked()
            raise

    async def _async_close_locked(self) -> None:
        """Log out and close the session without acquiring the lock.

        Releasing the server-side admin session matters on OS5: the firmware
        accepts one admin session at a time, so reconfigure and reauth must be
        able to log in while the old entry is being unloaded. Logout is best
        effort; a powered-off or unreachable NAS must not block the unload.
        """
        session = self.session
        if session is None:
            return
        try:
            if self.phpsessid is not None and not session.closed:
                try:
                    async with asyncio.timeout(_LOGOUT_TIMEOUT):
                        await self.logout()
                except Exception as err:  # noqa: BLE001 - cleanup is best effort
                    _LOGGER.debug("NAS logout failed: %s", err)
        finally:
            self.session = None
            self.phpsessid = None
            if not session.closed:
                await session.close()

    async def __aenter__(self) -> MyCloudClient:
        """Enter the async context manager."""
        await self.async_connect()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        """Exit the async context manager."""
        await self.async_close()


__all__ = [
    "AccountLockedError",
    "AdminSessionBusyError",
    "InvalidLoginError",
    "MyCloudClient",
    "NotAdminError",
    "PasswordExpiredError",
    "PowerActionBlockedError",
    "RequestFailedError",
    "parse_uptime_text",
    "status_code",
]
