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
    account_attributes,
    account_count,
    as_bool,
    as_float,
    as_int,
    build_device_info,
    build_disk_info,
    build_volume_info,
    cloud_access_state,
    get_disk,
    get_network,
    get_volume,
    latest_alert,
    network_interfaces,
    parse_alert_time,
    payload_attributes,
    share_names,
    usb_device_count,
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
    assert len(entities) == 17
    assert by_class["MyCloudCPUSensor"].native_value == 12
    assert by_class["MyCloudMemorySensor"].native_value == 60.0
    assert by_class["MyCloudMemorySensor"].extra_state_attributes == {
        "total": 1_000,
        "unused": 400,
        "simple": "400 / 1000 MB",
    }
    assert {entity._value_key: entity.native_value for entity in storage} == {
        "total": 4_000_000_000_000,
        "used": 1_000_000_000_000,
        "unused": 3_000_000_000_000,
    }
    assert by_class["MyCloudAlertCountSensor"].native_value == 2
    assert by_class["MyCloudLatestAlertSensor"].native_value == "Power supply failure"
    assert by_class["MyCloudLatestAlertSensor"].extra_state_attributes == {
        "code": "1022",
        "seq_num": "2",
        "level": "1",
        "description": "Power supply 1 failed.",
        "time": "Fri, Nov 13, 2026 11:55:36 AM",
    }
    assert by_class["MyCloudUptimeSensor"].native_value == 90_061
    assert by_class["MyCloudFirmwareSensor"].native_value == "5.31.108"
    assert by_class["MyCloudFirmwareSensor"].extra_state_attributes == {
        "oled": "My Cloud"
    }
    assert by_class["MyCloudSharesSensor"].native_value == 2
    assert by_class["MyCloudSharesSensor"].extra_state_attributes == {
        "shares": ["Public", "Backup"]
    }
    assert by_class["MyCloudAccountsSensor"].native_value == 1
    assert by_class["MyCloudAccountsSensor"].extra_state_attributes == {
        "users": coordinator.data["accounts"]["users"],
        "groups": coordinator.data["accounts"]["groups"],
    }
    assert by_class["MyCloudAccountsSensor"].entity_registry_enabled_default is False
    assert by_class["MyCloudCloudAccessSensor"].native_value == "on"
    assert by_class["MyCloudCloudAccessSensor"].extra_state_attributes == {
        "success": True,
        "item": {"enabled": True, "status": "on"},
    }
    assert by_class["MyCloudCloudAccessSensor"].entity_registry_enabled_default is False
    assert by_class["MyCloudUSBDevicesSensor"].native_value == 1
    assert by_class["MyCloudUSBDevicesSensor"].extra_state_attributes == {
        "success": True,
        "item": [{"name": "UPS"}],
    }
    assert by_class["MyCloudUSBDevicesSensor"].entity_registry_enabled_default is False
    assert by_class["MyCloudNetworkSensor"].native_value == "192.168.1.42"
    assert (
        by_class["MyCloudNetworkSensor"].extra_state_attributes
        == (coordinator.data["network"]["AA:BB:CC:DD:EE:FF"])
    )
    assert by_class["MyCloudNetworkSensor"].translation_placeholders == {
        "interface": "AA:BB:CC:DD:EE:FF"
    }
    assert by_class["MyCloudDiskTemperatureSensor"].native_value == 35.0
    assert by_class["MyCloudDiskSizeSensor"].native_value == 4_000_000_000_000
    assert by_class["MyCloudDiskSizeSensor"].extra_state_attributes == {
        "id": "disk-1",
        "name": "Disk 1",
        "sn": "WD-DISK-SN",
        "model": "WD Red",
        "rev": "1.0",
        "connected": 1,
        "failed": 0,
        "healthy": 1,
        "removable": 0,
        "over_temp": 0,
        "temp": 35,
        "sleep": 0,
    }
    assert by_class["MyCloudVolumeSizeSensor"].native_value == 3_999_000_000_000
    assert by_class["MyCloudVolumeSizeSensor"].extra_state_attributes == {
        "id": "volume-1",
        "name": "Volume_1",
        "label": "Data",
        "encrypted": 0,
        "unlocked": 1,
        "mounted": 1,
    }

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
    assert (
        by_class["MyCloudDiskTemperatureSensor"].device_info["via_device_id"]
        == "nas-device"
    )
    assert (
        by_class["MyCloudVolumeSizeSensor"].device_info["via_device_id"] == "nas-device"
    )
    assert "via_device" not in by_class["MyCloudDiskTemperatureSensor"].device_info
    assert "via_device" not in by_class["MyCloudVolumeSizeSensor"].device_info

    unique_ids = {entity.unique_id for entity in entities}
    assert "NAS-SERIAL_cpu_usage" in unique_ids
    assert "NAS-SERIAL_alert_count" in unique_ids
    assert "NAS-SERIAL_latest_alert" in unique_ids
    assert "NAS-SERIAL_uptime" in unique_ids
    assert "NAS-SERIAL_firmware" in unique_ids
    assert "NAS-SERIAL_shares" in unique_ids
    assert "NAS-SERIAL_accounts" in unique_ids
    assert "NAS-SERIAL_cloud_access" in unique_ids
    assert "NAS-SERIAL_usb_devices" in unique_ids
    assert "NAS-SERIAL_network_AA:BB:CC:DD:EE:FF" in unique_ids
    assert "NAS-SERIAL_disk-1_disk_temp" in unique_ids
    assert "NAS-SERIAL_volume-1_volume_size" in unique_ids

    identifiers = {
        identifier
        for entity in entities
        for identifier in entity.device_info["identifiers"]
    }
    assert (DOMAIN, "NAS-SERIAL:disk:disk-1") in identifiers
    assert (DOMAIN, "NAS-SERIAL:volume:volume-1") in identifiers


async def test_optional_sensors_are_unavailable_without_data(coordinator, config_entry):
    """Optional endpoints only disable their own entities."""
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    entities = {
        type(entity).__name__: entity for entity in _entities(async_add_entities)
    }

    coordinator.data["system_version"] = None
    coordinator.data["share_names"] = None
    coordinator.data["accounts"] = None
    coordinator.data["cloud_access"] = None
    coordinator.data["usb_info"] = None
    coordinator.data["network"] = None
    coordinator.data["uptime"] = None

    for name in (
        "MyCloudFirmwareSensor",
        "MyCloudSharesSensor",
        "MyCloudAccountsSensor",
        "MyCloudCloudAccessSensor",
        "MyCloudUSBDevicesSensor",
        "MyCloudNetworkSensor",
        "MyCloudUptimeSensor",
    ):
        assert entities[name].available is False

    assert entities["MyCloudFirmwareSensor"].native_value is None
    assert entities["MyCloudFirmwareSensor"].extra_state_attributes == {}
    assert entities["MyCloudSharesSensor"].native_value is None
    assert entities["MyCloudSharesSensor"].extra_state_attributes == {}
    assert entities["MyCloudAccountsSensor"].native_value is None
    assert entities["MyCloudAccountsSensor"].extra_state_attributes == {}
    assert entities["MyCloudCloudAccessSensor"].native_value is None
    assert entities["MyCloudCloudAccessSensor"].extra_state_attributes == {}
    assert entities["MyCloudUSBDevicesSensor"].native_value is None
    assert entities["MyCloudUSBDevicesSensor"].extra_state_attributes == {}
    assert entities["MyCloudNetworkSensor"].native_value is None
    assert entities["MyCloudNetworkSensor"].extra_state_attributes == {}
    assert entities["MyCloudUptimeSensor"].native_value is None


def test_disk_device_name_does_not_duplicate_disk_prefix():
    """A disk already named "Disk 1" does not become "Disk Disk 1"."""
    _, _, name = build_disk_info(
        "NAS-SERIAL",
        "NAS",
        None,
        {"id": "disk-1", "name": "Disk 1"},
        0,
        parent_device_id="nas-device",
    )
    assert name == "NAS Disk 1"

    _, _, name = build_disk_info(
        "NAS-SERIAL",
        "NAS",
        None,
        {"id": "bay-1", "name": "Bay 1"},
        0,
        parent_device_id="nas-device",
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
    assert len(entities) == 10
    assert by_class["MyCloudDiskHealthySensor"].is_on is True
    assert by_class["MyCloudDiskSleepSensor"].is_on is False
    assert by_class["MyCloudDiskFailedSensor"].is_on is False
    assert by_class["MyCloudDiskOverTemperatureSensor"].is_on is False
    assert by_class["MyCloudDiskConnectedSensor"].is_on is True
    assert by_class["MyCloudDiskRemovableSensor"].is_on is False
    assert by_class["MyCloudVolumeMountedSensor"].is_on is True
    assert by_class["MyCloudVolumeUnlockedSensor"].is_on is True
    assert by_class["MyCloudVolumeEncryptedSensor"].is_on is False
    assert by_class["MyCloudNetworkConnectedSensor"].is_on is True
    assert by_class["MyCloudNetworkConnectedSensor"].translation_placeholders == {
        "interface": "AA:BB:CC:DD:EE:FF"
    }

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
    """Non-dictionary disks, volumes and interfaces are ignored safely."""
    coordinator.data["system_info"]["disks"].append("not-a-disk")
    coordinator.data["system_info"]["volumes"].append(None)
    coordinator.data["network"]["AA:BB:CC:DD:EE:FF"] = "not-an-interface"
    config_entry.runtime_data = coordinator
    sensor_add = MagicMock()
    binary_add = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, sensor_add)
    await binary_sensor.async_setup_entry(MagicMock(), config_entry, binary_add)

    assert len(_entities(sensor_add)) == 16
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


def test_device_info_configuration_url_uses_the_entry_scheme(coordinator):
    """The device page opens the NAS with the scheme selected in the entry."""
    coordinator.config_entry.data = {"Host": "nas.local:8543", "https": True}

    info, _, _, _ = build_device_info(coordinator)

    assert info["configuration_url"] == "https://nas.local:8543"


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
    assert sensor_entities["MyCloudDiskSizeSensor"].native_value is None
    assert sensor_entities["MyCloudDiskSizeSensor"].extra_state_attributes == {}
    assert sensor_entities["MyCloudVolumeSizeSensor"].native_value is None
    assert sensor_entities["MyCloudVolumeSizeSensor"].extra_state_attributes == {}

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
        "NAS-SERIAL",
        "NAS",
        None,
        {"name": "   ", "id": ""},
        2,
        parent_device_id="nas-device",
    )
    assert key == "disk"
    assert name == "NAS Disk 3"
    assert info["identifiers"] == {(DOMAIN, "NAS-SERIAL:disk:disk")}
    assert info["via_device_id"] == "nas-device"
    assert "via_device" not in info


def test_volume_device_name_and_fallback():
    """Volumes use the label first, then the name, then the index."""
    info, key, name = build_volume_info(
        "NAS-SERIAL",
        "NAS",
        {"id": "v1", "label": "Data"},
        0,
        parent_device_id="nas-device",
    )
    assert key == "v1"
    assert name == "NAS Data"
    assert info["via_device_id"] == "nas-device"
    assert "via_device" not in info

    _, key, name = build_volume_info(
        "NAS-SERIAL",
        "NAS",
        {"name": "Backup"},
        0,
        parent_device_id="nas-device",
    )
    assert key == "Backup"
    assert name == "NAS Backup"

    _, key, name = build_volume_info(
        "NAS-SERIAL", "NAS", {}, 1, parent_device_id="nas-device"
    )
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


def test_share_and_account_helpers():
    """Share and account payloads are unwrapped defensively."""
    assert share_names(["Public", "Backup"]) == ["Public", "Backup"]
    assert share_names({"item": ["Public"]}) == ["Public"]
    assert share_names({"item": {"Public": "yes"}}) == ["Public"]
    assert share_names({"Public": "yes"}) == ["Public"]
    assert share_names("not a collection") is None
    assert share_names(None) is None

    accounts = {
        "users": [{"name": "admin"}],
        "groups": {"0": {"name": "administrators"}},
    }
    assert account_count(accounts) == 1
    assert account_count({"users": "bad"}) is None
    assert account_count(None) is None
    assert account_attributes(accounts) == {
        "users": accounts["users"],
        "groups": accounts["groups"],
    }
    assert account_attributes({"users": []}) == {"users": []}
    assert account_attributes(None) == {}


def test_network_helpers():
    """Network payloads expose only dictionary interfaces."""
    network = {
        "AA:BB": {"ip": "192.168.1.42"},
        "bad": "not-an-interface",
    }
    assert network_interfaces(network) == {"AA:BB": {"ip": "192.168.1.42"}}
    assert network_interfaces(None) == {}
    assert network_interfaces(["bad"]) == {}

    coordinator = MagicMock()
    coordinator.data = {"network": network}
    assert get_network(coordinator, "AA:BB") == {"ip": "192.168.1.42"}
    assert get_network(coordinator, "missing") is None

    coordinator.data = {"network": {"AA:BB": "bad"}}
    assert get_network(coordinator, "AA:BB") is None
    coordinator.data = {"network": "bad"}
    assert get_network(coordinator, "AA:BB") is None


def test_cloud_access_state_and_payload_attributes():
    """Free-form payloads get a readable state and full attributes."""
    assert cloud_access_state(True) == "on"
    assert cloud_access_state(False) == "off"
    assert cloud_access_state({"enabled": True}) == "on"
    assert cloud_access_state({"enabled": False}) == "off"
    assert cloud_access_state({"status": "on"}) == "on"
    assert cloud_access_state({"item": {"enabled": True}}) == "on"
    assert cloud_access_state({"value": "unknown"}) is None
    assert cloud_access_state("ready") == "ready"
    assert cloud_access_state(1) == "1"
    assert cloud_access_state(["a", "b"]) == "2"
    assert cloud_access_state(None) is None

    assert payload_attributes({"a": 1}) == {"a": 1}
    assert payload_attributes(None) == {}
    assert payload_attributes(["a"]) == {"value": ["a"]}


def test_usb_device_count():
    """USB payloads are counted without assuming a fixed schema."""
    assert usb_device_count([{"name": "UPS"}]) == 1
    assert usb_device_count({"item": [{"name": "UPS"}]}) == 1
    assert usb_device_count({"item": {"name": "UPS"}}) == 1
    assert usb_device_count({"devices": [{"name": "UPS"}]}) == 1
    assert usb_device_count({"data": [{"name": "UPS"}]}) == 1
    assert usb_device_count({"success": True}) is None
    assert usb_device_count("bad") is None
    assert usb_device_count(None) is None


async def test_network_sensor_without_ip_or_interface_is_unknown(
    coordinator, config_entry
):
    """A missing interface or IP reports unknown instead of raising."""
    coordinator.data["network"]["AA:BB:CC:DD:EE:FF"]["ip"] = None
    config_entry.runtime_data = coordinator
    sensor_add = MagicMock()
    binary_add = MagicMock()

    await sensor.async_setup_entry(MagicMock(), config_entry, sensor_add)
    await binary_sensor.async_setup_entry(MagicMock(), config_entry, binary_add)

    network = {type(entity).__name__: entity for entity in _entities(sensor_add)}[
        "MyCloudNetworkSensor"
    ]
    connected = {type(entity).__name__: entity for entity in _entities(binary_add)}[
        "MyCloudNetworkConnectedSensor"
    ]
    assert network.native_value is None
    assert connected.is_on is True
    assert connected.available is True

    coordinator.data["network"] = {}
    assert network.available is False
    assert network.native_value is None
    assert network.extra_state_attributes == {}
    assert connected.available is False
    assert connected.is_on is None


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
