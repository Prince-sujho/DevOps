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
# emulator and must not be collected in the same pytest process (see
# build-deploy.yaml).
SUITE_DIRS = ("unit", "api", "integration", "e2e")


def _collected_nodeids(stdout: str, suite: str) -> list[str]:
    """Node ids from one pytest --collect-only -q stdout.

    Args:
        stdout: the collector's stdout.
        suite: suite directory name prefixed onto each node id.
    Returns:
        Node ids shaped "{suite}/{path}::{test}".
    Raises:
        None.
    """
    nodeids = []
    for line in stdout.splitlines():
        stripped = line.strip()
        path = stripped.split("::", 1)[0]
        if "::" in stripped and path.endswith(".py"):
            nodeids.append(f"{suite}/{stripped}")
    return nodeids


def _collect_process(name: str) -> subprocess.CompletedProcess[str]:
    """Run pytest --collect-only -q for one suite directory.

    Args:
        name: suite directory name under tests/.
    Returns:
        The completed pytest process, stdout and stderr captured.
    Raises:
        None.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            str(TESTS_ROOT / name),
        ],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
    )


def collect_suite(name: str) -> list[str]:
    """Return nodeids for one suite directory, prefixed with its name.

    Each suite directory is its own pytest rootdir, so nodeids come back
    relative to it (e.g. "infra/test_leases.py::..."), not prefixed "tests/".
    Raises SystemExit if pytest fails to collect this suite at all.

    Args:
        name: suite directory name under tests/.
    Returns:
        The collected pytest node ids.
    Raises:
        SystemExit: pytest --collect-only for the suite exited nonzero.
    """
    completed = _collect_process(name)
    if completed.returncode not in (0, 1):
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise SystemExit(
            f"FAIL: pytest --collect-only ({name}) exited "
            f"{completed.returncode}"
        )
    return _collected_nodeids(completed.stdout, name)


def collect_nodeids() -> list[str]:
    """Return collected nodeids across all suites, one pytest process each.

    unit/api need no emulator; integration and e2e each start their own
    Firestore emulator and must not be collected in the same pytest process.

    Args:
        None.
    Returns:
        The collected pytest node ids.
    Raises:
        None.
    """
    nodeids: list[str] = []
    for name in SUITE_DIRS:
        nodeids.extend(collect_suite(name))
    return nodeids


def baseline_count(payload: object) -> int:
    """Return the total nodeid count across all suites in a collected.json
    payload.

    Raises SystemExit if the payload isn't the expected {suite: [nodeids]}
    shape.

    Args:
        payload: parsed collected.json object.
    Returns:
        The total number of nodeids across every suite.
    Raises:
        SystemExit: payload is not a mapping of suite name to a list of nodeids.
    """
    if not isinstance(payload, dict):
        raise SystemExit(
            "FAIL: collected.json must be an object of suite -> nodeids"
        )
    total = 0
    for value in payload.values():
        if not isinstance(value, list):
            raise SystemExit(
                "FAIL: collected.json values must be lists of nodeids"
            )
        total += len(value)
    return total


def main() -> int:
    """Entry point: fail if the current collected count is below the baseline.

    Args:
        None.
    Returns:
        0 when the collected count is at least the baseline, 1 when the baseline
        file is missing or the count dropped.
    Raises:
        None.
    """
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
