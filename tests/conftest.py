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
            "memory": {"total": 1_000, "unused": 400},
        },
        "device_info": {
            "serial_number": "NAS-SERIAL",
            "name": "My Cloud",
            "description": "EX2 Ultra",
        },
        "system_version": {"firmware": "5.31.108"},
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
        "Version": 5,
    }
    entry.options = {}
    entry.unique_id = "nas.local"
    entry.runtime_data = None
    entry.async_on_unload = MagicMock()
    return entry
