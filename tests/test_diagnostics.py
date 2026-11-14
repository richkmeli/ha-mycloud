"""Tests for the diagnostics download."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.mycloud.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_password(coordinator, config_entry):
    """The diagnostics payload never contains the password."""
    config_entry.runtime_data = coordinator
    hass = MagicMock()

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result["entry"]["data"]["Password"] == "**REDACTED**"
    assert "secret" not in str(result)
    assert result["entry"]["data"]["Host"] == "nas.local"
