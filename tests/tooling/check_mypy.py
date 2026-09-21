#!/usr/bin/env python3
"""Fail if `mypy --strict` finds more errors than the last recorded baseline.

Baseline: tests/outcomes/mypy/baseline.json (error count per package).
`stage_static` used to run mypy against `user_service/app/src` only, so a
pull request rewriting `whatsapp_adapter` (or anywhere else) passed no type
gate at all. Both packages carry pre-existing `--strict` errors today (14 in
user_service, 53 in whatsapp_adapter) that are product defects, not test
debt -- this gate does not require fixing them. It ratchets instead: the
baseline is the honest count measured today, and the gate fails only when a
package's count goes up, so new code cannot add type errors invisibly and
old debt can be paid down over time by lowering the baseline by hand.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = TESTS_ROOT.parent
BASELINE = TESTS_ROOT / "outcomes" / "mypy" / "baseline.json"

# Longest prefix first is unnecessary here (no nested pairs), but keep the
# packages explicit and ordered the way check_coverage.py orders its own.
PACKAGES: tuple[tuple[str, str], ...] = (
    ("user_service/app/src", "user_service"),
    ("whatsapp_adapter/app/src", "whatsapp_adapter"),
)


def error_count(package: str) -> int:
    """Run `mypy --strict` against one package and count its error lines."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--follow-imports=silent",
            package,
        ],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
    )
    lines = completed.stdout.splitlines()
    return sum(1 for line in lines if ": error:" in line)


def main() -> int:
    if not BASELINE.is_file():
        print(f"FAIL: baseline missing: {BASELINE}")
        return 1
    baselines = json.loads(BASELINE.read_text())

    failures: list[str] = []
    for path, name in PACKAGES:
        now = error_count(path)
        was = int(baselines[name])
        print(f"{name}={now} baseline={was}")
        if now > was:
            failures.append(f"{name} gained {now - was} mypy error(s) ({was} -> {now})")

    if failures:
        print("check_mypy: FAIL")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("check_mypy: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
