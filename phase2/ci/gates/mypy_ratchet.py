#!/usr/bin/env python3
"""Fail if mypy error count went up vs whatever's currently deployed to Pre-Prod.
Same baseline rule as Semgrep — the deployed commit, not a PR merge-base.

--baseline-root is that commit already checked out with its own pinned
gitlinks (resolve-baseline builds it), so both counts cover the same trees."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ERROR_LINE = re.compile(r": error:")


def count_errors(cwd: Path) -> int:
    completed = subprocess.run(
        ["mypy", "."],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return sum(1 for line in completed.stdout.splitlines() if ERROR_LINE.search(line))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-sha", required=True)
    p.add_argument("--baseline-root", required=True)
    p.add_argument("--root", default=".")
    args = p.parse_args()

    root = Path(args.root).resolve()
    baseline_root = Path(args.baseline_root).resolve()
    # never guess a baseline of 0
    if not (baseline_root / ".git").exists():
        print(f"::error::baseline {args.baseline_sha} not checked out at {baseline_root}", file=sys.stderr)
        return 1

    head_errors = count_errors(root)
    print(f"head mypy errors: {head_errors}")
    base_errors = count_errors(baseline_root)
    print(f"baseline ({args.baseline_sha}) mypy errors: {base_errors}")

    if head_errors > base_errors:
        print(f"::error::mypy errors went from {base_errors} to {head_errors}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
