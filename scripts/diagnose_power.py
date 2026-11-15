#!/usr/bin/env python3
"""Diagnose WD My Cloud OS5 power-action endpoints without powering off the NAS.

The script performs exactly one authenticated request to the safety-check
endpoint ``POST /cgi-bin/hd_config.cgi`` with ``cmd=cgi_Detect_Dangerous``,
the same call the integration makes before restarting or shutting down. It
then reports whether the NAS accepts the request or returns HTTP 403.

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

import aiohttp

SCHEME = "http://"
HTTPS_SCHEME = "https://"
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
    """Run one safety-check request and return a process exit code."""
    scheme = _scheme(args.https)
    url = f"{scheme}{host}{SAFETY_PATH}"
    headers = {
        "Host": host,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    # Legacy CGI endpoints under /cgi-bin/ must NOT receive Origin/Referer /
    # X-Requested-With, otherwise OS5 rejects them with HTTP 403.

    print(f"URL: {url}")
    print(f"Username: {username.lower()}")
    print(f"Command: {SAFETY_COMMAND}")
    if args.https:
        print("TLS certificate verification: disabled (WD self-signed certificate)")
    print("Origin/Referer/X-Requested-With: omitted (legacy CGI)")

    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(ssl=False) if args.https else None
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            async with session.post(
                url, data=SAFETY_COMMAND, headers=headers
            ) as response:
                body = await response.text()
                print(f"\nHTTP status: {response.status}")
                print(f"Final URL: {_redact_location(str(response.url))}")
                print(
                    f"Content-Type: {response.headers.get('Content-Type', '<missing>')}"
                )
                print(f"Body length: {len(body)} characters")
                _print_redirects(response)
                _print_set_cookie(response)
                _print_cookie_sources(response, session)
                print("\nResponse body (secrets redacted):")
                print(_redact_body(body, args.body_limit, password))

                ok = response.status == 200
                print(f"\nPower-action safety endpoint usable: {'yes' if ok else 'no'}")
                if not ok:
                    print(
                        "The NAS rejected the safety-check request with HTTP 403. "
                        "This is why Restart/Shutdown fail in Home Assistant. "
                        "Verify that no browser tab or WD app is logged in as admin, "
                        "then retry."
                    )
                    return 1
                return 0
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
