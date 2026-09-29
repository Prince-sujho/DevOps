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
_MISSING_REPORT = (
    "mutmut-cicd-stats.json missing — pipeline.py mutation did "
    "not write a report"
)


def write_result(**payload) -> None:
    """Write mutation-result.json, filling in defaults for any field the caller
    left out.

    Args:
        payload: fields to write (kind/skipped/flag_review/baseline/reason/
            score/killed/total/survivors/etc); unset fields get their default.
    Returns:
        None.
    Raises:
        None.
    """
    payload.setdefault("kind", "mutation")
    payload.setdefault("skipped", False)
    payload.setdefault("flag_review", False)
    payload.setdefault("baseline", BASELINE)
    RESULT.write_text(json.dumps(payload, indent=2) + "\n")


def parse_mutmut_report(data: dict) -> tuple[int, int]:
    """Return (killed, decided). decided = killed + survived when present.

    Args:
        data: a parsed mutmut-cicd-stats.json document.
    Returns:
        (killed, decided) mutant counts.
    Raises:
        ValueError: data has no decided/total mutants at all.
    """
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
    """killed / total; raises if there are no decided mutants.

    Args:
        killed: how many mutants were killed.
        total: how many mutants were decided.
    Returns:
        killed divided by total.
    Raises:
        ValueError: total is not positive.
    """
    if total <= 0:
        raise ValueError("no mutants")
    return killed / total


def should_flag(current: float, baseline: float = BASELINE) -> bool:
    """True if current is below baseline.

    Args:
        current: the score being judged.
        baseline: the score current must not fall below.
    Returns:
        True when current is strictly below baseline.
    Raises:
        None.
    """
    return current < baseline


def _skip_unscored(reason: str, baseline: float) -> None:
    """Record a skipped mutation result and flag it for review.

    Args:
        reason: why the score could not be loaded.
        baseline: the baseline written into the skip result.
    Returns:
        None.
    Raises:
        None.
    """
    write_result(
        skipped=True, reason=reason, flag_review=True, baseline=baseline
    )


def _parsed_score(report: Path) -> tuple[float, int, int]:
    """Read a mutmut report and return its score and counts.

    Args:
        report: path to mutmut-cicd-stats.json.
    Returns:
        (current, killed, total).
    Raises:
        OSError, ValueError, json.JSONDecodeError, KeyError, TypeError: the
            report cannot be read or scored.
    """
    killed, total = parse_mutmut_report(json.loads(report.read_text()))
    return score(killed, total), killed, total


def load_score(
    report_path: Path, baseline: float
) -> tuple[float, int, int] | None:
    """The mutation score from a report file, or None having already written a
    skip result.

    Args:
        report_path: path to the mutmut-cicd-stats.json report.
        baseline: the baseline score, written into any skip result.
    Returns:
        (current, killed, total), or None if the report is missing/unparseable.
    Raises:
        None — failures write a skip result and return None instead.
    """
    report = Path(report_path)
    if not report.exists():
        _skip_unscored(_MISSING_REPORT, baseline)
        return None
    try:
        return _parsed_score(report)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as err:
        _skip_unscored(f"could not parse mutmut report: {err}", baseline)
        return None


def _write_scored(
    current: float, killed: int, total: int, baseline: float
) -> None:
    """Write the scored mutation result, flagging a drop below baseline.

    Args:
        current: the score being judged.
        killed: how many mutants were killed.
        total: how many mutants were decided.
        baseline: the score current must not fall below.
    Returns:
        None.
    Raises:
        None.
    """
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


def main(argv: list[str] | None = None) -> int:
    """Read the mutmut report, score it against baseline, and write
    mutation-result.json.

    Args:
        argv: CLI arguments (--skip/--report), or None for sys.argv.
    Returns:
        0 always — this job reports only, it never fails the build.
    Raises:
        None.
    """
    p = argparse.ArgumentParser()
    p.add_argument("--skip", action="store_true")
    p.add_argument("--report", default=str(DEFAULT_REPORT))
    args = p.parse_args(argv)

    baseline = float(os.environ.get("BASELINE", BASELINE))

    if args.skip:
        write_result(skipped=True, reason="explicit skip", baseline=baseline)
        return 0

    loaded = load_score(Path(args.report), baseline)
    if loaded is None:
        return 0
    current, killed, total = loaded
    _write_scored(current, killed, total, baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
