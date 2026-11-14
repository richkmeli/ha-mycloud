# Upstream and maintenance notes

This document records how the fork relates to the upstream project and which upstream changes were reviewed or ported. It is intended for maintainers and users who want to understand the differences from `J-shw/ha-mycloud`.

## Relationship with upstream

- Upstream repository: [J-shw/ha-mycloud](https://github.com/J-shw/ha-mycloud).
- Upstream client library: [J-shw/wdnas_client](https://github.com/J-shw/wdnas_client).
- This fork is based on upstream commit `0314bdc`.
- Protocol work and the original integration were created by [@J-shw](https://github.com/J-shw) and the upstream contributors.

## Branch and release policy

- The maintained branch is `main`.
- Releases are cut from `main`.
- `dev` is kept only as an upstream mirror and is not used for development in this fork.
- Release assets must contain the integration files at the ZIP root, without an enclosing `mycloud/` folder. HACS extracts `mycloud.zip` directly into `custom_components/mycloud`.
- The manifest version, `CHANGELOG.md` and the release tag must be updated together.

## Upstream triage (2026-11-14)

The open issues and pull requests were reviewed before porting changes.

### Ported or already covered

- [#72](https://github.com/J-shw/ha-mycloud/issues/72) — aiohttp session leak. Already fixed: the fork owns the client lifecycle, closes the old session before reconnecting and closes the session on unload.
- [#79](https://github.com/J-shw/ha-mycloud/pull/79) — alert sensors. Ported as **Alert Count** and **Latest Alert**, with code, level, description and time attributes.
- [#40](https://github.com/J-shw/ha-mycloud/issues/40) — device info and uptime. Uptime ported for OS5. Device name, model and firmware are already exposed by the Home Assistant device registry.
- [#50](https://github.com/J-shw/wdnas_client/pull/50) — V5 uptime fallback. Ported in the client wrapper: `cgi_get_status` is used when `cgi_get_uptime` fails.
- [#68](https://github.com/J-shw/ha-mycloud/issues/68) and [#78](https://github.com/J-shw/ha-mycloud/issues/78) — setup, 401 and DNS failures. The config flow validates host, connection and credentials and reports separate errors. The `invalid_auth` message also mentions the single-admin-session limitation. DNS and VLAN problems remain environment issues.
- [#55](https://github.com/J-shw/ha-mycloud/issues/55) — 403 log spam. Addressed by re-authenticating once on 401 or 403 instead of logging every poll as a failure.

### Not ported

- [#48](https://github.com/J-shw/ha-mycloud/issues/48) — USB storage. `wdnas_client` exposes `usb_info()`, but there is no validated response schema or hardware test data.
- [#75](https://github.com/J-shw/ha-mycloud/issues/75) — license. Not added: the upstream project has no license, so this fork cannot grant one. See the License section in the README.
- [#76](https://github.com/J-shw/ha-mycloud/pull/76) and [#77](https://github.com/J-shw/ha-mycloud/issues/77) — V4 support and power controls. The pull request changes about 40 files, depends on the unmerged `wdnas_client#49`, vendors the library and ships shutdown untested. Revisit when upstream releases the client work.

## Repository maintenance

The HACS validation workflow ignores the `license`, `topics` and `issues` checks:

- The upstream project does not include a license, so this fork cannot grant one.
- Topics and issues are GitHub repository settings, not files. To improve discoverability, enable **Issues** and add the topics `home-assistant`, `hacs`, `nas`, `wd-my-cloud` and `integration` in the repository settings.

Manifest, `hacs.json`, brand and integration checks remain enforced.

## Adding upstream changes

Before porting an upstream change:

1. Check whether the change depends on an unreleased `wdnas_client` version.
2. Check whether it changes the authentication or session lifecycle.
3. Add or update tests for the affected behavior.
4. Run `ruff check`, `ruff format --check` and `pytest`.
5. Update `CHANGELOG.md`, the manifest version and the README or this document when the user-facing behavior changes.
