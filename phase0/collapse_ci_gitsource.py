#!/usr/bin/env python3
"""Collapse a Cloud Build deploy YAML's multi-repo `dependencies:` to one.

Every real `ci/*-deploy.yaml` in Sujho/platform lists 1-3 `gitSource` blocks
under `dependencies:` — always the super-repo itself (`destPath: .`), and
for service builds also that service's repo and `infra`, each pinned to
`revision: main` (which floats past whatever SHA the super-repo's gitlink
actually recorded). Once the 8 backend repos are merged into the
super-repo, every one of those other checkouts already exists inside the
`destPath: .` checkout, so this keeps only that one block and drops the
rest.

Pure text-level surgery, not a YAML parse+dump: these files carry Cloud
Build's `$$`-escaped shell variables and hand-placed comments that a
YAML round-trip would reformat or corrupt. A `- gitSource:` block always
spans exactly 6 lines (block header, then repository/developerConnect/
revision/depth/destPath), so blocks are found and removed by line range.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GITSOURCE_HEADER = "  - gitSource:"
DEST_PATH_PREFIX = "      destPath: "
BLOCK_LINES = 6


def find_gitsource_blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    """Every `- gitSource:` block's (start, end, destPath) in a deploy YAML.

    Args:
        lines: the file's lines, as returned by str.splitlines().
    Returns:
        (start, end, dest_path) triples, start/end as a Python slice
        (end exclusive), dest_path with its trailing newline/whitespace
        stripped. Empty if the file has no `dependencies:` gitSource blocks.
    Raises:
        ValueError: a `- gitSource:` block is truncated (fewer than
            BLOCK_LINES lines remain before the file or a sibling block ends).
    """
    blocks: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        if line != GITSOURCE_HEADER:
            continue
        end = i + BLOCK_LINES
        if end > len(lines):
            raise ValueError(
                f"truncated gitSource block starting at line {i + 1}"
            )
        dest_line = lines[end - 1]
        if not dest_line.startswith(DEST_PATH_PREFIX):
            raise ValueError(
                f"gitSource block at line {i + 1} has no destPath as its last "
                f"line"
            )
        dest_path = dest_line[len(DEST_PATH_PREFIX) :].strip()
        blocks.append((i, end, dest_path))
    return blocks


def collapse_dependencies(text: str) -> str:
    """Keep only the `destPath: .` gitSource block; drop every other one.

    Args:
        text: a ci/*-deploy.yaml file's full contents.
    Returns:
        The same text with every gitSource block whose destPath isn't `.`
        removed. Text with no gitSource blocks at all (e.g. the
        knowledge-store-jobs-deploy-local.yaml shape) is returned unchanged.
    Raises:
        ValueError: a gitSource block is malformed (see find_gitsource_blocks).
    """
    lines = text.splitlines(keepends=True)
    blocks = find_gitsource_blocks([line.rstrip("\n") for line in lines])
    drop = [(start, end) for start, end, dest in blocks if dest != "."]
    for start, end in sorted(drop, key=lambda pair: -pair[0]):
        del lines[start:end]
    return "".join(lines)


def collapse_file(path: Path) -> bool:
    """Collapse one ci/*-deploy.yaml file in place.

    Args:
        path: the deploy YAML file to rewrite.
    Returns:
        True if the file was changed, False if it had nothing to collapse
        (already single-source, or no gitSource blocks at all).
    Raises:
        ValueError: the file's gitSource blocks are malformed.
    """
    before = path.read_text()
    after = collapse_dependencies(before)
    if after == before:
        return False
    path.write_text(after)
    return True


def build_parser() -> argparse.ArgumentParser:
    """CLI parser: which deploy YAML files to collapse.

    Args:
        None.
    Returns:
        The configured parser.
    Raises:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="+", type=Path, help="ci/*-deploy.yaml files to collapse"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Collapse every given deploy YAML file in place; report what changed.

    Args:
        argv: CLI arguments, or None to use sys.argv.
    Returns:
        0 always — a file with nothing to collapse is not an error.
    Raises:
        None.
    """
    args = build_parser().parse_args(argv)
    for path in args.files:
        changed = collapse_file(path)
        print(
            f"{path}: {
                'collapsed' if changed else 'unchanged (already single-source)'
            }"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
