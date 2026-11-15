"""Config flow for the WD My Cloud integration."""

from __future__ import annotations

import logging
import re
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import MyCloudClient, status_code
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SERIAL,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)
from .wdnas import (
    AccountLockedError,
    AdminSessionBusyError,
    InvalidLoginError,
    RequestFailedError,
)

_LOGGER = logging.getLogger(__name__)

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME_RE = re.compile(rf"(?:{_LABEL}\.)*{_LABEL}", re.IGNORECASE)


def _schema(schema: dict[Any, Any]) -> Any:
    """Return a form schema accepted by every supported HA release.

    Home Assistant 2026.11 annotates form schemas with probatio, while the
    minimum supported release uses voluptuous. Both accept voluptuous schemas
    at runtime.
    """
    return vol.Schema(schema)


def _login_error_key(err: Exception) -> str:
    """Translate a NAS login error into a config flow error key."""
    if isinstance(err, AccountLockedError):
        return "account_locked"
    if isinstance(err, AdminSessionBusyError):
        return "admin_session_busy"
    if isinstance(err, InvalidLoginError):
        return "invalid_auth"
    if isinstance(err, RequestFailedError):
        return "invalid_auth" if status_code(err) in (401, 403) else "cannot_connect"
    if isinstance(err, (TimeoutError, aiohttp.ClientError, OSError)):
        return "cannot_connect"
    return "unknown"


def normalize_host(value: str) -> str:
    """Validate and normalize a NAS host.

    Only a hostname, IPv4/IPv6 address and optional port are accepted.  Schemes,
    paths, query strings, fragments and credentials are rejected so the value
    cannot be used to build an unexpected URL or inject headers.
    """
    if not isinstance(value, str):
        raise ValueError("Host must be a string")

    value = value.strip()
    if not value or len(value) > 253:
        raise ValueError("Invalid host length")
    if any(ord(char) < 33 for char in value):
        raise ValueError("Host contains whitespace or control characters")
    if any(char in value for char in "/\\?#@"):
        raise ValueError("Host must not contain a scheme, path or credentials")

    try:
        parsed = urlsplit(f"//{value}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as err:
        raise ValueError("Invalid host") from err

    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.netloc.endswith(":")
    ):
        raise ValueError("Invalid host")

    try:
        ip_address(hostname)
    except ValueError:
        if not _HOSTNAME_RE.fullmatch(hostname):
            raise ValueError("Invalid hostname") from None

    host = hostname.lower()
    normalized = f"[{host}]" if ":" in host else host
    if port is not None:
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
        normalized = f"{normalized}:{port}"
    return normalized


class MyCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WD My Cloud."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return MyCloudOptionsFlow()

    async def _async_release_admin_session(
        self, entry: config_entries.ConfigEntry
    ) -> bool:
        """Unload a loaded entry so the NAS accepts a new admin session.

        OS5 firmware allows one admin session at a time. The coordinator keeps
        the entry's session open, so validating new credentials while the
        entry is loaded fails with ``invalid_auth`` on the second login.
        """
        if entry.state is not ConfigEntryState.LOADED:
            return False
        return await self.hass.config_entries.async_unload(entry.entry_id)

    def _async_restore_entry(self, entry: config_entries.ConfigEntry) -> None:
        """Reload an entry that was unloaded only for validation."""
        if entry.state is not ConfigEntryState.LOADED:
            self.hass.config_entries.async_schedule_reload(entry.entry_id)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
            except ValueError:
                errors["base"] = "invalid_host"
            else:
                client = MyCloudClient(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    host,
                )
                title = host
                serial = ""
                try:
                    await client.async_connect()
                    device = await client.device_info()
                    await client.system_info()
                    title = str(device.get("name") or host).strip() or host
                    serial = str(device.get("serial_number") or "").strip()
                except Exception as err:
                    errors["base"] = _login_error_key(err)
                    if errors["base"] == "unknown":
                        _LOGGER.exception("Unexpected error validating the NAS")
                finally:
                    await client.async_close()

                if not errors:
                    unique_id = serial or host
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    data = {
                        CONF_HOST: host,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                    if serial:
                        data[CONF_SERIAL] = serial
                    return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(
                {
                    vol.Required(CONF_HOST): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_USERNAME): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "host_example": "192.168.1.10 or wdmycloud.local"
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a re-authentication request."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password and verify it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entry = self._get_reauth_entry()
            released = await self._async_release_admin_session(entry)
            reload_requested = False
            try:
                client = MyCloudClient(
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    entry.data[CONF_HOST],
                )
                try:
                    await client.async_connect()
                except Exception as err:
                    errors["base"] = _login_error_key(err)
                    if errors["base"] == "unknown":
                        _LOGGER.exception("Unexpected error during re-authentication")
                finally:
                    await client.async_close()

                if not errors:
                    data = {
                        key: value
                        for key, value in entry.data.items()
                        if key != CONF_VERSION
                    }
                    data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                    result = self.async_update_reload_and_abort(entry, data=data)
                    reload_requested = True
                    return result
            finally:
                if released and not reload_requested:
                    self._async_restore_entry(entry)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the host or credentials of an entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
            except ValueError:
                errors["base"] = "invalid_host"
            else:
                released = await self._async_release_admin_session(entry)
                reload_requested = False
                try:
                    client = MyCloudClient(
                        user_input[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                        host,
                    )
                    title = host
                    serial = ""
                    try:
                        await client.async_connect()
                        device = await client.device_info()
                        await client.system_info()
                        title = str(device.get("name") or host).strip() or host
                        serial = str(device.get("serial_number") or "").strip()
                    except Exception as err:
                        errors["base"] = _login_error_key(err)
                        if errors["base"] == "unknown":
                            _LOGGER.exception("Unexpected error validating the NAS")
                    finally:
                        await client.async_close()

                    if not errors:
                        stored_serial = str(entry.data.get(CONF_SERIAL) or "").strip()
                        legacy_unique_id = entry.unique_id == entry.data.get(CONF_HOST)
                        if serial:
                            if stored_serial:
                                if serial != stored_serial:
                                    await self.async_set_unique_id(serial)
                                    self._abort_if_unique_id_mismatch(
                                        reason="wrong_device"
                                    )
                            elif legacy_unique_id:
                                # Entries created before 1.5.0 use the host as
                                # unique ID. Migrate them once, after checking for
                                # duplicates.
                                await self.async_set_unique_id(serial)
                                self._abort_if_unique_id_configured()
                            else:
                                await self.async_set_unique_id(serial)
                                self._abort_if_unique_id_mismatch(reason="wrong_device")

                        data = {
                            key: value
                            for key, value in {
                                **entry.data,
                                **user_input,
                                CONF_HOST: host,
                            }.items()
                            if key != CONF_VERSION
                        }
                        if serial:
                            data[CONF_SERIAL] = serial
                        result = self.async_update_reload_and_abort(
                            entry,
                            unique_id=serial or entry.unique_id,
                            title=title,
                            data=data,
                        )
                        reload_requested = True
                        return result
                finally:
                    if released and not reload_requested:
                        self._async_restore_entry(entry)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST)
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_USERNAME, default=entry.data.get(CONF_USERNAME)
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_PASSWORD, default=entry.data.get(CONF_PASSWORD)
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
            errors=errors,
        )


class MyCloudOptionsFlow(config_entries.OptionsFlowWithReload):
    """Options for the WD My Cloud integration.

    ``OptionsFlowWithReload`` reloads the entry when the saved options change,
    so the coordinator picks up the new polling interval immediately.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the polling interval."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    ),
                }
            ),
            description_placeholders={
                "min_interval": str(MIN_UPDATE_INTERVAL),
                "max_interval": str(MAX_UPDATE_INTERVAL),
            },
        )
