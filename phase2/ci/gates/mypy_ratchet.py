#!/usr/bin/env python3
"""Fail if HEAD has any mypy error not already present on whatever's
currently deployed to Pre-Prod — a plain count comparison would let one
error get fixed while a different one is introduced, since the total stays
flat. Same baseline rule as Semgrep — the deployed commit, not a PR
merge-base. --baseline-root is that commit already checked out as its own
worktree (resolve-baseline builds it), so both runs cover the same tree.

Signatures are counted, not just listed: a second identical error in the
same file is a new error even though its text already exists. A mypy crash
(exit 2+, e.g. a bad config or a missing install) is a failure, never "zero
errors".

--absolute is for a first deploy with no baseline at all: any mypy error
fails, because there is nothing to ratchet against.

Usage:
    mypy_ratchet.py --baseline-sha=SHA --baseline-root=/baseline [--root=.]
    mypy_ratchet.py --absolute [--root=.]

Exit codes: 0 no new error signatures vs the baseline (or none at all with
--absolute), 1 there are new ones, mypy crashed, or the baseline worktree at
--baseline-root doesn't exist.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ERROR_LINE = re.compile(r"^(?P<file>[^:]+):\d+(?::\d+)?: error: (?P<rest>.*)$")


def parse_error_signatures(stdout: str) -> Counter[str]:
    """Each error's (file, message) signature from raw mypy stdout, line
    number dropped so an unrelated line shift elsewhere in the file doesn't
    look like a new error. Repeats are kept: two identical errors count twice.

    Args:
        stdout: mypy's stdout text.
    Returns:
        How many times mypy reported each "file: message" signature.
    Raises:
        None.
    """
    signatures: Counter[str] = Counter()
    for line in stdout.splitlines():
        match = ERROR_LINE.match(line)
        if match:
            signatures[f"{match['file']}: {match['rest']}"] += 1
    return signatures


def error_signatures(cwd: Path) -> Counter[str]:
    """Run mypy over cwd and return its error signatures.

    Args:
        cwd: directory to run mypy in.
    Returns:
        How many times mypy reported each "file: message" signature.
    Raises:
        RuntimeError: mypy itself crashed (exit code 2 or more), so its
            output can't be trusted as "no errors".
    """
    completed = subprocess.run(
        ["mypy", "."], cwd=cwd, capture_output=True, text=True, check=False
    )
    if completed.returncode >= 2:
        raise RuntimeError(
            f"mypy crashed in {cwd} (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:500]}"
        )
    return parse_error_signatures(completed.stdout)


def _parse_args() -> argparse.Namespace:
    """Parse the mypy ratchet CLI arguments.

    Args:
        None.
    Returns:
        The parsed namespace (baseline_sha/baseline_root/root/absolute).
    Raises:
        SystemExit: neither --absolute nor both baseline arguments given.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-sha")
    parser.add_argument("--baseline-root")
    parser.add_argument("--root", default=".")
    parser.add_argument("--absolute", action="store_true")
    args = parser.parse_args()
    if not args.absolute and not (args.baseline_sha and args.baseline_root):
        parser.error("--baseline-sha and --baseline-root, or --absolute")
    return args


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


def _compare_signatures(
    root: Path, baseline_root: Path, baseline_sha: str
) -> int:
    """Compare head and baseline error signatures; fail on any new one.

    Args:
        root: the head checkout to type-check.
        baseline_root: the deployed commit's checkout.
        baseline_sha: the baseline commit, printed in the messages.
    Returns:
        0 when head introduced no new error signature, 1 when it did.
    Raises:
        None.
    """
    head_errors = error_signatures(root)
    print(f"head mypy errors: {sum(head_errors.values())}")
    base_errors = error_signatures(baseline_root)
    print(f"baseline ({baseline_sha}) mypy errors: {sum(base_errors.values())}")
    return _report_new(head_errors - base_errors, f"baseline {baseline_sha}")


def _report_new(new_errors: Counter[str], against: str) -> int:
    """Print every new error signature and pick the exit code.

    Args:
        new_errors: signatures (with counts) that head has and the
            reference does not.
        against: what head was compared with, named in the message.
    Returns:
        0 when there are none, 1 otherwise.
    Raises:
        None.
    """
    if not new_errors:
        return 0
    print(
        f"::error::{sum(new_errors.values())} new mypy error(s) vs {against}:",
        file=sys.stderr,
    )
    for signature, count in sorted(new_errors.items()):
        print(f"::error::{signature} (x{count})", file=sys.stderr)
    return 1


def main() -> int:
    """Entry point: fail if HEAD introduced any mypy error the baseline
    didn't already have.

    Args:
        None.
    Returns:
        0 when no new error signature appeared, 1 when the baseline checkout
        is missing, mypy crashed, or a new signature appeared.
    Raises:
        None.
    """
    args = _parse_args()
    root = Path(args.root).resolve()
    try:
        if args.absolute:
            head_errors = error_signatures(root)
            print(f"absolute mode, head mypy errors: {sum(head_errors.values())}")
            return _report_new(head_errors, "an empty baseline (first deploy)")
        baseline_root = Path(args.baseline_root).resolve()
        # never guess a baseline of 0
        if _missing_baseline(args.baseline_sha, baseline_root):
            return 1
        return _compare_signatures(root, baseline_root, args.baseline_sha)
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
