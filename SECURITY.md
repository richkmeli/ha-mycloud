# Security policy

## Supported versions

Security fixes are applied to the latest release.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Use GitHub's private vulnerability reporting:

<https://github.com/richkmeli/ha-mycloud/security/advisories/new>

Include the affected version, a description, reproduction steps and any relevant logs with credentials removed.

## Security model

### Network behaviour

- The integration is **local polling only**. It never contacts a Western Digital cloud service, analytics endpoint or any other third party.
- Every request is built from the host configured by the user. The API paths are fixed by the NAS protocol, but there are no hardcoded hosts, cloud endpoints or fallback destinations in the integration or in the vendored OS5 client (`custom_components/mycloud/wdnas.py`).
- The host field only accepts a hostname, IPv4/IPv6 address and optional port. Schemes, paths, query strings, fragments and `user:password@host` are rejected before a connection is attempted.
- The transport scheme is selected by an explicit HTTPS option. HTTP remains the default for compatibility with entries created before 3.1.0. HTTPS uses a dedicated aiohttp connector with certificate verification disabled, because WD firmware serves a self-signed certificate: the traffic is encrypted but the server identity is not authenticated.
- Requests have a 30-second timeout so a dead NAS cannot block the Home Assistant event loop forever.
- The optional firmware, alert, uptime, share, network, account, cloud-access and USB endpoints use the same configured host and the same authenticated session. They do not introduce a second network destination. Each endpoint is isolated: a failure in one only makes its related entities unavailable, while the core sensors keep updating.
- The V5 uptime fallback (`cgi_get_status`) is a second command on the same NAS status endpoint. It is used only after the dedicated uptime command fails and still applies the same host, session and timeout rules.
- The account, cloud-access and USB payloads may contain personal or unvalidated data. Their sensors are created disabled in the entity registry and are never enabled automatically.
- Restart and shutdown buttons are always created for OS5 entries. Restart is enabled by default; Shutdown is disabled until the user enables it in the entity registry. Every action first runs the NAS dashboard's read-only `cgi_Detect_Dangerous` safety check; a non-zero result blocks the action. The command is sent once over the existing authenticated session and is never retried, because an unanswered request may already have powered the device off. The integration does not use SSH or a second connection for power actions.
- The optional `scripts/ssh_recover.py` helper is **not** part of the integration, is never imported at runtime and is not shipped in the HACS archive. It is a manual recovery tool for a stale `nasAdmin` session. It uses the system OpenSSH client with strict host-key verification, runs a fixed read-only discovery report by default and can only restart the allowlisted `nasadmin`, `php-fpm`, `apache` and `restsdk` services after an exact `--confirm` value. It has no arbitrary command option and no reboot, shutdown or power action.

### Credentials and storage

- The username and password are stored in the Home Assistant config entry, in `.storage/core.config_entries`, like every other Home Assistant integration. Protect the Home Assistant configuration directory accordingly.
- The password is **not** copied into `hass.data`; the coordinator is kept in `entry.runtime_data` and owns the single client session.
- The password is **not** written to logs.
- Diagnostics redact the password, account lists, cloud-access payload and USB payload before the file is generated.
- Configuration uses a password input field, so the password is not shown on screen while typing.
- The integration never stores SSH credentials. When the optional recovery helper is used, the SSH password is prompted without echo or read from `MYCLOUD_SSH_PASSWORD`; in the environment-variable case it is passed to `sshpass` through `SSHPASS`, never on the command line, and it is not written to disk.

### Known protocols and residual risk

1. **Transport security.** The integration supports HTTP and HTTPS. HTTP remains the default so entries created before 3.1.0 keep working. The password is base64-encoded, which is encoding, not encryption: over HTTP an attacker who can sniff the LAN can recover the credentials. HTTPS encrypts the connection, but the WD self-signed certificate is not verified, so an attacker who can actively intercept or redirect traffic is not detected. Prefer HTTPS when the NAS web interface supports it, use a trusted VLAN, do not expose the NAS to the internet, use a unique admin password and keep the firmware updated.
2. **Admin account.** The integration needs an admin account. WD firmware allows the admin account to be active in only one place at a time. A compromised Home Assistant host therefore exposes the NAS admin password. Harden the Home Assistant host and restrict access to its configuration.
3. **NAS firmware.** The integration trusts the XML/JSON returned by the NAS. A malicious or compromised NAS can return malformed data; the integration validates types and reports unavailable entities instead of crashing, but it cannot protect the NAS from itself. Alert messages, account details, cloud-access data and USB payloads are treated as opaque data, exposed only as sensor states/attributes and never rendered as HTML or executed. The account, cloud-access and USB sensors are disabled by default.
4. **Vendored client.** The OS5 protocol client is vendored from `wdnas-client` 0.9.4 (MIT License) and has no external runtime dependency. The source distribution was audited before vendoring: it only uses `aiohttp`, has no install hooks, no telemetry, no shell execution and no endpoint other than the configured host. The upstream copyright and license are preserved in `custom_components/mycloud/THIRD_PARTY_NOTICES.md`; local changes are listed in that file and in `UPSTREAM.md`.
5. **Optional SSH recovery.** Enabling SSH on the NAS exposes port 22 and gives the `sshd` account root-equivalent access. Keep SSH disabled when it is not needed, restrict it to the trusted LAN, use a unique password or a key and verify the host fingerprint before trusting it. The recovery helper refuses unknown host keys and does not store credentials.

## Audit — 2026-11-14

Scope:

- `custom_components/mycloud/*` (all Python, JSON and translation files)
- Vendored `wdnas-client` 0.9.4 source (`custom_components/mycloud/wdnas.py`)
- Git history of the fork and upstream repository
- GitHub Actions workflows and issue templates

Method:

- Manual review of every source file and every network call.
- Search for `eval`, `exec`, `compile`, `__import__`, `subprocess`, `os.system`, `os.popen`, `pickle`, base64/obfuscation and hardcoded URLs.
- Verification that all requests use the configured host and that no credentials are logged.
- Dependency inspection (sdist contents, `setup.py`, `install_requires`).
- Static checks and tests in CI (`ruff` with the `S` bandit rules and `tests/test_security.py`).

Findings and resolutions:

| ID | Severity | Finding | Status |
| --- | --- | --- | --- |
| F-01 | Medium (residual) | The NAS API sends credentials over plain HTTP by default. | Mitigated in 3.1.0 by the optional **Use HTTPS** setting. HTTPS encrypts traffic but does not verify the WD self-signed certificate; HTTP remains the default for existing entries. Mitigations documented in README and SECURITY.md. |
| F-02 | Medium | The setup copied the plaintext password into `hass.data`. | Fixed: only the coordinator is stored, now in `entry.runtime_data`. |
| F-03 | Medium | The host field accepted arbitrary strings, including schemes and paths. | Fixed: strict validation and normalization. |
| F-04 | Medium | The password field was a plain text input. | Fixed: password selector. |
| F-05 | Medium | The config flow stored credentials without validating the connection or the device endpoints. | Fixed: login, `device_info` and `system_info` are checked before creating the entry. |
| F-06 | Medium | `wdnas-client>=0.9.4` was unpinned (supply-chain drift). | Fixed: the reviewed client is vendored and the runtime dependency was removed. |
| F-07 | Low | The aiohttp session could leak on setup failure/unload; the platform unload function was dead code. | Fixed: session ownership moved to `client.py` and `__init__.py`. |
| F-08 | Low | Volume unique IDs were based on the volume label and could collide between NAS devices. | Fixed: device serial + volume ID. |
| F-09 | Low | Binary sensors were registered from the `sensor` platform. | Fixed: separate `binary_sensor` platform. |
| F-10 | Low | Requests had no explicit timeout. | Fixed: 30-second total timeout. |
| F-11 | Low | The new-device issue template contained malformed YAML/quoting. | Fixed. |
| F-12 | Low | GitHub Actions used floating `@main`/`@master` refs. | Fixed: actions pinned to commit SHAs; workflows use least-privilege permissions. |
| F-13 | Low | A failing alert or uptime endpoint could make every entity unavailable, even though those sensors are optional. | Fixed: optional endpoints are isolated and return `None` on failure; only the affected sensors become unavailable. |
| F-14 | Low | A power action button exposed by default could shut down the NAS accidentally. | Fixed: Shutdown is created disabled, enabled only by the user in the entity registry, and both actions are guarded by the NAS safety check and never retried. |
| F-15 | Low | The account, cloud-access and USB sensors could expose personal data or an unvalidated payload by default. | Fixed: all three are created disabled in the entity registry. |

No backdoor, hidden endpoint, credential exfiltration, obfuscated payload, install hook or unexpected outbound connection was found.

F-01 was updated on 2026-11-15 when optional HTTPS support was added.

## Hardening checklist for users

- [ ] **Use HTTPS** is enabled when the NAS web interface uses HTTPS, commonly on port 8543.
- [ ] Home Assistant and the NAS are on a trusted VLAN or network.
- [ ] The NAS web interface is not exposed to the internet.
- [ ] The NAS admin password is unique and stored in a password manager.
- [ ] SSH is disabled on the NAS unless it is needed for recovery, and uses a unique password or a key.
- [ ] Home Assistant configuration backups are encrypted.
- [ ] The NAS firmware is up to date.
- [ ] Only trusted people can access the Home Assistant UI and configuration.
