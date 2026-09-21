#!/usr/bin/env python3
"""Coverage ratchet: fail only when head coverage is lower than base.

Missing base coverage (new suite, or base tests failed) is treated as 0 so a
broken base cannot block a PR. Missing head coverage after tests ran is a fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EPS = 0.01


def percent_covered(path: Path) -> float | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    totals = data.get("totals") or {}
    if "percent_covered" not in totals:
        raise ValueError(f"{path} has no totals.percent_covered")
    return float(totals["percent_covered"])


def ratchet(head: Path, base: Path, summary: Path | None = None) -> int:
    summary_path = summary if summary is not None else Path("coverage-summary.txt")
    try:
        head_pct = percent_covered(head)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if head_pct is None:
        print(f"::error::No head coverage at {head} — tests ran but produced no report.", file=sys.stderr)
        return 1
    try:
        base_pct = percent_covered(base)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"::warning::Unreadable base coverage ({exc}); treating base as 0.0")
        base_pct = 0.0
    if base_pct is None:
        print("No base coverage file — treating base as 0.0 (new suite or base tests did not report).")
        base_pct = 0.0
    print(f"base={base_pct:.2f}%  head={head_pct:.2f}%")
    summary_path.write_text(f"{head_pct:.2f}|{base_pct:.2f}")
    if head_pct + EPS < base_pct:
        print(
            f"::error::Coverage dropped from {base_pct:.2f}% to {head_pct:.2f}% — the ratchet only allows moving up.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("head")
    parser.add_argument("base")
    args = parser.parse_args()
    return ratchet(Path(args.head), Path(args.base))


if __name__ == "__main__":
    sys.exit(main())
