#!/usr/bin/env python3
"""Pick a rollback revision: newest served=true, older than the one serving.
Ready isn't enough — a revision can start and still fail verify before taking
traffic.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def is_served(rev: dict[str, Any]) -> bool:
    """True if this revision carries the served=true label.

    Args:
        rev: a Cloud Run revision dict, including its labels.
    Returns:
        True when the revision label served equals "true".
    Raises:
        None.
    """
    labels = rev.get("metadata", {}).get("labels", {}) or {}
    return labels.get("served") == "true"


def serving_revision(service: dict[str, Any]) -> str:
    """The one revision name currently at 100% traffic; refuses on a traffic
    split.

    Args:
        service: `gcloud run services describe --format=json` output.
    Returns:
        The revision name at 100% traffic.
    Raises:
        SystemExit: traffic is split across more than one revision.
    """
    traffic = service.get("status", {}).get("traffic") or []
    at_100 = [
        t.get("revisionName")
        for t in traffic
        if t.get("revisionName") and int(t.get("percent") or 0) == 100
    ]
    if len(at_100) != 1:
        names = [t.get("revisionName") for t in traffic]
        raise SystemExit(
            f"refuse: traffic split across revisions {names!r}, pass --revision"
        )
    return str(at_100[0])


def _served_revisions(
    revisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The revisions that carry served=true and have a name.

    Args:
        revisions: `gcloud run revisions list --format=json` output.
    Returns:
        Served revisions that have metadata.name.
    Raises:
        None.
    """
    return [
        rev
        for rev in revisions
        if is_served(rev) and rev.get("metadata", {}).get("name")
    ]


def _newest_older(
    served: list[dict[str, Any]], current_ts: str
) -> dict[str, Any] | None:
    """The newest served revision created before current_ts.

    Args:
        served: served revisions, each with metadata.creationTimestamp.
        current_ts: creation timestamp of the revision currently serving.
    Returns:
        The newest older revision, or None if there is no older one.
    Raises:
        None.
    """
    older = [
        rev
        for rev in served
        if rev["metadata"]["creationTimestamp"] < current_ts
    ]
    older.sort(
        key=lambda rev: rev["metadata"]["creationTimestamp"], reverse=True
    )
    return older[0] if older else None


def pick_previous(
    service: dict[str, Any], revisions: list[dict[str, Any]]
) -> str:
    """The newest served=true revision older than the one currently serving.

    Args:
        service: `gcloud run services describe --format=json` output.
        revisions: `gcloud run revisions list --format=json` output.
    Returns:
        The rollback target's revision name.
    Raises:
        SystemExit: traffic is split, the serving revision has no served=true
            label, or no older served=true revision exists.
    """
    current = serving_revision(service)
    served = _served_revisions(revisions)
    by_name = {rev["metadata"]["name"]: rev for rev in served}
    if current not in by_name:
        raise SystemExit(
            f"refuse: serving revision {current} has no served=true label"
        )
    cur_ts = by_name[current]["metadata"]["creationTimestamp"]
    chosen = _newest_older(served, cur_ts)
    if chosen is None:
        raise SystemExit(
            f"refuse: no older served=true revision than {current}"
        )
    return str(chosen["metadata"]["name"])


def main(argv: list[str] | None = None) -> int:
    """Read service + revisions JSON from two file args, print the rollback
    pick.

    Args:
        argv: CLI arguments (SERVICE.json REVISIONS.json), or None for sys.argv.
    Returns:
        0 printed a pick; 1 pick_previous refused; 2 bad usage/input shape.
    Raises:
        None — refusals are caught and reported via the return code.
    """
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
