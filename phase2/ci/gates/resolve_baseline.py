#!/usr/bin/env python3
"""Read RELEASE_COMMIT_SHA off the currently-deployed resource's own
container env — the same field verify_revision.py's --method=revision
already reads for services, not a --set-annotations value nobody has
confirmed round-trips correctly. No prior deploy prints nothing, exits 0.

The --kind=jobs container path (spec.template.spec.template.spec.containers)
is the Cloud Run Jobs v1 execution-template shape — unverified against a
real `gcloud run jobs describe` output. If this ever prints nothing when a
prior deploy clearly exists, check this path first before anything else.
"""
from __future__ import annotations

import argparse
import json
import subprocess


def container_path(data: dict, kind: str) -> list:
    spec = data.get("spec", {}).get("template", {}).get("spec", {})
    if kind == "jobs":
        spec = spec.get("template", {}).get("spec", {})
    return spec.get("containers", [])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--kind", choices=["services", "jobs"], default="services")
    p.add_argument("--project", required=True)
    p.add_argument("--region", required=True)
    args = p.parse_args()

    completed = subprocess.run(
        [
            "gcloud", "run", args.kind, "describe", args.name,
            f"--project={args.project}", f"--region={args.region}",
            "--format=json",
        ],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        return 0  # no prior deploy, nothing to print

    data = json.loads(completed.stdout)
    for c in container_path(data, args.kind):
        for e in c.get("env", []) or []:
            if e.get("name") == "RELEASE_COMMIT_SHA" and e.get("value"):
                print(e["value"])
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
