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

from .const import CONF_VERSION
from .coordinator import MyCloudCoordinator
from .entity import (
    as_float,
    as_int,
    build_device_info,
    build_disk_info,
    build_volume_info,
    coordinator_data,
    get_disk,
    get_volume,
    latest_alert,
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
    ]

    if as_int(config_entry.data.get(CONF_VERSION)) == 5:
        sensors.append(MyCloudUptimeSensor(coordinator, device_info, serial_number))

    disks = system_info.get("disks") or []
    if isinstance(disks, list):
        for index, disk in enumerate(disks):
            if not isinstance(disk, dict):
                continue
            disk_device, key, _ = build_disk_info(
                serial_number, device_name, firmware, disk, index
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
                serial_number, device_name, volume, index
            )
            sensors.append(
                MyCloudVolumeSizeSensor(coordinator, volume_device, serial_number, key)
            )

    async_add_entities(sensors)


class MyCloudSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for My Cloud sensors."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

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
        """Return the memory usage percentage."""
        status = coordinator_data(self.coordinator).get("system_status") or {}
        memory = status.get("memory") or {}
        total = as_int(memory.get("total"))
        unused = as_int(memory.get("unused"))
        if total is None or unused is None or total <= 0:
            return None
        return round(((total - unused) / total) * 100, 2)


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
            "level": alert.get("level"),
            "description": alert.get("desc"),
            "time": alert.get("time"),
        }


class MyCloudUptimeSensor(MyCloudSensorBase):
    """Uptime of the NAS (V5 only)."""

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
    def native_value(self) -> int | None:
        """Return the uptime in seconds."""
        return as_int(coordinator_data(self.coordinator).get("uptime"))


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
