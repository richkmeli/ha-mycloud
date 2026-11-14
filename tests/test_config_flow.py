"""Tests for the WD My Cloud config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.data_entry_flow import AbortFlow
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from custom_components.mycloud.config_flow import (
    MyCloudConfigFlow,
    MyCloudOptionsFlow,
    normalize_host,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192.168.1.10", "192.168.1.10"),
        ("  nas.local  ", "nas.local"),
        ("NAS.LOCAL", "nas.local"),
        ("wdmycloud", "wdmycloud"),
        ("nas.local:8080", "nas.local:8080"),
        ("[2001:db8::1]", "[2001:db8::1]"),
        ("[2001:db8::1]:443", "[2001:db8::1]:443"),
    ],
)
def test_normalize_host_accepts_valid_values(value, expected):
    """Valid hostnames and addresses are normalized."""
    assert normalize_host(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "http://nas.local",
        "https://nas.local",
        "nas.local/path",
        "nas.local?x=1",
        "nas.local#fragment",
        "user@nas.local",
        "user:pass@nas.local",
        "nas.local:",
        "nas.local:0",
        "nas.local:99999",
        "bad_host",
        "nas..local",
        "nas local",
        "nas.local\nHost: evil",
    ],
)
def test_normalize_host_rejects_invalid_values(value):
    """Schemes, paths, credentials and malformed hosts are rejected."""
    with pytest.raises(ValueError):
        normalize_host(value)


@pytest.mark.parametrize("value", [None, 123, object()])
def test_normalize_host_rejects_non_strings(value):
    """Non-string values are rejected before URL parsing."""
    with pytest.raises(ValueError):
        normalize_host(value)


def test_options_flow_factory():
    """The options flow is returned by the config flow factory."""
    flow = MyCloudConfigFlow.async_get_options_flow(MagicMock())
    assert isinstance(flow, MyCloudOptionsFlow)


USER_INPUT = {
    "Host": "nas.local",
    "Username": "admin",
    "Password": "secret",
    "Version": 5,
}


@pytest.fixture
def flow():
    """Return a config flow with a mocked Home Assistant."""
    flow = MyCloudConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []
    flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = None
    flow.context = {"source": "user"}
    return flow


async def test_user_flow_creates_entry_with_serial_unique_id(flow):
    """A working NAS creates an entry identified by its serial number."""
    client = AsyncMock()
    client.device_info.return_value = {
        "name": "My Cloud",
        "serial_number": "NAS-SERIAL",
    }
    client.system_info.return_value = {"disks": [], "volumes": []}

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == "create_entry"
    assert result["title"] == "My Cloud"
    assert result["data"]["Host"] == "nas.local"
    assert result["data"]["Serial"] == "NAS-SERIAL"
    assert flow.unique_id == "NAS-SERIAL"
    client.async_close.assert_awaited_once()


async def test_user_flow_falls_back_to_host_without_serial(flow):
    """A NAS without a serial number keeps the host as unique ID."""
    client = AsyncMock()
    client.device_info.return_value = {"name": "My Cloud"}
    client.system_info.return_value = {}

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == "create_entry"
    assert "Serial" not in result["data"]
    assert flow.unique_id == "nas.local"


async def test_user_flow_aborts_for_duplicate_unique_id(flow):
    """A second entry for the same serial number is rejected."""
    client = AsyncMock()
    client.device_info.return_value = {
        "name": "My Cloud",
        "serial_number": "NAS-SERIAL",
    }
    client.system_info.return_value = {}
    flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = MagicMock(
        entry_id="other"
    )

    with (
        patch(
            "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
        ),
        pytest.raises(AbortFlow),
    ):
        await flow.async_step_user(USER_INPUT)

    client.async_close.assert_awaited_once()


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (InvalidLoginError("bad"), "invalid_auth"),
        (RequestFailedError(401), "invalid_auth"),
        (RequestFailedError(500), "cannot_connect"),
        (aiohttp.ClientError("offline"), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_maps_validation_errors(flow, exception, expected):
    """Validation errors keep the form open with a translated error key."""
    client = AsyncMock()
    client.async_connect.side_effect = exception

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await flow.async_step_user(USER_INPUT)

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == expected
    client.async_close.assert_awaited_once()


async def test_user_flow_rejects_invalid_host(flow):
    """A URL pasted into the host field is rejected before any connection."""
    with patch("custom_components.mycloud.config_flow.MyCloudClient") as client_cls:
        result = await flow.async_step_user({**USER_INPUT, "Host": "http://nas.local/"})

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_host"
    client_cls.assert_not_called()


@pytest.fixture
def reauth_entry():
    """Return an existing config entry to re-authenticate."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.unique_id = "NAS-SERIAL"
    entry.data = dict(USER_INPUT)
    entry.options = {}
    return entry


@pytest.fixture
def reauth_flow(reauth_entry):
    """Return a reauth flow with Home Assistant helpers mocked."""
    flow = MyCloudConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = reauth_entry
    flow.context = {"source": "reauth", "entry_id": "entry-1"}
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reauth_successful"}
    )
    return flow


async def test_reauth_shows_form(reauth_flow):
    """The reauth source immediately shows the password form."""
    result = await reauth_flow.async_step_reauth({})

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_confirm_updates_password(reauth_flow):
    """A valid password is stored and the entry reloads."""
    client = AsyncMock()

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ) as client_cls:
        result = await reauth_flow.async_step_reauth_confirm({"Password": "new-secret"})

    assert result["type"] == "abort"
    client_cls.assert_called_once_with("admin", "new-secret", "nas.local", 5)
    kwargs = reauth_flow.async_update_reload_and_abort.call_args.kwargs
    assert kwargs["data"]["Password"] == "new-secret"
    client.async_close.assert_awaited_once()


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (InvalidLoginError("bad"), "invalid_auth"),
        (RequestFailedError(401), "invalid_auth"),
        (RequestFailedError(500), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_reauth_confirm_maps_errors(reauth_flow, exception, expected):
    """Reauth errors keep the form open with a translated error key."""
    client = AsyncMock()
    client.async_connect.side_effect = exception

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await reauth_flow.async_step_reauth_confirm({"Password": "wrong"})

    assert result["type"] == "form"
    assert result["errors"]["base"] == expected
    reauth_flow.async_update_reload_and_abort.assert_not_called()
    client.async_close.assert_awaited_once()


@pytest.fixture
def reconfigure_entry():
    """Return an existing config entry to reconfigure."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.unique_id = "NAS-SERIAL"
    entry.title = "My Cloud"
    entry.data = {**USER_INPUT, "Serial": "NAS-SERIAL"}
    entry.options = {}
    return entry


@pytest.fixture
def reconfigure_flow(reconfigure_entry):
    """Return a reconfigure flow with Home Assistant helpers mocked."""
    flow = MyCloudConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = reconfigure_entry
    flow.context = {"source": "reconfigure", "entry_id": "entry-1"}
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow._abort_if_unique_id_mismatch = MagicMock()
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )
    return flow


async def test_reconfigure_same_device_updates_host(reconfigure_flow):
    """Changing the host of the same NAS updates the entry."""
    client = AsyncMock()
    client.device_info.return_value = {
        "name": "New Cloud",
        "serial_number": "NAS-SERIAL",
    }
    client.system_info.return_value = {"disks": [], "volumes": []}

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ) as client_cls:
        result = await reconfigure_flow.async_step_reconfigure(
            {
                "Host": "new-nas.local",
                "Username": "admin",
                "Password": "new-secret",
                "Version": 5,
            }
        )

    assert result["type"] == "abort"
    client_cls.assert_called_once_with("admin", "new-secret", "new-nas.local", 5)
    client.async_close.assert_awaited_once()
    reconfigure_flow.async_set_unique_id.assert_not_awaited()
    reconfigure_flow._abort_if_unique_id_mismatch.assert_not_called()

    kwargs = reconfigure_flow.async_update_reload_and_abort.call_args.kwargs
    assert kwargs["unique_id"] == "NAS-SERIAL"
    assert kwargs["title"] == "New Cloud"
    assert kwargs["data"] == {
        "Host": "new-nas.local",
        "Username": "admin",
        "Password": "new-secret",
        "Version": 5,
        "Serial": "NAS-SERIAL",
    }


async def test_reconfigure_rejects_a_different_device(reconfigure_flow):
    """A different serial number aborts the flow with wrong_device."""
    client = AsyncMock()
    client.device_info.return_value = {
        "name": "Other NAS",
        "serial_number": "OTHER-SERIAL",
    }
    client.system_info.return_value = {}
    reconfigure_flow._abort_if_unique_id_mismatch.side_effect = AbortFlow(
        "wrong_device"
    )

    with (
        patch(
            "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
        ),
        pytest.raises(AbortFlow),
    ):
        await reconfigure_flow.async_step_reconfigure(USER_INPUT)

    reconfigure_flow.async_set_unique_id.assert_awaited_once_with("OTHER-SERIAL")
    reconfigure_flow._abort_if_unique_id_mismatch.assert_called_once_with(
        reason="wrong_device"
    )
    reconfigure_flow.async_update_reload_and_abort.assert_not_called()


async def test_reconfigure_migrates_legacy_host_unique_id(reconfigure_flow):
    """A pre-1.5.0 entry gets its host unique ID replaced by the serial."""
    entry = reconfigure_flow.hass.config_entries.async_get_known_entry.return_value
    entry.unique_id = "nas.local"
    entry.data.pop("Serial")
    client = AsyncMock()
    client.device_info.return_value = {
        "name": "My Cloud",
        "serial_number": "NAS-SERIAL",
    }
    client.system_info.return_value = {}

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        await reconfigure_flow.async_step_reconfigure(USER_INPUT)

    reconfigure_flow.async_set_unique_id.assert_awaited_once_with("NAS-SERIAL")
    reconfigure_flow._abort_if_unique_id_configured.assert_called_once()
    assert (
        reconfigure_flow.async_update_reload_and_abort.call_args.kwargs["unique_id"]
        == "NAS-SERIAL"
    )


async def test_reconfigure_rejects_mismatch_without_stored_serial(reconfigure_flow):
    """An entry without a stored serial still validates the reported serial."""
    entry = reconfigure_flow.hass.config_entries.async_get_known_entry.return_value
    entry.unique_id = "custom-id"
    entry.data.pop("Serial")
    client = AsyncMock()
    client.device_info.return_value = {
        "name": "My Cloud",
        "serial_number": "NAS-SERIAL",
    }
    client.system_info.return_value = {}
    reconfigure_flow._abort_if_unique_id_mismatch.side_effect = AbortFlow(
        "wrong_device"
    )

    with (
        patch(
            "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
        ),
        pytest.raises(AbortFlow),
    ):
        await reconfigure_flow.async_step_reconfigure(USER_INPUT)

    reconfigure_flow.async_set_unique_id.assert_awaited_once_with("NAS-SERIAL")
    reconfigure_flow._abort_if_unique_id_mismatch.assert_called_once_with(
        reason="wrong_device"
    )
    reconfigure_flow.async_update_reload_and_abort.assert_not_called()


async def test_reconfigure_without_serial_keeps_unique_id(reconfigure_flow):
    """A NAS that does not report a serial cannot be compared."""
    client = AsyncMock()
    client.device_info.return_value = {"name": "My Cloud"}
    client.system_info.return_value = {}

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        await reconfigure_flow.async_step_reconfigure(USER_INPUT)

    reconfigure_flow.async_set_unique_id.assert_not_awaited()
    assert (
        reconfigure_flow.async_update_reload_and_abort.call_args.kwargs["unique_id"]
        == "NAS-SERIAL"
    )


async def test_reconfigure_shows_form(reconfigure_flow):
    """Opening reconfigure without input shows the prefilled form."""
    result = await reconfigure_flow.async_step_reconfigure()

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_rejects_invalid_host(reconfigure_flow):
    """An invalid host is rejected before contacting the NAS."""
    with patch("custom_components.mycloud.config_flow.MyCloudClient") as client_cls:
        result = await reconfigure_flow.async_step_reconfigure(
            {**USER_INPUT, "Host": "http://nas.local/"}
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_host"
    client_cls.assert_not_called()


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (InvalidLoginError("bad"), "invalid_auth"),
        (RequestFailedError(401), "invalid_auth"),
        (RequestFailedError(500), "cannot_connect"),
        (aiohttp.ClientError("offline"), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_reconfigure_maps_validation_errors(
    reconfigure_flow, exception, expected
):
    """Reconfigure errors keep the form open with a translated error key."""
    client = AsyncMock()
    client.async_connect.side_effect = exception

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await reconfigure_flow.async_step_reconfigure(USER_INPUT)

    assert result["type"] == "form"
    assert result["errors"]["base"] == expected
    reconfigure_flow.async_update_reload_and_abort.assert_not_called()
    client.async_close.assert_awaited_once()
