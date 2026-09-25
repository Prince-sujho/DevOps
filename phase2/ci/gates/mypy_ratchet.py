#!/usr/bin/env python3
"""Fail if mypy error count went up vs whatever's currently deployed to Pre-Prod.
Same baseline rule as Semgrep — the deployed commit, not a PR merge-base."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
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
    p.add_argument("--root", default=".")
    args = p.parse_args()

    root = Path(args.root).resolve()
    head_errors = count_errors(root)
    print(f"head mypy errors: {head_errors}")

    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp) / "baseline"
        try:
            subprocess.run(
                ["git", "-C", str(root), "fetch", "--depth=1", "origin", args.baseline_sha],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.baseline_sha],
                check=True, capture_output=True, text=True,
            )
            base_errors = count_errors(worktree)
        except subprocess.CalledProcessError:
            print(f"::warning::could not check out baseline {args.baseline_sha}, treating as 0 errors")
            base_errors = 0
        finally:
            subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)],
                capture_output=True, text=True,
            )

    print(f"baseline ({args.baseline_sha}) mypy errors: {base_errors}")

    if head_errors > base_errors:
        print(f"::error::mypy errors went from {base_errors} to {head_errors}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
