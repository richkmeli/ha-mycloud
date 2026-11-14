"""Tests for the WD My Cloud coordinator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from xml.etree.ElementTree import ParseError

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
    entry.data = {"Host": "nas.local"}
    return entry


@pytest.fixture
def client(nas_data):
    """Return a mocked NAS client."""
    client = AsyncMock()
    client.system_info.return_value = nas_data["system_info"]
    client.system_status.return_value = nas_data["system_status"]
    client.device_info.return_value = nas_data["device_info"]
    client.system_version.return_value = nas_data["system_version"]
    client.alerts.return_value = (len(nas_data["alerts"]), nas_data["alerts"])
    client.share_names.return_value = nas_data["share_names"]
    client.network_info.return_value = nas_data["network"]
    client.accounts.return_value = nas_data["accounts"]
    client.cloud_access.return_value = nas_data["cloud_access"]
    client.usb_info.return_value = nas_data["usb_info"]
    client.async_uptime.return_value = nas_data["uptime"]
    return client


@pytest.fixture
def hass():
    """Return a mocked Home Assistant object."""
    hass = MagicMock()
    hass.is_stopping = False
    return hass


@pytest.fixture
def coordinator(hass, entry, client):
    """Return a coordinator using the mocked client."""
    return MyCloudCoordinator(hass, entry, client)


def test_coordinator_skips_redundant_listener_updates(coordinator):
    """Identical payloads do not notify every entity on each poll."""
    assert coordinator.always_update is False
    assert coordinator.device_id is None


async def test_update_fetches_all_endpoints(coordinator, client, nas_data):
    """The coordinator returns the payload consumed by the entities."""
    data = await coordinator._async_update_data()

    assert data == nas_data
    client.system_info.assert_awaited_once()
    client.system_status.assert_awaited_once()
    client.device_info.assert_awaited_once()
    client.system_version.assert_awaited_once()
    client.alerts.assert_awaited_once()
    client.share_names.assert_awaited_once()
    client.network_info.assert_awaited_once()
    client.accounts.assert_awaited_once()
    client.cloud_access.assert_awaited_once()
    client.usb_info.assert_awaited_once()
    client.async_uptime.assert_awaited_once()


async def test_optional_alerts_failure_keeps_core_data(coordinator, client, nas_data):
    """A failing alert endpoint only disables the alert sensors."""
    client.alerts.side_effect = RequestFailedError(500)

    data = await coordinator._async_update_data()

    assert data["alerts"] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["uptime"] == nas_data["uptime"]


async def test_optional_alerts_parse_error_keeps_core_data(
    coordinator, client, nas_data
):
    """Malformed alert XML only disables the alert sensors."""
    client.alerts.side_effect = ParseError("malformed XML")

    data = await coordinator._async_update_data()

    assert data["alerts"] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["uptime"] == nas_data["uptime"]


async def test_optional_system_version_failure_keeps_core_data(
    coordinator, client, nas_data
):
    """A firmware endpoint without the expected XML nodes is not fatal."""
    client.system_version.side_effect = AttributeError("missing oled node")

    data = await coordinator._async_update_data()

    assert data["system_version"] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["device_info"] == nas_data["device_info"]


async def test_optional_uptime_failure_keeps_core_data(coordinator, client, nas_data):
    """A failing uptime endpoint only disables the uptime sensor."""
    client.async_uptime.side_effect = RequestFailedError(500)

    data = await coordinator._async_update_data()

    assert data["uptime"] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["alerts"] == nas_data["alerts"]


@pytest.mark.parametrize(
    ("method", "data_key"),
    [
        ("share_names", "share_names"),
        ("network_info", "network"),
        ("accounts", "accounts"),
        ("cloud_access", "cloud_access"),
        ("usb_info", "usb_info"),
    ],
)
async def test_optional_data_failures_are_isolated(
    coordinator, client, nas_data, method, data_key
):
    """A failing optional endpoint only disables its own entities."""
    getattr(client, method).side_effect = RequestFailedError(500)

    data = await coordinator._async_update_data()

    assert data[data_key] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["uptime"] == nas_data["uptime"]


@pytest.mark.parametrize(
    "side_effect",
    [
        TypeError("unexpected type"),
        IndexError("unexpected list access"),
        NameError("missing local"),
    ],
)
async def test_optional_parsing_failures_are_isolated(
    coordinator, client, nas_data, side_effect
):
    """Unexpected upstream parsing errors only disable the optional sensor."""
    client.accounts.side_effect = side_effect

    data = await coordinator._async_update_data()

    assert data["accounts"] is None
    assert data["system_info"] == nas_data["system_info"]
    assert data["uptime"] == nas_data["uptime"]


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
    """A missing session is reopened before polling."""
    client.session = None

    await coordinator._async_update_data()

    client.async_reconnect.assert_awaited_once()


async def test_update_reconnects_when_session_is_closed(coordinator, client):
    """A session object that is closed is reopened before polling."""
    client.session = SimpleNamespace(closed=True)

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

    with pytest.raises(UpdateFailed) as err:
        await coordinator._async_update_data()

    assert err.value.translation_key == "fetch_failed"


@pytest.mark.parametrize(
    ("side_effect", "exception", "key"),
    [
        (InvalidLoginError("bad"), ConfigEntryAuthFailed, "invalid_auth"),
        (RequestFailedError(401), ConfigEntryAuthFailed, "invalid_auth"),
        (RequestFailedError(403), ConfigEntryAuthFailed, "invalid_auth"),
        (RequestFailedError(500), UpdateFailed, "reconnect_failed"),
        (RuntimeError("boom"), UpdateFailed, "reconnect_failed"),
    ],
)
async def test_update_reconnect_errors(
    coordinator, client, side_effect, exception, key
):
    """A failing reconnect is translated before it reaches the user."""
    client.session = None
    client.async_reconnect.side_effect = side_effect

    with pytest.raises(exception) as err:
        await coordinator._async_update_data()

    assert err.value.translation_key == key


@pytest.mark.parametrize(
    ("side_effect", "exception", "key"),
    [
        (RequestFailedError(401), ConfigEntryAuthFailed, "invalid_auth"),
        (RequestFailedError(403), ConfigEntryAuthFailed, "invalid_auth"),
        (RequestFailedError(500), UpdateFailed, "reauth_fetch_failed"),
        (RuntimeError("boom"), UpdateFailed, "reauth_fetch_failed"),
    ],
)
async def test_update_retry_after_session_expiry_errors(
    coordinator, client, side_effect, exception, key
):
    """A failed retry after a session expiry is translated."""
    client.system_info.side_effect = RequestFailedError(403)

    async def reconnect() -> None:
        client.system_info.side_effect = side_effect

    client.async_reconnect.side_effect = reconnect

    with pytest.raises(exception) as err:
        await coordinator._async_update_data()

    assert err.value.translation_key == key


async def test_update_unexpected_error_is_translated(coordinator, client):
    """An unexpected fetch error is reported with a translation key."""
    client.system_info.side_effect = RuntimeError("boom")

    with pytest.raises(UpdateFailed) as err:
        await coordinator._async_update_data()

    assert err.value.translation_key == "unexpected_fetch_failed"


async def test_update_connection_error_is_translated(coordinator, client):
    """A transport error includes the configured host in the placeholders."""
    client.system_info.side_effect = TimeoutError()

    with pytest.raises(UpdateFailed) as err:
        await coordinator._async_update_data()

    assert err.value.translation_key == "cannot_connect"
    assert err.value.translation_placeholders == {"host": "nas.local", "error": ""}


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


async def test_topology_change_schedules_reload(coordinator, entry, nas_data):
    """Adding or removing a disk or volume reloads the entry once."""
    await coordinator._async_update_data()
    coordinator.hass.config_entries.async_schedule_reload.assert_not_called()

    await coordinator._async_update_data()
    coordinator.hass.config_entries.async_schedule_reload.assert_not_called()

    nas_data["system_info"]["disks"].append(
        {
            "id": "disk-2",
            "name": "Disk 2",
            "sn": "WD-DISK-SN-2",
            "model": "WD Red",
            "rev": "1.0",
            "size": 4_000_000_000_000,
            "temp": 34,
            "healthy": 1,
            "sleep": 0,
            "failed": 0,
            "over_temp": 0,
            "connected": 1,
            "removable": 0,
        }
    )

    await coordinator._async_update_data()

    coordinator.hass.config_entries.async_schedule_reload.assert_called_once_with(
        entry.entry_id
    )


async def test_topology_is_not_checked_while_stopping(coordinator, nas_data):
    """A topology change during shutdown does not schedule another reload."""
    await coordinator._async_update_data()
    coordinator.hass.is_stopping = True
    nas_data["system_info"]["volumes"].clear()

    await coordinator._async_update_data()

    coordinator.hass.config_entries.async_schedule_reload.assert_not_called()


async def test_network_change_schedules_reload(coordinator, entry, nas_data):
    """Adding or removing a network interface reloads the entry once."""
    await coordinator._async_update_data()
    coordinator.hass.config_entries.async_schedule_reload.assert_not_called()

    nas_data["network"]["11:22:33:44:55:66"] = {
        "ip": "192.168.1.43",
        "lan_enabled": True,
    }

    await coordinator._async_update_data()

    coordinator.hass.config_entries.async_schedule_reload.assert_called_once_with(
        entry.entry_id
    )


async def test_network_failure_does_not_trigger_a_topology_reload(
    coordinator, client, nas_data
):
    """A transient network endpoint failure keeps the known interfaces."""
    await coordinator._async_update_data()
    client.network_info.side_effect = RequestFailedError(500)

    data = await coordinator._async_update_data()

    assert data["network"] is None
    coordinator.hass.config_entries.async_schedule_reload.assert_not_called()


async def test_close_closes_client(coordinator, client):
    """Closing the coordinator closes the NAS session."""
    await coordinator.async_close()
    client.async_close.assert_awaited_once()
