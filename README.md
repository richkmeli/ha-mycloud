# WD My Cloud

Home Assistant integration for Western Digital My Cloud NAS devices running OS5. The integration polls the NAS on the local network and exposes system, disk, volume, network, share, account, cloud-access, USB, alert, power and uptime data as Home Assistant entities.

This is a community fork of [J-shw/ha-mycloud](https://github.com/J-shw/ha-mycloud). It is not affiliated with Western Digital or Home Assistant.

## Features

- **Local polling only** — no cloud service, telemetry or third-party endpoint.
- **HTTP and HTTPS** — an explicit HTTPS option for OS5 firmware that serves the web interface only over TLS, including the common port 8543 setup.
- **System status** — CPU and memory usage based on `MemAvailable`, including the raw memory and swap fields as attributes.
- **Device information** — serial number, name, model, firmware version and OLED text.
- **Disks** — temperature, size, health, sleep, failure, over-temperature, connected, removable and hardware details.
- **Volumes** — size, mounted, unlocked, encrypted and volume details.
- **Network** — IP address, link speed, DHCP, DNS, netmask, gateway and interface state.
- **Shares** — number of shares and their names.
- **Accounts** — user and group details, disabled by default because they contain personal data.
- **Cloud access** — the complete NAS cloud-access payload, disabled by default.
- **USB devices** — connected USB payload, disabled by default until its schema is validated.
- **Alerts** — number of entries in the NAS alert log and the latest alert with code, level, description, time and sequence number.
- **Uptime** — OS5 uptime, including a `cgi_get_status` fallback for firmware that fails the dedicated uptime command.
- **Config flow** — host and credentials are validated before the entry is created.
- **Reconfigure** — change the address or credentials without removing the entry.
- **Stable identity** — the NAS serial number identifies the config entry and survives address changes.
- **Re-authentication** — Home Assistant asks for the password again when the NAS rejects the stored credentials.
- **Options** — configurable polling interval.
- **Automatic topology refresh** — entities for new disks, volumes and network interfaces are created without a manual reload.
- **Stale device removal** — disks and volumes that are no longer reported can be removed from the device page.
- **Power controls** — Restart and Shutdown buttons. Restart is enabled by default; Shutdown is created disabled.
- **Diagnostics** — downloadable diagnostics with the password and personal payloads redacted.
- **Login diagnostics** — a standalone, redacted login diagnostic script for troubleshooting rejected credentials.
- **Translations** — English and Italian, including entity names and setup errors.

## Requirements

- Home Assistant 2026.8.0 or newer. Integration 2.0.0 and newer use `via_device_id` and do not load on Home Assistant 2025.8–2026.7; users on those versions must stay on integration 1.5.0.
- A WD My Cloud NAS running firmware OS5 (v5). OS2 is no longer supported; entries created for OS2 stop during setup with a clear error.
- An admin account on the NAS.
- The NAS web interface reachable from Home Assistant, over HTTP or HTTPS.

WD firmware allows only one active admin session at a time. Close the NAS web interface before using the same admin account in Home Assistant.

OS5 often serves the web interface over HTTPS on port 8543. Use the same scheme and port in the integration: include the port in the host and enable **Use HTTPS**.

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
   - **Host** — IP address or hostname of the NAS, optionally with a port. Examples: `192.168.1.10`, `wdmycloud.local`, `nas.local:8080`, `192.168.1.10:8543`. Do not include `http://`, `https://`, a path or credentials.
   - **Username** and **Password** — credentials of an admin account.
   - **Use HTTPS** — enable when the NAS web interface uses `https://`, for example on port 8543. The WD self-signed certificate is accepted without certificate verification.
4. The integration logs in, reads the device information and creates the entry only if the NAS responds correctly. The NAS serial number becomes the entry identity, so changing the host later does not create a duplicate entry.

The host field is validated. Schemes, paths, query strings, fragments and `user:password@host` values are rejected. The scheme itself is selected only by the **Use HTTPS** checkbox, so existing entries keep using HTTP unless the option is enabled.

### Reconfigure

Open the integration entry and choose **Reconfigure** to change the host, username, password or HTTPS option. The new connection is validated before saving, and the NAS serial number is checked so the entry stays linked to the same physical device. To connect a different NAS, add a new integration entry. The entry reloads automatically after saving.

## Options

Open the integration entry and choose **Configure** to change the polling interval. The default is 600 seconds; the accepted range is 30–86400 seconds.

Power controls are normal entities, not an option. They are created on the NAS device and managed from the entity registry:

- **Restart** is enabled by default.
- **Shutdown** is created disabled. Enable it in **Settings → Devices & services → Entities** when you want to use it. This prevents a misclick or a voice assistant from powering off the NAS by accident.

The integration asks the NAS to run its own safety check before either action; if the NAS is busy (for example during a RAID rebuild or firmware update), the action is refused. The command is sent once and never retried. Shutdown does not power the NAS back on: use Wake-on-LAN or physical access to start it again. Test the Shutdown button once while you can physically power the NAS back on, before relying on it in a UPS automation.

Restart and Shutdown use the legacy CGI endpoints under ``/cgi-bin/``. If either button fails with ``Azione di alimentazione non riuscita: Request failed: 403``:

1. Close the NAS web interface in every browser tab and close all WD apps (WD My Cloud, WD Discovery). OS5 allows only one active admin session.
2. Wait 2-3 minutes, then try once more.
3. If it still fails, run the standalone diagnostic from a computer that can reach the NAS:

```bash
python scripts/diagnose_power.py --host 192.168.1.10:8543 --https --username admin
```

It tests the safety-check endpoint without sending a shutdown or restart command.

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
- Uptime — `sensor.wd_my_cloud_uptime`
- Firmware — `sensor.wd_my_cloud_firmware`
- Shares — `sensor.wd_my_cloud_shares`
- Accounts — `sensor.wd_my_cloud_accounts` (disabled by default)
- Cloud access — `sensor.wd_my_cloud_cloud_access` (disabled by default)
- USB devices — `sensor.wd_my_cloud_usb_devices` (disabled by default)
- Network — `sensor.wd_my_cloud_network_[interface]`
- Disk temperature — `sensor.wd_my_cloud_disk_[disk_name]_temperature`
- Disk size — `sensor.wd_my_cloud_disk_[disk_name]_size`
- Volume size — `sensor.wd_my_cloud_volume_[volume_name]_size`

Memory usage is `(MemTotal - MemAvailable) / MemTotal`, so the reclaimable
page cache and buffers are not counted as used memory. Firmware that does not
report `MemAvailable` falls back to the previous
`(MemTotal - MemFree) / MemTotal` calculation. The sensor attributes expose the
raw fields reported by the NAS (`total`, `available`, `unused`, `cached`,
`buffers` and `simple`) and the swap usage (`swap_total`, `swap_free`,
`swap_used` and `swap_used_percent`) when present.

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
- Network connected — `binary_sensor.wd_my_cloud_network_[interface]_connected`

`[disk_name]`, `[volume_name]` and `[interface]` are replaced by the values reported by the NAS. Disk and volume devices are linked to the NAS device in the device registry. When disks, volumes or network interfaces are added, removed or replaced, the integration detects the change and reloads itself, so entities for new hardware are created without a manual step. If hardware is removed, its entities become unavailable; they return with their history when the hardware is reconnected. A disk or volume that will not come back can be deleted from its device page, and its entities are removed with it.

Network sensors use the IP address as state and expose every other field returned by the NAS as attributes: link speed, DHCP, manual DNS, netmask, gateway, DNS servers and interface state. The interface identifier (usually the MAC address) is used in the entity name. Disk size sensors expose the disk hardware fields as attributes; volume size sensors expose the volume fields. The latest alert exposes code, sequence number, level, description and time. Firmware exposes the OLED text. The share sensor exposes the share names; the account sensor exposes user and group details, while the cloud-access and USB sensors expose the raw payload.

### Buttons

- Restart — `button.wd_my_cloud_restart` (enabled by default)
- Shutdown — `button.wd_my_cloud_shutdown` (created disabled)

Both buttons are attached to the main NAS device. A shutdown is irreversible from Home Assistant: the NAS stays off until it is powered on again. Use them in automations only after checking the UPS state and the remaining runtime. Enable the Shutdown entity before referencing it in an automation.

Example UPS automation (replace the UPS entities with the ones exposed by your UPS integration):

```yaml
automation:
  - alias: Shut down the NAS on low UPS battery
    triggers:
      - trigger: numeric_state
        entity_id: sensor.ups_battery_charge
        below: 20
    conditions:
      - condition: state
        entity_id: sensor.ups_status
        state: "On Battery"
    actions:
      - action: button.press
        target:
          entity_id: button.wd_my_cloud_shutdown
```

Entity names use the Home Assistant entity-naming convention and are translated into English and Italian; existing entity IDs are preserved. CPU, memory, uptime, firmware, shares, network, network connectivity, account, cloud, USB, alert, disk sleep, removable and volume encryption/unlock entities are marked as diagnostic. The firmware, alert, uptime, share, network, account, cloud-access and USB sensors are optional: if the NAS does not expose one of those endpoints, only the related entities become unavailable.

## Security

- The integration talks only to the host configured by the user. There are no hardcoded hosts, cloud calls or telemetry.
- Every optional endpoint (firmware, shares, network, accounts, cloud access, USB) uses the same configured host and the same authenticated session; a failure in one endpoint only disables its own entities.
- The account, cloud-access and USB sensors are created disabled in the entity registry. The account sensor exposes user names, e-mail addresses and group membership; enable it only when you need it.
- The OS5 client is vendored in `custom_components/mycloud/wdnas.py`; there is no external runtime dependency. It is based on the audited, MIT-licensed `wdnas-client` 0.9.4. See [THIRD_PARTY_NOTICES.md](custom_components/mycloud/THIRD_PARTY_NOTICES.md).
- There is no `eval`, `exec`, `subprocess`, shell execution or dynamic import in the integration.
- The password is not copied into `hass.data`; the coordinator is kept in `entry.runtime_data` and owns the single client session.
- Diagnostics redact the password, account lists, cloud-access payload and USB payload.

### Transport security

The integration supports both HTTP and HTTPS. The default is HTTP so existing entries keep working. When the NAS web interface uses `https://`, enable **Use HTTPS** and include the port in the host, for example `192.168.1.10:8543`.

WD firmware uses a self-signed certificate. For HTTPS the integration therefore encrypts the connection but does not verify the certificate identity. This protects the credentials from passive sniffing on the local network, but not from an attacker who can actively intercept or redirect traffic. Over HTTP the credentials are sent as base64, which is encoding, not encryption, so anyone who can sniff the local network can recover them.

- Prefer HTTPS when the NAS web interface supports it.
- Put the NAS and Home Assistant on a dedicated VLAN or trusted network.
- Do not expose the NAS web interface to the internet.
- Use a unique admin password, not a password reused elsewhere.
- Keep the NAS firmware updated.

See [SECURITY.md](SECURITY.md) for the threat model, the audit findings and the residual risks.

## Troubleshooting

### `cannot_connect`

Verify the IP address or hostname, the port and the HTTP/HTTPS choice. The NAS web interface must be reachable from Home Assistant and the admin account must not already be logged in elsewhere.

### The NAS uses HTTPS or port 8543

Some OS5 firmware serves the web interface only over HTTPS on port 8543. In the integration:

1. Set **Host** to the NAS address and port, for example `192.168.1.10:8543`. Do not paste `https://` into the host field.
2. Enable **Use HTTPS**.
3. Leave the username and password unchanged and submit the form.

The integration accepts the WD self-signed certificate without verifying it. If the NAS still redirects HTTP to HTTPS, the HTTPS option was not enabled or the configured port is wrong.

### `invalid_auth` or "account is currently in use"

The NAS rejected the credentials, or the admin account is still in use. OS5
allows only one active admin session, so the same message appears when:

- the password is wrong;
- a browser tab, the WD My Cloud app, WD Discovery or another Home Assistant
  instance is logged in as the same admin;
- Home Assistant itself still holds an admin session created before 3.0.1.

Starting with 3.0.1 the integration releases its server-side session with
`DELETE /nas/v1/auth` on unload, reconfigure and re-authentication. It also
reports the busy response with a dedicated `admin_session_busy` error and
retries later, instead of asking for the password again. Starting with 3.0.6
the integration reads the OS5 JSON error code directly, so `{"error": "5"}` is
reported as a busy admin session even when the body contains no localized text.
Starting with 3.0.7 an expired domain password (`{"error": "-1"}`) is reported
as `password_expired`, and a non-administrator account (`{"error": "-2"}`) as
`not_admin`. Starting with 3.0.3 the login also accepts a `PHPSESSID` cookie set
by a redirect and ignores a malformed `Set-Cookie` header instead of reporting
the password as wrong. Starting with 3.0.8 the login accepts the opaque
authentication cookies used by newer OS5 firmware (`fe97238703cba` and
`ge41881ed8d9r`) as well as `PHPSESSID`, so a successful browser login is no
longer rejected because the PHP session cookie is absent. Starting with 3.1.1
the plain-text firmware replies `logged in from other IP address` and
`max session time exceeded` are also reported as `admin_session_busy` instead
of `invalid_auth`; earlier versions asked for the password again in that case.
Starting with 3.1.5 every authenticated request, including the legacy
`/cgi-bin/` endpoints (`system_status`, `uptime` and the power actions),
repeats the login's `Origin`, `Referer` and `X-Requested-With` headers.
Firmware that binds the token to the login origin otherwise accepts the login
and then rejects the data requests with `request origin != token origin`
(HTTP 403), which Home Assistant reports as `invalid_auth`. Versions 3.1.3
and 3.1.4 omitted those headers on the CGI endpoints for older firmware;
3.1.5 requires current OS5 firmware. Update the integration before
troubleshooting the NAS.

If the NAS still reports the account as in use:

1. Disable the integration entry, or stop Home Assistant, to stop polling.
2. Sign out of the NAS web interface and close every WD My Cloud and WD
   Discovery session on phones and computers.
3. Wait at least 30-60 minutes without any login attempt. Repeated attempts
   renew the NAS session timeout.
4. Re-enable the entry and retry. If the NAS remains locked, restart it once;
   a reboot releases the stale admin sessions. If SSH is enabled, the narrower
   `nasAdmin` restart described below clears the same in-memory session without
   rebooting the whole NAS.

### `account_locked`

The NAS temporarily blocks the admin account or the client IP after several
consecutive failed logins. This is not a wrong password. The firmware reports
JSON error `-3`; the integration reports `account_locked` and retries later
instead of opening re-authentication or continuing to submit the password.

1. Stop trying to log in for at least 30-60 minutes. WD documents IP blocks
   that can last 1-2 hours, and every new attempt can extend the block.
2. If the block persists, restart the NAS once. A reboot clears the block and
   any stale admin session.
3. Run the login diagnostic below only after the wait or the reboot, and only
   if the problem remains.

### The browser can log in but Home Assistant cannot

The browser and Home Assistant may not use the same URL or the same source IP:

1. Open the same URL in the browser: `http://<nas-address>` or `https://<nas-address>:8543`. In the integration use the same scheme and port. If the browser is redirected to HTTPS, enable **Use HTTPS** and include the port in the host.
2. Check the NAS firewall or IP allowlist. Home Assistant may connect from a
   different address than the computer that runs the browser, especially when
   Home Assistant runs in Docker, a VM or another VLAN.
3. Disable the integration entry, sign out of the NAS web interface and close
   every WD app. Wait 2-3 minutes, then enable the entry and retry once. A
   browser tab that still looks logged in can keep the single admin session
   active.
4. If the NAS log `/var/log/nasAdmin.log` shows
   `"operation":"login","status":"success"` followed by
   `request origin != token origin`, or the debug log shows
   `NAS system_status request failed: HTTP 403` right after
   `NAS login accepted`, the firmware bound the token to the login origin and
   rejected the data requests. Update the integration to 3.1.5 or newer.
5. Enable debug logging and retry once. A rejected login logs
   `NAS login failed: HTTP ...`; a login that succeeded but failed on a data
   call logs `NAS <endpoint> request failed: HTTP ...`; a successful login logs
   `NAS login accepted`. The endpoint name in the second line shows whether the
   failure is on `device_info` or `system_info`. The login lines also list the
   cookie names and JSON body keys, never their values.
6. If the debug log still only shows `invalid_auth`, run the diagnostic below
   from the Home Assistant host, not from the browser computer. It shows the
   NAS response and source-IP-specific result.

### Diagnose a rejected login

The integration logs the login HTTP status, redirect count, content type and a
short response body at debug level, without the password or cookies. If
`invalid_auth` persists with the correct password, run the standalone
diagnostic from a clone of this repository, on a computer that can reach the
NAS:

```bash
python3 -m pip install aiohttp
python scripts/diagnose_login.py --host 192.168.1.10 --username admin
```

For an HTTPS-only NAS, include the port and add `--https`:

```bash
python scripts/diagnose_login.py --host 192.168.1.10:8543 --https --username admin
```

The script needs Python 3 and `aiohttp`. It prompts for the password without
echoing it, performs exactly one login attempt and prints the status, redirect
chain, cookie names and attributes (values redacted) and the response body with
secrets redacted. `MYCLOUD_HOST`, `MYCLOUD_USERNAME`, `MYCLOUD_PASSWORD` and
`MYCLOUD_HTTPS=1` can replace the prompts and flags. The script is not imported
by the integration and is not a runtime dependency. Close the NAS web interface
first, and do not run it while an `account_locked` block is active.

### Diagnose memory values

To inspect the raw status payload reported by the firmware (for example to see
which memory fields it exposes), run the standalone status diagnostic from a
computer that can reach the NAS:

```bash
python3 -m pip install aiohttp
python scripts/diagnose_status.py --host 192.168.1.10 --username admin
```

It prints the XML returned by `/cgi-bin/status_mgr.cgi` for `cmd=resource`,
`cmd=cgi_get_general` and `cmd=cgi_get_status`. The password and the session
cookies are redacted. The same environment variables as `diagnose_login.py`
are accepted.

### Recover a stale admin session over SSH (optional)

OS5 keeps the admin login record and its rate limiter in the `nasAdmin`
process. Restarting that process clears both without rebooting the NAS. This is
an optional manual recovery path: the integration never uses SSH, never imports
this script and never stores SSH credentials.

SSH is disabled by default on OS5. Enable it in **Settings → Network → SSH**
and set an SSH password in the same dialog. The firmware's `sshd_config` allows
only the `sshd` account, which is uid 0. Use that account, not the web admin
name.

First run the read-only discovery from a clone of this repository:

```bash
python3 scripts/ssh_recover.py --host 192.168.1.10
```

The script uses the system OpenSSH client with `StrictHostKeyChecking=yes` and
your `~/.ssh/known_hosts`. It refuses to connect when the NAS host key is not
already trusted. Verify the fingerprint out of band, add it to `known_hosts`
and run again. The report shows the OS5 processes, listening ports, service
scripts, admin account flags and block-list files; it does not print password
hashes or log contents.

If the discovery confirms `nasAdmin` is running but the login remains stuck,
restart it:

```bash
python3 scripts/ssh_recover.py --host 192.168.1.10 \
    --action nasadmin --confirm nasadmin
```

Restarting `nasAdmin` clears the in-memory `loginRecord` and rate limiter. It
also restarts `restsdk` and `otaclient` when they are running, so the NAS web
services may be unavailable for a short time. It does not clear `/etc/blockip`,
an `/etc/shadow` account lock or a network-level block, and it does not reboot
or power off the NAS. Use `--dry-run` to inspect the exact SSH command, or
`--list-actions` to see the fixed allowlist (`nasadmin`, `php-fpm`, `apache`,
`restsdk`). Every action requires an exact `--confirm` value.

The script prompts for the SSH password without echoing it. For a
non-interactive run, set `MYCLOUD_SSH_PASSWORD` and install `sshpass`; the
password is passed to `sshpass` through its environment, never on the command
line. Alternatively, select a key with `--identity`. The script does not save
credentials to disk.

### `invalid_host`

Remove `http://`, `https://`, paths, query strings and credentials from the host field. Select HTTPS with the **Use HTTPS** checkbox instead of adding a scheme to the host.

### Some sensors are unavailable

The firmware, alert, uptime, share, network, account, cloud-access and USB endpoints are optional. If the NAS firmware does not support one of them, only the related entities become unavailable and the other sensors keep working. Check the Home Assistant log with debug logging enabled for the failed endpoint.

### An OS2 entry no longer loads

OS2 firmware is not supported. The entry stops during setup with `os2_not_supported` instead of trying an OS5 login. Update the NAS to OS5, delete the old entry, and add it again with the same admin credentials.

### The power action is refused

The NAS safety check (`cgi_Detect_Dangerous`) returned a non-zero code, usually because a RAID operation, a firmware update or another maintenance task is in progress. Wait for the NAS to finish and try again. The integration does not retry a power command automatically.

### The power action times out

The NAS may drop the HTTP connection while it is powering off. The integration treats a dropped connection as a successful action, but a timeout can still be reported if the NAS stays silent. Check whether the NAS is shutting down before pressing the button again; never assume the first command was ignored.

### The power buttons are missing or disabled

The Restart and Shutdown buttons are always created for OS5 entries. Restart is enabled by default; Shutdown is disabled by default. Enable Shutdown in **Settings → Devices & services → Entities** if you want to use it. If neither button exists, check that the entry loaded correctly and that Home Assistant is running 2026.8.0 or newer.

### Enable debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.mycloud: debug
```

### Download diagnostics

Go to **Settings → Devices & services → WD My Cloud → ⋮ → Download diagnostics**. The password, account lists, cloud-access payload and USB payload are redacted automatically. Attach the file to a GitHub issue and remove any remaining personal information.

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
mypy
ruff check custom_components tests scripts
ruff format --check custom_components tests scripts
```

The test suite covers host validation, config flow errors, setup and unload lifecycle, unique ID migration, stale device removal, coordinator re-authentication, entity values, translations, static security checks and every vendored OS5 endpoint. CI requires at least 95% line coverage for every module of the integration, including the vendored client.

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

- [@J-shw](https://github.com/J-shw) for the original [ha-mycloud](https://github.com/J-shw/ha-mycloud) integration and the [wdnas_client](https://github.com/J-shw/wdnas_client) library, from which the vendored OS5 client is derived.
- All upstream contributors who reverse-engineered and tested the WD NAS API.

## License

The upstream `J-shw/ha-mycloud` repository does not include a license file. This fork preserves that upstream status and does not add a license for its own code. No license is granted for the rest of this repository; if you need clear redistribution rights, ask the upstream author. The integration is provided as-is, without warranty.

The vendored OS5 client in `custom_components/mycloud/wdnas.py` is different: it is derived from `wdnas-client` and remains under the upstream MIT License. The full license text, copyright notice and provenance are in [THIRD_PARTY_NOTICES.md](custom_components/mycloud/THIRD_PARTY_NOTICES.md), which is included in every HACS release.

Western Digital, My Cloud and related marks are trademarks of their respective owners.
