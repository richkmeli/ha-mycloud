"""Tests for the WD My Cloud coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from custom_components.mycloud.coordinator import MyCloudCoordinator


@pytest.fixture
def entry():
    """Return a config entry-like object."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.options = {}
    return entry


@pytest.fixture
def client(nas_data):
    """Return a mocked NAS client."""
    client = AsyncMock()
    client.version = 5
    client.system_info.return_value = nas_data["system_info"]
    client.system_status.return_value = nas_data["system_status"]
    client.device_info.return_value = nas_data["device_info"]
    client.system_version.return_value = nas_data["system_version"]
    client.alerts.return_value = (len(nas_data["alerts"]), nas_data["alerts"])
    client.async_uptime.return_value = nas_data["uptime"]
    return client


@pytest.fixture
def coordinator(entry, client):
    """Return a coordinator using the mocked client."""
    return MyCloudCoordinator(MagicMock(), entry, client)


async def test_update_fetches_all_endpoints(coordinator, client, nas_data):
    """The coordinator returns the payload consumed by the entities."""
    data = await coordinator._async_update_data()

    assert data == nas_data
    client.system_info.assert_awaited_once()
    client.system_status.assert_awaited_once()
    client.device_info.assert_awaited_once()
    client.system_version.assert_awaited_once()
    client.alerts.assert_awaited_once()
    client.async_uptime.assert_awaited_once()


async def test_optional_alerts_failure_keeps_core_data(coordinator, client, nas_data):
    """A failing alert endpoint only disables the alert sensors."""
    client.alerts.side_effect = RequestFailedError(500)

    data = await coordinator._async_update_data()

    assert data["alerts"] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["uptime"] == nas_data["uptime"]


async def test_optional_uptime_failure_keeps_core_data(coordinator, client, nas_data):
    """A failing uptime endpoint only disables the uptime sensor."""
    client.async_uptime.side_effect = RequestFailedError(500)

    data = await coordinator._async_update_data()

    assert data["uptime"] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["alerts"] == nas_data["alerts"]


async def test_uptime_not_requested_for_v2(coordinator, client):
    """The uptime endpoint is V5-only."""
    client.version = 2

    data = await coordinator._async_update_data()

    assert data["uptime"] is None
    client.async_uptime.assert_not_awaited()


async def test_update_reauthenticates_on_403(coordinator, client, nas_data):
    """A 403 triggers one re-login and a retry."""
    client.system_info.side_effect = [
        RequestFailedError(403),
        nas_data["system_info"],
    ]

    data = await coordinator._async_update_data()

    assert data["system_info"] == nas_data["system_info"]
    client.async_reconnect.assert_awaited_once()


async def test_update_reconnects_when_session_is_missing(coordinator, client):
    """A closed session is reopened before polling."""
    client.session = None

    await coordinator._async_update_data()

    client.async_reconnect.assert_awaited_once()


async def test_update_invalid_credentials_requests_reauth(coordinator, client):
    """Invalid credentials raise ConfigEntryAuthFailed."""
    client.system_info.side_effect = InvalidLoginError("bad")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_reauth_failure_requests_reauth(coordinator, client):
    """A failed re-login raises ConfigEntryAuthFailed."""
    client.system_info.side_effect = RequestFailedError(403)
    client.async_reconnect.side_effect = InvalidLoginError("bad")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_server_error(coordinator, client):
    """A non-auth HTTP error is reported as UpdateFailed."""
    client.system_info.side_effect = RequestFailedError(500)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_timeout(coordinator, client):
    """A timeout is reported as UpdateFailed."""
    client.system_info.side_effect = TimeoutError()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_client_error(coordinator, client):
    """An aiohttp error is reported as UpdateFailed."""
    client.system_info.side_effect = aiohttp.ClientError("offline")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_close_closes_client(coordinator, client):
    """Closing the coordinator closes the NAS session."""
    await coordinator.async_close()
    client.async_close.assert_awaited_once()
