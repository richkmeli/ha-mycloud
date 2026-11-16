#!/usr/bin/env python3
"""Diagnose WD My Cloud OS5 power-action endpoints without powering off the NAS.

The script logs in with the same request as the integration, then performs
exactly one authenticated request to the safety-check endpoint
``POST /cgi-bin/hd_config.cgi`` with ``cmd=cgi_Detect_Dangerous``, the same
call the integration makes before restarting or shutting down. It reports the
HTTP status, the response body and the numeric ``<res>`` safety code, so a
refused power action can be distinguished from a rejected request or a login
problem.

It does NOT send ``cgi_shutdown`` or ``cgi_restart``, so it is safe to run on
a production NAS.

Close the NAS web interface and every WD app before running it, because OS5
allows only one active admin session.

Examples:
    python scripts/diagnose_power.py --host 192.168.1.10:8543 --https \\
        --username richk

    MYCLOUD_PASSWORD='secret' python scripts/diagnose_power.py \\
        --host 192.168.0.253:8543 --https --username richk

The password is read from ``MYCLOUD_PASSWORD`` or prompted interactively. It is
never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import http.cookies
import os
import re
import sys
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError, fromstring

import aiohttp

SCHEME = "http://"
HTTPS_SCHEME = "https://"
LOGIN_PATH = "/nas/v1/auth"
SAFETY_PATH = "/cgi-bin/hd_config.cgi"
SAFETY_COMMAND = "cmd=cgi_Detect_Dangerous"
DEFAULT_TIMEOUT = 30
DEFAULT_BODY_LIMIT = 2000

_SECRET_RE = re.compile(
    r"(?i)(PHPSESSID|fe97238703cba|ge41881ed8d9r"
    r"|session[_-]?id|csrf[_-]?token|token|password|pwd)"
    r"([\"'\s:=]+)"
    r"[^\"'\s<>,;&]+"
)


def _redact_body(body: str, limit: int, password: str) -> str:
    """Return a shareable excerpt of a response body."""
    redacted = body.replace(password, "<redacted>") if password else body
    if password:
        encoded = base64.b64encode(password.encode("utf-8")).decode("ascii")
        redacted = redacted.replace(encoded, "<redacted>")
    redacted = _SECRET_RE.sub(r"\1\2<redacted>", redacted)
    if len(redacted) > limit:
        return f"{redacted[:limit]}\n... ({len(redacted) - limit} more characters)"
    return redacted or "<empty>"


def _redact_location(location: str | None) -> str:
    """Hide the query string of a redirect target."""
    if not location:
        return "<none>"
    parsed = urlsplit(location)
    suffix = "?<redacted>" if parsed.query else ""
    if not parsed.scheme and not parsed.netloc:
        return f"{parsed.path}{suffix}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}{suffix}"


def _format_cookie(name: str, morsel: http.cookies.Morsel) -> str:
    """Return one Set-Cookie entry with its value replaced by a placeholder."""
    attributes = [f"{name}=<redacted>"]
    for attribute in ("path", "domain", "samesite"):
        value = morsel[attribute]
        if value:
            attributes.append(f"{attribute.capitalize()}={value}")
    for attribute, label in (("secure", "Secure"), ("httponly", "HttpOnly")):
        if morsel[attribute]:
            attributes.append(label)
    return "; ".join(attributes)


def _print_set_cookie(response: aiohttp.ClientResponse) -> None:
    """Print the Set-Cookie headers of the whole redirect chain."""
    print("\nSet-Cookie headers (values redacted):")
    found = False
    for item in (*response.history, response):
        label = "redirect" if item is not response else "final"
        for header in item.headers.getall("Set-Cookie", []):
            found = True
            cookie = http.cookies.SimpleCookie()
            try:
                cookie.load(header)
            except http.cookies.CookieError:
                print(f"  {label}: <unparseable header>")
                continue
            if not cookie:
                print(f"  {label}: <no cookie parsed>")
            for name, morsel in cookie.items():
                print(f"  {label}: {_format_cookie(name, morsel)}")
    if not found:
        print("  <none>")


def _print_redirects(response: aiohttp.ClientResponse) -> None:
    """Print the redirect chain without leaking tokens in the query string."""
    print(f"\nRedirects: {len(response.history)}")
    for index, item in enumerate(response.history, start=1):
        print(
            f"  {index}. HTTP {item.status} -> "
            f"{_redact_location(item.headers.get('Location'))}"
        )


def _scheme(use_https: bool) -> str:
    """Return the URL scheme selected for the diagnostic."""
    return HTTPS_SCHEME if use_https else SCHEME


def _headers(
    host: str,
    use_https: bool,
    *,
    form: bool = False,
    origin: bool = True,
) -> dict[str, str]:
    """Return the headers used by the integration for the same request.

    Current OS5 firmware binds the authentication token to the login origin,
    so every authenticated request, including the legacy ``/cgi-bin/`` power
    endpoints, must repeat the same ``Origin``/``Referer`` headers.
    """
    headers = {"Host": host}
    if origin:
        origin_url = f"{_scheme(use_https)}{host}"
        headers["Origin"] = origin_url
        headers["Referer"] = f"{origin_url}/"
        headers["X-Requested-With"] = "XMLHttpRequest"
    if form:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    return headers


def _login_cookies(
    response: aiohttp.ClientResponse,
) -> http.cookies.SimpleCookie:
    """Return the cookies set by a login response and its redirect chain."""
    cookies = http.cookies.SimpleCookie()
    for item in (*response.history, response):
        for header in item.headers.getall("Set-Cookie", []):
            try:
                cookies.load(header)
            except http.cookies.CookieError:
                print("Ignoring a malformed Set-Cookie header")
    return cookies


def _parse_safety_code(body: str) -> int:
    """Return the numeric ``res`` value of a safety-check response.

    A missing or non-numeric result is not treated as safe: it means the
    integration would reject the action with a parse error instead of sending
    a restart or shutdown command.
    """
    try:
        root = fromstring(body)  # noqa: S314 - the NAS is configured by the user
    except ParseError as err:
        raise ParseError("Safety response is not valid XML") from err
    result = root.findtext(".//res")
    if result is None:
        raise ParseError("Safety response has no res element")
    try:
        return int(result)
    except ValueError as err:
        raise ParseError("Safety res element is not numeric") from err


def _has_session_cookie(cookies: http.cookies.SimpleCookie) -> bool:
    """Return True when a cookie set contains a non-empty session cookie."""
    return any(bool(morsel.value) for morsel in cookies.values())


def _print_cookie_sources(
    response: aiohttp.ClientResponse, session: aiohttp.ClientSession
) -> None:
    """Show where a usable session cookie was visible to the client."""
    redirect_names = {
        name
        for item in response.history
        for name, morsel in item.cookies.items()
        if morsel.value
    }
    final_names = {name for name, morsel in response.cookies.items() if morsel.value}
    jar_names = sorted(morsel.key for morsel in session.cookie_jar if morsel.value)

    print("\nSession cookie sources:")
    print(f"  final response: {', '.join(sorted(final_names)) or 'none'}")
    print(f"  redirect chain: {', '.join(sorted(redirect_names)) or 'none'}")
    print(f"  cookie jar: {', '.join(jar_names) or 'none'}")


def _parse_args() -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Test the WD My Cloud OS5 power-action safety endpoint "
            "without powering off the NAS."
        )
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MYCLOUD_HOST"),
        help="NAS address, optionally with a port (env: MYCLOUD_HOST)",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("MYCLOUD_USERNAME"),
        help="admin username (env: MYCLOUD_USERNAME)",
    )
    parser.add_argument(
        "--https",
        action="store_true",
        default=os.environ.get("MYCLOUD_HTTPS", "").strip().lower()
        in {"1", "true", "yes", "on"},
        help=(
            "use HTTPS and accept the WD self-signed certificate (env: MYCLOUD_HTTPS)"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--body-limit",
        type=int,
        default=DEFAULT_BODY_LIMIT,
        help=f"maximum body characters to print (default: {DEFAULT_BODY_LIMIT})",
    )
    args = parser.parse_args()

    if not args.host:
        args.host = input("NAS host (address or hostname, optional port): ").strip()
    if not args.username:
        args.username = input("Admin username: ").strip()
    if not args.host or not args.username:
        parser.error("--host and --username are required")
    return args


async def _diagnose(host: str, username: str, password: str, args) -> int:
    """Log in, run one safety-check request and return a process exit code."""
    scheme = _scheme(args.https)
    login_url = f"{scheme}{host}{LOGIN_PATH}"
    safety_url = f"{scheme}{host}{SAFETY_PATH}"
    encoded_password = base64.b64encode(password.encode("utf-8")).decode("utf-8")

    login_headers = _headers(host, args.https)
    login_headers["Content-Type"] = "application/json"
    login_headers["Accept"] = "application/json"
    safety_headers = _headers(host, args.https, form=True)

    print(f"Login URL: {login_url}")
    print(f"Safety URL: {safety_url}")
    print(f"Username: {username.lower()}")
    print(f"Command: {SAFETY_COMMAND}")
    print("Power commands: not sent (cgi_restart and cgi_shutdown are disabled)")
    print("Origin/Referer/X-Requested-With: sent, matching the login")
    if args.https:
        print("TLS certificate verification: disabled (WD self-signed certificate)")

    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(ssl=False) if args.https else None
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            async with session.post(
                login_url,
                json={"username": username.lower(), "password": encoded_password},
                headers=login_headers,
            ) as response:
                await response.text()
                cookies = _login_cookies(response)
                names = [name for name, morsel in cookies.items() if morsel.value]
                print(
                    f"\nLogin: HTTP {response.status}, "
                    f"{len(response.history)} redirect(s), "
                    f"cookies: {', '.join(sorted(names)) or 'none'}"
                )
                _print_redirects(response)
                _print_set_cookie(response)
                _print_cookie_sources(response, session)
                if response.status != 200 or not _has_session_cookie(cookies):
                    print(
                        "Login was not accepted; the safety check needs a usable "
                        "admin session. Close every NAS browser tab and WD app, "
                        "then retry.",
                        file=sys.stderr,
                    )
                    return 1

            for name, morsel in cookies.items():
                if morsel.value:
                    session.cookie_jar.update_cookies({name: morsel.value})

            async with session.post(
                safety_url, data=SAFETY_COMMAND, headers=safety_headers
            ) as response:
                body = await response.text()
                print(f"\nSafety check HTTP status: {response.status}")
                print(f"Final URL: {_redact_location(str(response.url))}")
                print(
                    f"Content-Type: {response.headers.get('Content-Type', '<missing>')}"
                )
                print(f"Body length: {len(body)} characters")
                print("\nSafety response body (secrets redacted):")
                print(_redact_body(body, args.body_limit, password))

                if response.status != 200:
                    print(
                        f"\nThe NAS rejected the safety-check request with HTTP "
                        f"{response.status}. This is not a safety refusal: verify "
                        "the login, the host and the Origin headers.",
                        file=sys.stderr,
                    )
                    return 1

                try:
                    code = _parse_safety_code(body)
                except ParseError as err:
                    print(
                        f"\nSafety check result: unparseable ({err}). "
                        "The integration treats this as an error and does not "
                        "send a power command.",
                        file=sys.stderr,
                    )
                    return 1

                if code == 0:
                    print(
                        "\nSafety check result: 0. The NAS would allow the power "
                        "action."
                    )
                    return 0

                print(
                    f"\nSafety check result: {code}. The NAS refuses the power "
                    "action with this code."
                )
                print(
                    "The integration stops here and does not send cgi_restart or "
                    "cgi_shutdown. Wait for maintenance activity to finish and "
                    "check the NAS dashboard for RAID, firmware or volume warnings."
                )
                return 1
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            print(f"\nRequest failed: {type(err).__name__}: {err}", file=sys.stderr)
            return 2


def main() -> int:
    """Run the diagnostic."""
    args = _parse_args()
    password = os.environ.get("MYCLOUD_PASSWORD")
    if not password:
        password = getpass.getpass("Admin password (not echoed): ")
    if not password:
        print("A password is required.", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_diagnose(args.host, args.username, password, args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
