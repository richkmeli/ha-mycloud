"""Fail when any integration module is below the required test coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MIN_COVERAGE = 95.0
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "mycloud"
REPORT = ROOT / "coverage.json"


def main() -> int:
    """Check the coverage report and return a process exit code."""
    if not REPORT.exists():
        print(
            f"Missing {REPORT}. Run pytest with --cov-report=json first.",
            file=sys.stderr,
        )
        return 1

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    summaries = {
        Path(filename).resolve(): entry["summary"]
        for filename, entry in report.get("files", {}).items()
    }

    modules = sorted(PACKAGE.glob("*.py"))
    if not modules:
        print(f"No modules found in {PACKAGE}.", file=sys.stderr)
        return 1

    failures: list[tuple[Path, float]] = []
    for module in modules:
        summary = summaries.get(module.resolve())
        percent = float(summary["percent_covered"]) if summary else 0.0
        print(f"{percent:6.2f}%  {module.relative_to(ROOT)}")
        if percent < MIN_COVERAGE:
            failures.append((module, percent))

    if failures:
        print(
            f"\n{len(failures)} module(s) below the {MIN_COVERAGE:.0f}% "
            "coverage threshold:",
            file=sys.stderr,
        )
        for module, percent in failures:
            print(
                f"  {module.relative_to(ROOT)}: {percent:.2f}%",
                file=sys.stderr,
            )
        return 1

    print(f"\nAll modules meet the {MIN_COVERAGE:.0f}% coverage threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
