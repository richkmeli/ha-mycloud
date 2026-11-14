"""Async client wrapper for the WD NAS API.

The integration uses the MIT-licensed ``wdnas-client`` library, pinned in the
manifest.  This wrapper only adds lifecycle and timeout handling; it does not
send data anywhere except to the host configured by the user.  See SECURITY.md
for the threat model and the known HTTP limitation of the upstream library.
"""

from __future__ import annotations

import asyncio
import re

import aiohttp
from wdnas_client import client as nas_client

from .const import REQUEST_TIMEOUT

_STATUS_CODE_RE = re.compile(r"Request failed:\s*(\d{3})")


def status_code(err: Exception) -> int | None:
    """Extract the HTTP status code from a wdnas-client exception."""
    match = _STATUS_CODE_RE.search(str(err))
    return int(match.group(1)) if match else None


class MyCloudClient(nas_client):
    """A WD NAS client with bounded requests and clean session lifecycle."""

    def __init__(self, username: str, password: str, host: str, version: int) -> None:
        """Initialize the client."""
        super().__init__(username, password, host, version)
        self._session_lock = asyncio.Lock()

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

    async def _async_open(self) -> None:
        """Create a fresh session and log in."""
        await self._async_close_locked()
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        )
        try:
            await self.login()
        except Exception:
            await self._async_close_locked()
            raise

    async def _async_close_locked(self) -> None:
        """Close the session without acquiring the lock."""
        if self.session is not None and not self.session.closed:
            await self.session.close()
        self.session = None

    async def __aenter__(self) -> MyCloudClient:
        """Enter the async context manager."""
        await self.async_connect()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        """Exit the async context manager."""
        await self.async_close()
