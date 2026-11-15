#!/usr/bin/env python3
"""Recover a WD My Cloud OS5 admin login over SSH.

This is a manual recovery tool for the case where the NAS keeps rejecting the
admin password because a stale ``nasAdmin`` login record or rate limiter is
still active. It runs a fixed, read-only discovery report by default. Restarting
a service requires an explicit allowlisted action and a matching ``--confirm``
value.

The script is intentionally standalone: the integration never imports it, it
never stores credentials, and it never sends a password on the command line.
It uses the system OpenSSH client with strict host-key verification. OS5
normally accepts SSH logins only for the ``sshd`` account, which is uid 0 and
therefore has the privileges needed for the service scripts.

Examples:
    python3 scripts/ssh_recover.py --host 192.168.1.10

    python3 scripts/ssh_recover.py --host 192.168.1.10 \\
        --action nasadmin --confirm nasadmin

    MYCLOUD_SSH_PASSWORD='secret' python3 scripts/ssh_recover.py \\
        --host 192.168.1.10 --action php-fpm --confirm php-fpm

If no SSH key is selected with ``--identity`` and ``MYCLOUD_SSH_PASSWORD`` is
not set, the OpenSSH client prompts for the password on the terminal.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from ipaddress import ip_address
from pathlib import Path

DEFAULT_PORT = 22
DEFAULT_USERNAME = "sshd"
DEFAULT_KNOWN_HOSTS = "~/.ssh/known_hosts"
DEFAULT_TIMEOUT = 120
PASSWORD_ENV = "MYCLOUD_SSH_PASSWORD"  # noqa: S105 - environment variable name

# These are the fixed commands used by the firmware's own service scripts and
# monit configuration. The values are complete command lines, not user input.
ACTION_COMMANDS = {
    "nasadmin": "/usr/sbin/nasAdmin.sh restart",
    "php-fpm": "/usr/sbin/php-fpm.sh reload",
    "apache": "/usr/sbin/apache restart web",
    "restsdk": "/usr/sbin/restsdk.sh restart",
}

DISCOVERY_COMMAND = r"""
echo "== System =="
uname -a 2>/dev/null
cat /etc/model 2>/dev/null
cat /etc/version 2>/dev/null
uptime 2>/dev/null
echo
echo "== Identity =="
id 2>/dev/null
echo
echo "== Service processes =="
for name in nasAdmin php-fpm httpd restsdk-server otaclient chk_blockip; do
    pid=$(pidof "$name" 2>/dev/null)
    if [ -n "$pid" ]; then
        echo "$name: $pid"
    else
        echo "$name: not running"
    fi
done
echo
echo "== Matching processes =="
ps w 2>/dev/null \
    | grep -E 'nasAdmin|php-fpm|httpd|restsdk|otaclient|chk_blockip' \
    | grep -v grep
echo
echo "== Listening ports =="
if command -v netstat >/dev/null 2>&1; then
    netstat -lntp 2>/dev/null | grep -E ':(22|80|8000|8001|8543)[[:space:]]'
elif command -v ss >/dev/null 2>&1; then
    ss -lntp 2>/dev/null | grep -E ':(22|80|8000|8001|8543)[[:space:]]'
else
    echo "netstat/ss not available"
fi
echo
echo "== Service scripts =="
for path in \
    /usr/sbin/nasAdmin.sh \
    /usr/sbin/php-fpm.sh \
    /usr/sbin/apache \
    /usr/sbin/restsdk.sh \
    /usr/sbin/otaclient.sh
do
    if [ -x "$path" ]; then
        ls -l "$path"
    else
        echo "$path: missing or not executable"
    fi
done
echo
echo "== Admin account (hash never printed) =="
awk -F: '$1=="admin"{print "name=" $1, "hashlen=" length($2), \
    "changed=" $3, "expire=" $8}' /etc/shadow 2>/dev/null
passwd -S admin 2>/dev/null || true
echo
echo "== Block-list files =="
ls -l /etc/blockip /etc/blockip.bak /usr/local/config/blockip 2>/dev/null
wc -l /etc/blockip /etc/blockip.bak 2>/dev/null
echo
echo "== nasAdmin settings =="
grep -E \
    -e 'httpPort|httpsPort|proxyPort|sdkClientPort' \
    -e 'httpTimeoutSec|maxSessionTimeoutSec' \
    -e 'requests|seconds' \
    /etc/nasAdmin.toml 2>/dev/null
echo
echo "== Uptime =="
cat /proc/uptime 2>/dev/null
"""

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"(?:{_LABEL}\.)*{_LABEL}")
_USERNAME_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")


def normalize_host(value: str) -> str:
    """Return a validated hostname or IP address without a port."""
    host = value.strip()
    if not host:
        raise ValueError("A NAS host is required")
    if any(character.isspace() for character in host):
        raise ValueError("The NAS host must not contain whitespace")
    if any(character in host for character in "/?#@\\"):
        raise ValueError("Use only a hostname or IP address; pass the port with --port")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return str(ip_address(host))
    except ValueError:
        pass
    if len(host) > 253 or _HOSTNAME_RE.fullmatch(host) is None:
        raise ValueError(f"Invalid NAS host: {value!r}")
    return host.lower()


def normalize_username(value: str) -> str:
    """Return a safe SSH username."""
    if _USERNAME_RE.fullmatch(value) is None:
        raise ValueError(f"Invalid SSH username: {value!r}")
    return value


def normalize_path(value: str, *, setting: str) -> str:
    """Expand a path and reject characters that could corrupt an SSH option."""
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError(f"Invalid {setting} path")
    return str(Path(value).expanduser())


def normalize_port(value: int) -> int:
    """Return a valid TCP port."""
    if not 1 <= value <= 65535:
        raise ValueError(f"Invalid SSH port: {value}")
    return value


def known_host_entry(host: str, port: int) -> str:
    """Return the name used for the host in ``known_hosts``."""
    return host if port == DEFAULT_PORT else f"[{host}]:{port}"


def _ssh_path() -> str:
    """Return the absolute path of the OpenSSH client."""
    executable = shutil.which("ssh")
    if executable is None:
        raise RuntimeError("The OpenSSH client ('ssh') was not found in PATH")
    return executable


def build_ssh_command(
    *,
    host: str,
    port: int,
    username: str,
    known_hosts: str,
    identity: str | None,
    remote_command: str,
    use_password: bool,
) -> list[str]:
    """Build a strictly verified SSH command without embedding a password.

    ``sshpass -e`` reads the password from ``SSHPASS`` in the child
    environment. It is used only when the caller explicitly selected the
    password environment variable. Interactive logins do not use it.
    """
    command = [
        _ssh_path(),
        "-T",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=3",
        "-p",
        str(port),
    ]
    if identity is not None:
        command.extend(["-i", identity])
    if use_password:
        sshpass = shutil.which("sshpass")
        if sshpass is None:
            raise RuntimeError(
                "MYCLOUD_SSH_PASSWORD is set but 'sshpass' is not installed"
            )
        command = [sshpass, "-e", *command]
    command.extend([f"{username}@{host}", remote_command])
    return command


def restart_command(action: str) -> str:
    """Return the fixed restart script for an allowlisted action."""
    command = ACTION_COMMANDS.get(action)
    if command is None:
        raise ValueError(f"Unsupported action: {action}")

    guard = """if [ ! -e /etc/nasAdmin.toml ]; then
    echo "This does not look like a WD My Cloud OS5 system: " \\
        "/etc/nasAdmin.toml is missing" >&2
    exit 1
fi
"""

    if action == "nasadmin":
        return f"""set -u
{guard}echo "== Restarting nasAdmin =="
{command}
result=$?
if [ "$result" -ne 0 ]; then
    echo "nasAdmin.sh restart failed with status $result" >&2
    exit "$result"
fi
pid=$(pidof nasAdmin 2>/dev/null)
if [ -z "$pid" ]; then
    echo "nasAdmin is not running after the restart" >&2
    exit 1
fi
echo "nasAdmin is running: $pid"
"""

    if action == "php-fpm":
        process = "php-fpm"
        precheck = (
            f"pid=$(pidof {process} 2>/dev/null)\n"
            'if [ -z "$pid" ]; then\n'
            f'    echo "{process} is not running; refusing to reload" >&2\n'
            "    exit 1\n"
            "fi\n"
        )
    elif action == "apache":
        process = "httpd"
        precheck = (
            f"pid=$(pidof {process} 2>/dev/null)\n"
            'if [ -z "$pid" ]; then\n'
            f'    echo "{process} is not running; refusing to restart" >&2\n'
            "    exit 1\n"
            "fi\n"
        )
    else:
        process = "restsdk-server"
        precheck = (
            f"pid=$(pidof {process} 2>/dev/null)\n"
            'if [ -z "$pid" ]; then\n'
            f'    echo "{process} is not running; refusing to restart" >&2\n'
            "    exit 1\n"
            "fi\n"
        )

    return f"""set -u
{guard}{precheck}echo "== Running: {command} =="
{command}
result=$?
if [ "$result" -ne 0 ]; then
    echo "Command failed with status $result" >&2
    exit "$result"
fi
echo "Command completed"
"""


def _password_from_environment() -> str | None:
    """Return the SSH password from the environment, if it was provided."""
    password = os.environ.get(PASSWORD_ENV)
    if password is None:
        return None
    if not password:
        raise ValueError(f"{PASSWORD_ENV} is set but empty")
    if any(character in password for character in "\r\n\0"):
        raise ValueError(f"{PASSWORD_ENV} must not contain line breaks or NUL")
    return password


def _known_host_is_present(host: str, port: int, known_hosts: str) -> bool | None:
    """Check a known-hosts file with ssh-keygen, or return None if unavailable."""
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [ssh_keygen, "-F", known_host_entry(host, port), "-f", known_hosts],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.returncode == 0


def _print_host_key_help(host: str, port: int, known_hosts: str) -> None:
    """Print the safe way to add a verified host key."""
    entry = known_host_entry(host, port)
    scan_command = f"ssh-keyscan -p {port} {host}"
    print(
        f"No host key for {entry} was found in {known_hosts}.",
        file=sys.stderr,
    )
    print(
        "Verify the fingerprint out of band before trusting it, for example "
        "against a previous known_hosts entry or the NAS console. Then run:",
        file=sys.stderr,
    )
    print(f"  {scan_command} > /tmp/nas.hostkey", file=sys.stderr)
    print("  ssh-keygen -lf /tmp/nas.hostkey", file=sys.stderr)
    print(f"  cat /tmp/nas.hostkey >> {known_hosts}", file=sys.stderr)


def _run(
    command: list[str],
    *,
    timeout: int,
    password: str | None,
    dry_run: bool,
) -> int:
    """Run an SSH command, or only print it in dry-run mode."""
    if dry_run:
        print(shlex.join(command))
        return 0

    environment = None
    if password is not None:
        environment = os.environ.copy()
        environment["SSHPASS"] = password
    try:
        result = subprocess.run(  # noqa: S603 - fixed args, no shell
            command,
            env=environment,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"SSH command timed out after {timeout} seconds. The NAS may still "
            "be applying the change; reconnect and run the discovery again.",
            file=sys.stderr,
        )
        return 1
    except OSError as err:
        print(f"Could not run SSH: {err}", file=sys.stderr)
        return 1
    return result.returncode


def _parse_args() -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only OS5 login recovery report, or restart an "
            "allowlisted NAS service after an explicit confirmation."
        )
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MYCLOUD_HOST"),
        help="NAS hostname or IP address without a port (env: MYCLOUD_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"SSH port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("MYCLOUD_SSH_USERNAME", DEFAULT_USERNAME),
        help=f"SSH username (default: {DEFAULT_USERNAME})",
    )
    parser.add_argument(
        "--known-hosts",
        default=DEFAULT_KNOWN_HOSTS,
        help=f"known_hosts file (default: {DEFAULT_KNOWN_HOSTS})",
    )
    parser.add_argument(
        "--identity",
        help="SSH private key; omit to prompt for a password",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"SSH command timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--action",
        choices=sorted(ACTION_COMMANDS),
        help="restart one allowlisted service instead of running discovery",
    )
    parser.add_argument(
        "--confirm",
        metavar="ACTION",
        help="required with --action; must exactly match the action",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the SSH command without connecting",
    )
    parser.add_argument(
        "--list-actions",
        action="store_true",
        help="print the allowlisted actions and exit",
    )
    return parser.parse_args()


def main() -> int:
    """Run discovery or a confirmed recovery action."""
    args = _parse_args()
    if args.list_actions:
        for action in sorted(ACTION_COMMANDS):
            print(f"{action}: {ACTION_COMMANDS[action]}")
        return 0
    if not args.host:
        print("--host is required (or set MYCLOUD_HOST)", file=sys.stderr)
        return 2

    try:
        host = normalize_host(args.host)
        port = normalize_port(args.port)
        username = normalize_username(args.username)
        known_hosts = normalize_path(args.known_hosts, setting="known_hosts")
        identity = (
            normalize_path(args.identity, setting="identity") if args.identity else None
        )
        password = _password_from_environment() if identity is None else None
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 2

    if args.action is None:
        if args.confirm is not None:
            print("--confirm requires --action", file=sys.stderr)
            return 2
        remote_command = DISCOVERY_COMMAND
    else:
        if args.confirm != args.action:
            print(
                f"Refusing to run {args.action!r}: pass "
                f"--confirm {args.action} after reviewing the action",
                file=sys.stderr,
            )
            return 2
        remote_command = restart_command(args.action)

    if not args.dry_run:
        if not Path(known_hosts).is_file():
            print(
                f"Known-hosts file not found: {known_hosts}\n"
                "Create it and add the verified NAS host key before connecting.",
                file=sys.stderr,
            )
            return 2
        present = _known_host_is_present(host, port, known_hosts)
        if present is False:
            _print_host_key_help(host, port, known_hosts)
            return 2
        if identity is None and password is None and not sys.stdin.isatty():
            print(
                "No SSH identity and no MYCLOUD_SSH_PASSWORD were provided, "
                "and stdin is not a terminal. Use --identity, set "
                f"{PASSWORD_ENV}, or run interactively.",
                file=sys.stderr,
            )
            return 2

    try:
        command = build_ssh_command(
            host=host,
            port=port,
            username=username,
            known_hosts=known_hosts,
            identity=identity,
            remote_command=remote_command,
            use_password=password is not None,
        )
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 2

    if not args.dry_run:
        target = "discovery" if args.action is None else f"action {args.action}"
        print(
            f"Connecting to {username}@{host}:{port} for {target} "
            "(strict host-key verification)",
            file=sys.stderr,
        )
    return _run(
        command,
        timeout=args.timeout,
        password=password,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
