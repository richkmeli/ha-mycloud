"""Tests for the sensor and binary sensor platforms."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.mycloud import binary_sensor, sensor
from custom_components.mycloud.const import DOMAIN
from custom_components.mycloud.entity import (
    as_bool,
    as_float,
    as_int,
    build_device_info,
    build_disk_info,
    build_volume_info,
    get_disk,
    get_volume,
    latest_alert,
    parse_alert_time,
)

PACKAGE = Path(__file__).parents[1] / "custom_components" / "mycloud"


def _entities(async_add_entities):
    return list(async_add_entities.call_args.args[0])


async def test_sensor_setup_creates_system_disk_and_volume_entities(
    coordinator, config_entry
):
    """All sensor entities are created with stable unique IDs."""
    coordinator.config_entry = config_entry
    config_entry.runtime_data = coordinator
    hass = MagicMock()
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

    assert by_class["MyCloudCPUSensor"].entity_category == EntityCategory.DIAGNOSTIC
    assert by_class["MyCloudCPUSensor"].translation_key == "cpu_usage"
    assert (
        by_class["MyCloudDiskTemperatureSensor"].translation_key == "disk_temperature"
    )
    assert by_class["MyCloudVolumeSizeSensor"].translation_key == "volume_size"
    assert (
        by_class["MyCloudDiskTemperatureSensor"].device_info["name"]
        == "My Cloud Disk 1"
    )
    assert (
        by_class["MyCloudCPUSensor"].device_info["configuration_url"]
        == "http://nas.local"
    )
    assert by_class["MyCloudCPUSensor"].device_info["serial_number"] == "NAS-SERIAL"
    assert (
        by_class["MyCloudDiskTemperatureSensor"].device_info["serial_number"]
        == "WD-DISK-SN"
    )

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
    config_entry.runtime_data = coordinator
    hass = MagicMock()
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(hass, config_entry, async_add_entities)
    entities = _entities(async_add_entities)

    assert len(entities) == 10
    assert "MyCloudUptimeSensor" not in {type(entity).__name__ for entity in entities}


def test_disk_device_name_does_not_duplicate_disk_prefix():
    """A disk already named "Disk 1" does not become "Disk Disk 1"."""
    _, _, name = build_disk_info(
        "NAS-SERIAL", "NAS", None, {"id": "disk-1", "name": "Disk 1"}, 0
    )
    assert name == "NAS Disk 1"

    _, _, name = build_disk_info(
        "NAS-SERIAL", "NAS", None, {"id": "bay-1", "name": "Bay 1"}, 0
    )
    assert name == "NAS Disk Bay 1"


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
    config_entry.runtime_data = coordinator
    hass = MagicMock()
    async_add_entities = MagicMock()

    await binary_sensor.async_setup_entry(hass, config_entry, async_add_entities)
    entities = _entities(async_add_entities)

    by_class = {type(entity).__name__: entity for entity in entities}
    assert len(entities) == 9
    assert by_class["MyCloudDiskHealthySensor"].is_on is True
    assert by_class["MyCloudDiskSleepSensor"].is_on is False
    assert by_class["MyCloudDiskFailedSensor"].is_on is False
    assert by_class["MyCloudDiskOverTemperatureSensor"].is_on is False
    assert by_class["MyCloudDiskConnectedSensor"].is_on is True
    assert by_class["MyCloudDiskRemovableSensor"].is_on is False
    assert by_class["MyCloudVolumeMountedSensor"].is_on is True
    assert by_class["MyCloudVolumeUnlockedSensor"].is_on is True
    assert by_class["MyCloudVolumeEncryptedSensor"].is_on is False

    assert by_class["MyCloudDiskFailedSensor"].device_class == (
        BinarySensorDeviceClass.PROBLEM
    )
    assert by_class["MyCloudDiskOverTemperatureSensor"].device_class == (
        BinarySensorDeviceClass.PROBLEM
    )
    assert by_class["MyCloudDiskConnectedSensor"].device_class == (
        BinarySensorDeviceClass.CONNECTIVITY
    )
    assert by_class["MyCloudDiskFailedSensor"].translation_key == "disk_failed"
    assert by_class["MyCloudVolumeMountedSensor"].translation_key == "volume_mounted"


def test_sensor_device_classes_are_declared():
    """Device classes let Home Assistant render values with the right units."""
    coordinator = MagicMock()
    coordinator.data = {}
    storage = sensor.MyCloudStorageSensor(coordinator, {}, "id", "total")
    temperature = sensor.MyCloudDiskTemperatureSensor(coordinator, {}, "id", "disk-1")
    assert storage.device_class == SensorDeviceClass.DATA_SIZE
    assert temperature.device_class == SensorDeviceClass.TEMPERATURE


async def test_setup_skips_malformed_hardware_entries(coordinator, config_entry):
    """Non-dictionary disks and volumes do not create entities or raise."""
    coordinator.data["system_info"]["disks"].append("not-a-disk")
    coordinator.data["system_info"]["volumes"].append(None)
    config_entry.runtime_data = coordinator
    sensor_add = MagicMock()
    binary_add = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, sensor_add)
    await binary_sensor.async_setup_entry(MagicMock(), config_entry, binary_add)

    assert len(_entities(sensor_add)) == 11
    assert len(_entities(binary_add)) == 9


async def test_entities_without_serial_use_entry_id(coordinator, config_entry):
    """A NAS payload without a serial falls back to the config entry ID."""
    coordinator.data["device_info"].pop("serial_number")
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    entities = _entities(async_add_entities)

    assert all(entity.unique_id.startswith("entry-1_") for entity in entities)
    assert all(
        "serial_number" not in entity.device_info
        for entity in entities
        if entity.device_info["identifiers"] == {(DOMAIN, "entry-1")}
    )


def test_device_info_includes_serial_number_when_reported(coordinator):
    """The device page shows the NAS serial number when the NAS reports it."""
    coordinator.config_entry.data = {"Host": "nas.local"}

    info, serial, _, _ = build_device_info(coordinator)

    assert serial == "NAS-SERIAL"
    assert info["serial_number"] == "NAS-SERIAL"


async def test_all_entity_keys_have_translations_and_icons(coordinator, config_entry):
    """Every entity translation key is present in strings.json and icons.json."""
    config_entry.runtime_data = coordinator
    sensor_add = MagicMock()
    binary_add = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, sensor_add)
    await binary_sensor.async_setup_entry(MagicMock(), config_entry, binary_add)

    sensor_entities = _entities(sensor_add)
    binary_entities = _entities(binary_add)

    strings = json.loads((PACKAGE / "strings.json").read_text())
    icons = json.loads((PACKAGE / "icons.json").read_text())

    for platform, entities in (
        ("sensor", sensor_entities),
        ("binary_sensor", binary_entities),
    ):
        translated = strings["entity"][platform]
        iconed = icons["entity"][platform]
        assert {entity.translation_key for entity in entities} == set(translated)
        assert set(translated) == set(iconed)
        for entity in entities:
            assert translated[entity.translation_key]["name"]
            assert iconed[entity.translation_key]["default"].startswith("mdi:")


async def test_missing_disk_and_volume_return_unknown(coordinator, config_entry):
    """Removed hardware reports unknown instead of crashing."""
    config_entry.runtime_data = coordinator
    hass = MagicMock()
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
    config_entry.runtime_data = None
    hass = MagicMock()
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(hass, config_entry, async_add_entities)
    await binary_sensor.async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()


def test_disk_device_name_falls_back_when_label_is_blank():
    """A disk without a name, id or serial still gets a readable label."""
    info, key, name = build_disk_info(
        "NAS-SERIAL", "NAS", None, {"name": "   ", "id": ""}, 2
    )
    assert key == "disk"
    assert name == "NAS Disk 3"
    assert info["identifiers"] == {(DOMAIN, "NAS-SERIAL:disk:disk")}


def test_volume_device_name_and_fallback():
    """Volumes use the label first, then the name, then the index."""
    _, key, name = build_volume_info(
        "NAS-SERIAL", "NAS", {"id": "v1", "label": "Data"}, 0
    )
    assert key == "v1"
    assert name == "NAS Data"

    _, key, name = build_volume_info("NAS-SERIAL", "NAS", {"name": "Backup"}, 0)
    assert key == "Backup"
    assert name == "NAS Backup"

    _, key, name = build_volume_info("NAS-SERIAL", "NAS", {}, 1)
    assert key == "volume"
    assert name == "NAS Volume 2"


def test_lookup_helpers_handle_malformed_payloads(coordinator):
    """Non-list collections and non-dict entries are ignored safely."""
    coordinator.data = {"system_info": {"disks": "bad", "volumes": "bad"}}
    assert get_disk(coordinator, "disk-1") is None
    assert get_volume(coordinator, "volume-1") is None

    coordinator.data = {"system_info": {"disks": ["bad"], "volumes": [None]}}
    assert get_disk(coordinator, "disk-1") is None
    assert get_volume(coordinator, "volume-1") is None


def test_numeric_and_boolean_helpers():
    """NAS values are converted defensively."""
    assert as_int("12") == 12
    assert as_int("not a number") is None
    assert as_int(None) is None
    assert as_float("1.5") == 1.5
    assert as_float("not a number") is None
    assert as_bool(True) is True
    assert as_bool(False) is False
    assert as_bool(1) is True
    assert as_bool(0) is False
    assert as_bool("bad") is None


def test_parse_alert_time_rejects_unknown_month_and_invalid_date():
    """Locale-independent parsing rejects impossible timestamps."""
    assert parse_alert_time("Fri, Foo 13, 2026 11:55:36 AM") is None
    assert parse_alert_time("Fri, Feb 30, 2026 11:55:36 AM") is None
    assert parse_alert_time("Fri, Nov 13, 2026 01:55:36 PM") == datetime(
        2026, 11, 13, 13, 55, 36
    )


def test_latest_alert_ignores_non_dictionary_entries():
    """Malformed alert lists fall back to the first valid entry."""
    assert latest_alert(["bad", None]) is None
    assert latest_alert([None, {"msg": "fallback"}])["msg"] == "fallback"


async def test_alert_sensors_handle_missing_alerts(coordinator, config_entry):
    """Alert sensors become unavailable and unknown without an alert list."""
    config_entry.runtime_data = coordinator
    coordinator.data["alerts"] = None
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    entities = {
        type(entity).__name__: entity for entity in _entities(async_add_entities)
    }

    alert_count = entities["MyCloudAlertCountSensor"]
    latest = entities["MyCloudLatestAlertSensor"]
    assert alert_count.available is False
    assert alert_count.native_value is None
    assert latest.available is False
    assert latest.native_value is None
    assert latest.extra_state_attributes == {}


async def test_memory_sensor_returns_none_for_invalid_totals(coordinator, config_entry):
    """A zero or missing memory total is not reported as a percentage."""
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    memory = {
        type(entity).__name__: entity for entity in _entities(async_add_entities)
    }["MyCloudMemorySensor"]

    for memory_data in (
        {"total": 0, "unused": 0},
        {"total": None, "unused": 0},
        {"total": 1000, "unused": None},
    ):
        coordinator.data["system_status"]["memory"] = memory_data
        assert memory.native_value is None
