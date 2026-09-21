#!/usr/bin/env python3
"""Print Cloud Run job fields for Cloud Build. Reads manifests/<id>/job.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CATALOG = json.loads((HERE / "catalog.jobs.json").read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    args = parser.parse_args()

    job_path = HERE / "manifests" / args.id / "job.json"
    if not job_path.is_file():
        print(f"error: no job.json for {args.id}", file=sys.stderr)
        return 1
    job = json.loads(job_path.read_text())
    group = CATALOG["image_groups"][job["image_group"]]
    out = {
        "JOB_ID": job["id"],
        "CLOUD_RUN_JOB": job["cloud_run_job"],
        "IMAGE": group["image"],
        "DOCKERFILE": group["dockerfile"],
        "GITLINKS": " ".join(group["gitlinks"]),
        "RUNTIME_SA": group["runtime_sa"],
        "COMMAND": ",".join(job["command"]),
        "ARGS": ",".join(job["args"]),
        "CPU": job["cpu"],
        "MEMORY": job["memory"],
        "TASK_TIMEOUT": job["task_timeout"],
        "TASKS": str(job["tasks"]),
        "PARALLELISM": str(job["parallelism"]),
        "MAX_RETRIES": str(job["max_retries"]),
        "NEEDS_ENTRY_ID": "1" if job["needs_entry_id"] else "0",
        "REGISTRY": CATALOG["registry"],
        "REGION": CATALOG["region"],
    }
    if args.format == "json":
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    for key, value in out.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
