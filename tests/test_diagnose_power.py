"""Tests for the standalone power-action diagnostic."""

from __future__ import annotations

import http.cookies
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import ParseError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_power.py"
SPEC = importlib.util.spec_from_file_location("diagnose_power", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnose_power = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose_power)


class _FakeHeaders:
    """Minimal aiohttp headers replacement."""

    def __init__(self, values: dict[str, str], set_cookie: list[str]) -> None:
        self._values = values
        self._set_cookie = set_cookie

    def get(self, name: str, default=None):
        """Return one response header."""
        return self._values.get(name, default)

    def getall(self, name: str, default=None):
        """Return the configured Set-Cookie headers."""
        assert name == "Set-Cookie"
        return self._set_cookie


class _FakeResponse:
    """Minimal aiohttp response replacement."""

    def __init__(
        self,
        status: int,
        body: str = "",
        *,
        url: str = "http://nas.local/",
        set_cookie: list[str] | None = None,
        cookies: http.cookies.SimpleCookie | None = None,
        history=(),
    ) -> None:
        self.status = status
        self.url = url
        self.history = history
        self.cookies = cookies if cookies is not None else http.cookies.SimpleCookie()
        self.headers = _FakeHeaders({"Content-Type": "text/xml"}, set_cookie or [])
        self._body = body

    async def text(self) -> str:
        """Return the configured response body."""
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeCookieJar:
    """Cookie jar that records updated cookies for assertions."""

    def __init__(self) -> None:
        self.updated: dict[str, str] = {}

    def update_cookies(self, cookies: dict[str, str]) -> None:
        """Record cookies set by the diagnostic."""
        self.updated.update(cookies)

    def __iter__(self):
        return iter(())


class _FakeSession:
    """Return prepared responses and record every request."""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.cookie_jar = _FakeCookieJar()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def post(self, url, data=None, json=None, headers=None):
        """Record the request and return the next response."""
        self.calls.append(
            {"url": url, "data": data, "json": json, "headers": headers or {}}
        )
        return self.responses.pop(0)


def _args(**overrides) -> SimpleNamespace:
    """Return command-line arguments for the diagnostic."""
    values = {
        "host": "nas.local",
        "username": "admin",
        "https": False,
        "timeout": 30,
        "body_limit": 2000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _login_response() -> _FakeResponse:
    """Return a login response that sets a session cookie."""
    cookies = http.cookies.SimpleCookie()
    cookies["PHPSESSID"] = "abc123"
    return _FakeResponse(
        200,
        "{}",
        url="http://nas.local/nas/v1/auth",
        set_cookie=["PHPSESSID=abc123; Path=/"],
        cookies=cookies,
    )


async def test_diagnose_logs_in_then_only_checks_safety(monkeypatch):
    """The diagnostic logs in and never sends a power command."""
    session = _FakeSession(
        [_login_response(), _FakeResponse(200, "<root><res>0</res></root>")]
    )
    monkeypatch.setattr(
        diagnose_power.aiohttp, "ClientSession", lambda **kwargs: session
    )

    result = await diagnose_power._diagnose("nas.local", "Admin", "secret", _args())

    assert result == 0
    assert [call["url"] for call in session.calls] == [
        "http://nas.local/nas/v1/auth",
        "http://nas.local/cgi-bin/hd_config.cgi",
    ]
    assert session.calls[0]["data"] is None
    assert session.calls[0]["json"]["username"] == "admin"
    assert session.calls[1]["data"] == "cmd=cgi_Detect_Dangerous"
    assert all(
        "cgi_restart" not in str(call["data"])
        and "cgi_shutdown" not in str(call["data"])
        for call in session.calls
    )
    for call in session.calls:
        assert call["headers"]["Origin"] == "http://nas.local"
        assert call["headers"]["Referer"] == "http://nas.local/"
        assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"


async def test_diagnose_reports_non_zero_safety_code(monkeypatch, capsys):
    """A non-zero safety result is printed as a refusal of the power action."""
    session = _FakeSession(
        [_login_response(), _FakeResponse(200, "<root><res>6</res></root>")]
    )
    monkeypatch.setattr(
        diagnose_power.aiohttp, "ClientSession", lambda **kwargs: session
    )

    result = await diagnose_power._diagnose("nas.local", "admin", "secret", _args())

    output = capsys.readouterr().out
    assert result == 1
    assert "Safety check result: 6" in output
    assert "does not send cgi_restart or cgi_shutdown" in output
    assert len(session.calls) == 2


async def test_diagnose_stops_when_login_fails(monkeypatch, capsys):
    """A rejected login does not attempt the safety check."""
    session = _FakeSession([_FakeResponse(401, "")])
    monkeypatch.setattr(
        diagnose_power.aiohttp, "ClientSession", lambda **kwargs: session
    )

    result = await diagnose_power._diagnose("nas.local", "admin", "secret", _args())

    assert result == 1
    assert len(session.calls) == 1
    assert "Login was not accepted" in capsys.readouterr().err


async def test_diagnose_reports_safety_http_error(monkeypatch, capsys):
    """An HTTP error from the safety endpoint is not reported as a refusal."""
    session = _FakeSession([_login_response(), _FakeResponse(403, "forbidden")])
    monkeypatch.setattr(
        diagnose_power.aiohttp, "ClientSession", lambda **kwargs: session
    )

    result = await diagnose_power._diagnose("nas.local", "admin", "secret", _args())

    assert result == 1
    assert "rejected the safety-check request with HTTP 403" in capsys.readouterr().err


async def test_diagnose_reports_unparseable_safety_response(monkeypatch, capsys):
    """A malformed safety payload is not treated as an allowed action."""
    session = _FakeSession([_login_response(), _FakeResponse(200, "<root/>")])
    monkeypatch.setattr(
        diagnose_power.aiohttp, "ClientSession", lambda **kwargs: session
    )

    result = await diagnose_power._diagnose("nas.local", "admin", "secret", _args())

    assert result == 1
    assert "Safety check result: unparseable" in capsys.readouterr().err


def test_scheme_supports_http_and_https():
    """The diagnostic follows the same scheme selected in the integration."""
    assert diagnose_power._scheme(False) == "http://"
    assert diagnose_power._scheme(True) == "https://"


def test_headers_follow_the_login_origin():
    """Header construction mirrors the integration, including origin headers."""
    headers = diagnose_power._headers("nas.local:8543", True, form=True)

    assert headers["Host"] == "nas.local:8543"
    assert headers["Origin"] == "https://nas.local:8543"
    assert headers["Referer"] == "https://nas.local:8543/"
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Content-Type"].startswith("application/x-www-form-urlencoded")

    without_origin = diagnose_power._headers("nas.local", False, origin=False)
    assert "Origin" not in without_origin
    assert "Referer" not in without_origin
    assert "X-Requested-With" not in without_origin


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("<root><res>0</res></root>", 0),
        ("<root><res>6</res></root>", 6),
        ("<root><nested><res> 2 </res></nested></root>", 2),
    ],
)
def test_parse_safety_code_returns_the_numeric_result(body, expected):
    """The diagnostic reports the same res value the integration reads."""
    assert diagnose_power._parse_safety_code(body) == expected


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("<root><res>yes</res></root>", "not numeric"),
        ("<root/>", "no res element"),
        ("not xml", "not valid XML"),
    ],
)
def test_parse_safety_code_rejects_missing_or_invalid_results(body, message):
    """Malformed safety results are errors, never implicit approval."""
    with pytest.raises(ParseError, match=message):
        diagnose_power._parse_safety_code(body)


def test_login_cookies_reads_the_redirect_chain_and_reports_bad_headers():
    """Cookies are collected from every response and bad headers are ignored."""
    redirect = _FakeResponse(302, set_cookie=["PHPSESSID=first; Path=/nas/v1/auth"])
    response = _FakeResponse(
        200,
        set_cookie=[
            "malformed-cookie",
            "fe97238703cba=abc; Path=/",
            "ge41881ed8d9r=def",
        ],
        history=(redirect,),
    )

    cookies = diagnose_power._login_cookies(response)

    assert cookies["PHPSESSID"].value == "first"
    assert cookies["fe97238703cba"].value == "abc"
    assert cookies["ge41881ed8d9r"].value == "def"
