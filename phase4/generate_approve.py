#!/usr/bin/env python3
"""Write the Lead approve-preprod form.

One piece per click. Weekly eval does not stamp. A Lead runs this after
they tested that commit on Pre-Prod.
"""
from __future__ import annotations

import json
from pathlib import Path

import workflow_common as wc

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "catalog.json").read_text())
JOBS = json.loads((HERE / "jobs" / "catalog.jobs.json").read_text())
PINS = json.loads((HERE.parent / "action-pins.json").read_text())["pins"]
OUT = HERE / "workflows" / "approve-preprod.yaml"


def pieces() -> list[str]:
    ids = [s["id"] for s in CATALOG["services"]]
    pilot = CATALOG["pilot"]
    ordered = [pilot] + [i for i in ids if i != pilot]
    ordered.append(JOBS["image_groups"]["knowledge-store"]["image"])
    return ordered


def render() -> str:
    opts = "\n".join(f"          - {i}" for i in pieces())
    checkout = wc.pin(PINS, "actions/checkout")
    auth = wc.pin(PINS, "google-github-actions/auth")
    gcloud = wc.pin(PINS, "google-github-actions/setup-gcloud")
    return f"""name: Approve Pre-Prod image

# Lead-only. After you tested this commit on Pre-Prod, stamp preprod-approved
# for ONE image. Weekly eval does not stamp. Merge does not stamp.
# One piece per click.

on:
  workflow_dispatch:
    inputs:
      piece:
        description: Image to approve (one per run)
        required: true
        type: choice
        default: {CATALOG["pilot"]}
        options:
{opts}
      commit:
        description: Full git SHA that was built and tested (required)
        required: true
        type: string

permissions:
  contents: read
  id-token: write

jobs:
  approve:
    runs-on: ubuntu-latest
    steps:
{wc.MAIN_ONLY_STEP}
      - uses: {checkout}

      - uses: {auth}
        with:
          workload_identity_provider: ${{{{ vars.GCP_WIF_PROVIDER }}}}
          service_account: ${{{{ vars.GCP_WIF_SERVICE_ACCOUNT_PREPROD }}}}

      - uses: {gcloud}

      - name: Stamp preprod-approved for this piece only
        env:
          COMMIT: ${{{{ inputs.commit }}}}
          PIECE: ${{{{ inputs.piece }}}}
        run: |
          set -euo pipefail
          if [ -z "$COMMIT" ]; then
            echo "Refuse: commit is required. Do not stamp monday-tip by accident."
            exit 1
          fi
          bash scripts/tag-on-approval.sh "$COMMIT" "$PIECE"
"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
