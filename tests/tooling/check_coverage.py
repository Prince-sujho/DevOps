#!/usr/bin/env python3
"""Fail if whole-product coverage drops below the last measured floors.

Floors live in tests/outcomes/pytest/coverage_floors.json. They are the
integer percents actually measured (not targets). knowledge_store at 0 is
an honest floor until that suite exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = TESTS_ROOT.parent
FLOORS = TESTS_ROOT / "outcomes" / "pytest" / "coverage_floors.json"
COVERAGE_JSON = WORKSPACE_ROOT / "coverage.json"

# Longest prefix first so infra/ is not used for a nested path that isn't infra.
PACKAGE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("user_service/", "user_service"),
    ("whatsapp_adapter/", "whatsapp_adapter"),
    ("text_agent/", "text_agent"),
    ("document_worker/", "document_worker"),
    ("redirect_service/", "redirect_service"),
    ("knowledge_store/", "knowledge_store"),
    ("infra/", "infra"),
)


def _package_for(path: str) -> str | None:
    for prefix, name in PACKAGE_PREFIXES:
        if path.startswith(prefix):
            return name
    return None


def _percent(covered: int, total: int) -> float:
    if total == 0:
        return 100.0
    return 100.0 * covered / total


def package_percents(files: dict) -> tuple[float, dict[str, float]]:
    """Return (total percent, per-package percent) using coverage.py's
    branch-aware percent_covered (statements + branches).
    """
    buckets: dict[str, list[int]] = {
        name: [0, 0] for _, name in PACKAGE_PREFIXES
    }
    covered_all = 0
    total_all = 0
    for path, data in files.items():
        summary = data.get("summary") or {}
        covered = int(summary.get("covered_lines", 0)) + int(
            summary.get("covered_branches", 0)
        )
        total = int(summary.get("num_statements", 0)) + int(
            summary.get("num_branches", 0)
        )
        covered_all += covered
        total_all += total
        name = _package_for(path)
        if name is None:
            continue
        buckets[name][0] += covered
        buckets[name][1] += total
    percents = {name: _percent(c, t) for name, (c, t) in buckets.items()}
    return _percent(covered_all, total_all), percents


def main() -> int:
    if not FLOORS.is_file():
        print(f"FAIL: floors missing: {FLOORS}")
        return 1
    if not COVERAGE_JSON.is_file():
        print(f"FAIL: {COVERAGE_JSON.name} missing; run the coverage stage first")
        return 1

    floors = json.loads(FLOORS.read_text())
    report = json.loads(COVERAGE_JSON.read_text())
    files = report.get("files")
    if not isinstance(files, dict):
        print("FAIL: coverage.json has no files object")
        return 1

    total_pct, package_pct = package_percents(files)
    failures: list[str] = []

    total_floor = int(floors["total"])
    print(f"total={total_pct:.1f} floor={total_floor}")
    if total_pct < total_floor:
        failures.append(f"total {total_pct:.1f}% < {total_floor}%")

    package_floors = floors["packages"]
    for name in [n for _, n in PACKAGE_PREFIXES]:
        pct = package_pct[name]
        floor = int(package_floors[name])
        print(f"{name}={pct:.1f} floor={floor}")
        if pct < floor:
            failures.append(f"{name} {pct:.1f}% < {floor}%")

    if failures:
        print("check_coverage: FAIL")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("check_coverage: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
