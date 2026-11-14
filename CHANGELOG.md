# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
