#!/usr/bin/env python3
"""Poll a --no-traffic revision until it's confirmed healthy before shifting traffic.
health: hits /health then /version on the tagged revision's private URL.
revision: reads RELEASE_COMMIT_SHA off the revision spec (admin has no public HTTP path).
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
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def tagged_entry(service: str, project: str, region: str, tag: str) -> dict:
    out = run(
        [
            "gcloud", "run", "services", "describe", service,
            f"--project={project}", f"--region={region}",
            "--format=json",
        ]
    )
    data = json.loads(out)
    for t in data.get("status", {}).get("traffic", []) or []:
        if t.get("tag") == tag and t.get("revisionName"):
            return t
    raise SystemExit(f"refuse: no traffic entry tagged {tag!r} on {service}")


def tagged_url(service: str, project: str, region: str, tag: str) -> str:
    entry = tagged_entry(service, project, region, tag)
    if not entry.get("url"):
        raise SystemExit(f"refuse: traffic entry tagged {tag!r} on {service} has no url")
    return str(entry["url"])


def check_via_http(url: str, expect_sha: str) -> bool:
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
    """The one revision is Ready and carries the expected commit — no other revision counts."""
    conditions = revision.get("status", {}).get("conditions", []) or []
    ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
    for c in revision.get("spec", {}).get("containers", []) or []:
        env = {e.get("name"): e.get("value") for e in c.get("env", []) or []}
        if ready and env.get("RELEASE_COMMIT_SHA", "") == expect_sha:
            return True
    return False


def check_via_revision(service: str, project: str, region: str, tag: str, expect_sha: str) -> bool:
    name = tagged_entry(service, project, region, tag)["revisionName"]
    out = run(
        [
            "gcloud", "run", "revisions", "describe", name,
            f"--project={project}", f"--region={region}",
            "--format=json",
        ]
    )
    return revision_is_ready_at(json.loads(out), expect_sha)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--service", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--region", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--expect-sha", default="")
    p.add_argument("--method", choices=["health", "revision"], default="health")
    p.add_argument("--attempts", type=int, default=15)
    p.add_argument("--delay-seconds", type=int, default=10)
    # prints the revision behind --tag; shift-traffic uses it to move traffic
    # to (and label) exactly the revision this script verified
    p.add_argument("--print-revision", action="store_true")
    args = p.parse_args()

    if args.print_revision:
        print(tagged_entry(args.service, args.project, args.region, args.tag)["revisionName"])
        return 0
    if not args.expect_sha:
        p.error("--expect-sha is required unless --print-revision")

    for attempt in range(1, args.attempts + 1):
        ok = False
        if args.method == "health":
            url = tagged_url(args.service, args.project, args.region, args.tag)
            ok = check_via_http(url, args.expect_sha)
        else:
            ok = check_via_revision(args.service, args.project, args.region, args.tag, args.expect_sha)

        if ok:
            print(f"converged ({attempt}/{args.attempts}): {args.service} running {args.expect_sha}")
            return 0

        print(f"attempt {attempt}/{args.attempts}: not converged, retry in {args.delay_seconds}s")
        time.sleep(args.delay_seconds)

    print(
        f"refuse: {args.service} never converged on {args.expect_sha} after {args.attempts} attempts",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
