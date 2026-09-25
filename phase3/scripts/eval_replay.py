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
    payload.setdefault("kind", "eval")
    payload.setdefault("skipped", False)
    payload.setdefault("fail_open", False)
    payload.setdefault("escalate", [])
    payload.setdefault("flag_review", False)
    payload.setdefault("full_pass", False)
    RESULT.write_text(json.dumps(payload, indent=2) + "\n")


def missing_keys() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]


def persist_and_escalate(this_week: dict[str, str], history: dict) -> list[str]:
    """Escalate ids that were weak this week AND last week."""
    last = history.get("last_week") or {}
    escalate = [
        cid
        for cid, status in this_week.items()
        if status in WEAK_STATUSES and last.get(cid) in WEAK_STATUSES
    ]
    history["last_week"] = this_week
    return escalate


def latest_report(root: Path = REPORTS) -> dict | None:
    if not root.is_dir():
        return None
    files = sorted(root.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def statuses_from_report(data: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in data.get("results") or []:
        cid = row.get("case_id") or row.get("id")
        status = row.get("status")
        if cid and status:
            out[str(cid)] = str(status)
    return out


def run_suite() -> int:
    return subprocess.run(
        [sys.executable, str(RUNNER)],
        check=False,
    ).returncode


def main() -> int:
    missing = missing_keys()
    if missing:
        write_result(
            skipped=True,
            fail_open=True,
            reason=f"missing {', '.join(missing)}",
        )
        return 0
    if not RUNNER.is_file():
        write_result(
            skipped=True,
            reason="Eval-Suite/run.py missing — this job belongs on Sujho/sujho",
        )
        return 0

    run_suite()
    try:
        data = latest_report()
    except (OSError, json.JSONDecodeError) as err:
        write_result(skipped=True, fail_open=True, reason=str(err), flag_review=True)
        return 0
    if not data:
        write_result(
            skipped=True,
            reason="Eval-Suite wrote no report",
            flag_review=True,
        )
        return 0

    this_week = statuses_from_report(data)
    history: dict = {}
    if HISTORY.is_file():
        try:
            history = json.loads(HISTORY.read_text())
        except (OSError, json.JSONDecodeError):
            history = {}
    escalate = persist_and_escalate(this_week, history)
    HISTORY.write_text(json.dumps(history, indent=2) + "\n")
    counts = data.get("counts") or {}
    failed = [cid for cid, status in this_week.items() if status in WEAK_STATUSES]
    flag_review = bool(failed or escalate)
    write_result(
        skipped=False,
        counts=counts,
        failed=failed,
        escalate=escalate,
        flag_review=flag_review,
        full_pass=not flag_review,
        reason="eval complete",
        run_id=data.get("run_id"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
