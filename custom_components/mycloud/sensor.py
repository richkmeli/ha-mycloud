"""Sensor platform for the WD My Cloud integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MyCloudCoordinator
from .entity import (
    account_attributes,
    account_count,
    as_float,
    as_int,
    build_device_info,
    build_disk_info,
    build_volume_info,
    cloud_access_state,
    coordinator_data,
    get_disk,
    get_network,
    get_volume,
    latest_alert,
    network_interfaces,
    payload_attributes,
    share_names,
    usb_device_count,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WD My Cloud sensors."""
    coordinator: MyCloudCoordinator | None = config_entry.runtime_data
    if coordinator is None:
        return

    device_info, serial_number, device_name, firmware = build_device_info(coordinator)
    parent_device_id = coordinator.device_id
    data = coordinator_data(coordinator)
    system_info = data.get("system_info") or {}

    sensors: list[SensorEntity] = [
        MyCloudCPUSensor(coordinator, device_info, serial_number),
        MyCloudMemorySensor(coordinator, device_info, serial_number),
        MyCloudStorageSensor(coordinator, device_info, serial_number, "total"),
        MyCloudStorageSensor(coordinator, device_info, serial_number, "used"),
        MyCloudStorageSensor(coordinator, device_info, serial_number, "unused"),
        MyCloudAlertCountSensor(coordinator, device_info, serial_number),
        MyCloudLatestAlertSensor(coordinator, device_info, serial_number),
        MyCloudUptimeSensor(coordinator, device_info, serial_number),
        MyCloudFirmwareSensor(coordinator, device_info, serial_number),
        MyCloudSharesSensor(coordinator, device_info, serial_number),
        MyCloudAccountsSensor(coordinator, device_info, serial_number),
        MyCloudCloudAccessSensor(coordinator, device_info, serial_number),
        MyCloudUSBDevicesSensor(coordinator, device_info, serial_number),
    ]

    network = network_interfaces(coordinator_data(coordinator).get("network"))
    for interface in sorted(network):
        sensors.append(
            MyCloudNetworkSensor(coordinator, device_info, serial_number, interface)
        )

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
            sensors.extend(
                [
                    MyCloudDiskTemperatureSensor(
                        coordinator, disk_device, serial_number, key
                    ),
                    MyCloudDiskSizeSensor(coordinator, disk_device, serial_number, key),
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
            sensors.append(
                MyCloudVolumeSizeSensor(coordinator, volume_device, serial_number, key)
            )

    async_add_entities(sensors)


class MyCloudSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for My Cloud sensors."""

    _attr_has_entity_name = True
    _attr_state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: MyCloudCoordinator,
        device_info,
        unique_id: str,
        translation_key: str,
        *,
        unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
        suggested_unit: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_suggested_unit_of_measurement = suggested_unit


class MyCloudCPUSensor(MyCloudSensorBase):
    """CPU usage of the NAS."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_cpu_usage",
            "cpu_usage",
            unit=PERCENTAGE,
        )

    @property
    def native_value(self) -> int | None:
        """Return the CPU usage percentage."""
        status = coordinator_data(self.coordinator).get("system_status") or {}
        return as_int(status.get("cpu"))


class MyCloudMemorySensor(MyCloudSensorBase):
    """Memory usage of the NAS."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_memory_usage",
            "memory_usage",
            unit=PERCENTAGE,
        )

    @property
    def native_value(self) -> float | None:
        """Return the memory usage percentage.

        ``MemAvailable`` is the kernel estimate of the memory available for
        new applications, so it excludes the reclaimable page cache and
        buffers. Older firmware only reports ``MemFree``; the previous
        calculation is kept as a fallback.
        """
        status = coordinator_data(self.coordinator).get("system_status") or {}
        memory = status.get("memory") or {}
        total = as_int(memory.get("total"))
        if total is None or total <= 0:
            return None
        available = as_int(memory.get("available"))
        if available is not None and available > 0:
            used = max(total - available, 0)
            return round((used / total) * 100, 2)
        unused = as_int(memory.get("unused"))
        if unused is None:
            return None
        return round(((total - unused) / total) * 100, 2)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the memory fields reported by the NAS."""
        status = coordinator_data(self.coordinator).get("system_status") or {}
        memory = status.get("memory") or {}
        attributes: dict[str, object] = {
            key: memory[key]
            for key in (
                "total",
                "available",
                "unused",
                "cached",
                "buffers",
                "simple",
            )
            if memory.get(key) is not None
        }
        swap_total = as_int(memory.get("swap_total"))
        swap_free = as_int(memory.get("swap_free"))
        if swap_total is not None:
            attributes["swap_total"] = swap_total
        if swap_free is not None:
            attributes["swap_free"] = swap_free
        if swap_total is not None and swap_free is not None and swap_total > 0:
            swap_used = max(swap_total - swap_free, 0)
            attributes["swap_used"] = swap_used
            attributes["swap_used_percent"] = round((swap_used / swap_total) * 100, 2)
        return attributes


class MyCloudStorageSensor(MyCloudSensorBase):
    """Total, used or unused storage of the NAS."""

    def __init__(
        self,
        coordinator,
        device_info,
        serial_number,
        value_key,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{value_key}_storage",
            f"{value_key}_storage",
            unit=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            suggested_unit=UnitOfInformation.TERABYTES,
        )
        self._value_key = value_key

    @property
    def native_value(self) -> int | None:
        """Return the storage size in bytes."""
        system_info = coordinator_data(self.coordinator).get("system_info") or {}
        size = system_info.get("size") or {}
        return as_int(size.get(self._value_key))


class MyCloudAlertCountSensor(MyCloudSensorBase):
    """Number of entries in the NAS alert log."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_alert_count",
            "alert_count",
        )

    @property
    def available(self) -> bool:
        """Return True when the alert endpoint responded."""
        alerts = coordinator_data(self.coordinator).get("alerts")
        return super().available and isinstance(alerts, list)

    @property
    def native_value(self) -> int | None:
        """Return the number of active alerts."""
        alerts = coordinator_data(self.coordinator).get("alerts")
        return len(alerts) if isinstance(alerts, list) else None


class MyCloudLatestAlertSensor(MyCloudSensorBase):
    """Newest message in the NAS alert log."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = None

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_latest_alert",
            "latest_alert",
        )

    @property
    def available(self) -> bool:
        """Return True when the alert endpoint responded."""
        alerts = coordinator_data(self.coordinator).get("alerts")
        return super().available and isinstance(alerts, list)

    @property
    def native_value(self) -> str | None:
        """Return the newest alert message."""
        alert = latest_alert(coordinator_data(self.coordinator).get("alerts"))
        if not alert:
            return None
        message = alert.get("msg")
        return str(message) if message else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the alert details as attributes."""
        alert = latest_alert(coordinator_data(self.coordinator).get("alerts"))
        if not alert:
            return {}
        return {
            "code": alert.get("code"),
            "seq_num": alert.get("seq_num"),
            "level": alert.get("level"),
            "description": alert.get("desc"),
            "time": alert.get("time"),
        }


class MyCloudUptimeSensor(MyCloudSensorBase):
    """Uptime of the NAS (OS5 only)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_uptime",
            "uptime",
            unit=UnitOfTime.SECONDS,
            device_class=SensorDeviceClass.DURATION,
            suggested_unit=UnitOfTime.HOURS,
        )

    @property
    def available(self) -> bool:
        """Return True when the uptime endpoint responded."""
        return (
            super().available
            and coordinator_data(self.coordinator).get("uptime") is not None
        )

    @property
    def native_value(self) -> int | None:
        """Return the uptime in seconds."""
        return as_int(coordinator_data(self.coordinator).get("uptime"))


class MyCloudFirmwareSensor(MyCloudSensorBase):
    """Firmware version reported by the NAS."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = None

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_firmware",
            "firmware",
        )

    @property
    def available(self) -> bool:
        """Return True when the firmware endpoint responded."""
        version = coordinator_data(self.coordinator).get("system_version")
        return super().available and isinstance(version, dict)

    @property
    def native_value(self) -> str | None:
        """Return the firmware version."""
        version = coordinator_data(self.coordinator).get("system_version") or {}
        firmware = version.get("firmware")
        return str(firmware).strip() if firmware is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the OLED text reported with the firmware."""
        version = coordinator_data(self.coordinator).get("system_version") or {}
        oled = version.get("oled")
        return {"oled": oled} if oled is not None else {}


class MyCloudSharesSensor(MyCloudSensorBase):
    """Number of shares configured on the NAS."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = None

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_shares",
            "shares",
        )

    @property
    def available(self) -> bool:
        """Return True when the share endpoint responded."""
        return (
            super().available
            and share_names(coordinator_data(self.coordinator).get("share_names"))
            is not None
        )

    @property
    def native_value(self) -> int | None:
        """Return the number of shares."""
        shares = share_names(coordinator_data(self.coordinator).get("share_names"))
        return len(shares) if shares is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the share names."""
        shares = share_names(coordinator_data(self.coordinator).get("share_names"))
        return {"shares": shares} if shares is not None else {}


class MyCloudAccountsSensor(MyCloudSensorBase):
    """User accounts reported by the NAS."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_state_class = None

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_accounts",
            "accounts",
        )

    @property
    def available(self) -> bool:
        """Return True when the account endpoint responded."""
        accounts = coordinator_data(self.coordinator).get("accounts")
        return super().available and isinstance(accounts, dict)

    @property
    def native_value(self) -> int | None:
        """Return the number of user accounts."""
        return account_count(coordinator_data(self.coordinator).get("accounts"))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the user and group details."""
        return account_attributes(coordinator_data(self.coordinator).get("accounts"))


class MyCloudCloudAccessSensor(MyCloudSensorBase):
    """Cloud access configuration reported by the NAS."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_state_class = None

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_cloud_access",
            "cloud_access",
        )

    @property
    def available(self) -> bool:
        """Return True when the cloud-access endpoint responded."""
        payload = coordinator_data(self.coordinator).get("cloud_access")
        return super().available and payload is not None

    @property
    def native_value(self) -> str | None:
        """Return a summary of the cloud-access payload."""
        return cloud_access_state(
            coordinator_data(self.coordinator).get("cloud_access")
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the complete cloud-access payload."""
        return payload_attributes(
            coordinator_data(self.coordinator).get("cloud_access")
        )


class MyCloudUSBDevicesSensor(MyCloudSensorBase):
    """USB devices reported by the NAS."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_state_class = None

    def __init__(self, coordinator, device_info, serial_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_usb_devices",
            "usb_devices",
        )

    @property
    def available(self) -> bool:
        """Return True when the USB endpoint responded."""
        payload = coordinator_data(self.coordinator).get("usb_info")
        return super().available and payload is not None

    @property
    def native_value(self) -> int | None:
        """Return the number of USB devices."""
        return usb_device_count(coordinator_data(self.coordinator).get("usb_info"))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the complete USB payload."""
        return payload_attributes(coordinator_data(self.coordinator).get("usb_info"))


class MyCloudNetworkSensor(MyCloudSensorBase):
    """IP and link details of a network interface."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = None

    def __init__(self, coordinator, device_info, serial_number, interface) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_network_{interface}",
            "network",
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
    def native_value(self) -> str | None:
        """Return the interface IP address."""
        interface = get_network(self.coordinator, self._interface)
        if not interface:
            return None
        ip_address = interface.get("ip")
        return str(ip_address).strip() if ip_address is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return every network field reported for the interface."""
        interface = get_network(self.coordinator, self._interface)
        if not interface:
            return {}
        return dict(interface)


class MyCloudDiskTemperatureSensor(MyCloudSensorBase):
    """Temperature of a physical disk."""

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_temp",
            "disk_temperature",
            unit=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
        )
        self._disk_key = disk_key

    @property
    def native_value(self) -> float | None:
        """Return the disk temperature."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_float(disk.get("temp")) if disk else None


class MyCloudDiskSizeSensor(MyCloudSensorBase):
    """Capacity of a physical disk."""

    def __init__(self, coordinator, device_info, serial_number, disk_key) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{disk_key}_disk_size",
            "disk_size",
            unit=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            suggested_unit=UnitOfInformation.TERABYTES,
        )
        self._disk_key = disk_key

    @property
    def native_value(self) -> int | None:
        """Return the disk size in bytes."""
        disk = get_disk(self.coordinator, self._disk_key)
        return as_int(disk.get("size")) if disk else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the disk details reported by the NAS."""
        disk = get_disk(self.coordinator, self._disk_key)
        if not disk:
            return {}
        return {
            key: disk[key]
            for key in (
                "id",
                "name",
                "vendor",
                "model",
                "rev",
                "sn",
                "connected",
                "failed",
                "healthy",
                "removable",
                "over_temp",
                "temp",
                "sleep",
            )
            if disk.get(key) is not None
        }


class MyCloudVolumeSizeSensor(MyCloudSensorBase):
    """Size of a logical volume."""

    def __init__(self, coordinator, device_info, serial_number, volume_key) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            device_info,
            f"{serial_number}_{volume_key}_volume_size",
            "volume_size",
            unit=UnitOfInformation.BYTES,
            device_class=SensorDeviceClass.DATA_SIZE,
            suggested_unit=UnitOfInformation.TERABYTES,
        )
        self._volume_key = volume_key

    @property
    def native_value(self) -> int | None:
        """Return the volume size in bytes."""
        volume = get_volume(self.coordinator, self._volume_key)
        return as_int(volume.get("size")) if volume else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the volume details reported by the NAS."""
        volume = get_volume(self.coordinator, self._volume_key)
        if not volume:
            return {}
        return {
            key: volume[key]
            for key in (
                "id",
                "name",
                "label",
                "encrypted",
                "unlocked",
                "mounted",
            )
            if volume.get(key) is not None
        }
