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
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from .client import MyCloudClient, status_code
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    SUPPORTED_VERSIONS,
)

_LOGGER = logging.getLogger(__name__)

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME_RE = re.compile(rf"(?:{_LABEL}\.)*{_LABEL}", re.IGNORECASE)


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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
            except ValueError:
                errors["base"] = "invalid_host"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()

                client = MyCloudClient(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    host,
                    user_input[CONF_VERSION],
                )
                title = host
                try:
                    await client.async_connect()
                    device = await client.device_info()
                    await client.system_info()
                    title = str(device.get("name") or host).strip() or host
                except InvalidLoginError:
                    errors["base"] = "invalid_auth"
                except RequestFailedError as err:
                    errors["base"] = (
                        "invalid_auth"
                        if status_code(err) in (401, 403)
                        else "cannot_connect"
                    )
                except (TimeoutError, aiohttp.ClientError, OSError):
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error validating the NAS")
                    errors["base"] = "unknown"
                finally:
                    await client.async_close()

                if not errors:
                    return self.async_create_entry(
                        title=title,
                        data={**user_input, CONF_HOST: host},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
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
                    vol.Required(CONF_VERSION, default=5): vol.All(
                        vol.Coerce(int), vol.In(SUPPORTED_VERSIONS)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "host_example": "192.168.1.10 or wdmycloud.local"
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> dict[str, Any]:
        """Handle a re-authentication request."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Ask for a new password and verify it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entry = self._get_reauth_entry()
            client = MyCloudClient(
                entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                entry.data[CONF_HOST],
                entry.data[CONF_VERSION],
            )
            try:
                await client.async_connect()
            except InvalidLoginError:
                errors["base"] = "invalid_auth"
            except RequestFailedError as err:
                errors["base"] = (
                    "invalid_auth"
                    if status_code(err) in (401, 403)
                    else "cannot_connect"
                )
            except (TimeoutError, aiohttp.ClientError, OSError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during re-authentication")
                errors["base"] = "unknown"
            finally:
                await client.async_close()

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
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
    ) -> dict[str, Any]:
        """Update the host, credentials or software version of an entry."""
        entry = self._get_reconfigure_entry()
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
                    user_input[CONF_VERSION],
                )
                title = host
                try:
                    await client.async_connect()
                    device = await client.device_info()
                    await client.system_info()
                    title = str(device.get("name") or host).strip() or host
                except InvalidLoginError:
                    errors["base"] = "invalid_auth"
                except RequestFailedError as err:
                    errors["base"] = (
                        "invalid_auth"
                        if status_code(err) in (401, 403)
                        else "cannot_connect"
                    )
                except (TimeoutError, aiohttp.ClientError, OSError):
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error validating the NAS")
                    errors["base"] = "unknown"
                finally:
                    await client.async_close()

                if not errors:
                    if host != entry.unique_id:
                        await self.async_set_unique_id(host)
                        self._abort_if_unique_id_configured()
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=host,
                        title=title,
                        data={**entry.data, **user_input, CONF_HOST: host},
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
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
                    vol.Required(
                        CONF_VERSION, default=entry.data.get(CONF_VERSION)
                    ): vol.All(vol.Coerce(int), vol.In(SUPPORTED_VERSIONS)),
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
    ) -> dict[str, Any]:
        """Manage the polling interval."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    )
                }
            ),
            description_placeholders={
                "min_interval": str(MIN_UPDATE_INTERVAL),
                "max_interval": str(MAX_UPDATE_INTERVAL),
            },
        )
