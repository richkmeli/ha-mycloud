"""Tests for the WD My Cloud power buttons."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.button import ButtonDeviceClass
from homeassistant.exceptions import HomeAssistantError

from custom_components.mycloud import button
from custom_components.mycloud.client import PowerActionBlockedError
from custom_components.mycloud.const import DOMAIN
from custom_components.mycloud.wdnas import RequestFailedError

PACKAGE = Path(__file__).parents[1] / "custom_components" / "mycloud"


def _entities(async_add_entities):
    return list(async_add_entities.call_args.args[0])


def _by_action(entities):
    return {entity.translation_key: entity for entity in entities}


async def test_button_setup_without_coordinator_does_nothing(config_entry):
    """A missing coordinator is ignored instead of raising."""
    config_entry.runtime_data = None
    async_add_entities = MagicMock()

    await button.async_setup_entry(MagicMock(), config_entry, async_add_entities)

    async_add_entities.assert_not_called()


async def test_button_setup_creates_restart_and_shutdown(coordinator, config_entry):
    """Both power buttons use the NAS device and stable unique IDs."""
    coordinator.config_entry = config_entry
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()

    await button.async_setup_entry(MagicMock(), config_entry, async_add_entities)

    entities = _by_action(_entities(async_add_entities))
    assert set(entities) == {"restart", "shutdown"}
    assert entities["restart"].unique_id == "NAS-SERIAL_restart"
    assert entities["shutdown"].unique_id == "NAS-SERIAL_shutdown"
    assert entities["restart"].device_class == ButtonDeviceClass.RESTART
    assert entities["shutdown"].device_class is None
    assert entities["restart"].entity_registry_enabled_default is True
    assert entities["shutdown"].entity_registry_enabled_default is False
    assert entities["restart"].device_info["identifiers"] == {(DOMAIN, "NAS-SERIAL")}
    assert entities["restart"].device_info["name"] == "My Cloud"
    assert entities["restart"].has_entity_name is True


async def test_restart_button_presses_the_client(coordinator, config_entry):
    """A press forwards the restart action to the client."""
    coordinator.config_entry = config_entry
    coordinator.client.async_power_action = AsyncMock()
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()
    await button.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    restart = _by_action(_entities(async_add_entities))["restart"]

    await restart.async_press()

    coordinator.client.async_power_action.assert_awaited_once_with("restart")


async def test_shutdown_button_presses_the_client(coordinator, config_entry):
    """A press forwards the shutdown action to the client."""
    coordinator.config_entry = config_entry
    coordinator.client.async_power_action = AsyncMock()
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()
    await button.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    shutdown = _by_action(_entities(async_add_entities))["shutdown"]

    await shutdown.async_press()

    coordinator.client.async_power_action.assert_awaited_once_with("shutdown")


async def test_button_reports_a_blocked_power_action(coordinator, config_entry):
    """A safety refusal is translated for the user."""
    coordinator.config_entry = config_entry
    coordinator.client.async_power_action = AsyncMock(
        side_effect=PowerActionBlockedError(2)
    )
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()
    await button.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    shutdown = _by_action(_entities(async_add_entities))["shutdown"]

    with pytest.raises(HomeAssistantError) as err:
        await shutdown.async_press()

    assert err.value.translation_key == "power_action_blocked"
    assert err.value.translation_placeholders == {"code": "2"}


@pytest.mark.parametrize(
    "side_effect",
    [
        RequestFailedError(500),
        TimeoutError(),
        OSError("offline"),
        ValueError("bad response"),
    ],
)
async def test_button_reports_a_failed_power_action(
    coordinator, config_entry, side_effect
):
    """Transport, HTTP and parsing failures are translated."""
    coordinator.config_entry = config_entry
    coordinator.client.async_power_action = AsyncMock(side_effect=side_effect)
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()
    await button.async_setup_entry(MagicMock(), config_entry, async_add_entities)
    restart = _by_action(_entities(async_add_entities))["restart"]

    with pytest.raises(HomeAssistantError) as err:
        await restart.async_press()

    assert err.value.translation_key == "power_action_failed"
    assert err.value.translation_placeholders == {"error": str(side_effect)}


async def test_button_keys_have_translations_and_icons(coordinator, config_entry):
    """Both buttons are translated and have an icon."""
    coordinator.config_entry = config_entry
    config_entry.runtime_data = coordinator
    async_add_entities = MagicMock()
    await button.async_setup_entry(MagicMock(), config_entry, async_add_entities)

    strings = json.loads((PACKAGE / "strings.json").read_text())
    icons = json.loads((PACKAGE / "icons.json").read_text())
    translated = strings["entity"]["button"]
    iconed = icons["entity"]["button"]

    assert {entity.translation_key for entity in _entities(async_add_entities)} == set(
        translated
    )
    assert set(translated) == set(iconed)
    for entity in _entities(async_add_entities):
        assert translated[entity.translation_key]["name"]
        assert iconed[entity.translation_key]["default"].startswith("mdi:")
        assert strings["exceptions"]["power_action_blocked"]["message"]
        assert strings["exceptions"]["power_action_failed"]["message"]
