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


def tagged_url(service: str, project: str, region: str, tag: str) -> str:
    out = run(
        [
            "gcloud", "run", "services", "describe", service,
            f"--project={project}", f"--region={region}",
            "--format=json",
        ]
    )
    data = json.loads(out)
    for t in data.get("status", {}).get("traffic", []) or []:
        if t.get("tag") == tag and t.get("url"):
            return str(t["url"])
    raise SystemExit(f"refuse: no traffic entry tagged {tag!r} on {service}")


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


def check_via_revision(service: str, project: str, region: str, tag: str, expect_sha: str) -> bool:
    out = run(
        [
            "gcloud", "run", "revisions", "list",
            f"--service={service}", f"--project={project}", f"--region={region}",
            "--format=json",
        ]
    )
    revisions = json.loads(out)
    for rev in revisions:
        containers = rev.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for c in containers:
            env = {e.get("name"): e.get("value") for e in c.get("env", []) or []}
            if env.get("RELEASE_COMMIT_SHA", "").startswith(expect_sha[:7]):
                return True
    return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--service", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--region", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--expect-sha", required=True)
    p.add_argument("--method", choices=["health", "revision"], default="health")
    p.add_argument("--attempts", type=int, default=15)
    p.add_argument("--delay-seconds", type=int, default=10)
    args = p.parse_args()

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
