#!/usr/bin/env python3
"""Poll a --no-traffic revision until it's confirmed healthy before shifting
traffic.

health: hits /health then /version on the tagged revision's private URL.
revision: reads RELEASE_COMMIT_SHA off the revision spec (admin has no public
HTTP path).

Usage:
    verify_revision.py --service=S --project=P --region=R --tag=T \\
        --expect-sha=SHA --method=health|revision \\
        [--attempts=N] [--delay-seconds=N]
    verify_revision.py --service=S --project=P --region=R --tag=T \\
        --print-revision

Exit codes: 0 converged (or --print-revision succeeded), 1 never converged.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


def run(cmd: list[str]) -> str:
    """Run one command, raising if it fails; return its stripped stdout.

    Args:
        cmd: the argv to run.
    Returns:
        The command's stripped stdout.
    Raises:
        subprocess.CalledProcessError: cmd exited nonzero.
    """
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True
    ).stdout.strip()


def tagged_entry(service: str, project: str, region: str, tag: str) -> dict:
    """Return the traffic entry (revisionName, url, ...) carrying this tag.

    Args:
        service: the Cloud Run service name.
        project: the GCP project id.
        region: the Cloud Run region.
        tag: the traffic tag to look up.
    Returns:
        The matching traffic entry.
    Raises:
        SystemExit: no traffic entry on the service has this tag.
    """
    out = run(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service,
            f"--project={project}",
            f"--region={region}",
            "--format=json",
        ]
    )
    data = json.loads(out)
    for entry in data.get("status", {}).get("traffic", []) or []:
        if entry.get("tag") == tag and entry.get("revisionName"):
            return entry
    raise SystemExit(f"refuse: no traffic entry tagged {tag!r} on {service}")


def tagged_url(service: str, project: str, region: str, tag: str) -> str:
    """Return the private URL for the revision behind this tag.

    Args:
        service: the Cloud Run service name.
        project: the GCP project id.
        region: the Cloud Run region.
        tag: the traffic tag to look up.
    Returns:
        The revision's private URL.
    Raises:
        SystemExit: the tag exists but carries no url.
    """
    entry = tagged_entry(service, project, region, tag)
    if not entry.get("url"):
        raise SystemExit(
            f"refuse: traffic entry tagged {tag!r} on {service} has no url"
        )
    return str(entry["url"])


def check_via_http(url: str, expect_sha: str) -> bool:
    """True if /health and /version both respond and /version reports
    expect_sha.

    Args:
        url: the revision's private base URL.
        expect_sha: the commit sha /version must report (7+ char prefix match).
    Returns:
        Whether the revision looks healthy and up to date.
    Raises:
        None.
    """
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=10) as resp:
            if resp.status != 200:
                return False
    except (urllib.error.URLError, TimeoutError):
        return False
    try:
        with urllib.request.urlopen(f"{url}/version", timeout=10) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    return str(body.get("commit_sha", "")).startswith(expect_sha[:7])


def revision_is_ready_at(revision: dict, expect_sha: str) -> bool:
    """The one revision is Ready and carries the expected commit — no other
    revision counts.

    Args:
        revision: the revision's `gcloud run revisions describe --format=json`
            output.
        expect_sha: the RELEASE_COMMIT_SHA the revision's env must carry.
    Returns:
        Whether the revision is Ready and its env matches expect_sha exactly.
    Raises:
        None.
    """
    conditions = revision.get("status", {}).get("conditions", []) or []
    ready = any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in conditions
    )
    for container in revision.get("spec", {}).get("containers", []) or []:
        env = {
            e.get("name"): e.get("value")
            for e in container.get("env", []) or []
        }
        if ready and env.get("RELEASE_COMMIT_SHA", "") == expect_sha:
            return True
    return False


def check_via_revision(
    service: str, project: str, region: str, tag: str, expect_sha: str
) -> bool:
    """True if the one revision behind this tag (not any other) is Ready at
    expect_sha.

    Args:
        service: the Cloud Run service name.
        project: the GCP project id.
        region: the Cloud Run region.
        tag: the traffic tag naming the revision to check.
        expect_sha: the RELEASE_COMMIT_SHA the revision's env must carry.
    Returns:
        Whether that one revision is Ready and matches expect_sha.
    Raises:
        SystemExit: no traffic entry on the service has this tag.
    """
    name = tagged_entry(service, project, region, tag)["revisionName"]
    out = run(
        [
            "gcloud",
            "run",
            "revisions",
            "describe",
            name,
            f"--project={project}",
            f"--region={region}",
            "--format=json",
        ]
    )
    return revision_is_ready_at(json.loads(out), expect_sha)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments; --expect-sha is required unless --print-revision is
    set.

    Args:
        None.
    Returns:
        The parsed CLI namespace.
    Raises:
        SystemExit: --expect-sha was omitted and --print-revision was not set.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expect-sha", default="")
    parser.add_argument(
        "--method", choices=["health", "revision"], default="health"
    )
    parser.add_argument("--attempts", type=int, default=15)
    parser.add_argument("--delay-seconds", type=int, default=10)
    # prints the revision behind --tag; shift-traffic uses it to move traffic
    # to (and label) exactly the revision this script verified
    parser.add_argument("--print-revision", action="store_true")
    args = parser.parse_args()
    if not args.print_revision and not args.expect_sha:
        parser.error("--expect-sha is required unless --print-revision")
    return args


def _check_once(args: argparse.Namespace) -> bool:
    """Run the selected health or revision check one time.

    Args:
        args: parsed CLI arguments (service/project/region/tag/method/
            expect_sha).
    Returns:
        True when this attempt converged.
    Raises:
        SystemExit: no traffic entry on the service has the given tag.
    """
    if args.method == "health":
        url = tagged_url(args.service, args.project, args.region, args.tag)
        return check_via_http(url, args.expect_sha)
    return check_via_revision(
        args.service,
        args.project,
        args.region,
        args.tag,
        args.expect_sha,
    )


def poll_until_converged(args: argparse.Namespace) -> bool:
    """Retry the chosen check up to --attempts times; return whether it ever
    passed.

    Args:
        args: parsed CLI arguments (service/project/region/tag/method/
            expect_sha/attempts/delay_seconds).
    Returns:
        True the first time the check passes; False if every attempt failed.
    Raises:
        SystemExit: no traffic entry on the service has the given tag.
    """
    for attempt in range(1, args.attempts + 1):
        ok = _check_once(args)
        if ok:
            print(
                f"converged ({attempt}/{args.attempts}): "
                f"{args.service} running {args.expect_sha}"
            )
            return True
        print(
            f"attempt {attempt}/{args.attempts}: not converged, retry in "
            f"{args.delay_seconds}s"
        )
        time.sleep(args.delay_seconds)
    return False


def main() -> int:
    """Entry point.

    --print-revision short-circuits; otherwise poll until converged or out
    of attempts.

    Args:
        None.
    Returns:
        0 when --print-revision printed the revision name or the check
        converged, 1 when every poll attempt failed.
    Raises:
        None.
    """
    args = parse_args()
    if args.print_revision:
        print(
            tagged_entry(args.service, args.project, args.region, args.tag)[
                "revisionName"
            ]
        )
        return 0
    if poll_until_converged(args):
        return 0
    print(
        f"refuse: {args.service} never converged on {args.expect_sha} "
        f"after {args.attempts} attempts",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
