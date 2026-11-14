"""WD My Cloud integration for Home Assistant."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from .client import MyCloudClient, status_code
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERSION
from .coordinator import MyCloudCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type MyCloudConfigEntry = ConfigEntry[MyCloudCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MyCloudConfigEntry) -> bool:
    """Set up WD My Cloud from a config entry."""
    host = entry.data[CONF_HOST]
    client = MyCloudClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        host,
        entry.data[CONF_VERSION],
    )

    try:
        await client.async_connect()
    except InvalidLoginError as err:
        raise ConfigEntryAuthFailed("Invalid WD My Cloud credentials") from err
    except RequestFailedError as err:
        if status_code(err) in (401, 403):
            raise ConfigEntryAuthFailed("Invalid WD My Cloud credentials") from err
        raise ConfigEntryNotReady(f"Cannot connect to {host}: {err}") from err
    except (TimeoutError, aiohttp.ClientError, OSError) as err:
        raise ConfigEntryNotReady(f"Cannot connect to {host}: {err}") from err

    coordinator = MyCloudCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_close()
        raise

    entry.runtime_data = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        entry.runtime_data = None
        await coordinator.async_close()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: MyCloudConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator = entry.runtime_data
    if coordinator is not None:
        await coordinator.async_close()
        entry.runtime_data = None

    return True
