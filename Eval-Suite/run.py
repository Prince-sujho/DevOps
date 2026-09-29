"""List or run the Eval-Suite corpus."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUITE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SUITE))

from eval_suite.cases import select_cases  # noqa: E402


def main() -> None:
    """Parse CLI args, then either list matching case ids or run them.

    Args:
        None.
    Returns:
        None.
    Raises:
        ValueError: --case names an unknown case id, or the filters select
            nothing.
        SystemExit: (when actually running) at least one case failed or xpassed.
    """
    parser = argparse.ArgumentParser(prog="Eval-Suite")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    args = parser.parse_args()
    cases = select_cases(args.case, set(args.tag))
    if args.list:
        for case in cases:
            print(case.id)
        return
    from eval_suite.runner import run

    asyncio.run(run(args.case, set(args.tag)))


if __name__ == "__main__":
    main()
