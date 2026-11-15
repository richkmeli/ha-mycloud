"""Tests for the standalone login diagnostic redaction helpers."""

from __future__ import annotations

import http.cookies
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_login.py"
SPEC = importlib.util.spec_from_file_location("diagnose_login", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnose_login = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose_login)


def test_redact_body_hides_passwords_tokens_and_cookies():
    """The body excerpt cannot leak the password or common token fields."""
    body = (
        "login failed for password=s3cr3t-passw0rd "
        "PHPSESSID=abc123 token: xyz789 "
        "base64 czNjcjN0LXBhc3N3MHJk"
    )

    excerpt = diagnose_login._redact_body(body, 500, "s3cr3t-passw0rd")

    for secret in ("s3cr3t-passw0rd", "abc123", "xyz789", "czNjcjN0LXBhc3N3MHJk"):
        assert secret not in excerpt
    assert "password=<redacted>" in excerpt
    assert "PHPSESSID=<redacted>" in excerpt


def test_redact_body_truncates_long_payloads():
    """A long response body is clipped so it can be attached to an issue."""
    excerpt = diagnose_login._redact_body("x" * 120, 100, "secret")

    assert excerpt.startswith("x" * 100)
    assert "20 more characters" in excerpt


def test_redact_location_hides_relative_and_absolute_queries():
    """Redirect URLs keep the path but never the query string."""
    assert (
        diagnose_login._redact_location("/nas/v1/auth?token=abc")
        == "/nas/v1/auth?<redacted>"
    )
    assert (
        diagnose_login._redact_location("http://nas.local/login?session=abc")
        == "http://nas.local/login?<redacted>"
    )
    assert diagnose_login._redact_location(None) == "<none>"


def test_has_session_cookie_requires_a_non_empty_value():
    """An empty PHPSESSID is not a usable session."""
    empty = http.cookies.SimpleCookie()
    empty.load("PHPSESSID=; Path=/")
    valid = http.cookies.SimpleCookie()
    valid.load("PHPSESSID=session; Path=/")

    assert diagnose_login._has_session_cookie(empty) is False
    assert diagnose_login._has_session_cookie(valid) is True
    assert diagnose_login._has_session_cookie(http.cookies.SimpleCookie()) is False


def test_format_cookie_hides_the_value_and_keeps_attributes():
    """Cookie diagnostics keep the flags but redact the secret value."""
    cookie = http.cookies.SimpleCookie()
    cookie.load("PHPSESSID=secret-value; Path=/nas/v1/auth; HttpOnly; Secure")
    name, morsel = next(iter(cookie.items()))

    formatted = diagnose_login._format_cookie(name, morsel)

    assert "secret-value" not in formatted
    assert "PHPSESSID=<redacted>" in formatted
    assert "Path=/nas/v1/auth" in formatted
    assert "HttpOnly" in formatted
    assert "Secure" in formatted
