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
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERSION, DOMAIN
from .coordinator import MyCloudCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await coordinator.async_close()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator: MyCloudCoordinator | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if coordinator is not None:
        await coordinator.async_close()

    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
