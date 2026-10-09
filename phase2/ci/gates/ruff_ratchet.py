#!/usr/bin/env python3
"""Fail if HEAD has any ruff finding not already present on whatever's
currently deployed to Pre-Prod — a plain count comparison would let one
finding get fixed while a different one is introduced, since the total stays
flat. Same baseline rule as mypy_ratchet.py: the deployed commit, not a PR
merge-base. --baseline-root is that commit already checked out as its own
worktree (resolve-baseline builds it), so both runs cover the same tree.

Signatures are counted, not just listed: a second identical finding in the
same file is a new finding even though its text already exists. Line numbers
are dropped from the signature so an unrelated line shift elsewhere in the
file doesn't look like a new finding. A ruff crash (exit 2+, e.g. a bad
config) is a failure, never "zero findings".

--absolute is for a first deploy with no baseline at all: any finding fails,
because there is nothing to ratchet against.

Usage:
    ruff_ratchet.py --baseline-sha=SHA --baseline-root=/baseline [--root=.]
    ruff_ratchet.py --absolute [--root=.]

Exit codes: 0 no new finding signatures vs the baseline (or none at all with
--absolute), 1 there are new ones, ruff crashed, or the baseline worktree at
--baseline-root doesn't exist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def parse_finding_signatures(stdout: str, cwd: Path) -> Counter[str]:
    """Each finding's (file, rule, message) signature from ruff's JSON
    output, line number dropped so an unrelated line shift elsewhere in the
    file doesn't look like a new finding.

    ruff's JSON "filename" is always an absolute path, resolved against cwd,
    regardless of the relative target given on the command line — unlike
    mypy's text output, which stays relative to its own cwd. Made relative
    to cwd here so the same file in head and in the baseline worktree
    produces the same signature; otherwise every finding would look new
    purely because the two checkouts live in different directories.

    Args:
        stdout: ruff's stdout text, from --output-format=json.
        cwd: the directory ruff was run in, to relativize "filename" against.
    Returns:
        How many times ruff reported each "file: code message" signature.
    Raises:
        RuntimeError: stdout isn't the JSON array ruff's own format promises.
    """
    try:
        findings = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ruff did not return valid JSON: {exc}") from exc
    signatures: Counter[str] = Counter()
    for finding in findings:
        filename = Path(finding["filename"]).relative_to(cwd)
        code = finding.get("code") or "?"
        message = finding["message"]
        signatures[f"{filename}: {code} {message}"] += 1
    return signatures


def finding_signatures(cwd: Path) -> Counter[str]:
    """Run ruff over cwd and return its finding signatures.

    Args:
        cwd: directory to run ruff in.
    Returns:
        How many times ruff reported each "file: code message" signature.
    Raises:
        RuntimeError: ruff itself crashed (exit code 2 or more), so its
            output can't be trusted as "no findings".
    """
    completed = subprocess.run(
        ["ruff", "check", ".", "--output-format=json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode >= 2:
        raise RuntimeError(
            f"ruff crashed in {cwd} (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:500]}"
        )
    return parse_finding_signatures(completed.stdout, cwd)


def _parse_args() -> argparse.Namespace:
    """Parse the ruff ratchet CLI arguments.

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
    """Compare head and baseline finding signatures; fail on any new one.

    Args:
        root: the head checkout to lint.
        baseline_root: the deployed commit's checkout.
        baseline_sha: the baseline commit, printed in the messages.
    Returns:
        0 when head introduced no new finding signature, 1 when it did.
    Raises:
        None.
    """
    head_findings = finding_signatures(root)
    print(f"head ruff findings: {sum(head_findings.values())}")
    base_findings = finding_signatures(baseline_root)
    print(f"baseline ({baseline_sha}) ruff findings: {sum(base_findings.values())}")
    return _report_new(head_findings - base_findings, f"baseline {baseline_sha}")


def _report_new(new_findings: Counter[str], against: str) -> int:
    """Print every new finding signature and pick the exit code.

    Args:
        new_findings: signatures (with counts) that head has and the
            reference does not.
        against: what head was compared with, named in the message.
    Returns:
        0 when there are none, 1 otherwise.
    Raises:
        None.
    """
    if not new_findings:
        return 0
    print(
        f"::error::{sum(new_findings.values())} new ruff finding(s) vs {against}:",
        file=sys.stderr,
    )
    for signature, count in sorted(new_findings.items()):
        print(f"::error::{signature} (x{count})", file=sys.stderr)
    return 1


def main() -> int:
    """Entry point: fail if HEAD introduced any ruff finding the baseline
    didn't already have.

    Args:
        None.
    Returns:
        0 when no new finding signature appeared, 1 when the baseline
        checkout is missing, ruff crashed, or a new signature appeared.
    Raises:
        None.
    """
    args = _parse_args()
    root = Path(args.root).resolve()
    try:
        if args.absolute:
            head_findings = finding_signatures(root)
            print(
                f"absolute mode, head ruff findings: {sum(head_findings.values())}"
            )
            return _report_new(head_findings, "an empty baseline (first deploy)")
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
