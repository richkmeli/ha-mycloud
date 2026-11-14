"""Diagnostics support for the WD My Cloud integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry with credentials redacted."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = dict(entry.data)
    data[CONF_PASSWORD] = "**REDACTED**"

    return {
        "entry": {
            "data": data,
            "options": dict(entry.options),
            "version": entry.version,
        },
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "last_exception": str(getattr(coordinator, "last_exception", "")) or None,
            "data": getattr(coordinator, "data", None),
        },
    }
