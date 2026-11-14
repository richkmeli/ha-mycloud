"""Shared fixtures for the WD My Cloud tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def nas_data() -> dict:
    """Return a representative NAS payload."""
    return {
        "system_info": {
            "disks": [
                {
                    "id": "disk-1",
                    "name": "Disk 1",
                    "sn": "WD-DISK-SN",
                    "model": "WD Red",
                    "rev": "1.0",
                    "size": 4_000_000_000_000,
                    "temp": 35,
                    "healthy": 1,
                    "sleep": 0,
                    "failed": 0,
                    "over_temp": 0,
                    "connected": 1,
                    "removable": 0,
                }
            ],
            "volumes": [
                {
                    "id": "volume-1",
                    "name": "Volume_1",
                    "label": "Data",
                    "size": 3_999_000_000_000,
                    "mounted": 1,
                    "unlocked": 1,
                    "encrypted": 0,
                }
            ],
            "size": {
                "total": 4_000_000_000_000,
                "used": 1_000_000_000_000,
                "unused": 3_000_000_000_000,
            },
        },
        "system_status": {
            "cpu": 12,
            "memory": {
                "total": 1_000,
                "unused": 400,
                "simple": "400 / 1000 MB",
            },
        },
        "device_info": {
            "serial_number": "NAS-SERIAL",
            "name": "My Cloud",
            "description": "EX2 Ultra",
        },
        "system_version": {"firmware": "5.31.108", "oled": "My Cloud"},
        "share_names": ["Public", "Backup"],
        "network": {
            "AA:BB:CC:DD:EE:FF": {
                "speed": "1000",
                "dhcp_enable": True,
                "dns_manual": False,
                "ip": "192.168.1.42",
                "netmask": "255.255.255.0",
                "gateway": "192.168.1.1",
                "lan_speed": "1000 Mbps",
                "lan_enabled": True,
                "dns1": "192.168.1.1",
                "dns2": "",
                "dns3": "",
            }
        },
        "accounts": {
            "users": [
                {
                    "uid": "0",
                    "name": "admin",
                    "email": "admin@example.com",
                    "pwd": True,
                    "gid": "0",
                    "first_name": "Admin",
                    "last_name": [],
                    "hint": "",
                }
            ],
            "groups": {
                "0": {
                    "name": "administrators",
                    "user_cnt": "1",
                    "users": ["admin"],
                }
            },
        },
        "cloud_access": {
            "success": True,
            "item": {"enabled": True, "status": "on"},
        },
        "usb_info": {"success": True, "item": [{"name": "UPS"}]},
        "alerts": [
            {
                "code": "1002",
                "seq_num": "1",
                "level": "1",
                "msg": "Network connection lost",
                "desc": "The network connection is down.",
                "time": "Sun, Oct 26, 2025 12:20:06 PM",
            },
            {
                "code": "1022",
                "seq_num": "2",
                "level": "1",
                "msg": "Power supply failure",
                "desc": "Power supply 1 failed.",
                "time": "Fri, Nov 13, 2026 11:55:36 AM",
            },
        ],
        "uptime": 90_061,
    }


@pytest.fixture
def coordinator(nas_data):
    """Return a coordinator-like object with the NAS payload."""
    coordinator = MagicMock()
    coordinator.data = nas_data
    coordinator.config_entry.entry_id = "entry-1"
    coordinator.device_id = "nas-device"
    return coordinator


@pytest.fixture
def config_entry():
    """Return a config entry-like object."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.version = 1
    entry.data = {
        "Host": "nas.local",
        "Username": "admin",
        "Password": "secret",
    }
    entry.options = {}
    entry.unique_id = "nas.local"
    entry.runtime_data = None
    entry.async_on_unload = MagicMock()
    return entry
