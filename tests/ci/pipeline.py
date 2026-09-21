#!/usr/bin/env python3
"""Run one stage, several, or the full Sujho test pipeline.

Must be invoked from (or able to find) a Sujho umbrella checkout: the suites
import live product packages. Set SUJHO_ROOT if this tree is not at <workspace>/tests.

Examples:
  python tests/ci/pipeline.py --list
  python tests/ci/pipeline.py                  # blocking stages (same as CI)
  python tests/ci/pipeline.py --all            # blocking + integration + e2e
  python tests/ci/pipeline.py unit api
  python tests/ci/pipeline.py mutation
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_CI_DIR = Path(__file__).resolve().parent
_WORKSPACE_CANDIDATE = _CI_DIR.parent.parent
if str(_WORKSPACE_CANDIDATE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_CANDIDATE))

from tests.ci.paths import (  # noqa: E402
    MUTATION_PACKAGES,
    MUTATION_REQUIREMENTS,
    ROOT_PACKAGES,
    SECRET_EXCLUDE,
    SERVICE_REQUIREMENTS,
    TEST_REQUIREMENTS,
    TESTS_ROOT,
    workspace_root,
)

DEFAULT_STAGES = (
    "static",
    "secrets",
    "unit",
    "api",
    "eval-checks",
    "gates",
    "coverage",
)
ALL_STAGES = DEFAULT_STAGES + ("integration", "e2e")

STAGE_FOLDERS = {
    "install": "(pip: service + test requirements)",
    "install-mutation": "(pip: mutmut + user_service unit deps)",
    "static": "(ruff + mypy; product tree)",
    "secrets": "(.secrets.baseline at workspace root)",
    "unit": "tests/unit/",
    "api": "tests/api/",
    "eval-checks": "evals/tests/ (grader + corpus gate; no live model)",
    "integration": "tests/integration/",
    "e2e": "tests/e2e/",
    "gates": "tests/tooling/ (markers, assertions, collected-test count, mypy ratchet)",
    "coverage": "tests/unit/ + tests/api/ (whole-product floors)",
    "diff-cover": "(PR changed-line gate; needs coverage.xml)",
    "mutation": "tests/mutation/ + mutmut",
}


COVERAGE_SOURCE = (
    "user_service/app/src",
    "whatsapp_adapter/app/src",
    "text_agent/app/src",
    "document_worker/src",
    "redirect_service/app/src",
    "knowledge_store",
    "infra",
)


def _cov_args(*reports: str) -> list[str]:
    return [f"--cov={path}" for path in COVERAGE_SOURCE] + ["--cov-branch", *reports]


def _run(cmd: Sequence[str], *, cwd: Path) -> int:
    printable = " ".join(cmd)
    print(f"\n==> {printable}", flush=True)
    completed = subprocess.run(cmd, cwd=cwd)
    return int(completed.returncode)


def _pytest(*args: str, cwd: Path) -> int:
    return _run([sys.executable, "-m", "pytest", *args], cwd=cwd)


def _pip_install(workspace: Path, packages: Sequence[str], req_files: Sequence[str]) -> int:
    code = _run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], cwd=workspace)
    if code:
        return code
    if packages:
        code = _run([sys.executable, "-m", "pip", "install", *packages], cwd=workspace)
        if code:
            return code
    for rel in req_files:
        path = workspace / rel
        if path.is_file():
            code = _run([sys.executable, "-m", "pip", "install", "-r", str(path)], cwd=workspace)
            if code:
                return code
    return 0


def stage_install(workspace: Path, _args: argparse.Namespace) -> int:
    return _pip_install(
        workspace,
        ROOT_PACKAGES,
        (*SERVICE_REQUIREMENTS, *TEST_REQUIREMENTS),
    )


def stage_install_mutation(workspace: Path, _args: argparse.Namespace) -> int:
    return _pip_install(workspace, MUTATION_PACKAGES, MUTATION_REQUIREMENTS)


def stage_static(workspace: Path, _args: argparse.Namespace) -> int:
    # Bare "ruff"/"mypy" rely on PATH; in this checkout they live only in
    # .venv/bin, so invoking them as `python -m` finds them regardless of
    # shell PATH state.
    code = _run([sys.executable, "-m", "ruff", "check", "."], cwd=workspace)
    if code:
        return code
    return _run(
        [sys.executable, str(TESTS_ROOT / "tooling" / "check_mypy.py")],
        cwd=workspace,
    )


def stage_secrets(workspace: Path, _args: argparse.Namespace) -> int:
    baseline = workspace / ".secrets.baseline"
    if not baseline.is_file():
        print(f"FAIL: {baseline} is missing", flush=True)
        return 1
    code = _run(
        [
            "detect-secrets",
            "scan",
            "--all-files",
            "--exclude-files",
            SECRET_EXCLUDE,
            "--baseline",
            str(baseline),
        ],
        cwd=workspace,
    )
    if code:
        return code
    payload = json.loads(baseline.read_text())
    unaudited = [
        (filename, item["line_number"])
        for filename, items in payload.get("results", {}).items()
        for item in items
        if "is_secret" not in item
    ]
    if unaudited:
        print(f"New/unaudited secret candidates found: {unaudited}", flush=True)
        return 1
    print("detect-secrets: all findings are audited.", flush=True)
    return 0


def stage_unit(workspace: Path, _args: argparse.Namespace) -> int:
    return _pytest(
        "tests/unit",
        "-c",
        "tests/unit/pytest.ini",
        *_cov_args("--cov-report=term-missing"),
        cwd=workspace,
    )


def stage_api(workspace: Path, _args: argparse.Namespace) -> int:
    return _pytest("tests/api", "-q", cwd=workspace)


def stage_eval_checks(workspace: Path, _args: argparse.Namespace) -> int:
    return _pytest("evals/tests", "-q", cwd=workspace)


def stage_integration(workspace: Path, _args: argparse.Namespace) -> int:
    return _pytest("tests/integration", "-q", cwd=workspace)


def stage_e2e(workspace: Path, _args: argparse.Namespace) -> int:
    return _pytest("tests/e2e", "-q", cwd=workspace)


def stage_gates(workspace: Path, _args: argparse.Namespace) -> int:
    tooling = TESTS_ROOT / "tooling"
    for name in (
        "check_test_methods.py",
        "check_assertions.py",
        "check_test_count.py",
        "check_mypy.py",
    ):
        code = _run([sys.executable, str(tooling / name)], cwd=workspace)
        if code:
            return code
    return 0


def stage_coverage(workspace: Path, _args: argparse.Namespace) -> int:
    pytest_code = _pytest(
        "tests/unit",
        "tests/api",
        "-c",
        "tests/unit/pytest.ini",
        *_cov_args(
            "--cov-report=xml",
            "--cov-report=json:coverage.json",
            "--cov-report=term-missing",
        ),
        cwd=workspace,
    )
    floor_code = _run(
        [sys.executable, str(TESTS_ROOT / "tooling" / "check_coverage.py")],
        cwd=workspace,
    )
    return floor_code or pytest_code


def stage_diff_cover(workspace: Path, args: argparse.Namespace) -> int:
    if not args.base_branch:
        print("FAIL: diff-cover needs --base-branch (e.g. origin/main)", flush=True)
        return 2
    coverage_xml = workspace / "coverage.xml"
    if not coverage_xml.is_file():
        print("FAIL: coverage.xml missing; run the coverage or unit stage first", flush=True)
        return 1
    return _run(
        [
            "diff-cover",
            "coverage.xml",
            f"--compare-branch={args.base_branch}",
            "--fail-under=95",
        ],
        cwd=workspace,
    )


def stage_mutation(workspace: Path, _args: argparse.Namespace) -> int:
    mutants = workspace / "mutants"
    if mutants.exists():
        shutil.rmtree(mutants)
    code = _run(["mutmut", "run"], cwd=workspace)
    if code:
        return code
    subprocess.run(["mutmut", "export-cicd-stats"], cwd=workspace, check=False)
    code = _run([sys.executable, str(TESTS_ROOT / "mutation" / "render_report.py")], cwd=workspace)
    if code:
        return code
    return _run(
        [
            sys.executable,
            str(TESTS_ROOT / "mutation" / "check_threshold.py"),
            "--min-score",
            "0.980",
        ],
        cwd=workspace,
    )


STAGES = {
    "install": stage_install,
    "install-mutation": stage_install_mutation,
    "static": stage_static,
    "secrets": stage_secrets,
    "unit": stage_unit,
    "api": stage_api,
    "eval-checks": stage_eval_checks,
    "integration": stage_integration,
    "e2e": stage_e2e,
    "gates": stage_gates,
    "coverage": stage_coverage,
    "diff-cover": stage_diff_cover,
    "mutation": stage_mutation,
}


def _print_list() -> None:
    print("tests/ layout")
    print(f"  {TESTS_ROOT}/")
    print("    unit/ api/ integration/ e2e/   runnable pytest suites")
    print("    mutation/                      mutmut helpers")
    print("    tooling/                       marker, assertion, count, coverage-floor gates")
    print("    outcomes/                      audits, findings, pytest + mutation snapshots")
    print("    ci/pipeline.py                 this runner")
    print("    ci/github/                     copies of umbrella GitHub Actions workflows")
    print("    ci/pyproject.toml              copy of umbrella mutmut/coverage/ruff/mypy")
    print()
    print("stages")
    width = max(len(name) for name in STAGES)
    for name, folder in STAGE_FOLDERS.items():
        print(f"  {name:<{width}}  {folder}")
    print()
    print("aliases:  default = " + " ".join(DEFAULT_STAGES))
    print("          --all    = default + integration e2e")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Sujho test pipeline stages against a product checkout.",
    )
    parser.add_argument(
        "stages",
        nargs="*",
        help="Stage names (default: blocking CI set). Use --list to see them.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print stages and folder map, then exit",
    )
    parser.add_argument("--all", action="store_true", help="Also run integration and e2e")
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Run every requested stage even if one fails",
    )
    parser.add_argument(
        "--with-install",
        action="store_true",
        help="Run the install stage before the others",
    )
    parser.add_argument(
        "--base-branch",
        default="",
        help="Git ref for the diff-cover stage (e.g. origin/main)",
    )
    args = parser.parse_args()

    if args.list:
        _print_list()
        return 0

    requested = list(args.stages)
    if not requested:
        requested = list(ALL_STAGES if args.all else DEFAULT_STAGES)
    elif args.all:
        parser.error("--all cannot be combined with explicit stage names")

    unknown = [name for name in requested if name not in STAGES]
    if unknown:
        parser.error("unknown stage(s): " + ", ".join(unknown) + " (try --list)")

    if args.with_install and requested[0] != "install":
        requested.insert(0, "install")

    workspace = workspace_root()
    print(f"workspace: {workspace}", flush=True)
    print(f"tests:     {TESTS_ROOT}", flush=True)
    print(f"stages:    {' '.join(requested)}", flush=True)

    failed: list[str] = []
    for name in requested:
        code = STAGES[name](workspace, args)
        if code:
            print(f"FAIL: stage {name} exited {code}", flush=True)
            failed.append(name)
            if not args.keep_going:
                return code
    if failed:
        print("failed stages: " + " ".join(failed), flush=True)
        return 1
    print("OK: all requested stages passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
