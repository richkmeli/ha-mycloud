"""Tests for the standalone SSH recovery helper."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ssh_recover.py"
SPEC = importlib.util.spec_from_file_location("ssh_recover", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ssh_recover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ssh_recover)


def test_normalize_host_accepts_hostname_and_ip_addresses():
    """Hostnames, IPv4 and bracketed IPv6 addresses are accepted."""
    assert ssh_recover.normalize_host("nas.local") == "nas.local"
    assert ssh_recover.normalize_host("NAS.Local") == "nas.local"
    assert ssh_recover.normalize_host("192.168.1.10") == "192.168.1.10"
    assert ssh_recover.normalize_host("[fe80::1]") == "fe80::1"


@pytest.mark.parametrize(
    "host",
    [
        "",
        "http://nas.local",
        "nas.local/web",
        "nas.local:22",
        "user@nas.local",
        "nas local",
        "nas_local",
        "-nas.local",
    ],
)
def test_normalize_host_rejects_unsafe_values(host):
    """Schemes, paths, ports, credentials and shell-like hosts are rejected."""
    with pytest.raises(ValueError):
        ssh_recover.normalize_host(host)


@pytest.mark.parametrize("username", ["sshd", "root", "admin.user", "a-b_c"])
def test_normalize_username_accepts_safe_names(username):
    """Normal SSH account names are accepted."""
    assert ssh_recover.normalize_username(username) == username


@pytest.mark.parametrize("username", ["", "root;id", "root name", "root\nid"])
def test_normalize_username_rejects_unsafe_names(username):
    """Shell metacharacters and whitespace are rejected."""
    with pytest.raises(ValueError):
        ssh_recover.normalize_username(username)


@pytest.mark.parametrize("port", [1, 22, 2222, 65535])
def test_normalize_port_accepts_valid_ports(port):
    """TCP ports are accepted within the valid range."""
    assert ssh_recover.normalize_port(port) == port


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_normalize_port_rejects_invalid_ports(port):
    """Out-of-range ports are rejected."""
    with pytest.raises(ValueError):
        ssh_recover.normalize_port(port)


def test_known_host_entry_uses_brackets_only_for_non_default_ports():
    """known_hosts uses a bracketed host:port for non-default ports."""
    assert ssh_recover.known_host_entry("nas.local", 22) == "nas.local"
    assert ssh_recover.known_host_entry("nas.local", 2222) == "[nas.local]:2222"
    assert ssh_recover.known_host_entry("fe80::1", 2222) == "[fe80::1]:2222"


def test_build_ssh_command_uses_strict_host_key_verification(monkeypatch):
    """The command never accepts an unknown host key automatically."""
    monkeypatch.setattr(ssh_recover.shutil, "which", lambda name: f"/usr/bin/{name}")

    command = ssh_recover.build_ssh_command(
        host="nas.local",
        port=22,
        username="sshd",
        known_hosts="/home/user/.ssh/known_hosts",
        identity=None,
        remote_command="uname -a",
        use_password=False,
    )

    assert command[0] == "/usr/bin/ssh"
    assert "-T" in command
    assert "StrictHostKeyChecking=yes" in command
    assert "UserKnownHostsFile=/home/user/.ssh/known_hosts" in command
    assert "GlobalKnownHostsFile=/dev/null" in command
    assert "BatchMode" not in command
    assert "StrictHostKeyChecking=accept-new" not in command
    assert command[-2:] == ["sshd@nas.local", "uname -a"]


def test_build_ssh_command_adds_an_identity(monkeypatch):
    """An explicit private key is passed with -i."""
    monkeypatch.setattr(ssh_recover.shutil, "which", lambda name: f"/usr/bin/{name}")

    command = ssh_recover.build_ssh_command(
        host="nas.local",
        port=2222,
        username="sshd",
        known_hosts="/home/user/.ssh/known_hosts",
        identity="/home/user/.ssh/id_ed25519",
        remote_command="true",
        use_password=False,
    )

    index = command.index("-i")
    assert command[index + 1] == "/home/user/.ssh/id_ed25519"
    assert command[command.index("-p") + 1] == "2222"


def test_build_ssh_command_uses_sshpass_environment(monkeypatch):
    """Password mode uses sshpass -e and never puts the password in argv."""
    monkeypatch.setattr(
        ssh_recover.shutil,
        "which",
        lambda name: f"/usr/bin/{name}",
    )

    command = ssh_recover.build_ssh_command(
        host="nas.local",
        port=22,
        username="sshd",
        known_hosts="/home/user/.ssh/known_hosts",
        identity=None,
        remote_command="true",
        use_password=True,
    )

    assert command[:3] == ["/usr/bin/sshpass", "-e", "/usr/bin/ssh"]
    assert "secret" not in " ".join(command)


def test_build_ssh_command_requires_sshpass_for_password_mode(monkeypatch):
    """A missing sshpass produces a clear error instead of a plain prompt."""
    monkeypatch.setattr(
        ssh_recover.shutil,
        "which",
        lambda name: None if name == "sshpass" else "/usr/bin/ssh",
    )

    with pytest.raises(RuntimeError, match="sshpass"):
        ssh_recover.build_ssh_command(
            host="nas.local",
            port=22,
            username="sshd",
            known_hosts="/home/user/.ssh/known_hosts",
            identity=None,
            remote_command="true",
            use_password=True,
        )


def test_build_ssh_command_requires_an_ssh_client(monkeypatch):
    """A missing OpenSSH client produces a clear error."""
    monkeypatch.setattr(ssh_recover.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="OpenSSH"):
        ssh_recover.build_ssh_command(
            host="nas.local",
            port=22,
            username="sshd",
            known_hosts="/home/user/.ssh/known_hosts",
            identity=None,
            remote_command="true",
            use_password=False,
        )


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("nasadmin", "/usr/sbin/nasAdmin.sh restart"),
        ("php-fpm", "/usr/sbin/php-fpm.sh reload"),
        ("apache", "/usr/sbin/apache restart web"),
        ("restsdk", "/usr/sbin/restsdk.sh restart"),
    ],
)
def test_restart_command_uses_only_allowlisted_commands(action, expected):
    """Every action expands to a fixed firmware service command."""
    command = ssh_recover.restart_command(action)

    assert expected in command
    assert "set -u" in command
    assert "pidof" in command


def test_restart_command_rejects_unknown_actions():
    """Arbitrary shell commands cannot be turned into an action."""
    with pytest.raises(ValueError, match="Unsupported action"):
        ssh_recover.restart_command("rm -rf /")


def test_password_environment_rejects_line_breaks(monkeypatch):
    """A malformed password environment value is rejected before SSH runs."""
    monkeypatch.setenv(ssh_recover.PASSWORD_ENV, "secret\nother")

    with pytest.raises(ValueError, match="line breaks"):
        ssh_recover._password_from_environment()


def test_password_environment_rejects_empty_values(monkeypatch):
    """An empty password environment value is not treated as 'no password'."""
    monkeypatch.setenv(ssh_recover.PASSWORD_ENV, "")

    with pytest.raises(ValueError, match="empty"):
        ssh_recover._password_from_environment()


def test_run_returns_the_ssh_exit_code(monkeypatch):
    """The SSH process exit code is passed through."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(ssh_recover.subprocess, "run", fake_run)

    assert ssh_recover._run(["ssh"], timeout=10, password=None, dry_run=False) == 7
    assert calls[0][0] == ["ssh"]
    assert calls[0][1]["check"] is False


def test_run_puts_the_password_only_in_the_child_environment(monkeypatch):
    """The password is available to sshpass but not in the command line."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ssh_recover.subprocess, "run", fake_run)
    credential_value = "s3cr3t"

    assert (
        ssh_recover._run(
            ["sshpass", "-e", "ssh"],
            timeout=10,
            password=credential_value,
            dry_run=False,
        )
        == 0
    )
    assert calls[0][1]["env"]["SSHPASS"] == credential_value
    assert credential_value not in " ".join(calls[0][0])


def test_run_handles_timeouts(monkeypatch, capsys):
    """A hung SSH command returns a failure and explains the risk."""

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ssh_recover.subprocess, "run", fake_run)

    assert ssh_recover._run(["ssh"], timeout=1, password=None, dry_run=False) == 1
    assert "timed out" in capsys.readouterr().err


def test_run_handles_missing_executables(monkeypatch, capsys):
    """An OSError from the SSH client is reported without a traceback."""

    def fake_run(command, **kwargs):
        raise OSError("not found")

    monkeypatch.setattr(ssh_recover.subprocess, "run", fake_run)

    assert ssh_recover._run(["ssh"], timeout=1, password=None, dry_run=False) == 1
    assert "Could not run SSH" in capsys.readouterr().err


def test_main_dry_run_prints_discovery_without_connecting(monkeypatch, capsys):
    """Dry-run discovery prints the strict SSH command and exits successfully."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--dry-run",
        ],
    )
    monkeypatch.setattr(ssh_recover.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert ssh_recover.main() == 0
    output = capsys.readouterr().out
    assert "StrictHostKeyChecking=yes" in output
    assert "uname -a" in output


def test_main_dry_run_prints_an_allowlisted_action(monkeypatch, capsys):
    """A confirmed action can be inspected with --dry-run."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--action",
            "php-fpm",
            "--confirm",
            "php-fpm",
            "--dry-run",
        ],
    )
    monkeypatch.setattr(ssh_recover.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert ssh_recover.main() == 0
    output = capsys.readouterr().out
    assert "/usr/sbin/php-fpm.sh reload" in output


def test_main_refuses_an_action_without_confirmation(monkeypatch, capsys):
    """A restart is never sent without an exact confirmation."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--action",
            "nasadmin",
            "--dry-run",
        ],
    )

    assert ssh_recover.main() == 2
    assert "Refusing" in capsys.readouterr().err


def test_main_refuses_a_mismatched_confirmation(monkeypatch, capsys):
    """The confirmation must match the selected action exactly."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--action",
            "nasadmin",
            "--confirm",
            "apache",
            "--dry-run",
        ],
    )

    assert ssh_recover.main() == 2
    assert "Refusing" in capsys.readouterr().err


def test_main_rejects_confirmation_without_an_action(monkeypatch, capsys):
    """A stray --confirm is rejected instead of being ignored."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["ssh_recover.py", "--host", "nas.local", "--confirm", "nasadmin"],
    )

    assert ssh_recover.main() == 2
    assert "--confirm requires --action" in capsys.readouterr().err


def test_main_requires_a_host(monkeypatch, capsys):
    """The host must come from the command line or the environment."""
    monkeypatch.delenv("MYCLOUD_HOST", raising=False)
    monkeypatch.setattr(sys, "argv", ["ssh_recover.py"])

    assert ssh_recover.main() == 2
    assert "--host is required" in capsys.readouterr().err


def test_main_lists_actions_without_connecting(monkeypatch, capsys):
    """--list-actions documents the fixed allowlist."""
    monkeypatch.setattr(sys, "argv", ["ssh_recover.py", "--list-actions"])

    assert ssh_recover.main() == 0
    output = capsys.readouterr().out
    assert "nasadmin: /usr/sbin/nasAdmin.sh restart" in output
    assert "php-fpm: /usr/sbin/php-fpm.sh reload" in output


def test_main_rejects_a_missing_known_hosts_file(monkeypatch, tmp_path, capsys):
    """A real connection requires an existing known_hosts file."""
    # Dry-run does not need the file, so make it a real run and provide auth.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--known-hosts",
            str(tmp_path / "missing"),
            "--identity",
            str(tmp_path / "key"),
        ],
    )

    assert ssh_recover.main() == 2
    assert "Known-hosts file not found" in capsys.readouterr().err


def test_main_rejects_an_unknown_host_key(monkeypatch, tmp_path, capsys):
    """An unknown host key is refused before SSH can trust it."""
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--known-hosts",
            str(known_hosts),
            "--identity",
            str(tmp_path / "key"),
        ],
    )
    monkeypatch.setattr(ssh_recover, "_known_host_is_present", lambda *args: False)

    assert ssh_recover.main() == 2
    assert "No host key" in capsys.readouterr().err


def test_main_runs_ssh_with_password_from_the_environment(
    monkeypatch, tmp_path, capsys
):
    """A configured password reaches sshpass without appearing in argv or logs."""
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("", encoding="utf-8")
    monkeypatch.setenv(ssh_recover.PASSWORD_ENV, "s3cr3t")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--known-hosts",
            str(known_hosts),
        ],
    )
    monkeypatch.setattr(ssh_recover, "_known_host_is_present", lambda *args: True)
    monkeypatch.setattr(
        ssh_recover.shutil,
        "which",
        lambda name: f"/usr/bin/{name}",
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ssh_recover.subprocess, "run", fake_run)

    assert ssh_recover.main() == 0
    command, kwargs = calls[0]
    assert command[:3] == ["/usr/bin/sshpass", "-e", "/usr/bin/ssh"]
    assert kwargs["env"]["SSHPASS"] == "s3cr3t"
    assert "s3cr3t" not in " ".join(command)
    assert "strict host-key verification" in capsys.readouterr().err


def test_main_requires_interactive_auth_when_stdin_is_not_a_terminal(
    monkeypatch, tmp_path, capsys
):
    """A non-interactive run without a key or password cannot hang on a prompt."""
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("", encoding="utf-8")
    monkeypatch.delenv(ssh_recover.PASSWORD_ENV, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssh_recover.py",
            "--host",
            "nas.local",
            "--known-hosts",
            str(known_hosts),
        ],
    )
    monkeypatch.setattr(ssh_recover, "_known_host_is_present", lambda *args: True)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert ssh_recover.main() == 2
    assert "stdin is not a terminal" in capsys.readouterr().err
