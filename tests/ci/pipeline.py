#!/usr/bin/env python3
"""Run one stage, several, or the full Sujho test pipeline.

Must be invoked from (or able to find) a Sujho umbrella checkout: the suites
import live product packages. Set SUJHO_ROOT if this tree is not at
<workspace>/tests.

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
    "eval-checks": "Eval-Suite/tests/ (grader + corpus gate; no live model)",
    "integration": "tests/integration/",
    "e2e": "tests/e2e/",
    "gates": "tests/tooling/ (markers, assertions, collected-test count, mypy "
    "ratchet)",
    "coverage": "tests/unit/ + tests/api/ (whole-product floors)",
    "diff-cover": "(PR changed-line gate; needs coverage.xml)",
    "mutation": "mutmut run + export (scripts/mutation_report.py scores it)",
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
    """pytest --cov flags for every product source path, plus branch coverage
    and reports.

    Args:
        reports: extra pytest coverage-report flags appended after the source
            paths.
    Returns:
        pytest --cov flags for each source path, plus branch coverage and report
        flags.
    Raises:
        None.
    """
    return [f"--cov={path}" for path in COVERAGE_SOURCE] + [
        "--cov-branch",
        *reports,
    ]


def _run(cmd: Sequence[str], *, cwd: Path) -> int:
    """Run cmd in cwd, printing it first; return its exit code.

    Args:
        cmd: argv to execute.
        cwd: working directory for the process.
    Returns:
        The process exit code as an int.
    Raises:
        None.
    """
    printable = " ".join(cmd)
    print(f"\n==> {printable}", flush=True)
    completed = subprocess.run(cmd, cwd=cwd)
    return int(completed.returncode)


def _pytest(*args: str, cwd: Path) -> int:
    """Run pytest with the given args in cwd; return its exit code.

    Args:
        cwd: working directory pytest runs in.
        args: extra arguments appended to the pytest command.
    Returns:
        The pytest process exit code.
    Raises:
        None.
    """
    return _run([sys.executable, "-m", "pytest", *args], cwd=cwd)


def _install_requirement_files(
    workspace: Path, req_files: Sequence[str]
) -> int:
    """Install each requirements file that exists under workspace.

    Args:
        workspace: the product checkout to install into.
        req_files: requirements file paths, relative to workspace; missing ones
            are skipped.
    Returns:
        The exit code of the first failing pip invocation, or 0.
    Raises:
        None.
    """
    for rel in req_files:
        path = workspace / rel
        if not path.is_file():
            continue
        code = _run(
            [sys.executable, "-m", "pip", "install", "-r", str(path)],
            cwd=workspace,
        )
        if code:
            return code
    return 0


def _pip_install(
    workspace: Path, packages: Sequence[str], req_files: Sequence[str]
) -> int:
    """Upgrade pip, install packages, then install every requirements file that
    exists.

    Args:
        workspace: the product checkout to install into.
        packages: extra packages to install directly.
        req_files: requirements file paths, relative to workspace; missing ones
            are skipped.
    Returns:
        The exit code of the first failing pip invocation, or 0.
    Raises:
        None.
    """
    code = _run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
        cwd=workspace,
    )
    if code:
        return code
    if packages:
        code = _run(
            [sys.executable, "-m", "pip", "install", *packages], cwd=workspace
        )
        if code:
            return code
    return _install_requirement_files(workspace, req_files)


def stage_install(workspace: Path, _args: argparse.Namespace) -> int:
    """Install service + test requirements into the workspace.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    return _pip_install(
        workspace, ROOT_PACKAGES, (*SERVICE_REQUIREMENTS, *TEST_REQUIREMENTS)
    )


def stage_install_mutation(workspace: Path, _args: argparse.Namespace) -> int:
    """Install mutmut and the user_service unit-test dependencies.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    return _pip_install(workspace, MUTATION_PACKAGES, MUTATION_REQUIREMENTS)


def stage_static(workspace: Path, _args: argparse.Namespace) -> int:
    """Run ruff and the mypy ratchet check over the product tree.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
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


def _unaudited_secrets(payload: dict) -> list[tuple[str, int]]:
    """Findings in a detect-secrets payload that have not been audited.

    Args:
        payload: the parsed .secrets.baseline JSON.
    Returns:
        (filename, line_number) for each unaudited finding.
    Raises:
        None.
    """
    return [
        (filename, item["line_number"])
        for filename, items in payload.get("results", {}).items()
        for item in items
        if "is_secret" not in item
    ]


def _scan_secrets(workspace: Path, baseline: Path) -> int:
    """Scan the tree with detect-secrets against an existing baseline.

    Args:
        workspace: the product checkout to scan.
        baseline: the .secrets.baseline file to compare against.
    Returns:
        The detect-secrets process exit code.
    Raises:
        None.
    """
    return _run(
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


def stage_secrets(workspace: Path, _args: argparse.Namespace) -> int:
    """Run detect-secrets against the baseline and refuse any new unaudited
    finding.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    baseline = workspace / ".secrets.baseline"
    if not baseline.is_file():
        print(f"FAIL: {baseline} is missing", flush=True)
        return 1
    code = _scan_secrets(workspace, baseline)
    if code:
        return code
    payload = json.loads(baseline.read_text())
    unaudited = _unaudited_secrets(payload)
    if unaudited:
        print(f"New/unaudited secret candidates found: {unaudited}", flush=True)
        return 1
    print("detect-secrets: all findings are audited.", flush=True)
    return 0


def stage_unit(workspace: Path, _args: argparse.Namespace) -> int:
    """Run tests/unit with coverage.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    return _pytest(
        "tests/unit",
        "-c",
        "tests/unit/pytest.ini",
        *_cov_args("--cov-report=term-missing"),
        cwd=workspace,
    )


def stage_api(workspace: Path, _args: argparse.Namespace) -> int:
    """Run tests/api.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    return _pytest("tests/api", "-q", cwd=workspace)


def stage_eval_checks(workspace: Path, _args: argparse.Namespace) -> int:
    """Run the eval grader + corpus gate tests (no live model).

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    return _pytest("Eval-Suite/tests", "-q", cwd=workspace)


def stage_integration(workspace: Path, _args: argparse.Namespace) -> int:
    """Run tests/integration.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    return _pytest("tests/integration", "-q", cwd=workspace)


def stage_e2e(workspace: Path, _args: argparse.Namespace) -> int:
    """Run tests/e2e.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    return _pytest("tests/e2e", "-q", cwd=workspace)


def stage_gates(workspace: Path, _args: argparse.Namespace) -> int:
    """Run the marker, assertion, count, and mypy-ratchet gates in
    tests/tooling.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
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
    """Run unit + api with coverage reports, then check the coverage floor.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
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


def _diff_cover_refusal(
    workspace: Path, args: argparse.Namespace
) -> int | None:
    """An error code when diff-cover's inputs are missing, else None.

    Args:
        workspace: the product checkout coverage.xml should live in.
        args: parsed CLI args; args.base_branch is required.
    Returns:
        2 when --base-branch is missing, 1 when coverage.xml is missing, or
        None when the stage can run.
    Raises:
        None.
    """
    if not args.base_branch:
        print(
            "FAIL: diff-cover needs --base-branch (e.g. origin/main)",
            flush=True,
        )
        return 2
    if not (workspace / "coverage.xml").is_file():
        print(
            "FAIL: coverage.xml missing; run the coverage or unit stage first",
            flush=True,
        )
        return 1
    return None


def stage_diff_cover(workspace: Path, args: argparse.Namespace) -> int:
    """Check changed-line coverage against base_branch; needs coverage.xml
    already built.

    Args:
        workspace: the product checkout to run in.
        args: parsed CLI args; args.base_branch is required (e.g. origin/main).
    Returns:
        0 passed; 1 coverage.xml missing; 2 --base-branch not given; or
        diff-cover's own exit code.
    Raises:
        None.
    """
    refused = _diff_cover_refusal(workspace, args)
    if refused is not None:
        return refused
    return _run(
        [
            "diff-cover",
            "coverage.xml",
            f"--compare-branch={args.base_branch}",
            "--fail-under=95",
        ],
        cwd=workspace,
    )


def _export_mutmut_stats(workspace: Path) -> None:
    """Export mutmut's run into mutants/mutmut-cicd-stats.json.

    Scoring and threshold-checking happen elsewhere — scripts/mutation_report.py
    is the workflow's separate reporting step, and reads this same file. A
    failed export here is not fatal: mutation_report.py handles a missing/
    unparseable report as a skip, not a crash (see its _MISSING_REPORT
    message), so this stage never has to duplicate that judgment.

    Args:
        workspace: the product checkout mutmut just ran in.
    Returns:
        None.
    Raises:
        None.
    """
    subprocess.run(
        ["mutmut", "export-cicd-stats"], cwd=workspace, check=False
    )


def stage_mutation(workspace: Path, _args: argparse.Namespace) -> int:
    """Run mutmut fresh and export its stats for the workflow's report step.

    Args:
        workspace: the product checkout to run in.
        _args: parsed CLI args; unused here, kept for STAGES' uniform signature.
    Returns:
        The stage's exit code (0 on success).
    Raises:
        None.
    """
    mutants = workspace / "mutants"
    if mutants.exists():
        shutil.rmtree(mutants)
    code = _run(["mutmut", "run"], cwd=workspace)
    if code:
        return code
    _export_mutmut_stats(workspace)
    return 0


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
    """Print the tests/ layout and the available stages with their folder
    mapping.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    print("tests/ layout")
    print(f"  {TESTS_ROOT}/")
    print("    unit/ api/ integration/ e2e/   runnable pytest suites")
    print(
        "    tooling/                       marker, assertion, count, "
        "coverage-floor gates"
    )
    print(
        "    outcomes/                      audits, findings, pytest + "
        "mutation snapshots"
    )
    print("    ci/pipeline.py                 this runner")
    print(
        "    ci/github/                     copies of umbrella GitHub Actions "
        "workflows"
    )
    print(
        "    ci/pyproject.toml              copy of umbrella "
        "mutmut/coverage/ruff/mypy"
    )
    print()
    print("stages")
    width = max(len(name) for name in STAGES)
    for name, folder in STAGE_FOLDERS.items():
        print(f"  {name:<{width}}  {folder}")
    print()
    print("aliases:  default = " + " ".join(DEFAULT_STAGES))
    print("          --all    = default + integration e2e")


def build_parser() -> argparse.ArgumentParser:
    """CLI parser for stage selection and pipeline options.

    Args:
        None.
    Returns:
        The configured ArgumentParser.
    Raises:
        None.
    """
    parser = argparse.ArgumentParser(
        description="Run Sujho test pipeline stages against a product checkout."
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
    parser.add_argument(
        "--all", action="store_true", help="Also run integration and e2e"
    )
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
    return parser


def resolve_requested_stages(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> list[str]:
    """The stage list to run: explicit names, --all's set, or the default set.

    Args:
        args: parsed CLI args (stages/--all/--with-install).
        parser: the parser to call .error() on for a bad combination.
    Returns:
        The resolved stage name list, in run order.
    Raises:
        None — parser.error() prints and exits the process itself.
    """
    requested = list(args.stages)
    if not requested:
        requested = list(ALL_STAGES if args.all else DEFAULT_STAGES)
    elif args.all:
        parser.error("--all cannot be combined with explicit stage names")

    unknown = [name for name in requested if name not in STAGES]
    if unknown:
        parser.error(
            "unknown stage(s): " + ", ".join(unknown) + " (try --list)"
        )

    if args.with_install and requested[0] != "install":
        requested.insert(0, "install")
    return requested


def run_stages(
    requested: list[str], workspace: Path, args: argparse.Namespace
) -> int:
    """Run each requested stage in order; 0 only if every requested stage
    passed.

    Args:
        requested: stage names to run, in order.
        workspace: the product checkout to run in.
        args: parsed CLI args, passed through to each stage.
    Returns:
        The first failing stage's exit code (unless --keep-going), or 1 if
        any stage failed, or 0 if all passed.
    Raises:
        None.
    """
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


def main() -> int:
    """Parse args, resolve which stages to run, and run them against a checkout.

    Args:
        None.
    Returns:
        0 when --list printed the stages, otherwise the exit code from
        run_stages.
    Raises:
        None.
    """
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        _print_list()
        return 0

    requested = resolve_requested_stages(args, parser)

    workspace = workspace_root()
    print(f"workspace: {workspace}", flush=True)
    print(f"tests:     {TESTS_ROOT}", flush=True)
    print(f"stages:    {' '.join(requested)}", flush=True)

    return run_stages(requested, workspace, args)


if __name__ == "__main__":
    sys.exit(main())
