#!/usr/bin/env python3
"""Build tests/outcomes/PYTEST_RESULTS.md from JUnit XML + pytest --collect-only."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
OUTCOMES = TESTS_ROOT / "outcomes"
PYTEST_DIR = OUTCOMES / "pytest"
SUITES = ("unit", "api", "integration", "e2e")


def workspace_root() -> Path:
    return TESTS_ROOT.parent


def collect_nodeids(suite: str) -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/{suite}", "--collect-only", "-q"],
        cwd=workspace_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    nodeids: list[str] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("=") or "collected" in line:
            continue
        if "::" in line:
            nodeids.append(canonical_nodeid(suite, line))
    return nodeids


def junit_keys(case: ET.Element, suite: str) -> list[str]:
    name = case.get("name") or ""
    file_attr = case.get("file")
    classname = case.get("classname") or ""
    keys: list[str] = []
    if file_attr:
        keys.append(f"{file_attr}::{name}")
    recon = classname.replace(".", "/")
    if recon and not recon.endswith(".py"):
        recon = f"{recon}.py"
    if recon:
        keys.append(f"{recon}::{name}")
        keys.append(f"{Path(recon).name}::{name}")
    expanded: list[str] = []
    for key in keys:
        expanded.append(key)
        if not key.startswith("tests/"):
            expanded.append(f"tests/{suite}/{key}")
            expanded.append(f"{suite}/{key}")
    return expanded


def parse_junit(path: Path, suite: str) -> dict[str, dict[str, str]]:
    """Multiple nodeid spellings -> {result, message}."""
    rows: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return rows
    root = ET.parse(path).getroot()
    if root.tag == "testsuites":
        xml_suites = list(root.findall("testsuite"))
    elif root.tag == "testsuite":
        xml_suites = [root]
    else:
        xml_suites = list(root.findall("testsuite"))
    for xml_suite in xml_suites:
        for case in xml_suite.findall("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if failure is not None:
                result, node = "failed", failure
            elif error is not None:
                result, node = "error", error
            elif skipped is not None:
                result, node = "skipped", skipped
            else:
                result, node = "passed", None
            message = ""
            if node is not None:
                message = (node.get("message") or "").strip().replace("\n", " ")
                if not message and node.text:
                    message = node.text.strip().splitlines()[0][:200]
            info = {"result": result, "message": message}
            for key in junit_keys(case, suite):
                rows[key] = info
    return rows


def canonical_nodeid(suite: str, nodeid: str) -> str:
    prefix = f"tests/{suite}/"
    if nodeid.startswith("tests/"):
        return nodeid
    return prefix + nodeid


def lookup(nodeid: str, results: dict[str, dict[str, str]]) -> dict[str, str] | None:
    candidates: list[str] = []

    def add(key: str) -> None:
        if key and key not in candidates:
            candidates.append(key)

    add(nodeid)
    stripped = nodeid.removeprefix("tests/")
    add(stripped)
    for name in SUITES:
        prefix = f"{name}/"
        if stripped.startswith(prefix):
            add(stripped[len(prefix) :])
    path, sep, test_name = nodeid.partition("::")
    if sep:
        add(f"{Path(path).name}::{test_name}")
    for key in candidates:
        if key in results:
            return results[key]
    return None


def render(collected: dict[str, list[str]], results: dict[str, dict[str, str]]) -> str:
    counts: dict[str, Counter[str]] = {name: Counter() for name in SUITES}
    rows: list[tuple[str, str, str, str]] = []
    for suite, nodeids in collected.items():
        for nodeid in nodeids:
            info = lookup(nodeid, results)
            if info is None:
                status, message = "not-run", "no junit row"
            else:
                status, message = info["result"], info["message"]
            counts[suite][status] += 1
            rows.append((suite, nodeid, status, message))

    today = date.today().isoformat()
    lines = [
        "# Pytest results",
        "",
        f"Recorded {today} with `pytest --junitxml` from the Sujho workspace root. "
        "Integration and e2e used `JAVA_HOME=/opt/homebrew/opt/openjdk`. "
        "Raw XML and JSON live in [`pytest/`](pytest/). "
        "`skipped` includes pytest xfail. Failures are catalogued in "
        "[FINDINGS.md](FINDINGS.md); this table is the full collected set.",
        "",
        "## Summary",
        "",
        "| suite | collected | passed | failed | error | skipped | not-run |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for suite in SUITES:
        c = counts[suite]
        total = len(collected.get(suite, []))
        lines.append(
            f"| `{suite}` | {total} | {c['passed']} | {c['failed']} | "
            f"{c['error']} | {c['skipped']} | {c['not-run']} |"
        )
    grand = Counter()
    for c in counts.values():
        grand.update(c)
    total_all = sum(len(v) for v in collected.values())
    lines.append(
        f"| **all** | **{total_all}** | **{grand['passed']}** | **{grand['failed']}** | "
        f"**{grand['error']}** | **{grand['skipped']}** | **{grand['not-run']}** |"
    )
    lines.extend(
        ["", "## Every test", "", "| suite | result | nodeid | message |", "|---|---|---|---|"]
    )
    for suite, nodeid, status, message in rows:
        safe = message.replace("|", "\\|")
        lines.append(f"| `{suite}` | {status} | `{nodeid}` | {safe} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true", help="Re-run pytest --collect-only")
    args = parser.parse_args()
    PYTEST_DIR.mkdir(parents=True, exist_ok=True)

    collected: dict[str, list[str]] = {}
    collect_path = PYTEST_DIR / "collected.json"
    if args.collect or not collect_path.is_file():
        for suite in SUITES:
            collected[suite] = collect_nodeids(suite)
        collect_path.write_text(json.dumps(collected, indent=2) + "\n")
    else:
        collected = json.loads(collect_path.read_text())

    results: dict[str, dict[str, str]] = {}
    for suite in SUITES:
        results.update(parse_junit(PYTEST_DIR / f"{suite}.xml", suite))

    markdown = render(collected, results)
    (OUTCOMES / "PYTEST_RESULTS.md").write_text(markdown)
    payload = {
        "suites": {
            suite: {
                nodeid: lookup(nodeid, results)
                or {"result": "not-run", "message": "no junit row"}
                for nodeid in nodeids
            }
            for suite, nodeids in collected.items()
        }
    }
    (PYTEST_DIR / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    not_run = sum(
        1
        for suite_rows in payload["suites"].values()
        for info in suite_rows.values()
        if info["result"] == "not-run"
    )
    print(f"wrote {OUTCOMES / 'PYTEST_RESULTS.md'} (not-run={not_run})")
    return 1 if not_run else 0


if __name__ == "__main__":
    sys.exit(main())
