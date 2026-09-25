#!/usr/bin/env python3
"""Pick a rollback revision: newest served=true, older than the one serving.
Ready isn't enough — a revision can start and still fail verify before taking traffic."""
from __future__ import annotations

import json
import sys
from typing import Any


def is_served(rev: dict[str, Any]) -> bool:
    labels = rev.get("metadata", {}).get("labels", {}) or {}
    return labels.get("served") == "true"


def serving_revision(service: dict[str, Any]) -> str:
    traffic = service.get("status", {}).get("traffic") or []
    at_100 = [
        t.get("revisionName")
        for t in traffic
        if t.get("revisionName") and int(t.get("percent") or 0) == 100
    ]
    if len(at_100) != 1:
        names = [t.get("revisionName") for t in traffic]
        raise SystemExit(f"refuse: traffic split across revisions {names!r}, pass --revision")
    return str(at_100[0])


def pick_previous(service: dict[str, Any], revisions: list[dict[str, Any]]) -> str:
    current = serving_revision(service)
    served = [r for r in revisions if is_served(r) and r.get("metadata", {}).get("name")]
    by_name = {r["metadata"]["name"]: r for r in served}
    if current not in by_name:
        raise SystemExit(f"refuse: serving revision {current} has no served=true label")
    cur_ts = by_name[current]["metadata"]["creationTimestamp"]
    older = sorted(
        [r for r in served if r["metadata"]["creationTimestamp"] < cur_ts],
        key=lambda r: r["metadata"]["creationTimestamp"],
        reverse=True,
    )
    if not older:
        raise SystemExit(f"refuse: no older served=true revision than {current}")
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
        print("refuse: revisions JSON must be a list", file=sys.stderr)
        return 2
    try:
        print(pick_previous(service, revisions))
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
