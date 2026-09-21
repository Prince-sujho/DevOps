"""Write one JSON report and one Markdown scoreboard per run."""

from __future__ import annotations

from pathlib import Path

from .types import EvalRunResult


def write_reports(root: Path, run: EvalRunResult) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{run.run_id}.json").write_text(
        run.model_dump_json(indent=2), encoding="utf-8"
    )
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
            f"| `{result.case_id}` | {result.status} | {hard} | {soft} | {result.latency_ms} |"
        )
    (root / f"{run.run_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
