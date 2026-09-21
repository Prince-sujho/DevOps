#!/usr/bin/env python3
"""Pick a Cloud Run rollback revision from describe/list JSON.

Empty --revision must not send traffic to a newer Ready revision that never
had users (the --no-traffic revision that failed verify).

Rules:
  - Serving = the revision with 100% traffic.
  - If any Ready revision is *newer* than serving, refuse. Pass --revision.
  - Otherwise pick the newest Ready revision *older* than serving.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def is_ready(rev: dict[str, Any]) -> bool:
    for cond in rev.get("status", {}).get("conditions", []) or []:
        if cond.get("type") == "Ready":
            return cond.get("status") == "True"
    return False


def serving_revision(service: dict[str, Any]) -> str:
    traffic = service.get("status", {}).get("traffic") or []
    at_100 = [
        t.get("revisionName")
        for t in traffic
        if t.get("revisionName") and int(t.get("percent") or 0) == 100
    ]
    if len(at_100) != 1:
        names = [t.get("revisionName") for t in traffic]
        raise SystemExit(
            "Refuse: traffic is not 100% on one revision "
            f"(got {names!r}). Pass --revision."
        )
    return str(at_100[0])


def pick_previous(service: dict[str, Any], revisions: list[dict[str, Any]]) -> str:
    current = serving_revision(service)
    ready = [r for r in revisions if is_ready(r) and r.get("metadata", {}).get("name")]
    by_name = {r["metadata"]["name"]: r for r in ready}
    if current not in by_name:
        raise SystemExit(f"Refuse: serving revision {current} is not Ready.")
    cur_ts = by_name[current]["metadata"]["creationTimestamp"]
    newer = [
        r["metadata"]["name"]
        for r in ready
        if r["metadata"]["creationTimestamp"] > cur_ts
    ]
    if newer:
        raise SystemExit(
            "Refuse: Ready revision(s) newer than the one serving users: "
            + ", ".join(newer)
            + ". Those have no traffic (often an unverified --no-traffic deploy). "
            + "Pass --revision NAME if you really mean one of them. "
            + "Empty rollback will not send users there."
        )
    older = sorted(
        [r for r in ready if r["metadata"]["creationTimestamp"] < cur_ts],
        key=lambda r: r["metadata"]["creationTimestamp"],
        reverse=True,
    )
    if not older:
        raise SystemExit(f"Refuse: no older Ready revision than {current}.")
    return str(older[0]["metadata"]["name"])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(
            "usage: pick_rollback_revision.py SERVICE.json REVISIONS.json",
            file=sys.stderr,
        )
        return 2
    service = json.loads(open(argv[0], encoding="utf-8").read())
    revisions = json.loads(open(argv[1], encoding="utf-8").read())
    if not isinstance(revisions, list):
        print("Refuse: revisions JSON must be a list.", file=sys.stderr)
        return 2
    try:
        print(pick_previous(service, revisions))
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
