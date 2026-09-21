#!/usr/bin/env python3
"""Flag test functions whose assertions are *all* weak.

Walks ``tests/{unit,api,integration,e2e}/**/test_*.py``, finds ``def test_*``
functions (module-level or nested inside ``class Test*``-style bodies, sync
or async), and inspects every top-level ``assert`` statement reachable in the
function body (walking into ``if``/``for``/``with``/``try`` blocks, since real
tests often guard assertions).

A single ``assert`` statement is "weak-shaped" if it matches one of:

  - bare truthiness:      assert x
  - not-None check:       assert x is not None   (or `is not None` on any expr)
  - non-empty-length:     assert len(x) > 0       (also `len(x) != 0`, `len(x) >= 1`)
  - bare isinstance:      assert isinstance(x, T)

A test function is flagged ONLY if it contains at least one assert AND
every assert in it is weak-shaped. A function that mixes a weak assert with
a concrete-value assert (e.g. `assert result.total == 42`) is NOT flagged --
per spec, the weak assert there is scaffolding around a real check.

A test function with zero assert statements at all is not flagged by this
script (that's a different, arguably worse problem -- assertion-free tests
-- but it's out of scope for "weak assertions" and would need a separate
check to avoid conflating "no assertions" with "only weak assertions").

Exits non-zero and prints `file:line:function` for every offending test.
"""

# Nested control flow is easier to audit against the weak-assert shapes
# than the SIM-collapsed form.
# ruff: noqa: SIM102, SIM103

from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = TESTS_ROOT.parent
SUITE_DIRS = ("unit", "api", "integration", "e2e")


def _is_len_call(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len"


def _is_weak_assert(test_expr: ast.expr) -> bool:
    """Return True if `assert <test_expr>` is one of the recognized weak shapes."""
    # assert isinstance(x, T)
    if isinstance(test_expr, ast.Call):
        if isinstance(test_expr.func, ast.Name) and test_expr.func.id == "isinstance":
            return True
        return False

    # assert <comparison>: covers `x is not None` and `len(x) > 0` shapes.
    if isinstance(test_expr, ast.Compare) and len(test_expr.ops) == 1:
        op = test_expr.ops[0]
        left = test_expr.left
        (right,) = test_expr.comparators

        # x is not None / None is not x
        if isinstance(op, ast.IsNot):
            if isinstance(right, ast.Constant) and right.value is None:
                return True
            if isinstance(left, ast.Constant) and left.value is None:
                return True
            return False

        # len(x) > 0 / len(x) >= 1 / len(x) != 0  (either operand order)
        if isinstance(op, (ast.Gt, ast.GtE, ast.NotEq)):
            if _is_len_call(left) and isinstance(right, ast.Constant):
                if isinstance(op, ast.Gt) and right.value == 0:
                    return True
                if isinstance(op, ast.GtE) and right.value == 1:
                    return True
                if isinstance(op, ast.NotEq) and right.value == 0:
                    return True
            if _is_len_call(right) and isinstance(left, ast.Constant):
                if isinstance(op, ast.Lt) and left.value == 0:
                    return True
        return False

    # bare truthiness: assert x  (a bare Name, Attribute, Subscript, or
    # boolop of such -- essentially "not a comparison, not a call producing
    # a concrete-value check"). We deliberately treat any expression that
    # isn't a Compare/Call/BoolOp of concrete comparisons as weak-bare.
    if isinstance(test_expr, (ast.Name, ast.Attribute, ast.Subscript, ast.UnaryOp)):
        return True

    return False


def _iter_asserts(body: list[ast.stmt]) -> list[ast.Assert]:
    """Collect every ast.Assert reachable by walking into nested blocks
    (if/for/while/with/try), without crossing into nested function/class
    definitions (those are separate test units).
    """
    found: list[ast.Assert] = []
    stack: list[ast.stmt] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assert):
            found.append(node)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field_name in ("body", "orelse", "finalbody", "handlers"):
            value = getattr(node, field_name, None)
            if not value:
                continue
            for item in value:
                if isinstance(item, ast.ExceptHandler):
                    stack.extend(item.body)
                elif isinstance(item, ast.stmt):
                    stack.append(item)
    return found


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return [(line, qualified_test_name), ...] for offending tests in path."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    offenders: list[tuple[int, str]] = []

    def check_test_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, qualname: str) -> None:
        if not fn.name.startswith("test_"):
            return
        asserts = _iter_asserts(fn.body)
        if not asserts:
            return
        if all(_is_weak_assert(a.test) for a in asserts):
            offenders.append((fn.lineno, qualname))

    def walk(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                check_test_function(child, qualname)
                # Nested helper functions inside a test are rare but walk
                # anyway in case of class-based test organization.
                walk(child, prefix=f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix=f"{prefix}{child.name}.")

    walk(tree)
    return offenders


def _suite_test_files() -> list[Path]:
    files: list[Path] = []
    for name in SUITE_DIRS:
        directory = TESTS_ROOT / name
        if directory.is_dir():
            files.extend(sorted(directory.rglob("test_*.py")))
    return files


def main() -> int:
    if not TESTS_ROOT.exists():
        print("check_assertions: tests/ directory not found; nothing to check.")
        return 0

    test_files = _suite_test_files()
    all_offenses: list[str] = []

    for path in test_files:
        for line, qualname in check_file(path):
            rel = path.relative_to(WORKSPACE_ROOT)
            all_offenses.append(f"{rel}:{line}:{qualname}")

    if all_offenses:
        print("check_assertions: FAIL -- tests with only weak-shaped assertions:\n")
        for line in all_offenses:
            print(f"  {line}")
        print(f"\n{len(all_offenses)} offending test function(s).")
        return 1

    print("check_assertions: OK -- no test function relies solely on weak assertions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
