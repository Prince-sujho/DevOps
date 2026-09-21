"""Shared bits for generated GitHub workflow files."""

from __future__ import annotations


def pin(pins: dict, name: str) -> str:
    p = pins[name]
    return f"{name}@{p['sha']} # {p['tag']}"


# First step on every dispatch that can mutate GCP. github.ref is the branch
# chosen on "Run workflow". A feature-branch edit of the YAML must not run.
MAIN_ONLY_STEP = """      - name: Refuse unless this run is on main
        run: |
          if [ "${{ github.ref }}" != "refs/heads/main" ]; then
            echo "Refuse: dispatch from main, not ${{ github.ref }}"
            exit 1
          fi
"""
