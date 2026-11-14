"""Binary sensor platform for the WD My Cloud integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MyCloudCoordinator
from .entity import (
    as_bool,
    build_device_info,
    build_disk_info,
    build_volume_info,
    coordinator_data,
    get_disk,
    get_network,
    get_volume,
    network_interfaces,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WD My Cloud binary sensors."""
    coordinator: MyCloudCoordinator | None = config_entry.runtime_data
    if coordinator is None:
        return

    device_info, serial_number, device_name, firmware = build_device_info(coordinator)
    parent_device_id = coordinator.device_id
    system_info = (coordinator_data(coordinator).get("system_info")) or {}

    entities: list[BinarySensorEntity] = []

    disks = system_info.get("disks") or []
    if isinstance(disks, list):
        for index, disk in enumerate(disks):
            if not isinstance(disk, dict):
                continue
            disk_device, key, _ = build_disk_info(
                serial_number,
                device_name,
                firmware,
                disk,
                index,
                parent_device_id=parent_device_id,
            )
            entities.extend(
                [
                    MyCloudDiskHealthySensor(
                        coordinator, disk_device, serial_number, key
                    ),
                    MyCloudDiskSleepSensor(
                        coordinator, disk_device, serial_number, key
                    ),
                    MyCloudDiskFailedSensor(
                        coordinator, disk_device, serial_number, key
                    ),
                    MyCloudDiskOverTemperatureSensor(
                        coordinator, disk_device, serial_number, key
                    ),
                    MyCloudDiskConnectedSensor(
                        coordinator, disk_device, serial_number, key
                    ),
                    MyCloudDiskRemovableSensor(
                        coordinator, disk_device, serial_number, key
                    ),
                ]
            )

    volumes = system_info.get("volumes") or []
    if isinstance(volumes, list):
        for index, volume in enumerate(volumes):
            if not isinstance(volume, dict):
                continue
            volume_device, key, _ = build_volume_info(
                serial_number,
                device_name,
                volume,
                index,
                parent_device_id=parent_device_id,
            )
            entities.extend(
                [
                    MyCloudVolumeMountedSensor(
                        coordinator, volume_device, serial_number, key
                    ),
                    MyCloudVolumeUnlockedSensor(
                        coordinator, volume_device, serial_number, key
                    ),
                    MyCloudVolumeEncryptedSensor(
                        coordinator, volume_device, serial_number, key
                    ),
                ]
            )

    network = network_interfaces(coordinator_data(coordinator).get("network"))
    for interface in sorted(network):
        entities.append(
            MyCloudNetworkConnectedSensor(
                coordinator, device_info, serial_number, interface
            )
        )

    async_add_entities(entities)


class MyCloudBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for My Cloud binary sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MyCloudCoordinator,
        device_info,
        unique_id: str,
        translation_key: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key


class MyCloudDiskHealthySensor(MyCloudBinarySensorBase):
    """Whether the disk reports itself as healthy."""

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_healthy",
            "disk_healthy",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk is healthy."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("healthy")) if disk else None


class MyCloudDiskSleepSensor(MyCloudBinarySensorBase):
    """Whether the disk is sleeping."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_sleep",
            "disk_sleeping",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk is sleeping."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("sleep")) if disk else None


class MyCloudDiskFailedSensor(MyCloudBinarySensorBase):
    """Whether the disk reports a failure."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_failed",
            "disk_failed",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk has failed."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("failed")) if disk else None


class MyCloudDiskOverTemperatureSensor(MyCloudBinarySensorBase):
    """Whether the disk is over temperature."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_over_temp",
            "disk_over_temperature",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk is over temperature."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("over_temp")) if disk else None


class MyCloudDiskConnectedSensor(MyCloudBinarySensorBase):
    """Whether the disk is currently connected."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_connected",
            "disk_connected",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool:
        """Return True while the disk is present and connected."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("connected")) if disk else False


class MyCloudDiskRemovableSensor(MyCloudBinarySensorBase):
    """Whether the disk is removable."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_removable",
            "disk_removable",
        )
        self._disk_key = disk_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the disk is removable."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_bool(disk.get("removable")) if disk else None


class MyCloudVolumeMountedSensor(MyCloudBinarySensorBase):
    """Whether the volume is mounted."""

    def __init__(self, coordinator, device_info, serial_number, volume_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{volume_key}_volume_mounted",
            "volume_mounted",
        )
        self._volume_key = volume_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the volume is mounted."""
        volume = get_volume(self.coordinator, self._volume_key)
        return as_bool(volume.get("mounted")) if volume else None


class MyCloudVolumeUnlockedSensor(MyCloudBinarySensorBase):
    """Whether the volume is unlocked."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number, volume_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{volume_key}_volume_unlocked",
            "volume_unlocked",
        )
        self._volume_key = volume_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the volume is unlocked."""
        volume = get_volume(self.coordinator, self._volume_key)
        return as_bool(volume.get("unlocked")) if volume else None


class MyCloudVolumeEncryptedSensor(MyCloudBinarySensorBase):
    """Whether the volume is encrypted."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number, volume_key) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{volume_key}_volume_encrypted",
            "volume_encrypted",
        )
        self._volume_key = volume_key

    @property
    def is_on(self) -> bool | None:
        """Return True when the volume is encrypted."""
        volume = get_volume(self.coordinator, self._volume_key)
        return as_bool(volume.get("encrypted")) if volume else None


class MyCloudNetworkConnectedSensor(MyCloudBinarySensorBase):
    """Whether a network interface is enabled."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number, interface) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_network_{interface}_connected",
            "network_connected",
        )
        self._interface = interface
        self._attr_translation_placeholders = {"interface": interface}

    @property
    def available(self) -> bool:
        """Return True while the interface is reported."""
        return (
            super().available
            and get_network(self.coordinator, self._interface) is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return True when the interface is enabled."""
        interface = get_network(self.coordinator, self._interface)
        return as_bool(interface.get("lan_enabled")) if interface else None
