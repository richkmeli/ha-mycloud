# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Documentation: the README was rewritten in a text-only format aligned with Home Assistant conventions. Screenshots and CI badges were removed; upstream triage moved to `UPSTREAM.md`.
- Removed the duplicate `images/` directory. Integration brand assets remain in `custom_components/mycloud/brand`.

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
