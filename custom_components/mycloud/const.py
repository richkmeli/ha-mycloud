"""Constants for the WD My Cloud integration."""

from __future__ import annotations

DOMAIN = "mycloud"

CONF_HOST = "Host"
CONF_USERNAME = "Username"
CONF_PASSWORD = "Password"  # noqa: S105
CONF_SERIAL = "Serial"
CONF_UPDATE_INTERVAL = "update_interval"

# Legacy key. It is only read to reject entries created for OS2, which this
# integration no longer supports. New entries are always OS5.
CONF_VERSION = "Version"

DEFAULT_UPDATE_INTERVAL = 600
MIN_UPDATE_INTERVAL = 30
MAX_UPDATE_INTERVAL = 86400

# The upstream wdnas-client library uses a plain aiohttp request without an
# explicit timeout. Keep every request bounded so a dead NAS cannot block the
# Home Assistant event loop forever.
REQUEST_TIMEOUT = 30
