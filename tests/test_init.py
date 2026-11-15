"""Tests for the WD My Cloud setup and unload lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)

from custom_components.mycloud import (
    _not_ready,
    async_migrate_unique_id,
    async_remove_config_entry_device,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.mycloud.const import (
    ACCOUNT_LOCKED_RETRY,
    ADMIN_SESSION_BUSY_RETRY,
    DOMAIN,
)
from custom_components.mycloud.wdnas import (
    AccountLockedError,
    AdminSessionBusyError,
    InvalidLoginError,
    RequestFailedError,
)


@pytest.fixture
def hass():
    """Return a mocked Home Assistant object."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries.return_value = []
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.fixture
def coordinator(nas_data):
    """Return a coordinator-like object with the NAS payload."""
    coordinator = MagicMock()
    coordinator.data = nas_data
    return coordinator


def test_not_ready_carries_the_delay_when_supported(monkeypatch):
    """A Home Assistant with retry_after support receives the delay."""

    class SupportedNotReady(Exception):
        def __init__(self, *args, **kwargs):
            super().__init__(*args)
            self.translation_key = kwargs.get("translation_key")
            self.retry_after = kwargs.get("retry_after")

    monkeypatch.setattr(
        "custom_components.mycloud.ConfigEntryNotReady", SupportedNotReady
    )

    exc = _not_ready("account_locked", ACCOUNT_LOCKED_RETRY)

    assert exc.translation_key == "account_locked"
    assert exc.retry_after == ACCOUNT_LOCKED_RETRY


def test_not_ready_falls_back_without_retry_after_support(monkeypatch):
    """Home Assistant 2026.8 rejects retry_after, so it is omitted."""

    class LegacyNotReady(Exception):
        def __init__(self, *args, **kwargs):
            if "retry_after" in kwargs:
                raise TypeError("unsupported keyword")
            super().__init__(*args)
            self.translation_key = kwargs.get("translation_key")

    monkeypatch.setattr("custom_components.mycloud.ConfigEntryNotReady", LegacyNotReady)

    exc = _not_ready("admin_session_busy", ADMIN_SESSION_BUSY_RETRY)

    assert exc.translation_key == "admin_session_busy"
    assert not hasattr(exc, "retry_after")


async def test_setup_stores_only_coordinator(hass, config_entry):
    """Setup stores the coordinator and does not duplicate credentials."""
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_close = AsyncMock()
    coordinator.data = {"device_info": {"serial_number": "NAS-SERIAL"}}
    registry = MagicMock()
    registry.async_get_or_create.return_value.id = "nas-device"

    with (
        patch(
            "custom_components.mycloud.MyCloudClient", return_value=client
        ) as client_cls,
        patch("custom_components.mycloud.MyCloudCoordinator", return_value=coordinator),
        patch("custom_components.mycloud.dr.async_get", return_value=registry),
    ):
        result = await async_setup_entry(hass, config_entry)

    assert result is True
    assert config_entry.runtime_data is coordinator
    assert "secret" not in repr(config_entry.runtime_data)
    assert hass.data == {}
    client.async_connect.assert_awaited_once()
    client_cls.assert_called_once_with("admin", "secret", "nas.local")
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    registry.async_get_or_create.assert_called_once_with(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "NAS-SERIAL")},
        name="WD My Cloud",
        manufacturer="Western Digital",
        model=None,
        sw_version=None,
        serial_number="NAS-SERIAL",
        configuration_url=None,
    )
    assert coordinator.device_id == "nas-device"


async def test_setup_rejects_a_legacy_os2_entry(hass, config_entry):
    """An OS2 entry gets a clear error instead of an OS5 login attempt."""
    config_entry.data["Version"] = 2

    with patch("custom_components.mycloud.MyCloudClient") as client_cls:
        with pytest.raises(ConfigEntryError) as err:
            await async_setup_entry(hass, config_entry)

    assert err.value.translation_key == "os2_not_supported"
    client_cls.assert_not_called()
    assert config_entry.runtime_data is None


async def test_setup_accepts_a_legacy_os5_version_key(hass, config_entry):
    """An old OS5 entry with Version=5 still loads."""
    config_entry.data["Version"] = 5
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_close = AsyncMock()
    coordinator.data = {"device_info": {"serial_number": "NAS-SERIAL"}}
    registry = MagicMock()
    registry.async_get_or_create.return_value.id = "nas-device"

    with (
        patch("custom_components.mycloud.MyCloudClient", return_value=client),
        patch("custom_components.mycloud.MyCloudCoordinator", return_value=coordinator),
        patch("custom_components.mycloud.dr.async_get", return_value=registry),
    ):
        assert await async_setup_entry(hass, config_entry) is True


async def test_setup_invalid_credentials_starts_reauth(hass, config_entry):
    """Invalid credentials raise ConfigEntryAuthFailed."""
    client = AsyncMock()
    client.async_connect.side_effect = InvalidLoginError("bad")

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryAuthFailed) as err:
            await async_setup_entry(hass, config_entry)

    assert err.value.translation_key == "invalid_auth"
    assert config_entry.runtime_data is None


async def test_setup_busy_admin_session_is_retried(hass, config_entry):
    """Another admin session is a transient condition, not bad credentials."""
    client = AsyncMock()
    client.async_connect.side_effect = AdminSessionBusyError("account in use")

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryNotReady) as err:
            await async_setup_entry(hass, config_entry)

    assert err.value.translation_key == "admin_session_busy"
    if hasattr(ConfigEntryNotReady, "retry_after"):
        assert err.value.retry_after == ADMIN_SESSION_BUSY_RETRY
    assert config_entry.runtime_data is None


async def test_setup_temporary_account_block_is_retried(hass, config_entry):
    """A firmware login block is delayed instead of starting reauth."""
    client = AsyncMock()
    client.async_connect.side_effect = AccountLockedError("account blocked")

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryNotReady) as err:
            await async_setup_entry(hass, config_entry)

    assert err.value.translation_key == "account_locked"
    if hasattr(ConfigEntryNotReady, "retry_after"):
        assert err.value.retry_after == ACCOUNT_LOCKED_RETRY
    assert config_entry.runtime_data is None


@pytest.mark.parametrize("status", [401, 403])
async def test_setup_auth_http_error_starts_reauth(hass, config_entry, status):
    """A 401 or 403 during setup raises ConfigEntryAuthFailed."""
    client = AsyncMock()
    client.async_connect.side_effect = RequestFailedError(status)

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryAuthFailed) as err:
            await async_setup_entry(hass, config_entry)

    assert err.value.translation_key == "invalid_auth"


async def test_setup_connection_error_is_retried(hass, config_entry):
    """A connection error raises ConfigEntryNotReady."""
    client = AsyncMock()
    client.async_connect.side_effect = aiohttp.ClientError("offline")

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryNotReady) as err:
            await async_setup_entry(hass, config_entry)

    assert err.value.translation_key == "cannot_connect"
    assert err.value.translation_placeholders == {
        "host": "nas.local",
        "error": "offline",
    }
    assert config_entry.runtime_data is None


@pytest.mark.parametrize(
    "side_effect",
    [RequestFailedError(500), TimeoutError(), OSError("offline")],
)
async def test_setup_transient_errors_are_retried(hass, config_entry, side_effect):
    """Transient failures raise ConfigEntryNotReady."""
    client = AsyncMock()
    client.async_connect.side_effect = side_effect

    with patch("custom_components.mycloud.MyCloudClient", return_value=client):
        with pytest.raises(ConfigEntryNotReady) as err:
            await async_setup_entry(hass, config_entry)

    assert err.value.translation_key == "cannot_connect"


async def test_setup_failure_closes_client(hass, config_entry):
    """A failed first refresh closes the NAS session."""
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryNotReady("not ready")
    )
    coordinator.async_close = AsyncMock()

    with (
        patch("custom_components.mycloud.MyCloudClient", return_value=client),
        patch("custom_components.mycloud.MyCloudCoordinator", return_value=coordinator),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, config_entry)

    coordinator.async_close.assert_awaited_once()
    assert config_entry.runtime_data is None


async def test_setup_platform_failure_closes_coordinator(hass, config_entry):
    """A platform setup failure drops runtime_data and closes the session."""
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_close = AsyncMock()
    coordinator.data = {"device_info": {"serial_number": "NAS-SERIAL"}}
    hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("boom")
    registry = MagicMock()
    registry.async_get_or_create.return_value.id = "nas-device"

    with (
        patch("custom_components.mycloud.MyCloudClient", return_value=client),
        patch("custom_components.mycloud.MyCloudCoordinator", return_value=coordinator),
        patch("custom_components.mycloud.dr.async_get", return_value=registry),
    ):
        with pytest.raises(RuntimeError):
            await async_setup_entry(hass, config_entry)

    coordinator.async_close.assert_awaited_once()
    assert config_entry.runtime_data is None


async def test_unload_closes_client_and_removes_data(hass, config_entry):
    """Unload closes the session and drops the coordinator."""
    coordinator = MagicMock()
    coordinator.async_close = AsyncMock()
    config_entry.runtime_data = coordinator

    assert await async_unload_entry(hass, config_entry) is True
    coordinator.async_close.assert_awaited_once()
    assert config_entry.runtime_data is None


async def test_unload_without_coordinator_is_a_noop(hass, config_entry):
    """Unloading an entry that never finished setup still succeeds."""
    config_entry.runtime_data = None

    assert await async_unload_entry(hass, config_entry) is True
    hass.config_entries.async_unload_platforms.assert_awaited_once()


async def test_unload_failure_keeps_data(hass, config_entry):
    """A failed platform unload leaves the coordinator in place."""
    coordinator = MagicMock()
    coordinator.async_close = AsyncMock()
    config_entry.runtime_data = coordinator
    hass.config_entries.async_unload_platforms.return_value = False

    assert await async_unload_entry(hass, config_entry) is False
    coordinator.async_close.assert_not_awaited()
    assert config_entry.runtime_data is coordinator


async def test_migrate_unique_id_skips_without_serial(hass, config_entry, coordinator):
    """A NAS without a serial number keeps its current unique ID."""
    coordinator.data = {"device_info": {}}

    await async_migrate_unique_id(hass, config_entry, coordinator)

    hass.config_entries.async_update_entry.assert_not_called()


async def test_migrate_unique_id_skips_when_already_migrated(
    hass, config_entry, coordinator
):
    """An entry already identified by its serial is left untouched."""
    config_entry.unique_id = "NAS-SERIAL"
    config_entry.data["Serial"] = "NAS-SERIAL"

    await async_migrate_unique_id(hass, config_entry, coordinator)

    hass.config_entries.async_update_entry.assert_not_called()


async def test_migrate_unique_id_skips_unexpected_value(
    hass, config_entry, coordinator
):
    """An unknown unique ID is not overwritten."""
    config_entry.unique_id = "something-else"

    await async_migrate_unique_id(hass, config_entry, coordinator)

    hass.config_entries.async_update_entry.assert_not_called()


async def test_migrate_unique_id_skips_duplicate_serial(
    hass, config_entry, coordinator
):
    """A second entry cannot claim a serial that is already in use."""
    other = MagicMock()
    other.entry_id = "entry-2"
    other.unique_id = "NAS-SERIAL"
    hass.config_entries.async_entries.return_value = [other]

    await async_migrate_unique_id(hass, config_entry, coordinator)

    hass.config_entries.async_update_entry.assert_not_called()


async def test_migrate_unique_id_replaces_legacy_host(hass, config_entry, coordinator):
    """A legacy host-based entry is migrated to the serial number."""
    hass.config_entries.async_entries.return_value = [config_entry]

    await async_migrate_unique_id(hass, config_entry, coordinator)

    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["unique_id"] == "NAS-SERIAL"
    assert kwargs["data"]["Serial"] == "NAS-SERIAL"
    assert kwargs["data"]["Host"] == "nas.local"


def _device(identifiers, via_device_id="nas-device"):
    """Return a device registry entry-like object."""
    device = MagicMock()
    device.identifiers = set(identifiers)
    device.via_device_id = via_device_id
    return device


async def test_remove_device_rejects_other_integrations(hass, config_entry):
    """A device that does not belong to this integration is not removable."""
    device = _device({("other", "id")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is False


async def test_remove_device_rejects_the_main_nas(hass, config_entry):
    """The main NAS device is managed by the config entry, not this callback."""
    device = _device({(DOMAIN, "NAS-SERIAL")}, via_device_id=None)

    assert await async_remove_config_entry_device(hass, config_entry, device) is False


async def test_remove_device_without_coordinator_is_allowed(hass, config_entry):
    """A stale child can be removed even when the entry is not loaded."""
    config_entry.runtime_data = None
    device = _device({(DOMAIN, "NAS-SERIAL:disk:disk-1")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is True


async def test_remove_device_present_disk_is_rejected(hass, config_entry, coordinator):
    """A disk still reported by the NAS cannot be removed."""
    config_entry.runtime_data = coordinator
    device = _device({(DOMAIN, "NAS-SERIAL:disk:disk-1")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is False


async def test_remove_device_missing_disk_is_allowed(hass, config_entry, coordinator):
    """A disk no longer reported by the NAS can be removed."""
    config_entry.runtime_data = coordinator
    device = _device({(DOMAIN, "NAS-SERIAL:disk:disk-9")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is True


async def test_remove_device_missing_volume_is_allowed(hass, config_entry, coordinator):
    """A volume no longer reported by the NAS can be removed."""
    config_entry.runtime_data = coordinator
    device = _device({(DOMAIN, "NAS-SERIAL:volume:volume-9")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is True


async def test_remove_device_present_volume_is_rejected(
    hass, config_entry, coordinator
):
    """A volume still reported by the NAS cannot be removed."""
    config_entry.runtime_data = coordinator
    device = _device({(DOMAIN, "NAS-SERIAL:volume:volume-1")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is False


async def test_remove_device_unknown_identifier_is_rejected(
    hass, config_entry, coordinator
):
    """An identifier that is not a disk or volume cannot be removed."""
    config_entry.runtime_data = coordinator
    device = _device({(DOMAIN, "NAS-SERIAL:other:value"), ("other", "value")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is False


async def test_remove_device_uses_entry_unique_id_without_device_info(
    hass, config_entry, coordinator
):
    """The serial falls back to the entry unique ID when the payload is empty."""
    coordinator.data = {}
    config_entry.runtime_data = coordinator
    config_entry.unique_id = "NAS-SERIAL"
    device = _device({(DOMAIN, "NAS-SERIAL:disk:disk-9")})

    assert await async_remove_config_entry_device(hass, config_entry, device) is True
