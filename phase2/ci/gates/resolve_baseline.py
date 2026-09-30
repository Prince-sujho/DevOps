#!/usr/bin/env python3
"""Read RELEASE_COMMIT_SHA off the currently-deployed resource's own
container env — the same field verify_revision.py's --method=revision
already reads for services, not a --set-annotations value nobody has
confirmed round-trips correctly. No such resource prints nothing and exits
0. Any other failure — permission, network, a live resource with no
RELEASE_COMMIT_SHA — exits 1, so the build cannot treat it as a first deploy.

For services: `gcloud run services describe` reflects the latest deployed
*template*, not what's actually serving — a `--no-traffic` candidate from a
failed prior build updates it without ever taking traffic. So this resolves
the revision at 100% traffic first, then describes that revision directly.

The --kind=jobs container path (spec.template.spec.template.spec.containers)
is the Cloud Run Jobs v1 execution-template shape — unverified against a
real `gcloud run jobs describe` output. Jobs have no traffic/revision split
(one execution template, not a served-vs-candidate distinction), so this
gap doesn't apply there. If this ever prints nothing when a prior deploy
clearly exists, check this path first before anything else.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def container_path(data: dict, kind: str) -> list:
    """The job container list at its env-var path, one level deeper than a
    plain template.

    Args:
        data: `gcloud run jobs describe --format=json` output.
        kind: "jobs" — the only kind this reads (services use
            revision_containers instead).
    Returns:
        The containers list, or [] if the expected path isn't present.
    Raises:
        None.
    """
    spec = data.get("spec", {}).get("template", {}).get("spec", {})
    if kind == "jobs":
        spec = spec.get("template", {}).get("spec", {})
    return spec.get("containers", [])


def revision_containers(data: dict) -> list:
    """Containers straight off a `gcloud run revisions describe` payload —
    revisions have no template wrapper, unlike a service's own spec.

    Args:
        data: `gcloud run revisions describe --format=json` output.
    Returns:
        The containers list, or [] if the expected path isn't present.
    Raises:
        None.
    """
    return data.get("spec", {}).get("containers", [])


def serving_revision_name(service_data: dict) -> str | None:
    """The one revision at 100% traffic, or None if there isn't a clean one
    (no traffic at all, or a split — never guess a baseline from either).

    Args:
        service_data: `gcloud run services describe --format=json` output.
    Returns:
        The revision name at 100% traffic, or None.
    Raises:
        None.
    """
    traffic = service_data.get("status", {}).get("traffic") or []
    at_100 = [
        t.get("revisionName")
        for t in traffic
        if t.get("revisionName") and int(t.get("percent") or 0) == 100
    ]
    return at_100[0] if len(at_100) == 1 else None


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


# Spelled out per resource rather than pasted together from a variable, so
# that a reader (and phase2/validate.py) can see every gcloud command this
# gate can run without working out what the variable holds.
DESCRIBE = {
    "services": ["gcloud", "run", "services", "describe"],
    "jobs": ["gcloud", "run", "jobs", "describe"],
    "revisions": ["gcloud", "run", "revisions", "describe"],
}


class LookupError(RuntimeError):
    """gcloud failed for a reason other than the resource not existing."""


def _describe_json(
    resource: str, name: str, project: str, region: str
) -> str | None:
    """Describe one Cloud Run resource, or None when it does not exist.

    Args:
        resource: which DESCRIBE command to run.
        name: the resource's name.
        project: the GCP project id.
        region: the Cloud Run region.
    Returns:
        The describe JSON text, or None when gcloud reports NOT_FOUND.
    Raises:
        LookupError: gcloud failed for any other reason, including not being
            installed.
    """
    try:
        completed = subprocess.run(
            [
                *DESCRIBE[resource],
                name,
                f"--project={project}",
                f"--region={region}",
                "--format=json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise LookupError(str(exc)) from exc
    if completed.returncode != 0:
        err = (completed.stderr or "").strip()
        if "NOT_FOUND" in err:
            return None
        raise LookupError(err or f"gcloud exited {completed.returncode}")
    return completed.stdout


def _print_release_sha(containers: list) -> bool:
    """Print RELEASE_COMMIT_SHA from a container list, if one is set.

    Args:
        containers: a describe payload's container list.
    Returns:
        True when a value was printed.
    Raises:
        None.
    """
    for container in containers:
        for env in container.get("env", []) or []:
            name = env.get("name")
            value = env.get("value")
            if name == "RELEASE_COMMIT_SHA" and value:
                print(value)
                return True
    return False


def _services_containers(
    name: str, project: str, region: str
) -> list | None:
    """The serving revision's containers, or None when the service does not
    exist.

    Args:
        name: the Cloud Run service name.
        project: the GCP project id.
        region: the Cloud Run region.
    Returns:
        The serving revision's container list, or None if the service is
        missing.
    Raises:
        LookupError: the service exists but traffic is not on one revision,
            or that revision cannot be read.
    """
    raw = _describe_json("services", name, project, region)
    if raw is None:
        return None
    revision = serving_revision_name(json.loads(raw))
    if revision is None:
        raise LookupError(
            f"{name} exists but traffic is not 100% on one revision"
        )
    raw = _describe_json("revisions", revision, project, region)
    if raw is None:
        raise LookupError(f"serving revision {revision} was not found")
    return revision_containers(json.loads(raw))


def _finish(containers: list, name: str) -> int:
    """Print the live SHA, or fail when the resource exists without one.

    Args:
        containers: the live resource's container list.
        name: the service or job name, for the error.
    Returns:
        0 when a SHA was printed, 1 when the live resource has none.
    Raises:
        None.
    """
    if _print_release_sha(containers):
        return 0
    print(
        f"::error::{name} is live but has no RELEASE_COMMIT_SHA",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    """Print the deployed resource's RELEASE_COMMIT_SHA.

    Args:
        None.
    Returns:
        0 when nothing is deployed or the live SHA was printed, 1 when the
        lookup failed or the live resource has no SHA.
    Raises:
        None.
    """
    args = _parse_args()
    try:
        if args.kind == "services":
            containers = _services_containers(
                args.name, args.project, args.region
            )
            if containers is None:
                return 0
            return _finish(containers, args.name)
        raw = _describe_json("jobs", args.name, args.project, args.region)
        if raw is None:
            return 0
        return _finish(container_path(json.loads(raw), "jobs"), args.name)
    except LookupError as exc:
        print(f"::error::could not read what is live: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
