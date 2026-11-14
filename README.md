# <img src="images/icon.png" alt="WD My Cloud App Icon" width="100"> ha-mycloud

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=richkmeli&repository=ha-mycloud&category=Integration)
[![CI](https://github.com/richkmeli/ha-mycloud/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/richkmeli/ha-mycloud/actions/workflows/ci.yml)
[![HACS Action](https://github.com/richkmeli/ha-mycloud/actions/workflows/validate.yml/badge.svg)](https://github.com/richkmeli/ha-mycloud/actions/workflows/validate.yml)
[![Validate with hassfest](https://github.com/richkmeli/ha-mycloud/actions/workflows/hassfest.yml/badge.svg)](https://github.com/richkmeli/ha-mycloud/actions/workflows/hassfest.yml)

Home Assistant integration for Western Digital My Cloud NAS devices (OS2 and OS5).

This repository is a maintained fork of [J-shw/ha-mycloud](https://github.com/J-shw/ha-mycloud). The original integration and the [wdnas-client](https://github.com/J-shw/wdnas_client) library were created by [@J-shw](https://github.com/J-shw); all credit for the protocol work belongs to the upstream project.

> **Security first:** this fork was reviewed before being published. See [SECURITY.md](SECURITY.md) for the threat model, the audit findings and the residual risks. The integration is local-only: it does not contact any cloud service and does not collect telemetry.

---

## Features

- **System status**: CPU and memory usage.
- **Device information**: serial number, name, model and firmware version.
- **Disks**: temperature, size, health, sleep, failure and over-temperature state.
- **Volumes**: size, mounted/unlocked/encrypted state.
- **Alerts**: number of entries in the NAS alert log and the latest alert with its code, level, description and time.
- **Uptime**: NAS uptime on OS 5, including the `cgi_get_status` fallback for firmware that fails the dedicated uptime command.
- **Config flow**: connection and credentials are validated before the entry is created.
- **Re-authentication**: if the NAS invalidates the session or the password changes, Home Assistant asks for the password again.
- **Options**: configurable polling interval (30 seconds to 24 hours).
- **Diagnostics**: downloadable diagnostics with the password redacted.
- **Translations**: English and Italian.

## Requirements

- Home Assistant **2025.8.0** or newer.
- A WD My Cloud NAS running firmware **OS2 (v2)** or **OS5 (v5)**.
- An **admin** account on the NAS.

> The admin account can only be active in one place at a time: either the NAS web UI or this integration.

## Installation

### HACS (recommended)

This fork is not in the default HACS store, so add it as a custom repository:

1. Open **HACS → Integrations**.
2. Open the three-dot menu → **Custom repositories**.
3. Add `https://github.com/richkmeli/ha-mycloud` with category **Integration**.
4. Search for **WD My Cloud**, install it and restart Home Assistant.

### Manual

1. Copy `custom_components/mycloud` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **WD My Cloud**.
3. Enter:
   - **Host**: IP address or hostname of the NAS, for example `192.168.1.10`, `wdmycloud.local` or `nas.local:8080`. Do **not** include `http://`, `https://`, a path or credentials.
   - **Username** and **Password** of an admin account.
   - **Software version**: `2` for OS2, `5` for OS5.
4. The integration logs in, reads the device information and creates the entry only if the NAS responds correctly.

The host field is validated: schemes, paths, query strings, fragments and `user:password@host` values are rejected.

## Options

Open the integration entry → **Configure** to change the polling interval. The default is 600 seconds; the accepted range is 30–86400 seconds.

## Entities

`[disk_name]` and `[volume_name]` are replaced by the values reported by the NAS.

### Sensors

- `sensor.wd_my_cloud_cpu_usage`
- `sensor.wd_my_cloud_memory_usage`
- `sensor.wd_my_cloud_total_storage`
- `sensor.wd_my_cloud_used_storage`
- `sensor.wd_my_cloud_unused_storage`
- `sensor.wd_my_cloud_alert_count`
- `sensor.wd_my_cloud_latest_alert`
- `sensor.wd_my_cloud_uptime` (OS 5 only)
- `sensor.wd_my_cloud_disk_[disk_name]_temperature`
- `sensor.wd_my_cloud_disk_[disk_name]_size`
- `sensor.wd_my_cloud_volume_[volume_name]_size`

### Binary sensors

- `binary_sensor.wd_my_cloud_disk_[disk_name]_healthy`
- `binary_sensor.wd_my_cloud_disk_[disk_name]_sleeping`
- `binary_sensor.wd_my_cloud_disk_[disk_name]_failed`
- `binary_sensor.wd_my_cloud_disk_[disk_name]_over_temperature`
- `binary_sensor.wd_my_cloud_volume_[volume_name]_mounted`
- `binary_sensor.wd_my_cloud_volume_[volume_name]_unlocked`
- `binary_sensor.wd_my_cloud_volume_[volume_name]_encrypted`

## Security

- The integration talks **only** to the host you configure. There are no hardcoded endpoints, no cloud calls and no telemetry.
- The third-party dependency is pinned to the audited release `wdnas-client==0.9.4`.
- There is no `eval`, `exec`, `subprocess`, shell execution or dynamic import in the integration.
- The password is not copied into `hass.data`; only the coordinator is stored there.
- Diagnostics redact the password.

### Known limitation: plain HTTP

The upstream `wdnas-client` library uses `http://` (not HTTPS). Credentials are base64-encoded, which is **encoding, not encryption**, and traffic can be read by someone who can sniff your LAN. This is an upstream limitation that cannot be fixed safely without changing the library.

Use the integration only on a trusted network. Recommended mitigations:

- Put the NAS and Home Assistant on a dedicated VLAN or trusted network.
- Do not expose the NAS web interface to the internet.
- Use a unique admin password, not a password reused elsewhere.
- Keep the NAS firmware updated.

See [SECURITY.md](SECURITY.md) for the full audit.

## Troubleshooting

- **`cannot_connect`**: verify the IP/hostname, that the NAS web UI is reachable from Home Assistant and that the admin account is not already logged in elsewhere.
- **`invalid_auth`**: use an admin account and verify the password. WD firmware allows only one active admin session, so this error can also mean that the NAS web UI is still logged in. Close the web UI session and retry. The integration starts a re-authentication flow when the NAS rejects the stored credentials.
- **`invalid_host`**: remove `http://`, `https://`, paths, query strings or credentials from the host field.
- **Entities unavailable after a disk change**: reload the integration so the new disks/volumes are discovered.
- **Enable debug logging**:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.mycloud: debug
  ```

## Upstream triage (2026-11-14)

This fork is based on `J-shw/ha-mycloud` commit `0314bdc`. The open issues and pull requests were reviewed before porting changes:

| Upstream item | Decision |
| --- | --- |
| [#72](https://github.com/J-shw/ha-mycloud/issues/72) aiohttp session leak | Already fixed: the fork owns the client lifecycle, closes the old session before reconnecting and closes the session on unload. |
| [#79](https://github.com/J-shw/ha-mycloud/pull/79) alert sensors | Ported: **Alert Count** and **Latest Alert** (with code, level, description and time attributes). |
| [#40](https://github.com/J-shw/ha-mycloud/issues/40) device info and uptime | Uptime ported for OS 5. Device name, model and firmware are already exposed by the Home Assistant device registry. |
| [#50](https://github.com/J-shw/wdnas_client/pull/50) V5 uptime fallback | Ported in the client wrapper: `cgi_get_status` is used when `cgi_get_uptime` fails. |
| [#68](https://github.com/J-shw/ha-mycloud/issues/68), [#78](https://github.com/J-shw/ha-mycloud/issues/78) setup/401/DNS failures | The config flow now validates host, connection and credentials and reports separate errors. The `invalid_auth` message also mentions the single-admin-session limitation. DNS and VLAN problems remain environment issues. |
| [#48](https://github.com/J-shw/ha-mycloud/issues/48) USB storage | Not ported: `wdnas_client` exposes `usb_info()` but there is no validated response schema or hardware test data. |
| [#75](https://github.com/J-shw/ha-mycloud/issues/75) license | Cannot be added by this fork: the upstream project has no license. HACS custom-repository installation does not require it; see the License section. |
| [#76](https://github.com/J-shw/ha-mycloud/pull/76), [#77](https://github.com/J-shw/ha-mycloud/issues/77) V4 support and power buttons | Not merged: the PR changes 40 files, depends on the unmerged `wdnas_client#49`, vendors the library and ships shutdown untested. Revisit when upstream releases the client work. |
| [#55](https://github.com/J-shw/ha-mycloud/issues/55) 403 log spam | Addressed by re-authenticating once on 401/403 instead of logging every poll as a failure. |

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
pytest
ruff check custom_components tests
ruff format --check custom_components tests
```

The test suite covers host validation, config flow errors, setup/unload lifecycle, coordinator re-authentication, entity values and static security checks.

### Repository maintenance

The maintained branch is `main`; releases are cut from `main`. The `dev` branch belongs to the upstream project and is not used for this fork.

The HACS validation workflow ignores the `license`, `topics` and `issues` checks:

- The upstream project does not include a license, so this fork cannot grant one (see the License section).
- Topics and issues are GitHub repository settings, not files. To improve discoverability, enable **Issues** and add the topics `home-assistant`, `hacs`, `nas`, `wd-my-cloud`, `integration` in the repository settings.

Manifest, `hacs.json`, brand and integration checks remain enforced.

## Supported devices

The client library maintains the list of tested models:

- [Known supported models](https://github.com/J-shw/wdnas_client/blob/dev/docs/SUPPORTED_MODELS.md)

If your model is not listed, open an issue using the **New Device Support Request** template.

## Credits

- [@J-shw](https://github.com/J-shw) for the original [ha-mycloud](https://github.com/J-shw/ha-mycloud) integration and the [wdnas_client](https://github.com/J-shw/wdnas_client) library.
- All upstream contributors who reverse-engineered and tested the WD NAS API.

## License

The upstream `J-shw/ha-mycloud` repository does not include a license file. This fork preserves that upstream status; no additional license is granted here. If you need a clear redistribution license, ask the upstream author first.
