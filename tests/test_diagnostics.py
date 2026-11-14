"""Tests for the diagnostics download."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.mycloud.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_password(coordinator, config_entry):
    """The diagnostics payload never contains the password."""
    config_entry.runtime_data = coordinator
    config_entry.title = "My Cloud"
    hass = MagicMock()

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result["entry"]["data"]["Password"] == "**REDACTED**"
    assert "secret" not in str(result)
    assert result["entry"]["data"]["Host"] == "nas.local"
    assert result["entry"]["title"] == "My Cloud"
    assert result["entry"]["unique_id"] == "nas.local"
    assert result["coordinator"]["data"] == coordinator.data


async def test_diagnostics_tolerates_unloaded_entry(config_entry):
    """An entry that is not loaded still produces diagnostics."""
    config_entry.runtime_data = None

    result = await async_get_config_entry_diagnostics(MagicMock(), config_entry)

    assert result["coordinator"] == {
        "last_update_success": None,
        "last_exception": None,
        "data": None,
    }
