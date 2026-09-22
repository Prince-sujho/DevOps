#!/usr/bin/env python3
"""Write the GitHub Action forms for Cloud Run *services*.

Jobs already own cloud-run-*-deploy.yaml. These files are:
  cloud-run-dev-service.yaml     — build and deploy inside sujho-dev
  cloud-run-preprod-service.yaml — build in sujho-dev, deploy to sujho-preprod
  cloud-run-prod-service.yaml    — deploy-only to sujho-478914

Pass _COMMIT_SHA / _SHORT_SHA. Do not use Cloud Build trigger builtins.
"""
from __future__ import annotations

import json
from pathlib import Path

import workflow_common as wc

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "catalog.json").read_text())
PINS = json.loads((HERE.parent / "action-pins.json").read_text())["pins"]
OUT_DEV = HERE / "workflows" / "cloud-run-dev-service.yaml"
OUT_PREPROD = HERE / "workflows" / "cloud-run-preprod-service.yaml"
OUT_PROD = HERE / "workflows" / "cloud-run-prod-service.yaml"


def ordered_service_ids() -> list[str]:
    ids = [s["id"] for s in CATALOG["services"]]
    pilot = CATALOG["pilot"]
    return [pilot] + [i for i in ids if i != pilot]


def image_case() -> str:
    lines = ["          case \"$SERVICE\" in"]
    for svc in CATALOG["services"]:
        lines.append(f"            {svc['id']}) IMAGE={svc['image']} ;;")
    lines.append("            *) echo \"unknown service $SERVICE\"; exit 1 ;;")
    lines.append("          esac")
    return "\n".join(lines)


def render(
    name: str,
    target: str,
    sa_var: str,
    build_project: str,
    config_suffix: str,
    pin_digest: str,
    commit_help: str,
) -> str:
    opts = "\n".join(f"          - {i}" for i in ordered_service_ids())
    checkout = wc.pin(PINS, "actions/checkout")
    auth = wc.pin(PINS, "google-github-actions/auth")
    gcloud = wc.pin(PINS, "google-github-actions/setup-gcloud")
    images = image_case()
    return f"""name: {name}

# Manual only. Merge to main does not run this.
# Opening this file IS choosing the environment. Service dropdown only.

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
      commit:
        description: {commit_help}
        required: false
        type: string
        default: ""

concurrency:
  group: cloudrun-{target}-${{{{ inputs.service }}}}
  cancel-in-progress: false

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
{wc.MAIN_ONLY_STEP}
      - uses: {checkout}
        with:
          ref: ${{{{ inputs.commit || github.sha }}}}

      - uses: {auth}
        with:
          workload_identity_provider: ${{{{ vars.GCP_WIF_PROVIDER }}}}
          service_account: ${{{{ vars.{sa_var} }}}}

      - uses: {gcloud}

      - name: Start Cloud Build for this service
        env:
          SERVICE: ${{{{ inputs.service }}}}
          BUILD_PROJECT: {build_project}
          TARGET_PROJECT: {target}
          REGISTRY: {CATALOG["registry"]}
          PIN_DIGEST: "{pin_digest}"
          SHA: ${{{{ inputs.commit || github.sha }}}}
        run: |
          set -euo pipefail
          SHORT="$(printf '%s' "$SHA" | cut -c1-7)"
{images}
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
            --config="ci/${{SERVICE}}-{config_suffix}.yaml" \\
            --substitutions=_TARGET_PROJECT="$TARGET_PROJECT",_COMMIT_SHA="$SHA",_SHORT_SHA="$SHORT"$extra
"""


def render_dev() -> str:
    return render(
        "Deploy Cloud Run service (Dev)",
        "sujho-dev",
        "GCP_WIF_SERVICE_ACCOUNT_DEV",
        "sujho-dev",
        "build-deploy",
        "0",
        "Git commit to deploy (empty = this run's github.sha). Dev only. Does not stamp preprod-approved.",
    )


def render_preprod() -> str:
    return render(
        "Deploy Cloud Run service (Pre-Prod)",
        "sujho-preprod",
        "GCP_WIF_SERVICE_ACCOUNT_PREPROD",
        "sujho-dev",
        "build-deploy",
        "0",
        "Git commit to deploy (empty = this run's github.sha). Prod must be the commit tested on Pre-Prod.",
    )


def render_prod() -> str:
    return render(
        "Deploy Cloud Run service (Prod)",
        "sujho-478914",
        "GCP_WIF_SERVICE_ACCOUNT_PROD",
        "sujho-478914",
        "deploy-only",
        "1",
        "Git commit to deploy (empty = this run's github.sha). Prod must be the commit tested on Pre-Prod.",
    )


def main() -> None:
    OUT_DEV.parent.mkdir(parents=True, exist_ok=True)
    OUT_DEV.write_text(render_dev())
    OUT_PREPROD.write_text(render_preprod())
    OUT_PROD.write_text(render_prod())
    print(f"wrote {OUT_DEV.relative_to(HERE)}")
    print(f"wrote {OUT_PREPROD.relative_to(HERE)}")
    print(f"wrote {OUT_PROD.relative_to(HERE)}")


if __name__ == "__main__":
    main()
