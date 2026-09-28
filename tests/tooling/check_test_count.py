#!/usr/bin/env python3
"""Fail if the runnable suites collect fewer tests than last recorded.

Baseline: tests/outcomes/pytest/collected.json (nodeids grouped by suite).
A drop means tests vanished — the thing that already happened once when
five stale names switched off 71 tests with no alarm.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = TESTS_ROOT.parent
BASELINE = TESTS_ROOT / "outcomes" / "pytest" / "collected.json"
# unit/api need no emulator; integration and e2e each start their own Firestore
# emulator and must not be collected in the same pytest process (see build-deploy.yaml).
SUITE_DIRS = ("unit", "api", "integration", "e2e")


def collect_nodeids() -> list[str]:
    """Return collected nodeids, one suite per pytest process.

    Each suite directory is its own pytest rootdir here, so nodeids come back
    relative to it (e.g. "infra/test_leases.py::..."), not prefixed "tests/".
    Prefix with the suite name so ids stay unique and readable across suites.
    """
    nodeids: list[str] = []
    for name in SUITE_DIRS:
        args = [str(TESTS_ROOT / name)]
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
        )
        if completed.returncode not in (0, 1):
            sys.stderr.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            raise SystemExit(f"FAIL: pytest --collect-only ({name}) exited {completed.returncode}")
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            path = stripped.split("::", 1)[0]
            if "::" in stripped and path.endswith(".py"):
                nodeids.append(f"{name}/{stripped}")
    return nodeids


def baseline_count(payload: object) -> int:
    if not isinstance(payload, dict):
        raise SystemExit("FAIL: collected.json must be an object of suite -> nodeids")
    total = 0
    for value in payload.values():
        if not isinstance(value, list):
            raise SystemExit("FAIL: collected.json values must be lists of nodeids")
        total += len(value)
    return total


def main() -> int:
    if not BASELINE.is_file():
        print(f"FAIL: baseline missing: {BASELINE}")
        return 1
    payload = json.loads(BASELINE.read_text())
    was = baseline_count(payload)
    now = len(collect_nodeids())
    print(f"collected={now} baseline={was}")
    if now < was:
        print(f"FAIL: lost {was - now} tests")
        return 1
    print("check_test_count: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
