"""Tests for the sensor and binary sensor platforms."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from custom_components.mycloud import binary_sensor, sensor
from custom_components.mycloud.const import DOMAIN
from custom_components.mycloud.entity import latest_alert, parse_alert_time


def _entities(async_add_entities):
    return list(async_add_entities.call_args.args[0])


async def test_sensor_setup_creates_system_disk_and_volume_entities(
    coordinator, config_entry
):
    """All sensor entities are created with stable unique IDs."""
    hass = MagicMock()
    hass.data = {DOMAIN: {config_entry.entry_id: coordinator}}
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(hass, config_entry, async_add_entities)
    entities = _entities(async_add_entities)

    by_class = {type(entity).__name__: entity for entity in entities}
    storage = [
        entity for entity in entities if type(entity).__name__ == "MyCloudStorageSensor"
    ]
    assert len(entities) == 11
    assert by_class["MyCloudCPUSensor"].native_value == 12
    assert by_class["MyCloudMemorySensor"].native_value == 60.0
    assert {entity._value_key: entity.native_value for entity in storage} == {
        "total": 4_000_000_000_000,
        "used": 1_000_000_000_000,
        "unused": 3_000_000_000_000,
    }
    assert by_class["MyCloudAlertCountSensor"].native_value == 2
    assert by_class["MyCloudLatestAlertSensor"].native_value == "Power supply failure"
    assert by_class["MyCloudLatestAlertSensor"].extra_state_attributes == {
        "code": "1022",
        "level": "1",
        "description": "Power supply 1 failed.",
        "time": "Fri, Nov 13, 2026 11:55:36 AM",
    }
    assert by_class["MyCloudUptimeSensor"].native_value == 90_061
    assert by_class["MyCloudDiskTemperatureSensor"].native_value == 35.0
    assert by_class["MyCloudDiskSizeSensor"].native_value == 4_000_000_000_000
    assert by_class["MyCloudVolumeSizeSensor"].native_value == 3_999_000_000_000

    unique_ids = {entity.unique_id for entity in entities}
    assert "NAS-SERIAL_cpu_usage" in unique_ids
    assert "NAS-SERIAL_alert_count" in unique_ids
    assert "NAS-SERIAL_latest_alert" in unique_ids
    assert "NAS-SERIAL_uptime" in unique_ids
    assert "NAS-SERIAL_disk-1_disk_temp" in unique_ids
    assert "NAS-SERIAL_volume-1_volume_size" in unique_ids

    identifiers = {
        identifier
        for entity in entities
        for identifier in entity.device_info["identifiers"]
    }
    assert (DOMAIN, "NAS-SERIAL:disk:disk-1") in identifiers
    assert (DOMAIN, "NAS-SERIAL:volume:volume-1") in identifiers


async def test_v2_does_not_create_uptime_sensor(coordinator, config_entry):
    """Uptime is a V5-only endpoint, so V2 gets no permanently unknown sensor."""
    config_entry.data["Version"] = 2
    coordinator.data["uptime"] = None
    hass = MagicMock()
    hass.data = {DOMAIN: {config_entry.entry_id: coordinator}}
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(hass, config_entry, async_add_entities)
    entities = _entities(async_add_entities)

    assert len(entities) == 10
    assert "MyCloudUptimeSensor" not in {type(entity).__name__ for entity in entities}


def test_parse_alert_time_is_locale_independent():
    """English NAS timestamps parse regardless of the HA process locale."""
    assert parse_alert_time("Fri, Nov 13, 2026 11:55:36 AM") == datetime(
        2026, 11, 13, 11, 55, 36
    )
    assert parse_alert_time("Sun, Oct 26, 2025 12:20:06 PM") == datetime(
        2025, 10, 26, 12, 20, 6
    )
    assert parse_alert_time("Fri, Nov 13, 2026 12:05:00 AM") == datetime(
        2026, 11, 13, 0, 5
    )
    assert parse_alert_time("not a timestamp") is None
    assert parse_alert_time(None) is None


def test_latest_alert_uses_newest_parseable_entry():
    """The newest alert wins even when the list is not sorted."""
    alerts = [
        {"msg": "old", "time": "Sun, Oct 26, 2025 12:20:06 PM"},
        {"msg": "undated"},
        {"msg": "new", "time": "Fri, Nov 13, 2026 11:55:36 AM"},
    ]
    assert latest_alert(alerts)["msg"] == "new"
    assert latest_alert([{"msg": "only"}])["msg"] == "only"
    assert latest_alert([]) is None
    assert latest_alert(None) is None


async def test_binary_sensor_setup_creates_disk_and_volume_entities(
    coordinator, config_entry
):
    """All binary sensor entities are created with stable unique IDs."""
    hass = MagicMock()
    hass.data = {DOMAIN: {config_entry.entry_id: coordinator}}
    async_add_entities = MagicMock()

    await binary_sensor.async_setup_entry(hass, config_entry, async_add_entities)
    entities = _entities(async_add_entities)

    by_class = {type(entity).__name__: entity for entity in entities}
    assert len(entities) == 7
    assert by_class["MyCloudDiskHealthySensor"].is_on is True
    assert by_class["MyCloudDiskSleepSensor"].is_on is False
    assert by_class["MyCloudDiskFailedSensor"].is_on is False
    assert by_class["MyCloudDiskOverTemperatureSensor"].is_on is False
    assert by_class["MyCloudVolumeMountedSensor"].is_on is True
    assert by_class["MyCloudVolumeUnlockedSensor"].is_on is True
    assert by_class["MyCloudVolumeEncryptedSensor"].is_on is False


async def test_missing_disk_and_volume_return_unknown(coordinator, config_entry):
    """Removed hardware reports unknown instead of crashing."""
    hass = MagicMock()
    hass.data = {DOMAIN: {config_entry.entry_id: coordinator}}
    sensor_add = MagicMock()
    binary_add = MagicMock()

    await sensor.async_setup_entry(hass, config_entry, sensor_add)
    await binary_sensor.async_setup_entry(hass, config_entry, binary_add)

    coordinator.data["system_info"]["disks"] = []
    coordinator.data["system_info"]["volumes"] = []

    sensor_entities = {
        type(entity).__name__: entity for entity in _entities(sensor_add)
    }
    assert sensor_entities["MyCloudDiskTemperatureSensor"].native_value is None
    assert sensor_entities["MyCloudVolumeSizeSensor"].native_value is None

    binary_entities = {
        type(entity).__name__: entity for entity in _entities(binary_add)
    }
    assert binary_entities["MyCloudDiskHealthySensor"].is_on is None
    assert binary_entities["MyCloudVolumeMountedSensor"].is_on is None


async def test_platform_setup_without_coordinator_does_nothing(config_entry):
    """A missing coordinator is ignored instead of raising."""
    hass = MagicMock()
    hass.data = {}
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(hass, config_entry, async_add_entities)
    await binary_sensor.async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()
