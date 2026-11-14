"""Static security checks for the integration package."""

from __future__ import annotations

import json
import re
from pathlib import Path

PACKAGE = Path(__file__).parents[1] / "custom_components" / "mycloud"
FORBIDDEN = re.compile(
    r"\b(eval|exec|__import__|subprocess|os\.system|os\.popen|pickle)\b"
)
SCHEME_DECLARATION = 'SCHEME = "http://"'


def test_manifest_has_no_external_requirements():
    """The NAS client is vendored, so no runtime package is installed."""
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    assert manifest.get("requirements", []) == []


def test_no_dangerous_dynamic_code():
    """The package does not execute code or spawn processes."""
    for path in PACKAGE.rglob("*.py"):
        content = path.read_text()
        assert not FORBIDDEN.search(content), path


def test_no_hardcoded_network_endpoints():
    """All traffic is built from the user-configured NAS host."""
    for path in PACKAGE.rglob("*.py"):
        for line in path.read_text().splitlines():
            if path.name == "wdnas.py" and line.strip() == SCHEME_DECLARATION:
                # The WD firmware exposes a plain HTTP API only. This is the
                # single scheme declaration used to build every request.
                continue
            assert "http://" not in line, path
            assert "https://" not in line, path


def test_no_credentials_in_log_calls():
    """Log messages never interpolate the password."""
    for path in PACKAGE.rglob("*.py"):
        for line in path.read_text().splitlines():
            if "_LOGGER." in line:
                assert "PASSWORD" not in line, path
                assert "password" not in line.lower(), path


def test_vendored_client_keeps_license_and_provenance():
    """The vendored client ships the upstream MIT notice."""
    notices = (PACKAGE / "THIRD_PARTY_NOTICES.md").read_text()
    assert "MIT License" in notices
    assert "Copyright (c) 2019 - 2024  Joakim Sørensen @ludeeus" in notices
    assert "wdnas_client" in notices

    source = (PACKAGE / "wdnas.py").read_text()
    assert "MIT License" in source
    assert "@ludeeus" in source


def test_no_external_wdnas_imports():
    """Every integration module uses the vendored client."""
    for path in PACKAGE.rglob("*.py"):
        content = path.read_text()
        assert "from wdnas_client" not in content, path
        assert "import wdnas_client" not in content, path
