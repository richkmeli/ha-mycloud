"""Shared helpers for WD My Cloud entities."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_HOST, DOMAIN
from .wdnas import SCHEME

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
    reported_serial = str(device.get("serial_number") or "").strip()
    serial_number = reported_serial or entry_id
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
    if reported_serial:
        info["serial_number"] = reported_serial
    return info, serial_number, device_name, firmware


def disk_key(disk: dict[str, Any]) -> str:
    """Return the stable key used to match a disk across polls."""
    for value in (disk.get("id"), disk.get("sn"), disk.get("name")):
        if value is not None and str(value).strip():
            return str(value).strip()
    return "disk"


def build_disk_info(
    serial_number: str,
    device_name: str,
    firmware: str | None,
    disk: dict[str, Any],
    index: int,
    *,
    parent_device_id: str | None,
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
    )
    if parent_device_id is not None:
        info["via_device_id"] = parent_device_id
    if disk_serial := str(disk.get("sn") or "").strip():
        info["serial_number"] = disk_serial
    return info, key, name


def volume_key(volume: dict[str, Any]) -> str:
    """Return the stable key used to match a volume across polls."""
    for value in (volume.get("id"), volume.get("name")):
        if value is not None and str(value).strip():
            return str(value).strip()
    return "volume"


def build_volume_info(
    serial_number: str,
    device_name: str,
    volume: dict[str, Any],
    index: int,
    *,
    parent_device_id: str | None,
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
    )
    if parent_device_id is not None:
        info["via_device_id"] = parent_device_id
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


def share_names(value: Any) -> list[Any] | None:
    """Return the share names from the NAS payload, unwrapping ``item``."""
    payload = (
        value.get("item") if isinstance(value, dict) and "item" in value else value
    )
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return list(payload)
    return None


def account_count(value: Any) -> int | None:
    """Return the number of user accounts reported by the NAS."""
    if not isinstance(value, dict):
        return None
    users = value.get("users")
    return len(users) if isinstance(users, list) else None


def account_attributes(value: Any) -> dict[str, Any]:
    """Return the account fields exposed as entity attributes."""
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in ("users", "groups") if key in value}


def network_interfaces(value: Any) -> dict[str, dict[str, Any]]:
    """Return the usable network interfaces keyed by a string identifier."""
    if not isinstance(value, dict):
        return {}
    return {
        str(key): details for key, details in value.items() if isinstance(details, dict)
    }


def get_network(coordinator, key: str) -> dict[str, Any] | None:
    """Return the current network interface matching ``key``."""
    network = coordinator_data(coordinator).get("network")
    if not isinstance(network, dict):
        return None
    for interface_key, details in network.items():
        if str(interface_key) == key and isinstance(details, dict):
            return details
    return None


def cloud_access_state(value: Any) -> str | None:
    """Return a readable state for the free-form cloud-access payload."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, dict):
        for key in ("enabled", "active", "cloud_enabled", "relay_enabled"):
            enabled = value.get(key)
            if isinstance(enabled, bool):
                return "on" if enabled else "off"
        for key in ("status", "state"):
            status = value.get(key)
            if isinstance(status, (str, int, float)) and not isinstance(status, bool):
                return str(status)
        for key in ("item", "data", "result", "cloud_access"):
            if key in value:
                state = cloud_access_state(value[key])
                if state is not None:
                    return state
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list):
        return str(len(value))
    return None


def usb_device_count(value: Any) -> int | None:
    """Return the number of USB devices in the free-form payload."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("item", "items", "devices", "usb", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return len(nested)
            if isinstance(nested, dict):
                return len(nested)
        return None
    return None


def payload_attributes(value: Any) -> dict[str, Any]:
    """Return a free-form payload as Home Assistant state attributes."""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return {"value": value}


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
