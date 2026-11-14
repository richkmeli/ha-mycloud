"""Tests for the WD My Cloud setup and unload lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from wdnas_client.exceptions import InvalidLoginError

from custom_components.mycloud import async_setup_entry, async_unload_entry
from custom_components.mycloud.const import DOMAIN


@pytest.fixture
def hass():
    """Return a mocked Home Assistant object."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


async def test_setup_stores_only_coordinator(hass, config_entry):
    """Setup stores the coordinator and does not duplicate credentials."""
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_close = AsyncMock()

    with (
        patch(
            "custom_components.mycloud.MyCloudClient", return_value=client
        ) as client_cls,
        patch("custom_components.mycloud.MyCloudCoordinator", return_value=coordinator),
    ):
        result = await async_setup_entry(hass, config_entry)

    assert result is True
    assert hass.data[DOMAIN][config_entry.entry_id] is coordinator
    assert "secret" not in repr(hass.data)
    client.async_connect.assert_awaited_once()
    client_cls.assert_called_once_with("admin", "secret", "nas.local", 5)
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


async def test_setup_invalid_credentials_starts_reauth(hass, config_entry):
    """Invalid credentials raise ConfigEntryAuthFailed."""
    client = AsyncMock()
    client.async_connect.side_effect = InvalidLoginError("bad")

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, config_entry)

    assert DOMAIN not in hass.data


async def test_setup_connection_error_is_retried(hass, config_entry):
    """A connection error raises ConfigEntryNotReady."""
    client = AsyncMock()
    client.async_connect.side_effect = aiohttp.ClientError("offline")

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, config_entry)

    assert DOMAIN not in hass.data


async def test_setup_failure_closes_client(hass, config_entry):
    """A failed first refresh closes the NAS session."""
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryNotReady("not ready")
    )
    coordinator.async_close = AsyncMock()

    with (
        patch("custom_components.mycloud.MyCloudClient", return_value=client),
        patch("custom_components.mycloud.MyCloudCoordinator", return_value=coordinator),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, config_entry)

    coordinator.async_close.assert_awaited_once()
    assert DOMAIN not in hass.data


async def test_unload_closes_client_and_removes_data(hass, config_entry):
    """Unload closes the session and drops the coordinator."""
    coordinator = MagicMock()
    coordinator.async_close = AsyncMock()
    hass.data[DOMAIN] = {config_entry.entry_id: coordinator}

    assert await async_unload_entry(hass, config_entry) is True
    coordinator.async_close.assert_awaited_once()
    assert DOMAIN not in hass.data


async def test_unload_failure_keeps_data(hass, config_entry):
    """A failed platform unload leaves the coordinator in place."""
    coordinator = MagicMock()
    coordinator.async_close = AsyncMock()
    hass.data[DOMAIN] = {config_entry.entry_id: coordinator}
    hass.config_entries.async_unload_platforms.return_value = False

    assert await async_unload_entry(hass, config_entry) is False
    coordinator.async_close.assert_not_awaited()
    assert hass.data[DOMAIN][config_entry.entry_id] is coordinator
