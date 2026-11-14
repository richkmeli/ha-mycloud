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
