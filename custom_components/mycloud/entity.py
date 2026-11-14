"""Shared helpers for WD My Cloud entities."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from wdnas_client.const import SCHEME

from .const import CONF_HOST, DOMAIN

# The NAS returns alert times in English, for example
# "Fri, Nov 13, 2026 11:55:36 AM". Parsing them with strptime would depend on
# the Home Assistant process locale, so use a fixed English table instead.
_ALERT_TIME_RE = re.compile(
    r"(?:[A-Za-z]{3},\s*)?([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})\s+"
    r"(\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)",
    re.IGNORECASE,
)
_ALERT_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def coordinator_data(coordinator) -> dict[str, Any]:
    """Return coordinator data as a dictionary."""
    data = coordinator.data
    return data if isinstance(data, dict) else {}


def build_device_info(coordinator) -> tuple[DeviceInfo, str, str, str | None]:
    """Build the main NAS device and return its identifiers."""
    data = coordinator_data(coordinator)
    device = data.get("device_info") or {}
    version = data.get("system_version") or {}

    entry_id = getattr(coordinator.config_entry, "entry_id", DOMAIN)
    serial_number = str(device.get("serial_number") or entry_id)
    device_name = str(device.get("name") or "WD My Cloud").strip() or "WD My Cloud"
    firmware = version.get("firmware")

    entry_data = getattr(coordinator.config_entry, "data", None)
    host = entry_data.get(CONF_HOST) if isinstance(entry_data, dict) else None
    configuration_url = f"{SCHEME}{host}" if host else None

    info = DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=device_name,
        manufacturer="Western Digital",
        model=device.get("description"),
        sw_version=firmware,
        configuration_url=configuration_url,
    )
    return info, serial_number, device_name, firmware


def disk_key(disk: dict[str, Any]) -> str:
    """Return the stable key used to match a disk across polls."""
    return str(disk.get("id") or disk.get("sn") or disk.get("name") or "disk")


def build_disk_info(
    serial_number: str,
    device_name: str,
    firmware: str | None,
    disk: dict[str, Any],
    index: int,
) -> tuple[DeviceInfo, str, str]:
    """Build a disk device and return its key and display name."""
    key = disk_key(disk)
    label = str(disk.get("name") or disk.get("id") or f"Disk {index + 1}").strip()
    if not label:
        label = f"Disk {index + 1}"
    if label.lower().startswith("disk"):
        name = f"{device_name} {label}"
    else:
        name = f"{device_name} Disk {label}"

    info = DeviceInfo(
        identifiers={(DOMAIN, f"{serial_number}:disk:{key}")},
        name=name,
        manufacturer="Western Digital",
        model=disk.get("model"),
        sw_version=firmware,
        hw_version=disk.get("rev"),
        via_device=(DOMAIN, serial_number),
    )
    return info, key, name


def volume_key(volume: dict[str, Any]) -> str:
    """Return the stable key used to match a volume across polls."""
    return str(volume.get("id") or volume.get("name") or "volume")


def build_volume_info(
    serial_number: str,
    device_name: str,
    volume: dict[str, Any],
    index: int,
) -> tuple[DeviceInfo, str, str]:
    """Build a volume device and return its key and display name."""
    key = volume_key(volume)
    label = volume.get("label") or volume.get("name") or f"Volume {index + 1}"
    name = f"{device_name} {label}"

    info = DeviceInfo(
        identifiers={(DOMAIN, f"{serial_number}:volume:{key}")},
        name=name,
        manufacturer="Western Digital",
        model="Storage Volume",
        via_device=(DOMAIN, serial_number),
    )
    return info, key, name


def get_disk(coordinator, key: str) -> dict[str, Any] | None:
    """Return the current disk matching ``key``."""
    system_info = coordinator_data(coordinator).get("system_info") or {}
    disks = system_info.get("disks") or []
    if not isinstance(disks, list):
        return None
    for disk in disks:
        if isinstance(disk, dict) and disk_key(disk) == key:
            return disk
    return None


def get_volume(coordinator, key: str) -> dict[str, Any] | None:
    """Return the current volume matching ``key``."""
    system_info = coordinator_data(coordinator).get("system_info") or {}
    volumes = system_info.get("volumes") or []
    if not isinstance(volumes, list):
        return None
    for volume in volumes:
        if isinstance(volume, dict) and volume_key(volume) == key:
            return volume
    return None


def as_int(value: Any) -> int | None:
    """Convert a value to int, returning None when it is not numeric."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    """Convert a value to float, returning None when it is not numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    """Convert the NAS 0/1 values to bool, returning None when unknown."""
    if isinstance(value, bool):
        return value
    converted = as_int(value)
    return None if converted is None else bool(converted)


def parse_alert_time(value: Any) -> datetime | None:
    """Parse an alert timestamp returned by the NAS, ignoring the locale."""
    if not isinstance(value, str):
        return None

    match = _ALERT_TIME_RE.fullmatch(value.strip())
    if match is None:
        return None

    month_name, day, year, hour, minute, second, meridiem = match.groups()
    month = _ALERT_MONTHS.get(month_name.lower())
    if month is None:
        return None

    hour_value = int(hour)
    if meridiem.upper() == "AM" and hour_value == 12:
        hour_value = 0
    elif meridiem.upper() == "PM" and hour_value != 12:
        hour_value += 12

    try:
        return datetime(
            int(year),
            month,
            int(day),
            hour_value,
            int(minute),
            int(second),
        )
    except ValueError:
        return None


def latest_alert(alerts: Any) -> dict[str, Any] | None:
    """Return the newest alert, falling back to the first valid entry."""
    if not isinstance(alerts, list) or not alerts:
        return None

    dated: list[tuple[datetime, dict[str, Any]]] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        parsed = parse_alert_time(alert.get("time"))
        if parsed is not None:
            dated.append((parsed, alert))

    if dated:
        return max(dated, key=lambda item: item[0])[1]

    for alert in alerts:
        if isinstance(alert, dict):
            return alert
    return None
