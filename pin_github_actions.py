#!/usr/bin/env python3
"""Rewrite GitHub Actions `uses:` lines to full SHAs from action-pins.json.

Tags like @v4 move. Pins do not. Re-run after changing action-pins.json.
Skips Cloud Build YAML under phase4/ci/.
"""
from __future__ import annotations

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

SKIP_DIRS = {ROOT / "phase4" / "ci"}


def pin_comment(name: str) -> str:
    pin = PINS[name]
    return f"{name}@{pin['sha']} # {pin['tag']}"


def pin_text(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in PINS:
            return match.group(0)
        return match.group("pre") + pin_comment(name)

    return USES_RE.sub(repl, text)


def should_skip(path: Path) -> bool:
    if path.suffix not in {".yml", ".yaml"}:
        return True
    for skip in SKIP_DIRS:
        try:
            path.relative_to(skip)
            return True
        except ValueError:
            pass
    return False


def iter_workflow_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if should_skip(path):
            continue
        out.append(path)
    return sorted(out)


def main() -> None:
    for path in iter_workflow_files():
        before = path.read_text()
        after = pin_text(before)
        if after != before:
            path.write_text(after)
            print(f"pinned {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
