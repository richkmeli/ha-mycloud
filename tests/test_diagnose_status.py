"""Tests for the standalone status diagnostic helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_status.py"
SPEC = importlib.util.spec_from_file_location("diagnose_status", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnose_status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose_status)


class _FakeHeaders:
    """Minimal aiohttp headers replacement for cookie tests."""

    def __init__(self, set_cookie: list[str]) -> None:
        self._set_cookie = set_cookie

    def getall(self, name: str, default=None):
        """Return the configured Set-Cookie headers."""
        assert name == "Set-Cookie"
        return self._set_cookie


class _FakeResponse:
    """Minimal aiohttp response replacement for cookie tests."""

    def __init__(self, set_cookie: list[str], history=()) -> None:
        self.headers = _FakeHeaders(set_cookie)
        self.history = history


def test_scheme_supports_http_and_https():
    """The diagnostic follows the same scheme selected in the integration."""
    assert diagnose_status._scheme(False) == "http://"
    assert diagnose_status._scheme(True) == "https://"


def test_headers_follow_the_login_origin():
    """Header construction mirrors the integration, including origin headers."""
    headers = diagnose_status._headers("nas.local:8543", True, form=True)

    assert headers["Host"] == "nas.local:8543"
    assert headers["Origin"] == "https://nas.local:8543"
    assert headers["Referer"] == "https://nas.local:8543/"
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Content-Type"].startswith("application/x-www-form-urlencoded")

    without_origin = diagnose_status._headers("nas.local", False, origin=False)
    assert "Origin" not in without_origin
    assert "Referer" not in without_origin
    assert "X-Requested-With" not in without_origin


def test_tag_names_lists_distinct_xml_tags_in_order():
    """Tag discovery keeps the document order and removes duplicates."""
    root = diagnose_status.fromstring(
        "<root><cpu>1</cpu><mem_total>2</mem_total></root>"
    )

    assert diagnose_status._tag_names(root) == ["root", "cpu", "mem_total"]


def test_format_payload_shows_tags_and_body():
    """A valid XML payload is printed with its tag names."""
    payload = "<root><cpu>12%</cpu><mem_available>441856</mem_available></root>"

    formatted = diagnose_status._format_payload(payload, 1000)

    assert "XML tags: root, cpu, mem_available" in formatted
    assert "441856" in formatted


def test_format_payload_handles_invalid_and_long_bodies():
    """A malformed or long payload is still printable and marked as such."""
    invalid = diagnose_status._format_payload("<root><broken>", 100)
    assert invalid.startswith("XML: unparseable")
    assert "<root><broken>" in invalid

    long_body = "<root>" + "x" * 50 + "</root>"
    clipped = diagnose_status._format_payload(long_body, 10)
    assert clipped.startswith("XML tags: root")
    assert "more characters" in clipped


def test_format_payload_marks_empty_bodies():
    """An empty body is not printed as a blank line."""
    assert diagnose_status._format_payload("", 100).endswith("<empty>")


def test_login_cookies_reads_the_redirect_chain_and_reports_bad_headers():
    """Cookies are collected from every response and bad headers are ignored."""
    redirect = _FakeResponse(["PHPSESSID=first; Path=/nas/v1/auth"])
    response = _FakeResponse(
        [
            "malformed-cookie",
            "fe97238703cba=abc; Path=/",
            "ge41881ed8d9r=def",
        ],
        history=(redirect,),
    )

    cookies = diagnose_status._login_cookies(response)

    assert cookies["PHPSESSID"].value == "first"
    assert cookies["fe97238703cba"].value == "abc"
    assert cookies["ge41881ed8d9r"].value == "def"
