#!/usr/bin/env python3
"""Enforce that critical modules are covered by tests carrying required
pytest markers (``property`` and/or ``boundary``, as registered in
``tests/unit/pytest.ini``).

Convention (documented here since it is the one implemented, not the only
one imaginable):

1. A module is "covered" by a test file if the test file's module-level
   stem, with a leading ``test_`` stripped, equals the critical module's
   stem -- e.g. ``user_service/app/src/gifting.py`` is covered by any file
   matching ``tests/**/test_gifting*.py``. This is a filename convention,
   not an import scan: it is simpler, avoids false positives from modules
   that merely import a helper for setup, and matches this repository's
   existing tests/unit/user_service/test_<module>.py layout.
2. Multiple covering files are allowed (markers are the union across all
   covering files) and covering files may live in any tests/** subtree
   (unit/api/integration/e2e), though in practice property/boundary tests
   are unit-only in this repo.
3. Markers actually present on a module are collected via an ``ast`` walk
   of top-level ``def test_*`` functions (including ones nested in
   ``class Test*`` bodies), reading their ``@pytest.mark.<name>`` /
   ``@mark.<name>`` decorators. This intentionally does NOT run pytest --
   it is a static check, fast and side-effect free.

Exit status is non-zero if any critical module is missing one or more of
its required markers (including the case of no covering test file at all).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = TESTS_ROOT.parent
SUITE_DIRS = ("unit", "api", "integration", "e2e")

# Critical module (relative to repo root) -> required pytest marker names.
CRITICAL_MODULES: dict[str, set[str]] = {
    "user_service/app/src/gifting.py": {"property", "boundary"},
    "user_service/app/src/influencers.py": {"boundary"},
    "user_service/app/src/ambassadors.py": {"property", "boundary"},
    "user_service/app/src/attribution.py": {"property"},
    "user_service/app/src/directory.py": {"boundary"},
}


def find_covering_test_files(module_stem: str) -> list[Path]:
    """Return all suite ``test_<module_stem>*.py`` files, if any."""
    files: list[Path] = []
    for name in SUITE_DIRS:
        directory = TESTS_ROOT / name
        if directory.is_dir():
            files.extend(sorted(directory.rglob(f"test_{module_stem}*.py")))
    return files


def _decorator_marker_name(dec: ast.expr) -> str | None:
    """Extract the marker name from a `@pytest.mark.X` / `@mark.X` /
    `@pytest.mark.X(...)` decorator node, else None.
    """
    node: ast.expr = dec
    if isinstance(node, ast.Call):
        node = node.func
    # node should now be an Attribute: <...>.mark.<name>
    if isinstance(node, ast.Attribute):
        attr_name = node.attr
        value = node.value
        if isinstance(value, ast.Attribute) and value.attr == "mark":
            return attr_name
        if isinstance(value, ast.Name) and value.id == "mark":
            return attr_name
    return None


def collect_markers_in_file(path: Path) -> set[str]:
    """Return the set of pytest marker names applied to any test_* function
    (top-level or nested in a class) in the given file.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return set()

    tree = ast.parse(source, filename=str(path))
    markers: set[str] = set()

    def visit_function(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not fn.name.startswith("test_"):
            return
        for dec in fn.decorator_list:
            name = _decorator_marker_name(dec)
            if name:
                markers.add(name)

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit_function(child)
                walk(child)
            elif isinstance(child, ast.ClassDef):
                walk(child)
            # Do not descend into unrelated nodes' bodies beyond what
            # iter_child_nodes already yields; ast.walk-equivalent by
            # recursion keeps this simple and correct for our shapes.

    walk(tree)
    return markers


def main() -> int:
    failures: list[str] = []

    for rel_module, required_markers in sorted(CRITICAL_MODULES.items()):
        module_path = WORKSPACE_ROOT / rel_module
        module_stem = module_path.stem

        if not module_path.exists():
            failures.append(
                f"{rel_module}: critical module listed in "
                f"CRITICAL_MODULES does not exist on disk"
            )
            continue

        covering_files = find_covering_test_files(module_stem)
        if not covering_files:
            missing = ", ".join(sorted(required_markers))
            failures.append(
                f"{rel_module}: NO covering test file found "
                f"(expected tests/**/test_{module_stem}*.py) -- "
                f"missing required markers: {missing}"
            )
            continue

        found_markers: set[str] = set()
        for tf in covering_files:
            found_markers |= collect_markers_in_file(tf)

        missing_markers = required_markers - found_markers
        if missing_markers:
            rel_covering = ", ".join(
                str(f.relative_to(WORKSPACE_ROOT)) for f in covering_files
            )
            failures.append(
                f"{rel_module}: covering file(s) [{rel_covering}] are "
                f"missing required marker(s): {', '.join(sorted(missing_markers))}"
            )

    if failures:
        print("check_test_methods: FAIL\n")
        for line in failures:
            print(f"  - {line}")
        print(
            f"\n{len(failures)} critical-module marker requirement(s) not met."
        )
        return 1

    print("check_test_methods: OK -- all critical modules carry their required markers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
