"""Fail if the mutmut score dropped below the recorded ratchet threshold.

Score = killed / (killed + survived). Untested and timeout mutants are
reported but not in this denominator — same formula as
tests/outcomes/MUTATION_BASELINE.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Honest baseline recorded 2026-09-06 before killer tests: 448/551 = 81.3%.
# After KILLABLE tests: 553/564 = 98.05%. Ratchet to 98.0%; never lower it.
DEFAULT_MIN_SCORE = 0.980


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stats",
        type=Path,
        default=Path("mutants/mutmut-cicd-stats.json"),
    )
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    args = parser.parse_args()
    stats = json.loads(args.stats.read_text())
    killed = int(stats["killed"])
    survived = int(stats["survived"])
    decided = killed + survived
    score = killed / decided if decided else 0.0
    print(
        f"killed={killed} survived={survived} no_tests={stats.get('no_tests')} "
        f"timeout={stats.get('timeout')} total={stats.get('total')} "
        f"score={score:.4f} min={args.min_score:.4f}"
    )
    if score + 1e-12 < args.min_score:
        print(f"FAIL: mutation score {score:.4f} dropped below ratchet {args.min_score:.4f}")
        return 1
    print("OK: mutation score is at or above the ratchet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
