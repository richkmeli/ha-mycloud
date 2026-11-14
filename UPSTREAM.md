# Upstream and maintenance notes

This document records how the fork relates to the upstream project and which upstream changes were reviewed or ported. It is intended for maintainers and users who want to understand the differences from `J-shw/ha-mycloud`.

## Relationship with upstream

- Upstream repository: [J-shw/ha-mycloud](https://github.com/J-shw/ha-mycloud).
- Upstream client library: [J-shw/wdnas_client](https://github.com/J-shw/wdnas_client).
- This fork is based on upstream commit `0314bdc`.
- The fork targets OS5 firmware only. OS2 support was removed; legacy OS2 entries are rejected during setup with a clear error.
- Protocol work and the original integration were created by [@J-shw](https://github.com/J-shw) and the upstream contributors.

## Vendored OS5 client

The integration no longer installs `wdnas-client` from PyPI. A trimmed, OS5-only copy lives in `custom_components/mycloud/wdnas.py` and is owned by this project. The Home Assistant lifecycle remains in `client.py`.

- Upstream: [J-shw/wdnas_client](https://github.com/J-shw/wdnas_client), release `0.9.4`, commit `68bc89983194fdcd15c03d495af59119b592666e`.
- License: MIT, copyright `2019 - 2024 Joakim Sørensen @ludeeus`. The full text and provenance are in `custom_components/mycloud/THIRD_PARTY_NOTICES.md`, which is included in every HACS release.
- Removed: OS2 endpoints and branches, the version selector, the V2 login format and the OS2-only `latest_version` endpoint.
- Kept: every OS5 endpoint used by the integration (`login`, `system_info`, `share_names`, `system_status`, `network_info`, `device_info`, `system_version`, `accounts`, `alerts`, `cloud_access`, `usb_info`, `uptime`), with the same response shapes.
- Added by this fork: bounded aiohttp sessions, serialized connect/reconnect/close, the OS5 server-side logout, the `cgi_get_status` uptime fallback, and the safety-checked restart/shutdown actions. Login now requires `PHPSESSID`; account parsing no longer mixes groups into users; missing optional numeric fields default to zero.
- Sync policy: this is not a drop-in copy. Before syncing an upstream change, read the upstream diff, port only the OS5 protocol part, keep the local hardening and tests, and update `THIRD_PARTY_NOTICES.md` if the upstream version or commit changes. Do not re-add the PyPI dependency or the OS2 code paths.
- Every vendored module is covered by the same per-module coverage gate as the rest of the integration.

## Branch and release policy

- `main` is the only maintained branch.
- Releases are cut from `main`.
- Release assets must contain the integration files at the ZIP root, without an enclosing `mycloud/` folder. HACS extracts `mycloud.zip` directly into `custom_components/mycloud`.
- The manifest version, `CHANGELOG.md` and the release tag must be updated together.
- Versions follow Semantic Versioning and commits follow Conventional Commits. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Upstream triage (2026-11-14)

The open issues and pull requests were reviewed before porting changes.

### Ported or already covered

- [#72](https://github.com/J-shw/ha-mycloud/issues/72) — aiohttp session leak. Already fixed: the fork owns the client lifecycle, closes the old session before reconnecting and closes the session on unload.
- [#79](https://github.com/J-shw/ha-mycloud/pull/79) — alert sensors. Ported as **Alert Count** and **Latest Alert**, with code, sequence number, level, description and time attributes.
- [#40](https://github.com/J-shw/ha-mycloud/issues/40) — device info and uptime. Uptime ported for OS5. Device name, model and firmware are already exposed by the Home Assistant device registry.
- [#50](https://github.com/J-shw/wdnas_client/pull/50) — OS5 uptime fallback. Ported in the client wrapper: `cgi_get_status` is used when `cgi_get_uptime` fails.
- [#68](https://github.com/J-shw/ha-mycloud/issues/68) and [#78](https://github.com/J-shw/ha-mycloud/issues/78) — setup, 401 and DNS failures. The config flow validates host, connection and credentials and reports separate errors. The `invalid_auth` message also mentions the single-admin-session limitation. DNS and VLAN problems remain environment issues.
- [#55](https://github.com/J-shw/ha-mycloud/issues/55) — 403 log spam. Addressed by re-authenticating once on 401 or 403 instead of logging every poll as a failure.
- [#76](https://github.com/J-shw/ha-mycloud/pull/76) and [#77](https://github.com/J-shw/ha-mycloud/issues/77) — OS5 restart and shutdown. Ported without the V4 support or the other changes in those proposals. The integration implements the two OS5 commands in its client: the `cgi_Detect_Dangerous` safety check, then one `cgi_restart` or `cgi_shutdown` request. Both buttons are created for every OS5 entry; Restart is enabled by default and Shutdown is disabled by default.
- [`wdnas_client#49`](https://github.com/J-shw/wdnas_client/pull/49) — OS5 server-side logout. Ported as a best-effort `DELETE /nas/v1/auth` before closing the local session, so unload, reconfigure and re-authentication release the single admin session.
- [#48](https://github.com/J-shw/ha-mycloud/issues/48) — USB storage. `usb_info()` is exposed as a raw diagnostic sensor, disabled by default until the response schema is validated with hardware test data.

### Not ported

- [#75](https://github.com/J-shw/ha-mycloud/issues/75) — repository license. Not added: the upstream project has no license, so this fork cannot grant one for its own code. The vendored client keeps its upstream MIT license. See the License section in the README.
- The rest of [#76](https://github.com/J-shw/ha-mycloud/pull/76): V4 support and the optional release-admin-session option. Those need more hardware validation.

## Repository maintenance

The HACS validation workflow ignores the `license`, `topics` and `issues` checks:

- The upstream project does not include a license, so this fork cannot grant a license for its own code. The vendored OS5 client remains MIT-licensed.
- Topics and issues are GitHub repository settings, not files. To improve discoverability, enable **Issues** and add the topics `home-assistant`, `hacs`, `nas`, `wd-my-cloud` and `integration` in the repository settings.

Manifest, `hacs.json`, brand and integration checks remain enforced.

## Adding upstream changes

Before porting an upstream change:

1. Check whether the upstream change touches `wdnas_client` and whether it is OS5-only. Port the protocol delta to `wdnas.py`; never re-add the PyPI dependency or OS2 code paths.
2. Check whether it changes the authentication or session lifecycle.
3. Add or update tests for the affected behavior and keep the vendored module above the per-module coverage threshold.
4. Run `ruff check`, `ruff format --check` and `pytest`.
5. Update `THIRD_PARTY_NOTICES.md` when the vendored upstream version or commit changes.
6. Update `CHANGELOG.md`, the manifest version and the README or this document when the user-facing behavior changes.
