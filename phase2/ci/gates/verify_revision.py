#!/usr/bin/env python3
"""Poll a --no-traffic revision until it's confirmed healthy before shifting
traffic.

The check that can genuinely fail is --expect-digest: the image the revision
is actually running, read back from Cloud Run, must be the exact digest the
caller built or resolved. That catches a tag that moved, a stale revision
answering on the tag, and a deploy of the wrong image.

--expect-sha is weaker on purpose and is not proof by itself: the same deploy
set RELEASE_COMMIT_SHA, so it only confirms the revision behind this tag is
the one this build created rather than an older one.

health: hits /health then /version on the tagged revision's private URL for
liveness, then cross-checks digest and sha against the revision spec via
gcloud — never trusts the app's own self-reported commit_sha, which an
untouched old revision could echo back unchanged.
revision: reads the image and RELEASE_COMMIT_SHA off the revision spec
(admin has no public HTTP path).

Usage:
    verify_revision.py --service=S --project=P --region=R --tag=T \\
        --expect-sha=SHA --expect-digest=sha256:... \\
        --method=health|revision [--attempts=N] [--delay-seconds=N]
    verify_revision.py --service=S --project=P --region=R --tag=T \\
        --print-revision [--allow-missing]

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


def tagged_entry(
    service: str,
    project: str,
    region: str,
    tag: str,
    allow_missing: bool = False,
) -> dict | None:
    """Return the traffic entry (revisionName, url, ...) carrying this tag.

    Args:
        service: the Cloud Run service name.
        project: the GCP project id.
        region: the Cloud Run region.
        tag: the traffic tag to look up.
        allow_missing: return None instead of exiting when no entry has the
            tag — used to ask "is there an lkg tag yet?" on a first deploy.
    Returns:
        The matching traffic entry, or None when allow_missing and there is
        no such tag.
    Raises:
        SystemExit: no traffic entry has this tag and allow_missing is False.
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
    if allow_missing:
        return None
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
    entry = tagged_entry(service, project, region, tag) or {}
    if not entry.get("url"):
        raise SystemExit(
            f"refuse: traffic entry tagged {tag!r} on {service} has no url"
        )
    return str(entry["url"])


def check_via_http(
    url: str,
    expect_sha: str,
    expect_digest: str,
    service: str,
    project: str,
    region: str,
    tag: str,
) -> bool:
    """True if /health and /version both respond, and gcloud confirms the
    revision behind this tag runs expect_digest at expect_sha.

    The app's own /version body is read only as a liveness signal (did it
    respond at all) — the image and sha comparisons always go through gcloud,
    so an old revision cannot pass by echoing back a stale self-reported value.

    Args:
        url: the revision's private base URL.
        expect_sha: the commit sha the revision spec must carry.
        expect_digest: the image digest the revision must actually run.
        service: the Cloud Run service name.
        project: the GCP project id.
        region: the Cloud Run region.
        tag: the traffic tag naming the revision to check.
    Returns:
        Whether the revision is live and gcloud confirms both values.
    Raises:
        SystemExit: no traffic entry on the service has this tag.
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
    except (urllib.error.URLError, TimeoutError):
        return False
    return check_via_revision(
        service, project, region, tag, expect_sha, expect_digest
    )


def revision_is_ready_at(
    revision: dict, expect_sha: str, expect_digest: str = ""
) -> bool:
    """The one revision is Ready, runs the expected image, and carries the
    expected commit — no other revision counts.

    Args:
        revision: the revision's `gcloud run revisions describe --format=json`
            output.
        expect_sha: the RELEASE_COMMIT_SHA the revision's env must carry.
        expect_digest: the image digest the revision must run, e.g.
            "sha256:...". Empty skips the image check.
    Returns:
        Whether the revision is Ready, running expect_digest, and matching
        expect_sha exactly.
    Raises:
        None.
    """
    conditions = revision.get("status", {}).get("conditions", []) or []
    ready = any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in conditions
    )
    if not ready:
        return False
    for container in revision.get("spec", {}).get("containers", []) or []:
        env = {
            e.get("name"): e.get("value")
            for e in container.get("env", []) or []
        }
        image = str(container.get("image") or "")
        digest_ok = not expect_digest or image.endswith(f"@{expect_digest}")
        if digest_ok and env.get("RELEASE_COMMIT_SHA", "") == expect_sha:
            return True
    return False


def check_via_revision(
    service: str,
    project: str,
    region: str,
    tag: str,
    expect_sha: str,
    expect_digest: str = "",
) -> bool:
    """True if the one revision behind this tag (not any other) is Ready,
    running expect_digest, at expect_sha.

    Args:
        service: the Cloud Run service name.
        project: the GCP project id.
        region: the Cloud Run region.
        tag: the traffic tag naming the revision to check.
        expect_sha: the RELEASE_COMMIT_SHA the revision's env must carry.
        expect_digest: the image digest the revision must run.
    Returns:
        Whether that one revision is Ready and matches both values.
    Raises:
        SystemExit: no traffic entry on the service has this tag.
    """
    entry = tagged_entry(service, project, region, tag) or {}
    name = entry["revisionName"]
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
    return revision_is_ready_at(json.loads(out), expect_sha, expect_digest)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments; --expect-sha and --expect-digest are required
    unless --print-revision is set.

    Args:
        None.
    Returns:
        The parsed CLI namespace.
    Raises:
        SystemExit: an expectation was omitted without --print-revision.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expect-sha", default="")
    parser.add_argument("--expect-digest", default="")
    parser.add_argument(
        "--method", choices=["health", "revision"], default="health"
    )
    parser.add_argument("--attempts", type=int, default=15)
    parser.add_argument("--delay-seconds", type=int, default=10)
    # prints the revision behind --tag; shift-traffic uses it to move traffic
    # to exactly the revision this script verified, and to read the lkg/prev
    # rollback markers
    parser.add_argument("--print-revision", action="store_true")
    # with --print-revision: print nothing and succeed when the tag does not
    # exist (no lkg yet on a service's first deploy)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    if not args.print_revision:
        if not args.expect_sha:
            parser.error("--expect-sha is required unless --print-revision")
        if not args.expect_digest:
            parser.error("--expect-digest is required unless --print-revision")
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
        return check_via_http(
            url,
            args.expect_sha,
            args.expect_digest,
            args.service,
            args.project,
            args.region,
            args.tag,
        )
    return check_via_revision(
        args.service,
        args.project,
        args.region,
        args.tag,
        args.expect_sha,
        args.expect_digest,
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
        entry = tagged_entry(
            args.service,
            args.project,
            args.region,
            args.tag,
            allow_missing=args.allow_missing,
        )
        if entry is not None:
            print(entry["revisionName"])
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
