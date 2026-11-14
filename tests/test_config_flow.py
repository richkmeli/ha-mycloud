"""Tests for the WD My Cloud config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from wdnas_client.exceptions import InvalidLoginError

from custom_components.mycloud.config_flow import MyCloudConfigFlow, normalize_host


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


@pytest.fixture
def flow():
    """Return a config flow with a mocked Home Assistant."""
    flow = MyCloudConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_entries.return_value = []
    flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = None
    flow.context = {"source": "user"}
    return flow


async def test_user_flow_creates_entry(flow):
    """A working NAS creates a config entry with the device name as title."""
    client = AsyncMock()
    client.device_info.return_value = {"name": "My Cloud"}
    client.system_info.return_value = {"disks": [], "volumes": []}

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await flow.async_step_user(
            {
                "Host": "nas.local",
                "Username": "admin",
                "Password": "secret",
                "Version": 5,
            }
        )

    assert result["type"] == "create_entry"
    assert result["title"] == "My Cloud"
    assert result["data"]["Host"] == "nas.local"
    client.async_close.assert_awaited_once()


async def test_user_flow_invalid_auth(flow):
    """Bad credentials show the invalid_auth error."""
    client = AsyncMock()
    client.async_connect.side_effect = InvalidLoginError("bad credentials")

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await flow.async_step_user(
            {
                "Host": "nas.local",
                "Username": "admin",
                "Password": "wrong",
                "Version": 5,
            }
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"
    client.async_close.assert_awaited_once()


async def test_user_flow_cannot_connect(flow):
    """A network error shows the cannot_connect error."""
    client = AsyncMock()
    client.async_connect.side_effect = aiohttp.ClientError("offline")

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await flow.async_step_user(
            {
                "Host": "nas.local",
                "Username": "admin",
                "Password": "secret",
                "Version": 5,
            }
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


async def test_user_flow_timeout(flow):
    """A timeout is reported as cannot_connect."""
    client = AsyncMock()
    client.async_connect.side_effect = TimeoutError()

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await flow.async_step_user(
            {
                "Host": "nas.local",
                "Username": "admin",
                "Password": "secret",
                "Version": 5,
            }
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


async def test_user_flow_rejects_invalid_host(flow):
    """A URL pasted into the host field is rejected before any connection."""
    result = await flow.async_step_user(
        {
            "Host": "http://nas.local/",
            "Username": "admin",
            "Password": "secret",
            "Version": 5,
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_host"


@pytest.fixture
def reconfigure_entry():
    """Return an existing config entry to reconfigure."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.unique_id = "nas.local"
    entry.title = "My Cloud"
    entry.data = {
        "Host": "nas.local",
        "Username": "admin",
        "Password": "secret",
        "Version": 5,
    }
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
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )
    return flow


async def test_reconfigure_updates_host_and_title(reconfigure_flow, reconfigure_entry):
    """A reconfigured host updates the entry after validating the new NAS."""
    client = AsyncMock()
    client.device_info.return_value = {"name": "New Cloud"}
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
    reconfigure_flow.async_set_unique_id.assert_awaited_once_with("new-nas.local")
    reconfigure_flow._abort_if_unique_id_configured.assert_called_once()

    kwargs = reconfigure_flow.async_update_reload_and_abort.call_args.kwargs
    assert kwargs["unique_id"] == "new-nas.local"
    assert kwargs["title"] == "New Cloud"
    assert kwargs["data"] == {
        "Host": "new-nas.local",
        "Username": "admin",
        "Password": "new-secret",
        "Version": 5,
    }
    assert reconfigure_entry.entry_id == "entry-1"


async def test_reconfigure_same_host_skips_duplicate_check(
    reconfigure_flow, reconfigure_entry
):
    """Keeping the same host does not run the duplicate-entry check."""
    client = AsyncMock()
    client.device_info.return_value = {"name": "My Cloud"}
    client.system_info.return_value = {}

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        await reconfigure_flow.async_step_reconfigure(
            {
                "Host": "nas.local",
                "Username": "admin",
                "Password": "secret",
                "Version": 5,
            }
        )

    reconfigure_flow.async_set_unique_id.assert_not_awaited()
    reconfigure_flow._abort_if_unique_id_configured.assert_not_called()
    assert (
        reconfigure_flow.async_update_reload_and_abort.call_args.kwargs["unique_id"]
        == "nas.local"
    )


async def test_reconfigure_invalid_host(reconfigure_flow):
    """An invalid host is rejected before contacting the NAS."""
    with patch("custom_components.mycloud.config_flow.MyCloudClient") as client_cls:
        result = await reconfigure_flow.async_step_reconfigure(
            {
                "Host": "http://nas.local/",
                "Username": "admin",
                "Password": "secret",
                "Version": 5,
            }
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_host"
    client_cls.assert_not_called()


async def test_reconfigure_invalid_auth(reconfigure_flow):
    """Bad credentials keep the reconfigure form open."""
    client = AsyncMock()
    client.async_connect.side_effect = InvalidLoginError("bad credentials")

    with patch(
        "custom_components.mycloud.config_flow.MyCloudClient", return_value=client
    ):
        result = await reconfigure_flow.async_step_reconfigure(
            {
                "Host": "nas.local",
                "Username": "admin",
                "Password": "wrong",
                "Version": 5,
            }
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"
    client.async_close.assert_awaited_once()
    reconfigure_flow.async_update_reload_and_abort.assert_not_called()
