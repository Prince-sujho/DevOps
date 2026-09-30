#!/usr/bin/env python3
"""Pick a rollback revision from the service's own rollback markers.

Why markers and not labels: a Cloud Run revision's labels are fixed when it
is created, and there is no `gcloud run revisions update` to change them
afterwards — so "this revision took traffic and passed" cannot be recorded on
the revision itself. It is recorded as a traffic tag on the *service*, which
is editable (`gcloud run services update-traffic --update-tags`):

    lkg   the revision serving now, after it passed verify and took traffic
    prev  the lkg from before that — the rollback target

Ready is not enough on its own: a revision can start and still fail verify
before ever taking traffic, and Cloud Run keeps it around either way.

A rollback then sets lkg to whatever it rolled to and drops prev, so the
revision it fled can never be picked again (see rollback-cloudrun.sh).
"""

from __future__ import annotations

import json
import sys
from typing import Any

LKG_TAG = "lkg"
PREV_TAG = "prev"


def tagged_revision(service: dict[str, Any], tag: str) -> str | None:
    """The revision name carrying this traffic tag, if any.

    Args:
        service: `gcloud run services describe --format=json` output.
        tag: the traffic tag to look up ("lkg" / "prev").
    Returns:
        The revision name, or None when nothing carries the tag.
    Raises:
        None.
    """
    for entry in service.get("status", {}).get("traffic") or []:
        if entry.get("tag") == tag and entry.get("revisionName"):
            return str(entry["revisionName"])
    return None


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


def _ready_revision_names(revisions: list[dict[str, Any]]) -> set[str]:
    """The names of the revisions Cloud Run currently reports as Ready.

    Args:
        revisions: `gcloud run revisions list --format=json` output.
    Returns:
        Ready revision names.
    Raises:
        None.
    """
    ready: set[str] = set()
    for rev in revisions:
        name = rev.get("metadata", {}).get("name")
        conditions = rev.get("status", {}).get("conditions") or []
        if name and any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in conditions
        ):
            ready.add(str(name))
    return ready


def pick_previous(
    service: dict[str, Any], revisions: list[dict[str, Any]]
) -> str:
    """The revision recorded as the last known good one before the current.

    Args:
        service: `gcloud run services describe --format=json` output.
        revisions: `gcloud run revisions list --format=json` output.
    Returns:
        The rollback target's revision name.
    Raises:
        SystemExit: traffic is split, there is no prev marker, the marker
            points at the revision already serving, or at a revision that is
            no longer Ready. Every refusal says to pass --revision instead —
            guessing an untested revision is worse than asking.
    """
    current = serving_revision(service)
    previous = tagged_revision(service, PREV_TAG)
    if previous is None:
        raise SystemExit(
            f"refuse: no {PREV_TAG!r} tag on this service, so no revision is "
            "recorded as the last known good one before the current deploy "
            "(first deploy, or the previous rollback consumed it). Pass "
            "--revision to name one yourself."
        )
    if previous == current:
        raise SystemExit(
            f"refuse: {PREV_TAG!r} points at {previous}, which is already "
            "serving. Pass --revision to name one yourself."
        )
    if previous not in _ready_revision_names(revisions):
        raise SystemExit(
            f"refuse: {PREV_TAG!r} points at {previous}, which is not Ready. "
            "Pass --revision to name one yourself."
        )
    return previous


def _read_json(path: str) -> Any:
    """Parse one JSON file.

    Args:
        path: the file to read.
    Returns:
        The parsed JSON.
    Raises:
        OSError: the file could not be read.
        json.JSONDecodeError: it was not JSON.
    """
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    """Read service (+ revisions) JSON from file args, print a rollback pick
    or the current serving revision.

    Args:
        argv: CLI arguments — "--print-current SERVICE.json" (the revision at
            100% traffic), "--print-tag TAG SERVICE.json" (a marker, empty if
            unset), "SERVICE.json REVISIONS.json" (the rollback pick), or None
            for sys.argv.
    Returns:
        0 printed a pick/revision; 1 refused; 2 bad usage/input shape.
    Raises:
        None — refusals are caught and reported via the return code.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "--print-current":
        try:
            print(serving_revision(_read_json(argv[1])))
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    if len(argv) == 3 and argv[0] == "--print-tag":
        print(tagged_revision(_read_json(argv[2]), argv[1]) or "")
        return 0
    if len(argv) != 2:
        print(
            "usage: pick_rollback_revision.py SERVICE.json REVISIONS.json\n"
            "       pick_rollback_revision.py --print-current SERVICE.json\n"
            "       pick_rollback_revision.py --print-tag TAG SERVICE.json",
            file=sys.stderr,
        )
        return 2
    service = _read_json(argv[0])
    revisions = _read_json(argv[1])
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
