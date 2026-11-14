"""Static security checks for the integration package."""

from __future__ import annotations

import json
import re
from pathlib import Path

PACKAGE = Path(__file__).parents[1] / "custom_components" / "mycloud"
FORBIDDEN = re.compile(
    r"\b(eval|exec|__import__|subprocess|os\.system|os\.popen|pickle)\b"
)


def test_manifest_requirement_is_exactly_pinned():
    """The third-party library is pinned to the audited release."""
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    requirements = manifest["requirements"]
    assert requirements == ["wdnas-client==0.9.4"]


def test_no_dangerous_dynamic_code():
    """The package does not execute code or spawn processes."""
    for path in PACKAGE.rglob("*.py"):
        content = path.read_text()
        assert not FORBIDDEN.search(content), path


def test_no_hardcoded_network_endpoints():
    """All traffic is built from the user-configured NAS host."""
    for path in PACKAGE.rglob("*.py"):
        content = path.read_text()
        assert "http://" not in content, path
        assert "https://" not in content, path


def test_no_credentials_in_log_calls():
    """Log messages never interpolate the password."""
    for path in PACKAGE.rglob("*.py"):
        for line in path.read_text().splitlines():
            if "_LOGGER." in line:
                assert "PASSWORD" not in line, path
                assert "password" not in line.lower(), path
