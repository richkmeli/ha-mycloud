#!/usr/bin/env python3
"""Print the WD My Cloud OS5 status payloads without exposing secrets.

The script logs in with the same request as the integration, then posts
``cmd=resource``, ``cmd=cgi_get_general`` and ``cmd=cgi_get_status`` to
``/cgi-bin/status_mgr.cgi``. It prints the HTTP status, the content type, the
XML tag names and the body so the memory fields reported by the firmware can
be inspected. The password
and the session cookies are never printed. It is a troubleshooting tool only:
the integration never calls it.

Close the NAS web interface and every WD app before running it, because OS5
allows only one active admin session.

Examples:
    python scripts/diagnose_status.py --host 192.168.1.10 --username admin

    python scripts/diagnose_status.py --host 192.168.1.10:8543 --https \\
        --username admin

The password is read from ``MYCLOUD_PASSWORD`` or prompted interactively. It is
never printed and the login response body is not shown.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import http.cookies
import os
import sys
from xml.etree.ElementTree import Element, ParseError, fromstring

import aiohttp

SCHEME = "http://"
HTTPS_SCHEME = "https://"
LOGIN_PATH = "/nas/v1/auth"
STATUS_PATH = "/cgi-bin/status_mgr.cgi"
DEFAULT_TIMEOUT = 30
DEFAULT_BODY_LIMIT = 8000

STATUS_COMMANDS = ("cmd=resource", "cmd=cgi_get_general", "cmd=cgi_get_status")


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

    The login and the status endpoint both use the login origin on current
    firmware; ``origin=False`` is kept for completeness and local tests.
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


def _tag_names(root: Element) -> list[str]:
    """Return the distinct XML tag names in document order."""
    names: list[str] = []
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = element.tag.rsplit("}", 1)[-1]
        if name not in names:
            names.append(name)
    return names


def _format_payload(body: str, limit: int) -> str:
    """Return a readable status payload, clipped to a body limit."""
    try:
        root = fromstring(body)  # noqa: S314 - the NAS is configured by the user
    except ParseError:
        excerpt = body[:limit]
        suffix = (
            f"\n... ({len(body) - limit} more characters)" if len(body) > limit else ""
        )
        return f"XML: unparseable\n{excerpt or '<empty>'}{suffix}"
    tags = ", ".join(_tag_names(root)) or "none"
    excerpt = body[:limit]
    suffix = f"\n... ({len(body) - limit} more characters)" if len(body) > limit else ""
    return f"XML tags: {tags}\n{excerpt or '<empty>'}{suffix}"


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


def _parse_args() -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description="Print the WD My Cloud OS5 status XML payloads."
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


async def _diagnose(args: argparse.Namespace, password: str) -> int:
    """Log in and print both status payloads."""
    scheme = _scheme(args.https)
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(ssl=False) if args.https else None
    encoded_password = base64.b64encode(password.encode("utf-8")).decode("utf-8")

    login_headers = _headers(args.host, args.https)
    login_headers["Content-Type"] = "application/json"
    login_headers["Accept"] = "application/json"

    print(f"URL: {scheme}{args.host}{STATUS_PATH}")
    print(f"Username: {args.username.lower()}")
    if args.https:
        print("TLS certificate verification: disabled (WD self-signed certificate)")

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            async with session.post(
                f"{scheme}{args.host}{LOGIN_PATH}",
                json={
                    "username": args.username.lower(),
                    "password": encoded_password,
                },
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
                if response.status != 200 or not names:
                    print(
                        "Login was not accepted; the status payloads need a "
                        "usable admin session.",
                        file=sys.stderr,
                    )
                    return 1

            for name, morsel in cookies.items():
                if morsel.value:
                    session.cookie_jar.update_cookies({name: morsel.value})

            for command in STATUS_COMMANDS:
                async with session.post(
                    f"{scheme}{args.host}{STATUS_PATH}",
                    data=command,
                    headers=_headers(args.host, args.https, form=True, origin=True),
                ) as response:
                    body = await response.text()
                    print(
                        f"\n=== POST {STATUS_PATH} {command}: "
                        f"HTTP {response.status} ==="
                    )
                    print(
                        "Content-Type: "
                        f"{response.headers.get('Content-Type', '<missing>')}"
                    )
                    print(_format_payload(body, args.body_limit))
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
        return asyncio.run(_diagnose(args, password))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
