#!/usr/bin/env python3
"""Diagnose a WD My Cloud OS5 admin login without exposing the password.

The script performs exactly one login attempt against the same endpoint and
payload as the integration, then prints the HTTP status, the redirect chain,
the cookie names and attributes (values are redacted) and a truncated response
body. It is a troubleshooting tool only: the integration never calls it.

Close the NAS web interface and every WD app before running it, because OS5
allows only one active admin session.

Examples:
    python scripts/diagnose_login.py --host 192.168.1.10 --username admin

    MYCLOUD_PASSWORD='secret' python scripts/diagnose_login.py \\
        --host 192.168.1.10 --username admin

The password is read from ``MYCLOUD_PASSWORD`` or prompted interactively. It is
never printed and is removed from the response body before it is shown.
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
LOGIN_PATH = "/nas/v1/auth"
DEFAULT_TIMEOUT = 30
DEFAULT_BODY_LIMIT = 2000

_SECRET_RE = re.compile(
    r"(?i)(PHPSESSID|session[_-]?id|csrf[_-]?token|token|password|pwd)"
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


def _has_session_cookie(cookies: http.cookies.SimpleCookie) -> bool:
    """Return True when a cookie set contains a non-empty PHPSESSID."""
    morsel = cookies.get("PHPSESSID")
    return morsel is not None and bool(morsel.value)


def _print_cookie_sources(
    response: aiohttp.ClientResponse, session: aiohttp.ClientSession
) -> None:
    """Show where a PHPSESSID was visible to the client."""
    redirect_names: set[str] = set()
    for item in response.history:
        redirect_names.update(item.cookies.keys())
    jar_names = sorted(morsel.key for morsel in session.cookie_jar)

    print("\nPHPSESSID sources:")
    print(
        f"  final response: {'yes' if _has_session_cookie(response.cookies) else 'no'}"
    )
    print(f"  redirect chain: {'yes' if 'PHPSESSID' in redirect_names else 'no'}")
    print(f"  cookie jar: {'yes' if 'PHPSESSID' in jar_names else 'no'}")
    print(f"  all jar cookie names: {', '.join(jar_names) or '<none>'}")


def _parse_args() -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description="Run one WD My Cloud OS5 login and print a redacted report."
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
    """Run one login attempt and return a process exit code."""
    url = f"{SCHEME}{host}{LOGIN_PATH}"
    encoded_password = base64.b64encode(password.encode("utf-8")).decode("utf-8")
    origin = f"{SCHEME}{host}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Host": host,
        "Origin": origin,
        "Referer": f"{origin}/",
        "X-Requested-With": "XMLHttpRequest",
    }

    print(f"URL: {url}")
    print(f"Username: {username.lower()}")
    print(f"Payload password: base64, {len(encoded_password)} characters")

    timeout = aiohttp.ClientTimeout(total=args.timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(
                url,
                json={"username": username.lower(), "password": encoded_password},
                headers=headers,
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

                success = response.status == 200 and (
                    _has_session_cookie(response.cookies)
                    or any(
                        _has_session_cookie(item.cookies) for item in response.history
                    )
                    or any(
                        morsel.key == "PHPSESSID" and bool(morsel.value)
                        for morsel in session.cookie_jar
                    )
                )
                print(
                    f"\nLogin usable by the integration: {'yes' if success else 'no'}"
                )
                return 0 if success else 1
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
