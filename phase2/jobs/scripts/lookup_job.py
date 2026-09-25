#!/usr/bin/env python3
"""Derives a job's build/deploy fields from its id — no per-job manifest file.
e.g. knowledge-store-import-ncert -> group knowledge-store, verb import-ncert,
entry knowledge_store/jobs/import_ncert.py. Unset fields fall back to the group's."""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CATALOG = json.loads((HERE / "catalog.jobs.json").read_text())


def find_job(job_id: str) -> dict:
    for job in CATALOG["jobs"]:
        if job["id"] == job_id:
            return job
    print(f"error: {job_id} is not in catalog.jobs.json", file=sys.stderr)
    sys.exit(1)


def find_group_name(job_id: str) -> str:
    # longest match wins, avoids a shorter group name matching as a false prefix
    candidates = [
        name for name in CATALOG["image_groups"]
        if job_id == name or job_id.startswith(name + "-")
    ]
    if not candidates:
        print(f"error: {job_id} matches no image_group prefix", file=sys.stderr)
        sys.exit(1)
    return max(candidates, key=len)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    args = parser.parse_args()

    job = find_job(args.id)
    group_name = find_group_name(job["id"])
    group = CATALOG["image_groups"][group_name]

    verb = job["id"][len(group_name) + 1:] if job["id"] != group_name else ""
    package = group_name.replace("-", "_")
    verb_module = verb.replace("-", "_")
    entry_file = f"{package}/jobs/{verb_module}.py"
    entry_module = f"{package}.jobs.{verb_module}"

    out = {
        "JOB_ID": job["id"],
        "IMAGE_GROUP": group_name,
        "IMAGE": group["image"],
        "DOCKERFILE": group["dockerfile"],
        "GITLINKS": " ".join(group["gitlinks"]),
        "RUNTIME_SA": group["runtime_sa"],
        "ENTRY_FILE": entry_file,
        "ENTRY_MODULE": entry_module,
        "CPU": job.get("cpu", group.get("cpu", "1")),
        "MEMORY": job.get("memory", group.get("memory", "512Mi")),
        "TASK_TIMEOUT": job.get("task_timeout", group.get("task_timeout", "3600s")),
        "TASKS": str(job.get("tasks", group.get("tasks", 1))),
        "PARALLELISM": str(job.get("parallelism", group.get("parallelism", 1))),
        "MAX_RETRIES": str(job.get("max_retries", group.get("max_retries", 0))),
        "NEEDS_ENTRY_ID": "1" if job.get("needs_entry_id", False) else "0",
        "SCHEDULE": job.get("schedule", ""),
        "REGISTRY": CATALOG["registry"],
        "REGION": CATALOG["region"],
    }
    if args.format == "json":
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    # quoted so a caller can safely `eval` this even with spaces in GITLINKS
    for key, value in out.items():
        print(f"{key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
