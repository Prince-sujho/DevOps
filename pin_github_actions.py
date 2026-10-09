#!/usr/bin/env python3
"""Rewrite GitHub Actions `uses:` lines to full SHAs from action-pins.json.

Tags like @v4 move. Pins do not. Re-run after changing action-pins.json.
Skips Cloud Build YAML under phase2/ci/.

Usage:
    python3 pin_github_actions.py          rewrite files in place
    python3 pin_github_actions.py --check  change nothing; exit 1 if any file needs pinning
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PINS = json.loads((ROOT / "action-pins.json").read_text())["pins"]

USES_RE = re.compile(
    r"(?P<pre>uses:\s+)(?P<name>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"@(?P<ref>[0-9a-fA-F]{40}|v[^\s#]+)"
    r"(?P<comment>[^\n]*)"
)

SKIP_DIRS = {ROOT / "phase2" / "ci"}
SKIP_PARTS = {".git", ".venv", "node_modules"}


def pin_comment(name: str) -> str:
    """The full uses: value for name, pinned to its recorded SHA with the tag as
    a comment.

    Args:
        name: action name (owner/repo) to look up in the pin table.
    Returns:
        The action name, its pinned SHA, and the tag as a comment.
    Raises:
        None.
    """
    pin = PINS[name]
    return f"{name}@{pin['sha']} # {pin['tag']}"


def pin_text(text: str) -> str:
    """Replace every pinnable uses: line in text with its full-SHA pin.

    Args:
        text: workflow file text whose uses: lines are rewritten.
    Returns:
        text with every pinnable uses: line replaced by its SHA pin.
    Raises:
        None.
    """

    def repl(match: re.Match[str]) -> str:
        """Replace one matched uses: line with its pin, or leave it untouched if
        unpinned.

        Args:
            match: one uses: line matched by USES_RE.
        Returns:
            The original matched text when the action is not pinned, otherwise
            the line prefix plus the SHA pin.
        Raises:
            None.
        """
        name = match.group("name")
        if name not in PINS:
            return match.group(0)
        return match.group("pre") + pin_comment(name)

    return USES_RE.sub(repl, text)


def should_skip(path: Path) -> bool:
    """True for non-workflow files and anything under a skipped directory (Cloud
    Build YAML).

    Args:
        path: the file to check.
    Returns:
        Whether pin_text should skip this file.
    Raises:
        None.
    """
    if path.suffix not in {".yml", ".yaml"}:
        return True
    if SKIP_PARTS & set(path.relative_to(ROOT).parts):
        return True
    for skip in SKIP_DIRS:
        try:
            path.relative_to(skip)
            return True
        except ValueError:
            pass
    return False


def iter_workflow_files() -> list[Path]:
    """Every workflow file under ROOT that isn't skipped, sorted.

    Args:
        None.
    Returns:
        The collected paths, sorted.
    Raises:
        None.
    """
    out = []
    for path in ROOT.rglob("*"):
        if should_skip(path):
            continue
        out.append(path)
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    """Pin every uses: line in every workflow file that changed, printing which
    ones touched. With --check, change nothing and report instead.

    Args:
        argv: command-line arguments; None means sys.argv.
    Returns:
        0, or 1 when --check found a file that needs pinning.
    Raises:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="change nothing; exit 1 if any file needs pinning",
    )
    args = parser.parse_args(argv)
    stale = 0
    for path in iter_workflow_files():
        before = path.read_text()
        after = pin_text(before)
        if after == before:
            continue
        stale += 1
        if args.check:
            print(f"needs pinning {path.relative_to(ROOT)}")
        else:
            path.write_text(after)
            print(f"pinned {path.relative_to(ROOT)}")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
