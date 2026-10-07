#!/usr/bin/env python3
"""Weekly Eval-Suite run against RespondService. Never blocks a merge.
Cases live in Eval-Suite (fake eval users) — escalates only if a case failed
this week and last week. Real spend limits live at the provider, not here."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RESULT = Path("eval-result.json")
HISTORY = Path("eval-history.json")
RUNNER = Path("Eval-Suite/run.py")
REPORTS = Path("Eval-Suite/reports")
REQUIRED_ENV = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
)
WEAK_STATUSES = frozenset({"fail", "xpass"})


def write_result(**payload) -> None:
    """Write eval-result.json, filling in defaults for any field the caller left
    out.

    Args:
        payload: fields to write (kind/skipped/fail_open/escalate/flag_review/
            full_pass/reason/etc); unset fields get their default.
    Returns:
        None.
    Raises:
        None.
    """
    payload.setdefault("kind", "eval")
    payload.setdefault("skipped", False)
    payload.setdefault("fail_open", False)
    payload.setdefault("escalate", [])
    payload.setdefault("flag_review", False)
    payload.setdefault("full_pass", False)
    RESULT.write_text(json.dumps(payload, indent=2) + "\n")


def missing_keys() -> list[str]:
    """Required env var names that are unset or blank.

    Args:
        None.
    Returns:
        Required env var names that are unset or blank.
    Raises:
        None.
    """
    return [
        name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()
    ]


def persist_and_escalate(this_week: dict[str, str], history: dict) -> list[str]:
    """Escalate ids that were weak this week AND last week.

    Args:
        this_week: {case_id: status} from today's run.
        history: mutable history dict; updated in place with this_week under
            "last_week".
    Returns:
        Case ids weak both this week and last week.
    Raises:
        None.
    """
    last = history.get("last_week") or {}
    escalate = [
        cid
        for cid, status in this_week.items()
        if status in WEAK_STATUSES and last.get(cid) in WEAK_STATUSES
    ]
    history["last_week"] = this_week
    return escalate


def latest_report(root: Path = REPORTS) -> dict | None:
    """The newest Eval-Suite report JSON under root, or None if there isn't one.

    Args:
        root: directory of Eval-Suite report JSON files.
    Returns:
        The newest report parsed as a dict, or None if root is not a directory
        or contains no JSON files.
    Raises:
        None.
    """
    if not root.is_dir():
        return None
    files = sorted(root.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def statuses_from_report(data: dict) -> dict[str, str]:
    """Map each case id to its status, from a report's results list.

    Args:
        data: a parsed Eval-Suite report (with a "results" list).
    Returns:
        {case_id: status} for every row that has both.
    Raises:
        None.
    """
    out: dict[str, str] = {}
    for row in data.get("results") or []:
        cid = row.get("case_id") or row.get("id")
        status = row.get("status")
        if cid and status:
            out[str(cid)] = str(status)
    return out


def run_suite() -> int:
    """Run Eval-Suite/run.py as a subprocess; returns its exit code, never
    raises.

    Args:
        None.
    Returns:
        The subprocess exit code.
    Raises:
        None.
    """
    return subprocess.run([sys.executable, str(RUNNER)], check=False).returncode


def handle_missing_prereqs() -> bool:
    """Write a skip result and return True if env or the runner isn't ready.

    Args:
        None.
    Returns:
        True when a skip result was written because env vars or the runner are
        missing, otherwise False.
    Raises:
        None.
    """
    missing = missing_keys()
    if missing:
        write_result(
            skipped=True, fail_open=True, reason=f"missing {', '.join(missing)}"
        )
        return True
    if not RUNNER.is_file():
        write_result(
            skipped=True,
            reason="Eval-Suite/run.py missing — this job belongs on "
            "Sujho/platform",
        )
        return True
    return False


def load_this_week_report() -> dict | None:
    """Run the suite and return its report, or None having already written a
    skip result.

    Args:
        None.
    Returns:
        This week's report dict, or None if the suite wrote nothing usable.
    Raises:
        None.
    """
    run_suite()
    try:
        data = latest_report()
    except (OSError, json.JSONDecodeError) as err:
        write_result(
            skipped=True, fail_open=True, reason=str(err), flag_review=True
        )
        return None
    if not data:
        write_result(
            skipped=True, reason="Eval-Suite wrote no report", flag_review=True
        )
        return None
    return data


def load_history() -> dict:
    """Last week's per-case statuses, or {} if there's no history yet or it's
    unreadable.

    Args:
        None.
    Returns:
        The history dict, or an empty dict if the history file is missing or
        unreadable.
    Raises:
        None.
    """
    if not HISTORY.is_file():
        return {}
    try:
        return json.loads(HISTORY.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _record_week(data: dict) -> None:
    """Persist this week's statuses and write the completed eval result.

    Args:
        data: the eval report loaded for this week.
    Returns:
        None.
    Raises:
        None.
    """
    this_week = statuses_from_report(data)
    history = load_history()
    escalate = persist_and_escalate(this_week, history)
    HISTORY.write_text(json.dumps(history, indent=2) + "\n")
    failed = [
        cid for cid, status in this_week.items() if status in WEAK_STATUSES
    ]
    flag_review = bool(failed or escalate)
    write_result(
        skipped=False,
        counts=data.get("counts") or {},
        failed=failed,
        escalate=escalate,
        flag_review=flag_review,
        full_pass=not flag_review,
        reason="eval complete",
        run_id=data.get("run_id"),
    )


def main() -> int:
    """Run the weekly eval suite and write eval-result.json; never fails the
    job.

    Args:
        None.
    Returns:
        Always 0, including when the run was skipped.
    Raises:
        None.
    """
    if handle_missing_prereqs():
        return 0
    data = load_this_week_report()
    if data is None:
        return 0

    _record_week(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
