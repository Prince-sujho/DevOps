#!/usr/bin/env python3
"""Weekly mutation score reporter for the sujho umbrella.

Not a merge gate. A missing mutmut dump or a score drop all exit 0. A drop
below baseline is flagged for a human on the tracking issue — it does not
fail the workflow. The live runner is tests/ci/pipeline.py mutation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

BASELINE = 0.98
RESULT = Path("mutation-result.json")
DEFAULT_REPORT = Path("mutants/mutmut-cicd-stats.json")


def write_result(**payload) -> None:
    payload.setdefault("kind", "mutation")
    payload.setdefault("skipped", False)
    payload.setdefault("flag_review", False)
    payload.setdefault("baseline", BASELINE)
    RESULT.write_text(json.dumps(payload, indent=2) + "\n")


def parse_mutmut_report(data: dict) -> tuple[int, int]:
    """Return (killed, decided). decided = killed + survived when present."""
    killed = int(data.get("killed", data.get("killed_mutants", 0)))
    if "survived" in data or "survivor_count" in data:
        survived = int(data.get("survived", data.get("survivor_count", 0)))
        decided = killed + survived
        if decided <= 0:
            raise ValueError("mutmut report has no decided mutants")
        return killed, decided
    if "total" in data:
        total = int(data["total"])
        if total <= 0:
            raise ValueError("mutmut report has no mutants")
        return killed, total
    raise ValueError("mutmut report has no mutants")


def score(killed: int, total: int) -> float:
    if total <= 0:
        raise ValueError("no mutants")
    return killed / total


def should_flag(current: float, baseline: float = BASELINE) -> bool:
    return current < baseline


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--skip", action="store_true")
    p.add_argument("--report", default=str(DEFAULT_REPORT))
    args = p.parse_args(argv)

    baseline = float(os.environ.get("BASELINE", BASELINE))

    if args.skip:
        write_result(skipped=True, reason="explicit skip", baseline=baseline)
        return 0

    report = Path(args.report)
    if not report.exists():
        write_result(
            skipped=True,
            reason="mutmut-cicd-stats.json missing — pipeline.py mutation did not write a report",
            flag_review=True,
            baseline=baseline,
        )
        return 0

    try:
        killed, total = parse_mutmut_report(json.loads(report.read_text()))
        current = score(killed, total)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as err:
        write_result(
            skipped=True,
            reason=f"could not parse mutmut report: {err}",
            flag_review=True,
            baseline=baseline,
        )
        return 0

    flag = should_flag(current, baseline)
    write_result(
        skipped=False,
        score=round(current, 4),
        killed=killed,
        total=total,
        survivors=total - killed,
        flag_review=flag,
        baseline=baseline,
        reason="score dropped below baseline" if flag else "within band",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
