"""WD My Cloud integration for Home Assistant."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import device_registry as dr

from .client import MyCloudClient, status_code
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SERIAL,
    CONF_USERNAME,
    CONF_VERSION,
    DOMAIN,
)
from .coordinator import MyCloudCoordinator
from .entity import build_device_info, get_disk, get_volume
from .wdnas import (
    AccountLockedError,
    AdminSessionBusyError,
    InvalidLoginError,
    RequestFailedError,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

type MyCloudConfigEntry = ConfigEntry[MyCloudCoordinator]


async def async_migrate_unique_id(
    hass: HomeAssistant,
    entry: MyCloudConfigEntry,
    coordinator: MyCloudCoordinator,
) -> None:
    """Migrate a legacy host-based unique ID to the NAS serial number."""
    data = coordinator.data if isinstance(coordinator.data, dict) else {}
    device = data.get("device_info") or {}
    serial = str(device.get("serial_number") or "").strip()
    if not serial:
        return
    if entry.unique_id == serial and entry.data.get(CONF_SERIAL) == serial:
        return

    legacy_host_id = entry.unique_id == entry.data.get(CONF_HOST)
    if entry.unique_id != serial and not legacy_host_id:
        _LOGGER.warning(
            "Not migrating unique ID for entry %s: unexpected value", entry.entry_id
        )
        return

    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and other.unique_id == serial:
            _LOGGER.warning(
                "Not migrating unique ID for entry %s: serial already in use",
                entry.entry_id,
            )
            return

    hass.config_entries.async_update_entry(
        entry,
        unique_id=serial,
        data={**entry.data, CONF_SERIAL: serial},
    )


async def async_setup_entry(hass: HomeAssistant, entry: MyCloudConfigEntry) -> bool:
    """Set up WD My Cloud from a config entry."""
    legacy_version = entry.data.get(CONF_VERSION)
    if legacy_version is not None and str(legacy_version).strip() != "5":
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="os2_not_supported",
        )

    host = entry.data[CONF_HOST]
    client = MyCloudClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        host,
    )

    try:
        await client.async_connect()
    except AccountLockedError as err:
        # Repeated failed logins temporarily block the account or the client
        # IP. Retry later instead of asking for the password again.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="account_locked"
        ) from err
    except AdminSessionBusyError as err:
        # Not a credential problem: another admin session is active. Retry
        # with Home Assistant's setup backoff instead of asking for reauth.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="admin_session_busy"
        ) from err
    except InvalidLoginError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except RequestFailedError as err:
        if status_code(err) in (401, 403):
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": host, "error": str(err)},
        ) from err
    except (TimeoutError, aiohttp.ClientError, OSError) as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": host, "error": str(err)},
        ) from err

    coordinator = MyCloudCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_close()
        raise

    await async_migrate_unique_id(hass, entry, coordinator)

    # Create the NAS device before the platforms so disks and volumes can use
    # its registry ID as via_device_id.
    device_info, _, _, _ = build_device_info(coordinator)
    coordinator.device_id = (
        dr.async_get(hass)
        .async_get_or_create(config_entry_id=entry.entry_id, **device_info)
        .id
    )
    entry.runtime_data = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        entry.runtime_data = None  # type: ignore[assignment]
        await coordinator.async_close()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: MyCloudConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator = entry.runtime_data
    if coordinator is not None:
        await coordinator.async_close()
        entry.runtime_data = None  # type: ignore[assignment]

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: MyCloudConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing a disk or volume that is no longer reported."""
    if not any(domain == DOMAIN for domain, _ in device_entry.identifiers):
        return False
    if device_entry.via_device_id is None:
        # The NAS itself belongs to the config entry, not to this device page.
        return False

    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return True

    data = coordinator.data if isinstance(coordinator.data, dict) else {}
    device = data.get("device_info") or {}
    serial = str(device.get("serial_number") or entry.unique_id or entry.entry_id)

    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        for kind, finder in (("disk", get_disk), ("volume", get_volume)):
            prefix = f"{serial}:{kind}:"
            if not identifier.startswith(prefix):
                continue
            key = identifier.removeprefix(prefix)
            return finder(coordinator, key) is None

    return False
