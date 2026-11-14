"""Data update coordinator for the WD My Cloud integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from .client import MyCloudClient, status_code
from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class MyCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the NAS and keep the latest data for all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: MyCloudClient,
    ) -> None:
        """Initialize the coordinator."""
        update_interval = entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=update_interval),
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all data used by the entities."""
        if self.client.session is None:
            try:
                await self.client.async_reconnect()
            except InvalidLoginError as err:
                raise ConfigEntryAuthFailed("Invalid WD My Cloud credentials") from err
            except RequestFailedError as err:
                if status_code(err) in (401, 403):
                    raise ConfigEntryAuthFailed(
                        "Invalid WD My Cloud credentials"
                    ) from err
                raise UpdateFailed(f"Cannot reconnect to the NAS: {err}") from err
            except Exception as err:
                raise UpdateFailed(f"Cannot reconnect to the NAS: {err}") from err

        try:
            return await self._async_fetch()
        except InvalidLoginError as err:
            raise ConfigEntryAuthFailed("Invalid WD My Cloud credentials") from err
        except RequestFailedError as err:
            if status_code(err) not in (401, 403):
                raise UpdateFailed(f"Error fetching data: {err}") from err

            # The NAS invalidated the PHP session. Log in again once before
            # reporting a failure, otherwise every poll would require a reload.
            try:
                await self.client.async_reconnect()
                return await self._async_fetch()
            except InvalidLoginError as retry_err:
                raise ConfigEntryAuthFailed(
                    "Invalid WD My Cloud credentials"
                ) from retry_err
            except RequestFailedError as retry_err:
                if status_code(retry_err) in (401, 403):
                    raise ConfigEntryAuthFailed(
                        "Invalid WD My Cloud credentials"
                    ) from retry_err
                raise UpdateFailed(
                    f"Failed to fetch data after re-authentication: {retry_err}"
                ) from retry_err
            except Exception as retry_err:
                raise UpdateFailed(
                    f"Failed to fetch data after re-authentication: {retry_err}"
                ) from retry_err
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise UpdateFailed(f"Cannot connect to the NAS: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error fetching data: {err}") from err

    async def _async_fetch(self) -> dict[str, Any]:
        """Fetch the data set exposed to the entities.

        Alerts and uptime are optional: a failure in one of those endpoints
        must not make the whole integration unavailable.
        """
        data: dict[str, Any] = {
            "system_info": await self.client.system_info(),
            "system_status": await self.client.system_status(),
            "device_info": await self.client.device_info(),
            "system_version": await self.client.system_version(),
            "alerts": await self._async_alerts(),
            "uptime": None,
        }

        if getattr(self.client, "version", None) == 5:
            data["uptime"] = await self._async_optional(self.client.async_uptime)

        return data

    async def _async_optional(self, fetch):
        """Call an optional endpoint, returning None instead of failing."""
        try:
            return await fetch()
        except (
            InvalidLoginError,
            RequestFailedError,
            aiohttp.ClientError,
            TimeoutError,
            OSError,
            ValueError,
        ) as err:
            _LOGGER.debug("Optional NAS endpoint failed: %s", err)
            return None

    async def _async_alerts(self) -> list[dict[str, Any]] | None:
        """Return the alert list, or None when the NAS cannot provide it."""
        result = await self._async_optional(self.client.alerts)
        if (
            isinstance(result, tuple)
            and len(result) == 2
            and isinstance(result[1], list)
        ):
            return result[1]
        return None

    async def async_close(self) -> None:
        """Close the NAS session."""
        await self.client.async_close()
