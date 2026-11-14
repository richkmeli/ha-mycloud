"""Data update coordinator for the WD My Cloud integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from xml.etree.ElementTree import ParseError

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from .client import MyCloudClient, status_code
from .const import (
    CONF_HOST,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .entity import disk_key, volume_key

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
            always_update=False,
        )
        self.client = client
        self.device_id: str | None = None
        self._entry = entry
        self._topology: (
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None
        ) = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all data used by the entities."""
        session = self.client.session
        if session is None or getattr(session, "closed", False) is True:
            try:
                await self.client.async_reconnect()
            except InvalidLoginError as err:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN, translation_key="invalid_auth"
                ) from err
            except RequestFailedError as err:
                if status_code(err) in (401, 403):
                    raise ConfigEntryAuthFailed(
                        translation_domain=DOMAIN, translation_key="invalid_auth"
                    ) from err
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="reconnect_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            except Exception as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="reconnect_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

        try:
            return await self._async_fetch()
        except InvalidLoginError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except RequestFailedError as err:
            if status_code(err) not in (401, 403):
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="fetch_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

            # The NAS invalidated the PHP session. Log in again once before
            # reporting a failure, otherwise every poll would require a reload.
            try:
                await self.client.async_reconnect()
                return await self._async_fetch()
            except InvalidLoginError as retry_err:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN, translation_key="invalid_auth"
                ) from retry_err
            except RequestFailedError as retry_err:
                if status_code(retry_err) in (401, 403):
                    raise ConfigEntryAuthFailed(
                        translation_domain=DOMAIN, translation_key="invalid_auth"
                    ) from retry_err
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="reauth_fetch_failed",
                    translation_placeholders={"error": str(retry_err)},
                ) from retry_err
            except Exception as retry_err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="reauth_fetch_failed",
                    translation_placeholders={"error": str(retry_err)},
                ) from retry_err
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={
                    "host": self._entry.data.get(CONF_HOST, ""),
                    "error": str(err),
                },
            ) from err
        except Exception as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unexpected_fetch_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_fetch(self) -> dict[str, Any]:
        """Fetch the data set exposed to the entities.

        Optional endpoints are isolated: a failure in one of them must not make
        the whole integration unavailable. This also keeps newer firmware or a
        partially disabled NAS service from breaking the core sensors.
        """
        data: dict[str, Any] = {
            "system_info": await self.client.system_info(),
            "system_status": await self.client.system_status(),
            "device_info": await self.client.device_info(),
            "system_version": await self._async_optional(self.client.system_version),
            "alerts": await self._async_alerts(),
            "share_names": await self._async_optional(self.client.share_names),
            "network": await self._async_optional(self.client.network_info),
            "accounts": await self._async_optional(self.client.accounts),
            "cloud_access": await self._async_optional(self.client.cloud_access),
            "usb_info": await self._async_optional(self.client.usb_info),
            "uptime": await self._async_optional(self.client.async_uptime),
        }

        self._async_check_topology(data)
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
            TypeError,
            AttributeError,
            KeyError,
            IndexError,
            NameError,
            ParseError,
        ) as err:
            _LOGGER.debug("Optional NAS endpoint failed: %s", err)
            return None

    def _async_check_topology(self, data: dict[str, Any]) -> None:
        """Reload the entry when disks, volumes or network interfaces change."""
        system_info = data.get("system_info") or {}
        disks = system_info.get("disks") or []
        volumes = system_info.get("volumes") or []
        network = data.get("network")
        if isinstance(network, dict):
            network_keys = tuple(sorted(str(key) for key in network))
        elif self._topology is not None:
            # Keep the previous interfaces when the optional endpoint fails so
            # a transient error does not reload the entry twice.
            network_keys = self._topology[2]
        else:
            network_keys = ()

        topology = (
            tuple(
                sorted(str(disk_key(disk)) for disk in disks if isinstance(disk, dict))
            ),
            tuple(
                sorted(
                    str(volume_key(volume))
                    for volume in volumes
                    if isinstance(volume, dict)
                )
            ),
            network_keys,
        )

        if self._topology is None:
            self._topology = topology
            return
        if topology == self._topology:
            return

        self._topology = topology
        if getattr(self.hass, "is_stopping", False):
            return
        self.hass.config_entries.async_schedule_reload(self._entry.entry_id)

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
