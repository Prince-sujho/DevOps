"""Write one JSON report and one Markdown scoreboard per run."""

from __future__ import annotations

from pathlib import Path

from .types import EvalRunResult


def _scoreboard_lines(run: EvalRunResult) -> list[str]:
    """The Markdown scoreboard rows for one eval run.

    Args:
        run: the full run result to render.
    Returns:
        Markdown lines, without a trailing newline.
    Raises:
        None.
    """
    lines = [
        f"# Eval-Suite {run.run_id}",
        "",
        f"duration_ms: {run.duration_ms}",
        f"pass: {run.counts['pass']}  fail: {run.counts['fail']}  "
        f"xfail: {run.counts['xfail']}  xpass: {run.counts['xpass']}",
        "",
        "| case | status | hard | soft | ms |",
        "|---|---|---|---|---|",
    ]
    for result in run.results:
        hard = "<br>".join(result.failures) if result.failures else ""
        soft = "<br>".join(result.soft) if result.soft else ""
        lines.append(
            f"| `{result.case_id}` | {result.status} | {hard} | {soft} | "
            f"{result.latency_ms} |"
        )
    return lines


def write_reports(root: Path, run: EvalRunResult) -> None:
    """Write run's JSON report and a Markdown scoreboard table under root.

    Args:
        root: directory to write into, created if it doesn't exist.
        run: the full run result to report.
    Returns:
        None.
    Raises:
        None.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{run.run_id}.json").write_text(
        run.model_dump_json(indent=2), encoding="utf-8"
    )
    text = "\n".join(_scoreboard_lines(run)) + "\n"
    (root / f"{run.run_id}.md").write_text(text, encoding="utf-8")
