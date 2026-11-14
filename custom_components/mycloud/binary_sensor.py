"""Binary sensor platform for the WD My Cloud integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MyCloudCoordinator
from .entity import (
    as_bool,
    build_device_info,
    build_disk_info,
    build_volume_info,
    coordinator_data,
    get_disk,
    get_volume,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WD My Cloud binary sensors."""
    coordinator: MyCloudCoordinator | None = hass.data.get(DOMAIN, {}).get(
        config_entry.entry_id
    )
    if coordinator is None:
        return

    device_info, serial_number, device_name, firmware = build_device_info(coordinator)
    system_info = (coordinator_data(coordinator).get("system_info")) or {}

    entities: list[BinarySensorEntity] = []

    disks = system_info.get("disks") or []
    if isinstance(disks, list):
        for index, disk in enumerate(disks):
            if not isinstance(disk, dict):
                continue
            disk_device, key, disk_name = build_disk_info(
                serial_number, device_name, firmware, disk, index
            )
            entities.extend(
                [
                    MyCloudDiskHealthySensor(
                        coordinator, disk_device, serial_number, key, disk_name
                    ),
                    MyCloudDiskSleepSensor(
                        coordinator, disk_device, serial_number, key, disk_name
                    ),
                    MyCloudDiskFailedSensor(
                        coordinator, disk_device, serial_number, key, disk_name
                    ),
                    MyCloudDiskOverTemperatureSensor(
                        coordinator, disk_device, serial_number, key, disk_name
                    ),
                ]
            )

    volumes = system_info.get("volumes") or []
    if isinstance(volumes, list):
        for index, volume in enumerate(volumes):
            if not isinstance(volume, dict):
                continue
            volume_device, key, volume_name = build_volume_info(
                serial_number, device_name, volume, index
            )
            entities.extend(
                [
                    MyCloudVolumeMountedSensor(
                        coordinator, volume_device, serial_number, key, volume_name
                    ),
                    MyCloudVolumeUnlockedSensor(
                        coordinator, volume_device, serial_number, key, volume_name
                    ),
                    MyCloudVolumeEncryptedSensor(
                        coordinator, volume_device, serial_number, key, volume_name
                    ),
                ]
            )

    async_add_entities(entities)


class MyCloudBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for My Cloud binary sensors."""

    def __init__(
        self,
        coordinator: MyCloudCoordinator,
        device_info,
        unique_id: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_icon = icon


class MyCloudDiskHealthySensor(MyCloudBinarySensorBase):
    """Whether the disk reports itself as healthy."""

    def __init__(
        self, coordinator, device_info, serial_number, disk_key, disk_name
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_healthy",
            f"{disk_name} Healthy",
            "mdi:shield-check",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk is healthy."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("healthy")) if disk else None


class MyCloudDiskSleepSensor(MyCloudBinarySensorBase):
    """Whether the disk is sleeping."""

    def __init__(
        self, coordinator, device_info, serial_number, disk_key, disk_name
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_sleep",
            f"{disk_name} Sleeping",
            "mdi:sleep",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk is sleeping."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("sleep")) if disk else None


class MyCloudDiskFailedSensor(MyCloudBinarySensorBase):
    """Whether the disk reports a failure."""

    def __init__(
        self, coordinator, device_info, serial_number, disk_key, disk_name
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_failed",
            f"{disk_name} Failed",
            "mdi:alert",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk has failed."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("failed")) if disk else None


class MyCloudDiskOverTemperatureSensor(MyCloudBinarySensorBase):
    """Whether the disk is over temperature."""

    def __init__(
        self, coordinator, device_info, serial_number, disk_key, disk_name
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_over_temp",
            f"{disk_name} Over Temperature",
            "mdi:thermometer-alert",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk is over temperature."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("over_temp")) if disk else None


class MyCloudVolumeMountedSensor(MyCloudBinarySensorBase):
    """Whether the volume is mounted."""

    def __init__(
        self, coordinator, device_info, serial_number, volume_key, volume_name
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{volume_key}_volume_mounted",
            f"{volume_name} Mounted",
            "mdi:folder-pound",
        )
        self._volume_key = volume_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the volume is mounted."""
        volume = get_volume(self.coordinator, self._volume_key)
        return as_bool(volume.get("mounted")) if volume else None


class MyCloudVolumeUnlockedSensor(MyCloudBinarySensorBase):
    """Whether the volume is unlocked."""

    def __init__(
        self, coordinator, device_info, serial_number, volume_key, volume_name
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{volume_key}_volume_unlocked",
            f"{volume_name} Unlocked",
            "mdi:lock-open",
        )
        self._volume_key = volume_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the volume is unlocked."""
        volume = get_volume(self.coordinator, self._volume_key)
        return as_bool(volume.get("unlocked")) if volume else None


class MyCloudVolumeEncryptedSensor(MyCloudBinarySensorBase):
    """Whether the volume is encrypted."""

    def __init__(
        self, coordinator, device_info, serial_number, volume_key, volume_name
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{volume_key}_volume_encrypted",
            f"{volume_name} Encrypted",
            "mdi:lock",
        )
        self._volume_key = volume_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the volume is encrypted."""
        volume = get_volume(self.coordinator, self._volume_key)
        return as_bool(volume.get("encrypted")) if volume else None
