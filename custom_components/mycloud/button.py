"""Button platform for the WD My Cloud integration."""

from __future__ import annotations

from xml.etree.ElementTree import ParseError

import aiohttp
from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import PowerActionBlockedError
from .const import DOMAIN
from .coordinator import MyCloudCoordinator
from .entity import build_device_info
from .wdnas import InvalidLoginError, RequestFailedError

PARALLEL_UPDATES = 0

_POWER_ERRORS = (
    InvalidLoginError,
    RequestFailedError,
    aiohttp.ClientError,
    TimeoutError,
    OSError,
    ParseError,
    ValueError,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WD My Cloud power buttons."""
    coordinator: MyCloudCoordinator | None = config_entry.runtime_data
    if coordinator is None:
        return

    device_info, serial_number, _, _ = build_device_info(coordinator)
    async_add_entities(
        [
            MyCloudPowerButton(
                coordinator,
                device_info,
                serial_number,
                "restart",
                ButtonDeviceClass.RESTART,
            ),
            MyCloudPowerButton(
                coordinator,
                device_info,
                serial_number,
                "shutdown",
                enabled_by_default=False,
            ),
        ]
    )


class MyCloudPowerButton(CoordinatorEntity, ButtonEntity):
    """Restart or shut down the NAS."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MyCloudCoordinator,
        device_info,
        serial_number: str,
        action: str,
        device_class: ButtonDeviceClass | None = None,
        *,
        enabled_by_default: bool = True,
    ) -> None:
        """Initialize the power button."""
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_{action}"
        self._attr_translation_key = action
        self._attr_device_class = device_class
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._action = action

    async def async_press(self) -> None:
        """Send the power action to the NAS."""
        try:
            await self.coordinator.client.async_power_action(self._action)
        except PowerActionBlockedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="power_action_blocked",
                translation_placeholders={"code": str(err.code)},
            ) from err
        except _POWER_ERRORS as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="power_action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
