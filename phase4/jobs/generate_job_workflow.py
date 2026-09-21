#!/usr/bin/env python3
"""Write the two GitHub Action forms from catalog.jobs.json.

Two files = which environment (no env/mode dropdown):
  cloud-run-preprod-deploy.yaml — Pre-Prod; build in sujho-dev, deploy to preprod
  cloud-run-prod-deploy.yaml    — Prod; deploy-only (same image, refuse rebuild)

gcloud builds submit --no-source does not fill COMMIT_SHA / SHORT_SHA.
The forms pass _COMMIT_SHA / _SHORT_SHA. Pre-Prod builds run in sujho-dev
so Kaniko uses the SA that can write the registry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import workflow_common as wc  # noqa: E402
CATALOG = json.loads((HERE / "catalog.jobs.json").read_text())
PINS = json.loads((HERE.parent.parent / "action-pins.json").read_text())["pins"]
OUT_PREPROD = HERE / "workflows" / "cloud-run-preprod-deploy.yaml"
OUT_PROD = HERE / "workflows" / "cloud-run-prod-deploy.yaml"
OLD_SINGLE = HERE / "workflows" / "deploy-cloudrun-job.yml"


def uses(name: str) -> str:
    return wc.pin(PINS, name)


_INPUTS = """    inputs:
      job:
        description: Cloud Run job (one job per run)
        required: true
        type: choice
        default: __PILOT__
        options:
__JOB_OPTIONS__
      commit:
        description: Git commit to deploy (empty = this run's github.sha). Prod must be the commit tested on Pre-Prod.
        required: false
        type: string
        default: ""
      entry_id:
        description: Required later to execute ingest/remove. Ignored for sessions.
        required: false
        type: string
        default: ""
      execute:
        description: Run the job once after a successful deploy
        type: boolean
        default: false
"""

_AUTH_STEPS = f"""{wc.MAIN_ONLY_STEP}      - uses: {uses("actions/checkout")}
        with:
          ref: ${{{{ inputs.commit || github.sha }}}}

      - uses: {uses("google-github-actions/auth")}
        with:
          workload_identity_provider: ${{{{ vars.GCP_WIF_PROVIDER }}}}
          service_account: ${{{{ vars.__WIF_SA__ }}}}

      - uses: {uses("google-github-actions/setup-gcloud")}
"""

_CONCURRENCY = """
concurrency:
  group: cloudrun-job-__TARGET__-${{ inputs.job }}
  cancel-in-progress: false
"""

_SUBMIT_AND_EXECUTE = """      - name: Start Cloud Build for this job
        env:
          JOB_ID: ${{ inputs.job }}
          BUILD_PROJECT: __BUILD_PROJECT__
          TARGET_PROJECT: __TARGET__
          CONFIG: __CONFIG__
          ENTRY_ID: ${{ inputs.entry_id }}
          REGISTRY: __REGISTRY__
          IMAGE: __IMAGE__
          PIN_DIGEST: "__PIN_DIGEST__"
          SHA: ${{ inputs.commit || github.sha }}
        run: |
          set -euo pipefail
          SHORT="$(printf '%s' "$SHA" | cut -c1-7)"
          extra=""
          if [ "$PIN_DIGEST" = "1" ]; then
            DIGEST="$(gcloud artifacts docker images describe \\
              "$REGISTRY/$IMAGE:sha-$SHORT" --format='value(image_summary.digest)')"
            APPROVED="$(gcloud artifacts docker images describe \\
              "$REGISTRY/$IMAGE:preprod-approved" --format='value(image_summary.digest)')"
            if [ -z "$DIGEST" ] || [ "$DIGEST" != "$APPROVED" ]; then
              echo "Refuse: sha-$SHORT is not preprod-approved (TOCTOU / not stamped)."
              exit 1
            fi
            extra=",_IMAGE_DIGEST=$DIGEST"
          fi
          gcloud builds submit --no-source \\
            --project="$BUILD_PROJECT" \\
            --region=asia-south1 \\
            --config="$CONFIG" \\
            --substitutions=_JOB_ID="$JOB_ID",_TARGET_PROJECT="$TARGET_PROJECT",_ENTRY_ID="$ENTRY_ID",_COMMIT_SHA="$SHA",_SHORT_SHA="$SHORT"$extra

      - name: Execute job once
        if: ${{ inputs.execute }}
        env:
          JOB_ID: ${{ inputs.job }}
          PROJECT: __TARGET__
          ENTRY_ID: ${{ inputs.entry_id }}
        run: |
          set -euo pipefail
          python3 jobs/scripts/lookup_job.py --id "$JOB_ID" > /tmp/job.env
          # shellcheck disable=SC1091
          source /tmp/job.env
          if [ "$NEEDS_ENTRY_ID" = "1" ]; then
            if [ -z "$ENTRY_ID" ]; then
              echo "ingest/remove execute needs entry_id"
              exit 1
            fi
            gcloud run jobs execute "$CLOUD_RUN_JOB" \\
              --project="$PROJECT" --region=asia-south1 \\
              --update-args="$ARGS,$ENTRY_ID" --wait
          else
            gcloud run jobs execute "$CLOUD_RUN_JOB" \\
              --project="$PROJECT" --region=asia-south1 --wait
          fi
"""

PREPROD_TEMPLATE = (
    """name: Deploy Cloud Run job (Pre-Prod)

# Manual only. Merge to main does not run this.
# Opening this file IS choosing Pre-Prod. Job dropdown only (no env/mode).
# Cloud Build runs in sujho-dev (registry writer). Deploy target is sujho-preprod.

on:
  workflow_dispatch:
"""
    + _INPUTS
    + _CONCURRENCY.replace("__TARGET__", "sujho-preprod")
    + """
permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    name: deploy-cloudrun-job-preprod
    runs-on: ubuntu-latest
    steps:
"""
    + _AUTH_STEPS.replace("__WIF_SA__", "GCP_WIF_SERVICE_ACCOUNT_PREPROD")
    + _SUBMIT_AND_EXECUTE.replace("__BUILD_PROJECT__", "sujho-dev")
    .replace("__TARGET__", "sujho-preprod")
    .replace("__CONFIG__", "ci/jobs/job-build-deploy.yaml")
    .replace("__REGISTRY__", CATALOG["registry"])
    .replace("__IMAGE__", CATALOG["image_groups"]["knowledge-store"]["image"])
    .replace("__PIN_DIGEST__", "0")
)

PROD_TEMPLATE = (
    """name: Deploy Cloud Run job (Prod)

# Manual only. Merge to main does not run this.
# Opening this file IS choosing Prod. Job dropdown only (no env/mode).
# Deploy-only: this file never builds. Same image as Pre-Prod (preprod-approved).

on:
  workflow_dispatch:
"""
    + _INPUTS
    + _CONCURRENCY.replace("__TARGET__", "sujho-478914")
    + """
permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    name: deploy-cloudrun-job-prod
    runs-on: ubuntu-latest
    steps:
"""
    + _AUTH_STEPS.replace("__WIF_SA__", "GCP_WIF_SERVICE_ACCOUNT_PROD")
    + _SUBMIT_AND_EXECUTE.replace("__BUILD_PROJECT__", "sujho-478914")
    .replace("__TARGET__", "sujho-478914")
    .replace("__CONFIG__", "ci/jobs/job-deploy-only.yaml")
    .replace("__REGISTRY__", CATALOG["registry"])
    .replace("__IMAGE__", CATALOG["image_groups"]["knowledge-store"]["image"])
    .replace("__PIN_DIGEST__", "1")
)


def ordered_job_ids() -> list[str]:
    ids = [j["id"] for j in CATALOG["jobs"]]
    pilot = CATALOG["pilot"]
    if pilot not in ids:
        raise SystemExit(f"pilot {pilot} missing from jobs")
    return [pilot] + [i for i in ids if i != pilot]


def _fill(template: str) -> str:
    job_opts = "\n".join(f"          - {i}" for i in ordered_job_ids())
    return template.replace("__PILOT__", CATALOG["pilot"]).replace(
        "__JOB_OPTIONS__", job_opts
    )


def render_preprod() -> str:
    return _fill(PREPROD_TEMPLATE)


def render_prod() -> str:
    return _fill(PROD_TEMPLATE)


def main() -> None:
    OUT_PREPROD.parent.mkdir(parents=True, exist_ok=True)
    OUT_PREPROD.write_text(render_preprod())
    OUT_PROD.write_text(render_prod())
    if OLD_SINGLE.is_file():
        OLD_SINGLE.unlink()
        print(f"removed {OLD_SINGLE.relative_to(HERE)}")
    print(f"wrote {OUT_PREPROD.relative_to(HERE)}")
    print(f"wrote {OUT_PROD.relative_to(HERE)}")


if __name__ == "__main__":
    main()
