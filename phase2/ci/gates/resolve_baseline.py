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
    """The container list at the env-var path; jobs nest one level deeper than
    services.

    Args:
        data: `gcloud run services|jobs describe --format=json` output.
        kind: "services" or "jobs" — selects which nesting to read.
    Returns:
        The containers list, or [] if the expected path isn't present.
    Raises:
        None.
    """
    spec = data.get("spec", {}).get("template", {}).get("spec", {})
    if kind == "jobs":
        spec = spec.get("template", {}).get("spec", {})
    return spec.get("containers", [])


def _parse_args() -> argparse.Namespace:
    """Parse the deployed-resource describe arguments.

    Args:
        None.
    Returns:
        The parsed CLI namespace (name/kind/project/region).
    Raises:
        SystemExit: a required argument is missing.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--kind", choices=["services", "jobs"], default="services"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    return parser.parse_args()


def _describe_json(args: argparse.Namespace) -> str | None:
    """Describe the Cloud Run resource, or None when no prior deploy exists.

    Args:
        args: parsed CLI arguments (name/kind/project/region).
    Returns:
        The describe JSON text, or None if gcloud failed.
    Raises:
        None.
    """
    completed = subprocess.run(
        [
            "gcloud",
            "run",
            args.kind,
            "describe",
            args.name,
            f"--project={args.project}",
            f"--region={args.region}",
            "--format=json",
        ],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def _print_release_sha(data: dict, kind: str) -> None:
    """Print RELEASE_COMMIT_SHA from a describe payload, if one is set.

    Args:
        data: `gcloud run describe --format=json` output.
        kind: "services" or "jobs" — selects which nesting to read.
    Returns:
        None.
    Raises:
        None.
    """
    for container in container_path(data, kind):
        for env in container.get("env", []) or []:
            name = env.get("name")
            value = env.get("value")
            if name == "RELEASE_COMMIT_SHA" and value:
                print(value)
                return


def main() -> int:
    """Print the deployed resource's RELEASE_COMMIT_SHA, or nothing if none is
    deployed.

    Args:
        None.
    Returns:
        Always 0.
    Raises:
        None.
    """
    args = _parse_args()
    raw = _describe_json(args)
    if raw is None:
        return 0
    _print_release_sha(json.loads(raw), args.kind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
