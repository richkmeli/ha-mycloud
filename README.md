# WD My Cloud

Home Assistant integration for Western Digital My Cloud NAS devices running OS2 or OS5. The integration polls the NAS on the local network and exposes system, disk, volume, alert and uptime data as Home Assistant entities.

This is a community fork of [J-shw/ha-mycloud](https://github.com/J-shw/ha-mycloud). It is not affiliated with Western Digital or Home Assistant.

## Features

- **Local polling only** — no cloud service, telemetry or third-party endpoint.
- **System status** — CPU and memory usage.
- **Device information** — serial number, name, model and firmware version.
- **Disks** — temperature, size, health, sleep, failure, over-temperature, connected and removable state.
- **Volumes** — size, mounted, unlocked and encrypted state.
- **Alerts** — number of entries in the NAS alert log and the latest alert with code, level, description and time.
- **Uptime** — OS5 uptime, including a `cgi_get_status` fallback for firmware that fails the dedicated uptime command.
- **Config flow** — host, connection and credentials are validated before the entry is created.
- **Reconfigure** — change the address, credentials or software version without removing the entry.
- **Stable identity** — the NAS serial number identifies the config entry and survives address changes.
- **Re-authentication** — Home Assistant asks for the password again when the NAS rejects the stored credentials.
- **Options** — configurable polling interval.
- **Automatic topology refresh** — entities for new disks and volumes are created without a manual reload.
- **Stale device removal** — disks and volumes that are no longer reported can be removed from the device page.
- **Diagnostics** — downloadable diagnostics with the password redacted.
- **Translations** — English and Italian, including entity names and setup errors.

## Requirements

- Home Assistant 2026.8.0 or newer. Version 2.0.0 uses `via_device_id` and no longer loads on Home Assistant 2025.8–2026.7; users on those versions must stay on integration 1.5.0.
- A WD My Cloud NAS running firmware OS2 (v2) or OS5 (v5).
- An admin account on the NAS.
- The NAS web interface reachable from Home Assistant.

WD firmware allows only one active admin session at a time. Close the NAS web interface before using the same admin account in Home Assistant.

## Installation

### HACS (recommended)

This fork is not in the default HACS store. Add it as a custom repository:

1. Open **HACS → Integrations**.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/richkmeli/ha-mycloud` with category **Integration**.
4. Search for **WD My Cloud**, install it and restart Home Assistant.

### Manual

1. Copy `custom_components/mycloud` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **WD My Cloud**.
3. Enter the connection details:
   - **Host** — IP address or hostname of the NAS, optionally with a port. Examples: `192.168.1.10`, `wdmycloud.local`, `nas.local:8080`. Do not include `http://`, `https://`, a path or credentials.
   - **Username** and **Password** — credentials of an admin account.
   - **Software version** — `2` for OS2 or `5` for OS5.
4. The integration logs in, reads the device information and creates the entry only if the NAS responds correctly. The NAS serial number becomes the entry identity, so changing the host later does not create a duplicate entry.

The host field is validated. Schemes, paths, query strings, fragments and `user:password@host` values are rejected.

### Reconfigure

Open the integration entry and choose **Reconfigure** to change the host, username, password or software version. The new connection is validated before saving, and the NAS serial number is checked so the entry stays linked to the same physical device. To connect a different NAS, add a new integration entry. The entry reloads automatically after saving.

## Options

Open the integration entry and choose **Configure** to change the polling interval. The default is 600 seconds; the accepted range is 30–86400 seconds.

## Entities

Entity IDs depend on the device name. The examples below use `wd_my_cloud`; your installation may use a different prefix.

### Sensors

- CPU usage — `sensor.wd_my_cloud_cpu_usage`
- Memory usage — `sensor.wd_my_cloud_memory_usage`
- Total storage — `sensor.wd_my_cloud_total_storage`
- Used storage — `sensor.wd_my_cloud_used_storage`
- Unused storage — `sensor.wd_my_cloud_unused_storage`
- Alert count — `sensor.wd_my_cloud_alert_count`
- Latest alert — `sensor.wd_my_cloud_latest_alert`
- Uptime (OS5 only) — `sensor.wd_my_cloud_uptime`
- Disk temperature — `sensor.wd_my_cloud_disk_[disk_name]_temperature`
- Disk size — `sensor.wd_my_cloud_disk_[disk_name]_size`
- Volume size — `sensor.wd_my_cloud_volume_[volume_name]_size`

### Binary sensors

- Disk healthy — `binary_sensor.wd_my_cloud_disk_[disk_name]_healthy`
- Disk sleeping — `binary_sensor.wd_my_cloud_disk_[disk_name]_sleeping`
- Disk failed — `binary_sensor.wd_my_cloud_disk_[disk_name]_failed`
- Disk over-temperature — `binary_sensor.wd_my_cloud_disk_[disk_name]_over_temperature`
- Disk connected — `binary_sensor.wd_my_cloud_disk_[disk_name]_connected`
- Disk removable — `binary_sensor.wd_my_cloud_disk_[disk_name]_removable`
- Volume mounted — `binary_sensor.wd_my_cloud_volume_[volume_name]_mounted`
- Volume unlocked — `binary_sensor.wd_my_cloud_volume_[volume_name]_unlocked`
- Volume encrypted — `binary_sensor.wd_my_cloud_volume_[volume_name]_encrypted`

`[disk_name]` and `[volume_name]` are replaced by the values reported by the NAS. Disk and volume devices are linked to the NAS device in the device registry. When disks or volumes are added, removed or replaced, the integration detects the change and reloads itself, so entities for new hardware are created without a manual step. If hardware is removed, its entities become unavailable; they return with their history when the hardware is reconnected. A disk or volume that will not come back can be deleted from its device page, and its entities are removed with it.

Entity names use the Home Assistant entity-naming convention and are translated into English and Italian; existing entity IDs are preserved. CPU, memory, uptime, alert, disk sleep, removable and volume encryption/unlock entities are marked as diagnostic. The alert sensors are optional: if the NAS does not expose the alert log, only those two entities become unavailable. The uptime sensor is created on OS5 only.

## Security

- The integration talks only to the host configured by the user. There are no hardcoded endpoints, cloud calls or telemetry.
- The third-party dependency is pinned to the audited release `wdnas-client==0.9.4`.
- There is no `eval`, `exec`, `subprocess`, shell execution or dynamic import in the integration.
- The password is not copied into `hass.data`; the coordinator is kept in `entry.runtime_data` and owns the single client session.
- Diagnostics redact the password.

### Known limitation: plain HTTP

The upstream `wdnas-client` library uses `http://` instead of HTTPS. Credentials are base64-encoded, which is encoding, not encryption. Someone who can sniff the local network can recover them. Use the integration only on a trusted network:

- Put the NAS and Home Assistant on a dedicated VLAN or trusted network.
- Do not expose the NAS web interface to the internet.
- Use a unique admin password, not a password reused elsewhere.
- Keep the NAS firmware updated.

See [SECURITY.md](SECURITY.md) for the threat model, the audit findings and the residual risks.

## Troubleshooting

### `cannot_connect`

Verify the IP address or hostname, that the NAS web interface is reachable from Home Assistant and that the admin account is not already logged in elsewhere.

### `invalid_auth`

Use an admin account and verify the password. WD firmware allows only one active admin session, so this error can also mean that the NAS web interface is still logged in. Close the web session and retry.

### `invalid_host`

Remove `http://`, `https://`, paths, query strings and credentials from the host field.

### Alerts or uptime are unavailable

The alert and uptime endpoints are optional. If the NAS firmware does not support them, the other sensors continue to work. Check the Home Assistant log with debug logging enabled.

### Enable debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.mycloud: debug
```

### Download diagnostics

Go to **Settings → Devices & services → WD My Cloud → ⋮ → Download diagnostics**. The password is redacted automatically. Attach the file to a GitHub issue and remove any remaining personal information.

## Removal

1. Remove the **WD My Cloud** entry from **Settings → Devices & services**.
2. Uninstall the integration from HACS, or delete `custom_components/mycloud`.
3. Restart Home Assistant.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
pytest --cov=custom_components/mycloud --cov-report=term-missing --cov-report=json
python scripts/check_coverage.py
ruff check custom_components tests
ruff format --check custom_components tests
```

The test suite covers host validation, config flow errors, setup and unload lifecycle, unique ID migration, stale device removal, coordinator re-authentication, entity values, translations and static security checks. CI requires at least 95% line coverage for every module of the integration.

CI, HACS validation, hassfest and CodeQL run on every push to `main`.

## Contributing

Issues and pull requests are welcome at [richkmeli/ha-mycloud](https://github.com/richkmeli/ha-mycloud). Add or update tests for behavior changes, run the development checks above, and read [UPSTREAM.md](UPSTREAM.md) before porting upstream work.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) and releases follow [Semantic Versioning](https://semver.org/). See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch policy and release process.

## Fork and upstream

This fork is based on `J-shw/ha-mycloud` commit `0314bdc`. `main` is the only maintained branch; releases are cut from `main`.

See [UPSTREAM.md](UPSTREAM.md) for the upstream issue and pull-request triage, porting decisions and repository maintenance notes.

## Supported devices

The client library maintains the list of tested models:

- [Known supported models](https://github.com/J-shw/wdnas_client/blob/dev/docs/SUPPORTED_MODELS.md)

If your model is not listed, open an issue using the **New Device Support Request** template.

## Support

- Bugs and feature requests: [GitHub Issues](https://github.com/richkmeli/ha-mycloud/issues).
- Security problems: use [GitHub private vulnerability reporting](https://github.com/richkmeli/ha-mycloud/security/advisories/new) instead of a public issue.
- Include the integration version, Home Assistant version, NAS model, firmware version and diagnostics when reporting a problem.

## Credits

- [@J-shw](https://github.com/J-shw) for the original [ha-mycloud](https://github.com/J-shw/ha-mycloud) integration and the [wdnas_client](https://github.com/J-shw/wdnas_client) library.
- All upstream contributors who reverse-engineered and tested the WD NAS API.

## License

The upstream `J-shw/ha-mycloud` repository does not include a license file. This fork preserves that upstream status and does not add a license. No license is granted for this repository; if you need clear redistribution rights, ask the upstream author. The integration is provided as-is, without warranty.

Western Digital, My Cloud and related marks are trademarks of their respective owners.
