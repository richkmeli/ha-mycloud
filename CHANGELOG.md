# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.3] - 2026-11-16

### Fixed

- Le azioni di alimentazione (Riavvia/Spegni) restituivano HTTP 403 sui CGI di sistema legacy (`/cgi-bin/hd_config.cgi`, `/cgi-bin/system_mgr.cgi`). Questi endpoint predate CORS e rifiutano gli header `Origin`/`Referer`/`X-Requested-With` che `nasAdmin` richiede sulle API `/nas/v1/auth`. Le power action ora omettono quegli header, mentre login, logout e tutte le richieste di dati continuano a ripeterli, mantenendo la correzione della 3.1.2 contro `request origin != token origin`.

## [3.1.2] - 2026-11-15

### Fixed

- Login on OS5 firmware that binds the authentication token to the request origin no longer fails after an accepted login. `nasAdmin` derives the token origin from `Origin`/`Referer` during `POST /nas/v1/auth`, then rejects every later request whose origin differs with `request origin != token origin`. The integration sent those headers only on login, so `device_info` and `system_info` were answered with HTTP 401 and Home Assistant reported `invalid_auth` even though the NAS log showed `"operation":"login","status":"success"`. Every authenticated request, including form posts, power actions and logout, now repeats the login's `Origin`, `Referer` and `X-Requested-With`.
- The fake-NAS contract tests now enforce the token origin on data requests and logout, like the real firmware, so a future header regression fails the suite.

## [3.1.1] - 2026-11-15

### Fixed

- A duplicate admin login is now reported as `admin_session_busy` instead of `invalid_auth`. The OS5 `nasAdmin` service answers a second login with HTTP 401 and the plain body `logged in from other IP address`; that text was not recognised, so Home Assistant opened re-authentication and kept submitting the password instead of waiting for the NAS to release the session. The body `max session time exceeded` is mapped the same way.
- Regression tests cover the exact firmware 401 body and the session-timeout message. The README now documents both replies under the busy-session troubleshooting section.

## [3.1.0] - 2026-11-15

### Added

- Optional **Use HTTPS** checkbox in initial setup and reconfigure. The Host field stays scheme-less and may include the port, for example `192.168.1.10:8543`.
- HTTPS uses a dedicated aiohttp connector that accepts the WD self-signed certificate without verification. Traffic is encrypted, but the certificate identity is not authenticated; see `SECURITY.md`.
- The standalone login diagnostic accepts `--https` or `MYCLOUD_HTTPS=1` and follows the same certificate policy as the integration.
- Tests for HTTPS URL construction, login `Origin`/`Referer`, connector setup, setup/reauth/reconfigure propagation, config-flow translations and a fake NAS served over TLS with a self-signed certificate.

### Changed

- Every API request, login header and power action now follows the scheme selected for the entry.
- The HTTPS option is stored only when enabled. Existing entries and new entries that leave the checkbox off continue to use HTTP.

### Fixed

- Login failed with `invalid_auth` when OS5 served the web interface only over HTTPS, commonly on port 8543, because the vendored client always used `http://` and an HTTP-to-HTTPS redirect lost the login request. Set the Host to the NAS address with the port and enable **Use HTTPS**.

## [3.0.8] - 2026-11-15

### Fixed

- Login now accepts the authentication cookies used by newer OS5 firmware. The NAS admin API sets `fe97238703cba` and `ge41881ed8d9r` instead of `PHPSESSID`; the integration previously rejected an otherwise successful login because it required `PHPSESSID`. It now accepts any non-empty cookie from a 200 login response, while still preferring `PHPSESSID` on older firmware.
- An explicit OS5 JSON error code is now rejected even when the login response is HTTP 200 and also sets a cookie.

### Changed

- The accepted-login and rejected-login debug lines now list the cookie names and JSON body keys, never their values. This identifies the firmware's cookie naming and the response shape in the next report.
- The standalone login diagnostic now treats any non-empty session cookie as usable and lists the cookie names seen on the final response, the redirect chain and the cookie jar.
- Fake-NAS tests now run the full login, data and logout cycle with `PHPSESSID`, `fe97238703cba` and `ge41881ed8d9r`, and cover a 200 response without a cookie and a 200 JSON error.

## [3.0.7] - 2026-11-15

### Added

- Dedicated `password_expired` and `not_admin` config-flow errors for the OS5 JSON codes `-1` and `-2`. These codes were previously reported as generic `invalid_auth`, even though the password or account needs a different fix.
- Debug logs now name the failing data endpoint and its HTTP status, and confirm when a login is accepted. This separates a rejected login from a later `401`/`403` on `device_info` or `system_info`.

### Fixed

- Login requests now send the same `Origin`, `Referer` and `X-Requested-With` headers as the NAS web interface. Some firmware revisions validate the request origin or expect the dashboard's XHR headers.
- A broken error body no longer replaces the HTTP status in a failed data request.

## [3.0.6] - 2026-11-15

### Added

- `scripts/ssh_recover.py`, an optional standalone SSH recovery helper for a stale `nasAdmin` admin session. It runs a fixed read-only discovery report by default and can restart only the allowlisted `nasadmin`, `php-fpm`, `apache` and `restsdk` services after an exact `--confirm` value. It uses strict host-key verification, never stores credentials and is not part of the integration or the HACS archive.

### Fixed

- Login failures now parse the OS5 JSON response body. The firmware returns `{"error": "-3"}` for a temporary account lock and `{"error": "5"}` when another admin session is active; both were previously reported as generic HTTP failures. Integer and string forms are accepted, and the JSON code takes precedence over localized text in other fields.

## [3.0.5] - 2026-11-15

### Fixed

- Restore compatibility with Home Assistant 2026.8, which does not support `ConfigEntryNotReady.retry_after`. The account-lock and busy-session setup delays are applied when Home Assistant supports them and omitted otherwise, instead of failing setup with a `TypeError`.

## [3.0.4] - 2026-11-15

### Fixed

- Setup now passes the account-lock and busy-session delays to Home Assistant's setup retry. A locked account or an active admin session is no longer retried with the default fast backoff, which could keep submitting the password and extend the block.

## [3.0.3] - 2026-11-15

### Added

- Dedicated `account_locked` error when the NAS temporarily blocks the admin account or the client IP after repeated failed logins. Setup retries with Home Assistant's backoff and the coordinator retries after 30 minutes, instead of asking for the password again.
- `scripts/diagnose_login.py`, a standalone diagnostic that performs one login and prints the HTTP status, redirect chain, cookie attributes and response body with secrets redacted. It is not imported by the integration and is not a runtime dependency.
- Login failures are logged at debug level with the HTTP status, redirect count, content type and a sanitized body, never the password or cookie values.
- Tests for redirect cookies, malformed `Set-Cookie` headers, account blocks, expanded busy-session messages and redacted login logging.

### Changed

- Busy-session detection now also recognises "already logged in", "already connected", "another session", "maximum sessions", "session limit" and the corresponding Italian phrases.
- The `invalid_auth` message now explains that another admin session can produce the same error, instead of implying that the password is always wrong.

### Fixed

- A login that sets `PHPSESSID` on an intermediate redirect response now authenticates correctly. Previously only the final response and the session cookie jar were checked, so a valid login could be reported as invalid credentials.
- A malformed `Set-Cookie` header is ignored instead of failing the complete login.

## [3.0.2] - 2026-11-15

### Added

- Dedicated `admin_session_busy` error when another admin session is active on the NAS. Setup retries with backoff and the coordinator retries after five minutes, instead of asking for the password again.
- Contract tests against a local fake OS5 NAS covering the single admin session, the path-scoped `PHPSESSID` cookie and the server-side logout.
- `mypy` type checking in CI.

### Changed

- The NAS parser now tolerates missing disk and volume IDs, textual or unexpected boolean flags and non-numeric fields. A partial payload no longer makes every core sensor unavailable.
- A malformed core response, for example a login HTML page instead of XML, triggers one reconnect and retry before reporting a failure.

### Fixed

- Share list responses without an `item` list are treated as empty instead of failing the endpoint.

## [3.0.1] - 2026-11-15

### Fixed

- Reconfigure and re-authentication now unload the existing entry and release its NAS admin session before validating the new credentials. OS5 allows a single admin session, so the validation previously failed with `invalid_auth` even when the host and credentials were correct.
- Closing the client now logs out with `DELETE /nas/v1/auth` before closing the local HTTP session. The logout is best effort, so an unreachable NAS cannot block a reload or unload, but it prevents an orphaned admin session from blocking the next login.

## [3.0.0] - 2026-11-14

### Added

- All remaining OS5 data is now exposed, so users can enable only the entities they need:
  - **Firmware** sensor, with the OLED text as an attribute.
  - **Shares** sensor, with the share list as an attribute.
  - **Network** sensor per interface, with the IP address as state and link speed, DHCP, DNS, netmask, gateway and interface state as attributes.
  - **Accounts** sensor, with user and group details. It is disabled by default because it contains personal data.
  - **Cloud access** sensor, with the complete NAS payload. It is disabled by default.
  - **USB devices** sensor, with the complete payload. It is disabled by default until the schema is validated.
  - **Network connected** binary sensor per interface.
- Extra attributes on existing sensors: raw memory fields (total, unused and simple), alert sequence number, full disk hardware fields and volume fields.
- **Restart** and **Shutdown** buttons. Restart is enabled by default; Shutdown is created disabled and can be enabled from the entity registry. The integration runs the NAS `cgi_Detect_Dangerous` safety check first, sends the action once and never retries.

### Changed

- **Breaking:** the integration now supports OS5 firmware only. Entries created for OS2 stop during setup with a clear `os2_not_supported` error. Users still on OS2 must update the NAS or stay on integration 2.0.0.
- The config and reconfigure flows no longer ask for the software version; new entries are always OS5.
- Restart and Shutdown are normal entities instead of an options-flow toggle, and the `power_controls` option was removed.
- The coordinator also reloads the entry when network interfaces are added, removed or replaced, so their entities are created automatically.
- Optional endpoint failures are isolated per endpoint and no longer affect the core sensors.
- Diagnostics also redact the account lists and the cloud-access and USB payloads, not only the password.
- The OS5 protocol client is now vendored in `custom_components/mycloud/wdnas.py`, based on `wdnas-client` 0.9.4 under its MIT license. There is no external runtime dependency, and the client is covered by the same per-module coverage gate as the integration.
- The vendored client now requires the `PHPSESSID` cookie for a successful login, so a 200 response without a session is reported as an authentication failure instead of failing on the first data request.

### Removed

- OS2 support: the software-version selector and the OS2 code paths.
- The `power_controls` option.
- The pinned `wdnas-client` runtime dependency and `requirements.txt`.

### Fixed

- The account response no longer includes groups in the user list, and group members are read from every `<user>` element instead of only the first one.
- Missing optional disk and volume numeric fields default to zero instead of breaking the whole system-info payload.

## [2.0.0] - 2026-11-14

### Changed

- **Breaking:** the minimum supported Home Assistant version is now 2026.8.0. Users on Home Assistant 2025.8–2026.7 stay on release 1.5.0.
- Disk and volume devices are attached to the NAS with `via_device_id` instead of the deprecated `via_device` field, which Home Assistant will remove in 2027.8. The NAS device is created during setup so its registry ID is available to both platforms.
- The coordinator sets `always_update=False`, so listeners are notified only when the NAS payload changes.
- Diagnostics redacts the password with `async_redact_data` in both entry data and options.

## [1.5.0] - 2026-11-14

### Added

- Entity name and icon translations through `translation_key` and `icons.json`. Existing entity IDs are preserved, and names are available in English and Italian.
- Exception translations for setup, re-authentication, reconnection and data-fetch failures, with host and error placeholders.
- `data_description` for every config, reconfigure, reauth and options field.
- `serial_number` on the main NAS and disk devices when the NAS reports it.
- `async_remove_config_entry_device`, so disks and volumes that no longer exist can be removed from their device page without touching the main NAS device.
- Per-module coverage enforcement (`>95%` for every module) in CI, with `scripts/check_coverage.py`.
- Tests for unique ID migration, stale device removal, translated exceptions, alert fallbacks and all config/reconfigure error paths.

### Changed

- The config entry unique ID is now the NAS serial number instead of the host. Existing entries are migrated automatically during setup, with guards for missing or duplicate serial numbers.
- Reconfigure validates the NAS serial number and aborts with `wrong_device` when the address points to a different device.
- `BinarySensorDeviceClass.PROBLEM` is used for disk failure and over-temperature, and `CONNECTIVITY` for disk presence.
- `PARALLEL_UPDATES = 0` is declared on both entity platforms because the shared coordinator serializes polling.
- Entity icons are defined in `icons.json` instead of Python attributes.

### Fixed

- Blank disk or volume identifiers no longer produce empty device identifiers.
- The reconfigure flow stores the serial number and updates the title and unique ID consistently.
- Diagnostics tolerate an entry that is not loaded and report the entry title and unique ID.

## [1.4.0] - 2026-11-14

### Added

- **Reconfigure** flow: the host, username, password and software version can be changed without deleting the entry. The new connection is validated first; the unique ID, title and entry data are updated, and the entry reloads.
- **Disk Connected** and **Disk Removable** binary sensors.
- Automatic reload when disks or volumes are added, removed or replaced, so entities for new hardware are created without a manual integration reload.
- `configuration_url` on the main device, linking back to the NAS web interface.
- A CI job that runs the test suite against the minimum supported Home Assistant version (`2025.8.0`).
- The release workflow now checks that the manifest version matches the release tag.

### Changed

- The coordinator is stored in `entry.runtime_data` instead of `hass.data`. Setup, unload, platforms and diagnostics were updated; credentials are still never duplicated outside the config entry.
- Entities use `has_entity_name` with English entity names. Existing entity IDs are preserved; new installations get cleaner IDs such as `sensor.<device>_disk_1_temperature`.
- CPU, memory, uptime, alert, disk sleep, disk removable and volume unlock/encryption entities are marked as diagnostic.
- The uptime sensor uses `TOTAL_INCREASING` instead of `MEASUREMENT`.
- Release assets are built with `git archive` from `HEAD`, which excludes local and untracked files.
- The README was rewritten in a text-only format aligned with Home Assistant conventions. Screenshots and CI badges were removed; upstream triage moved to `UPSTREAM.md`.
- Added `CONTRIBUTING.md` with the branch policy, Conventional Commits and Semantic Versioning rules.
- `main` is the only maintained branch. Development and releases no longer use `dev`.
- Removed the duplicate `images/` directory. Integration brand assets remain in `custom_components/mycloud/brand`.

### Fixed

- Optional endpoints now isolate `ParseError`, `AttributeError`, `KeyError`, `ValueError`, authentication and network errors, so malformed or unsupported responses do not make the core sensors unavailable. The firmware version endpoint is optional as well.
- The coordinator reconnects when the session is missing **or** already closed.
- The uptime fallback is also used on transport errors, not only on `RequestFailedError`.
- Disk names no longer produce labels such as “Disk Disk 1”.
- `SECURITY.md` now tracks security fixes against the latest release instead of a fixed minor series.

## [1.3.3] - 2026-11-14

### Added

- **Alert Count** and **Latest Alert** sensors, ported from upstream PR #79 and issue #40. The newest alert is selected by parsing the NAS timestamp independently of the Home Assistant locale; code, level, description and time are exposed as attributes.
- **Uptime** sensor for OS 5, with the `cgi_get_status` fallback proposed in upstream `wdnas_client#50`.
- Optional alert and uptime failures no longer make the core sensors unavailable.

### Changed

- The maintained branch is now `main`; CI, CodeQL, documentation and future releases target `main`.
- The `invalid_auth` message now mentions the WD single-admin-session limitation.
- Added an upstream issue/PR triage table to the README.

### Fixed

- Alert timestamps are parsed with a fixed English table, so an Italian or other non-English Home Assistant locale cannot break the selection.

## [1.3.2] - 2026-11-14

### Fixed

- CI: the HACS validation `ignore` input now uses the space-separated format required by the action, so the release check is green.

## [1.3.1] - 2026-11-14

### Added

- Integration brand assets (`brand/icon.png`, `brand/logo.png`) and the `computers_network.nas_servers` category in the manifest.

### Changed

- HACS validation ignores the license, topics and issues checks: the upstream project has no license, and topics/issues are repository settings. Manifest, HACS metadata, brand and integration checks remain enforced.

## [1.3.0] - 2026-11-14

### Security

- Added a written security audit and threat model in `SECURITY.md`.
- Pinned the audited dependency `wdnas-client==0.9.4` (was `>=0.9.4`).
- Removed the duplicate copy of the password from `hass.data`.
- Added strict host validation: schemes, paths, query strings, fragments and credentials are rejected.
- Switched the password field to a masked selector.
- Added a 30-second request timeout.
- Pinned GitHub Actions to commit SHAs and reduced workflow permissions.

### Added

- Connection and credentials are validated before a config entry is created.
- Re-authentication flow when the NAS invalidates the session or the password changes.
- Configurable polling interval with a 30–86400 second range.
- Diagnostics download with the password redacted.
- Italian translation.
- Test suite covering config flow, lifecycle, coordinator, entities and static security checks.
- CI, CodeQL, HACS, hassfest and release workflows.
- Bug report issue template.

### Changed

- Repository metadata, documentation and HACS metadata point to `richkmeli/ha-mycloud`.
- Binary sensors moved from `sensor.py` to their own `binary_sensor.py` platform.
- Coordinator and client lifecycle are owned by `__init__.py`; the platform unload function is now effective.
- Volume and disk unique IDs include the NAS serial number to avoid collisions between devices.
- Entity values return `unknown` when a disk or volume disappears instead of raising.

### Fixed

- Session leak on setup failure and on unload.
- Dead `async_unload_entry` code in the sensor platform.
- Malformed quoting in the new-device issue template.
- Wrong or missing documentation links.

## Upstream history

This fork starts from `J-shw/ha-mycloud` v1.2.5. See the upstream repository for the full history before this release.
