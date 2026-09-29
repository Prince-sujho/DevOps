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
  - non-empty-length: assert len(x) > 0 (also `len(x) != 0`, `len(x) >= 1`)
  - bare isinstance:      assert isinstance(x, T)

A test function is flagged ONLY if it contains at least one assert AND
every assert in it is weak-shaped. A function that mixes a weak assert with
a concrete-value assert (e.g. `assert result.total == 42`) is NOT flagged --
per spec, the weak assert there is scaffolding around a real check.

A test function with zero assert statements at all is not flagged by this
script (that's a different, arguably worse problem -- assertion-free tests
-- but it's out of scope for "weak assertions" and would need a separate
check to avoid conflating "no assertions" with "only weak assertions").

A test that delegates its real checks to a module-level helper (e.g.
``_assert_processed_exactly_once(openai, whatsapp)``) is judged on the
union of its own top-level asserts and every directly- or transitively-
called local helper's asserts, not just its own body -- otherwise
extracting a helper to shrink a test under the function-length limit would
silently turn a strongly-asserted test into a false "weak-only" positive.

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
    """True if node is a bare call to len(...).

    Args:
        node: an AST node that might be a call to len.
    Returns:
        True when node is a call to the name len.
    Raises:
        None.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
    )


def _is_weak_compare(test_expr: ast.Compare) -> bool:
    """True for a single `x is not None` or `len(x) > 0`-shaped comparison.

    Args:
        test_expr: an ast.Compare with exactly one operator.
    Returns:
        Whether the comparison is one of the recognized weak shapes.
    Raises:
        None.
    """
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


def _is_weak_assert(test_expr: ast.expr) -> bool:
    """Return True if `assert <test_expr>` is one of the recognized weak shapes.

    Args:
        test_expr: the expression from an assert statement.
    Returns:
        True if test_expr is an isinstance() call, a weak comparison, or another
        recognized weak shape; otherwise False.
    Raises:
        None.
    """
    # assert isinstance(x, T)
    if isinstance(test_expr, ast.Call):
        return (
            isinstance(test_expr.func, ast.Name)
            and test_expr.func.id == "isinstance"
        )

    # assert <comparison>: covers `x is not None` and `len(x) > 0` shapes.
    if isinstance(test_expr, ast.Compare) and len(test_expr.ops) == 1:
        return _is_weak_compare(test_expr)

    # bare truthiness: assert x  (a bare Name, Attribute, Subscript, or
    # boolop of such -- essentially "not a comparison, not a call producing
    # a concrete-value check"). We deliberately treat any expression that
    # isn't a Compare/Call/BoolOp of concrete comparisons as weak-bare.
    if isinstance(
        test_expr, (ast.Name, ast.Attribute, ast.Subscript, ast.UnaryOp)
    ):
        return True

    return False


def _iter_asserts(body: list[ast.stmt]) -> list[ast.Assert]:
    """Collect every ast.Assert reachable by walking into nested blocks
    (if/for/while/with/try), without crossing into nested function/class
    definitions (those are separate test units).

    Args:
        body: a function's statement list to search.
    Returns:
        Every ast.Assert node found.
    Raises:
        None.
    """
    found: list[ast.Assert] = []
    stack: list[ast.stmt] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assert):
            found.append(node)
            continue
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
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


def _called_local_names(body: list[ast.stmt]) -> set[str]:
    """Every locally-defined-looking function name called anywhere in body.

    A plain name match, not a real call-graph resolution: good enough to
    find `_assert_foo(...)`-style delegation without needing full binding
    analysis, and harmless if it over-matches a name that isn't actually
    a local helper (resolve_asserts simply won't find it in local_funcs).

    Args:
        body: a function's statement list to search.
    Returns:
        Every ast.Name a Call's func resolves to, anywhere in body.
    Raises:
        None.
    """
    names: set[str] = set()
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                names.add(node.func.id)
    return names


def _resolve_asserts(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    local_funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    seen: set[str],
) -> list[ast.Assert]:
    """fn's own asserts, plus every directly- or transitively-called local
    helper's.

    Args:
        fn: the function/method node whose asserts (including delegated
            ones) are being resolved.
        local_funcs: every module-level function in this file, by name.
        seen: helper names already expanded, to avoid infinite recursion on
            mutual/self calls; mutated in place.
    Returns:
        The combined list of ast.Assert nodes.
    Raises:
        None.
    """
    asserts = list(_iter_asserts(fn.body))
    for name in _called_local_names(fn.body):
        if name in seen or name not in local_funcs:
            continue
        seen.add(name)
        asserts.extend(_resolve_asserts(local_funcs[name], local_funcs, seen))
    return asserts


def _check_test_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str,
    local_funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    offenders: list[tuple[int, str]],
) -> None:
    """Append fn to offenders if it's a test_* function whose asserts are all
    weak-shaped.

    Args:
        fn: the function/method node to check.
        qualname: fn's dotted name, for the offenders report.
        local_funcs: every module-level function in this file, by name --
            used to resolve asserts delegated to a local helper.
        offenders: the report list to append (line, qualname) to; mutated in
            place.
    Returns:
        None.
    Raises:
        None.
    """
    if not fn.name.startswith("test_"):
        return
    asserts = _resolve_asserts(fn, local_funcs, seen={fn.name})
    if not asserts:
        return
    if all(_is_weak_assert(a.test) for a in asserts):
        offenders.append((fn.lineno, qualname))


def _module_level_funcs(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every module-level (not nested, not class-body) function, by name.

    Args:
        tree: the parsed module.
    Returns:
        {name: node} for every top-level function/async function def.
    Raises:
        None.
    """
    return {
        node.name: node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _walk(
    node: ast.AST,
    local_funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    offenders: list[tuple[int, str]],
    prefix: str = "",
) -> None:
    """Recurse into functions and classes, checking every test_* function found.

    Args:
        node: the AST node to recurse from.
        local_funcs: every module-level function in this file, by name --
            used to resolve asserts delegated to a local helper.
        offenders: the report list to append findings to; mutated in place.
        prefix: dotted-name prefix accumulated from enclosing classes/functions.
    Returns:
        None.
    Raises:
        None.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{prefix}{child.name}"
            _check_test_function(child, qualname, local_funcs, offenders)
            # Nested helper functions inside a test are rare but walk
            # anyway in case of class-based test organization.
            _walk(child, local_funcs, offenders, prefix=f"{qualname}.")
        elif isinstance(child, ast.ClassDef):
            _walk(
                child, local_funcs, offenders, prefix=f"{prefix}{child.name}."
            )


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return [(line, qualified_test_name), ...] for offending tests in path.

    Args:
        path: the test file to check.
    Returns:
        Every offending test function found, or [] if path is unreadable or
        doesn't parse.
    Raises:
        None.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    offenders: list[tuple[int, str]] = []
    _walk(tree, _module_level_funcs(tree), offenders)
    return offenders


def _suite_test_files() -> list[Path]:
    """Every test_*.py under the configured suite directories, sorted.

    Args:
        None.
    Returns:
        The sorted test_*.py paths under the suite directories.
    Raises:
        None.
    """
    files: list[Path] = []
    for name in SUITE_DIRS:
        directory = TESTS_ROOT / name
        if directory.is_dir():
            files.extend(sorted(directory.rglob("test_*.py")))
    return files


def _collect_offenses(test_files: list[Path]) -> list[str]:
    """Every weak-only test, as 'path:line:qualname'.

    Args:
        test_files: suite test modules to inspect.
    Returns:
        One string per offending test function.
    Raises:
        None.
    """
    offenses: list[str] = []
    for path in test_files:
        for line, qualname in check_file(path):
            rel = path.relative_to(WORKSPACE_ROOT)
            offenses.append(f"{rel}:{line}:{qualname}")
    return offenses


def _report_offenses(offenses: list[str]) -> int:
    """Print the weak-only result and return the process exit code.

    Args:
        offenses: 'path:line:qualname' lines, empty when the tree is clean.
    Returns:
        0 when offenses is empty, 1 otherwise.
    Raises:
        None.
    """
    if not offenses:
        print(
            "check_assertions: OK -- no test function relies solely on weak "
            "assertions."
        )
        return 0
    print(
        "check_assertions: FAIL -- tests with only weak-shaped "
        "assertions:\n"
    )
    for line in offenses:
        print(f"  {line}")
    print(f"\n{len(offenses)} offending test function(s).")
    return 1


def main() -> int:
    """Check every suite's test files for weak-only assertions; exit nonzero if
    any are found.

    Args:
        None.
    Returns:
        0 when tests/ is missing or every test has a strong assertion, 1 when
        any test is weak-only.
    Raises:
        None.
    """
    if not TESTS_ROOT.exists():
        print("check_assertions: tests/ directory not found; nothing to check.")
        return 0

    return _report_offenses(_collect_offenses(_suite_test_files()))


if __name__ == "__main__":
    sys.exit(main())
