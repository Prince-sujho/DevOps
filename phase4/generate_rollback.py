#!/usr/bin/env python3
"""Write the Cloud Run *service* rollback GitHub forms from catalog.json.

Opening the file is choosing Dev, Pre-Prod, or Prod. Job rollback is not this
form: jobs have no HTTP traffic; redeploy a previous digest instead.

The run step uses equals-form flags. rollback-cloudrun.sh must parse those.
Tests extract this command from the rendered YAML — do not re-type it.
"""
from __future__ import annotations

import json
from pathlib import Path

import workflow_common as wc

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "catalog.json").read_text())
PINS = json.loads((HERE.parent / "action-pins.json").read_text())["pins"]
OUT_DEV = HERE / "workflows" / "cloud-run-dev-rollback.yaml"
OUT_PREPROD = HERE / "workflows" / "cloud-run-preprod-rollback.yaml"
OUT_PROD = HERE / "workflows" / "cloud-run-prod-rollback.yaml"


def ordered_service_ids() -> list[str]:
    ids = [s["id"] for s in CATALOG["services"]]
    pilot = CATALOG["pilot"]
    return [pilot] + [i for i in ids if i != pilot]


def render(name: str, project: str, sa_var: str) -> str:
    opts = "\n".join(f"          - {i}" for i in ordered_service_ids())
    checkout = wc.pin(PINS, "actions/checkout")
    auth = wc.pin(PINS, "google-github-actions/auth")
    gcloud = wc.pin(PINS, "google-github-actions/setup-gcloud")
    return f"""name: {name}

# Manual only. Merge does not run this. Shift traffic to a previous revision.
# Empty revision = older Ready revision than the one serving users.
# Refuses a newer Ready revision with no traffic (unverified --no-traffic).

on:
  workflow_dispatch:
    inputs:
      service:
        description: Cloud Run service (one per run)
        required: true
        type: choice
        default: {CATALOG["pilot"]}
        options:
{opts}
      revision:
        description: Cloud Run revision name (empty = previous serving)
        required: false
        type: string
        default: ""

concurrency:
  group: cloudrun-{project}-${{{{ inputs.service }}}}
  cancel-in-progress: false

permissions:
  contents: read
  id-token: write

jobs:
  rollback:
    runs-on: ubuntu-latest
    steps:
{wc.MAIN_ONLY_STEP}
      - uses: {checkout}

      - uses: {auth}
        with:
          workload_identity_provider: ${{{{ vars.GCP_WIF_PROVIDER }}}}
          service_account: ${{{{ vars.{sa_var} }}}}

      - uses: {gcloud}

      - name: Shift traffic to previous revision
        env:
          PROJECT: {project}
          SERVICE: ${{{{ inputs.service }}}}
          REVISION: ${{{{ inputs.revision }}}}
        run: |
          set -euo pipefail
          extra=()
          if [ -n "$REVISION" ]; then
            extra=(--revision="$REVISION")
          fi
          bash scripts/rollback-cloudrun.sh --project="$PROJECT" --service="$SERVICE" "${{extra[@]}}"
"""


def main() -> None:
    OUT_DEV.parent.mkdir(parents=True, exist_ok=True)
    OUT_DEV.write_text(
        render(
            "Rollback Cloud Run service (Dev)",
            "sujho-dev",
            "GCP_WIF_SERVICE_ACCOUNT_DEV",
        )
    )
    OUT_PREPROD.write_text(
        render(
            "Rollback Cloud Run service (Pre-Prod)",
            "sujho-preprod",
            "GCP_WIF_SERVICE_ACCOUNT_PREPROD",
        )
    )
    OUT_PROD.write_text(
        render(
            "Rollback Cloud Run service (Prod)",
            "sujho-478914",
            "GCP_WIF_SERVICE_ACCOUNT_PROD",
        )
    )
    print(f"wrote {OUT_DEV.relative_to(HERE)}")
    print(f"wrote {OUT_PREPROD.relative_to(HERE)}")
    print(f"wrote {OUT_PROD.relative_to(HERE)}")


if __name__ == "__main__":
    main()
