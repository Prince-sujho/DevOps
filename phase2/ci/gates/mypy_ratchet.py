#!/usr/bin/env python3
"""Fail if mypy error count went up vs whatever's currently deployed to
Pre-Prod.

Same baseline rule as Semgrep — the deployed commit, not a PR merge-base.
--baseline-root is that commit already checked out as its own worktree
(resolve-baseline builds it), so both counts cover the same tree.

Usage:
    mypy_ratchet.py --baseline-sha=SHA --baseline-root=/baseline [--root=.]

Exit codes: 0 error count did not increase, 1 it went up or the baseline
worktree at --baseline-root doesn't exist.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ERROR_LINE = re.compile(r": error:")


def count_errors(cwd: Path) -> int:
    """Run mypy over cwd and count its `: error:` lines.

    Args:
        cwd: directory to run mypy in.
    Returns:
        How many output lines contain `: error:`.
    Raises:
        None.
    """
    completed = subprocess.run(
        ["mypy", "."], cwd=cwd, capture_output=True, text=True
    )
    return sum(
        1 for line in completed.stdout.splitlines() if ERROR_LINE.search(line)
    )


def _parse_args() -> argparse.Namespace:
    """Parse the mypy ratchet CLI arguments.

    Args:
        None.
    Returns:
        The parsed namespace (baseline_sha/baseline_root/root).
    Raises:
        SystemExit: a required argument is missing.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--root", default=".")
    return parser.parse_args()


def _missing_baseline(baseline_sha: str, baseline_root: Path) -> bool:
    """Whether the baseline worktree is not a git checkout.

    Args:
        baseline_sha: the baseline commit, named in the error.
        baseline_root: the directory that should hold that checkout.
    Returns:
        True after printing an error when the checkout is missing.
    Raises:
        None.
    """
    if (baseline_root / ".git").exists():
        return False
    print(
        f"::error::baseline {baseline_sha} not checked out at {baseline_root}",
        file=sys.stderr,
    )
    return True


def _compare_counts(root: Path, baseline_root: Path, baseline_sha: str) -> int:
    """Count mypy errors on head and baseline; fail if the head count rose.

    Args:
        root: the head checkout to type-check.
        baseline_root: the deployed commit's checkout.
        baseline_sha: the baseline commit, printed in the messages.
    Returns:
        0 when the head count did not rise, 1 when it did.
    Raises:
        None.
    """
    head_errors = count_errors(root)
    print(f"head mypy errors: {head_errors}")
    base_errors = count_errors(baseline_root)
    print(f"baseline ({baseline_sha}) mypy errors: {base_errors}")
    if head_errors > base_errors:
        print(
            f"::error::mypy errors went from {base_errors} to {head_errors}",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    """Entry point: compare HEAD's mypy error count against the baseline's.

    Args:
        None.
    Returns:
        0 when the head error count did not rise, 1 when the baseline checkout
        is missing or the count rose.
    Raises:
        None.
    """
    args = _parse_args()
    root = Path(args.root).resolve()
    baseline_root = Path(args.baseline_root).resolve()
    # never guess a baseline of 0
    if _missing_baseline(args.baseline_sha, baseline_root):
        return 1
    return _compare_counts(root, baseline_root, args.baseline_sha)


if __name__ == "__main__":
    raise SystemExit(main())
