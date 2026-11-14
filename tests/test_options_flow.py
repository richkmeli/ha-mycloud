"""Tests for the WD My Cloud options flow."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.mycloud.config_flow import MyCloudOptionsFlow


async def test_options_flow_shows_and_saves_interval():
    """The polling interval is shown and stored."""
    entry = MagicMock()
    entry.options = {"update_interval": 600}

    flow = MyCloudOptionsFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.handler = "entry-1"

    form = await flow.async_step_init()
    assert form["type"] == "form"
    assert form["step_id"] == "init"

    result = await flow.async_step_init({"update_interval": 120})
    assert result["type"] == "create_entry"
    assert result["data"] == {"update_interval": 120}
