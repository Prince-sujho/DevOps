"""Turn mutmut 3 results into a single HTML report (mutmut 3 has no `mutmut html`)."""

from __future__ import annotations

import html
import json
from pathlib import Path


def _exit_label(code: int) -> str:
    if code == 0:
        return "survived"
    if code == 1:
        return "killed"
    if code == 33:
        return "no tests"
    if code in (-24, 24):
        return "timeout"
    return f"exit {code}"


def _module_of(key: str) -> str:
    # user_service.app.src.gifting.x__apply_order__mutmut_1
    parts = key.split(".")
    if len(parts) >= 4:
        return parts[3]
    return key


def render(mutants_dir: Path, out_path: Path) -> None:
    stats_path = mutants_dir / "mutmut-cicd-stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    killed = int(stats.get("killed") or 0)
    survived = int(stats.get("survived") or 0)
    decided = killed + survived
    score = (100.0 * killed / decided) if decided else 0.0

    rows: list[tuple[str, str, str, str]] = []
    for meta in sorted(mutants_dir.rglob("*.meta")):
        payload = json.loads(meta.read_text())
        by_key = payload.get("exit_code_by_key") or {}
        for key, code in by_key.items():
            rows.append((_module_of(key), key, str(code), _exit_label(int(code))))

    by_module: dict[str, dict[str, int]] = {}
    for module, _key, _code, label in rows:
        bucket = by_module.setdefault(
            module, {"killed": 0, "survived": 0, "no tests": 0, "timeout": 0, "other": 0}
        )
        if label in bucket:
            bucket[label] += 1
        else:
            bucket["other"] += 1

    module_rows = []
    for module, counts in sorted(by_module.items()):
        k, s = counts["killed"], counts["survived"]
        mod_score = (100.0 * k / (k + s)) if (k + s) else 0.0
        module_rows.append(
            "<tr>"
            f"<td>{html.escape(module)}</td>"
            f"<td>{k}</td><td>{s}</td>"
            f"<td>{counts['no tests']}</td><td>{counts['timeout']}</td>"
            f"<td>{mod_score:.1f}%</td>"
            "</tr>"
        )

    detail = []
    for module, key, code, label in sorted(rows, key=lambda r: (r[3] != "survived", r[0], r[1])):
        detail.append(
            "<tr>"
            f"<td>{html.escape(module)}</td>"
            f"<td><code>{html.escape(key)}</code></td>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(code)}</td>"
            "</tr>"
        )

    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>mutmut report</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
code {{ font-size: 0.85em; }}
</style></head><body>
<h1>mutmut report</h1>
<p>killed {killed} / survived {survived} / no tests {stats.get("no_tests")} /
timeout {stats.get("timeout")} / total {stats.get("total")}</p>
<p><strong>Score killed/(killed+survived) = {score:.1f}%</strong></p>
<h2>Per module</h2>
<table><thead><tr><th>module</th><th>killed</th><th>survived</th>
<th>no tests</th><th>timeout</th><th>score</th></tr></thead>
<tbody>{"".join(module_rows)}</tbody></table>
<h2>Every mutant</h2>
<table><thead><tr><th>module</th><th>key</th><th>result</th><th>exit</th></tr></thead>
<tbody>{"".join(detail)}</tbody></table>
</body></html>
"""
    out_path.write_text(body)


if __name__ == "__main__":
    tests_root = Path(__file__).resolve().parent.parent
    repo = tests_root.parent
    render(repo / "mutants", repo / "mutants" / "mutmut-report.html")
