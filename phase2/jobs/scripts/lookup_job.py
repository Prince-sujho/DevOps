#!/usr/bin/env python3
"""Derives a job's build/deploy fields from its id — no per-job manifest file.
e.g. knowledge-store-import-ncert -> group knowledge-store, verb import-ncert,
entry knowledge_store/jobs/import_ncert.py. Unset fields fall back to the
group's.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CATALOG = json.loads((HERE / "catalog.jobs.json").read_text())


def find_job(job_id: str) -> dict:
    """The catalog entry for job_id, or exit 1 if it isn't listed.

    Args:
        job_id: catalog job id to look up.
    Returns:
        The catalog job dict whose id equals job_id.
    Raises:
        SystemExit: job_id is not listed in catalog.jobs.json.
    """
    for job in CATALOG["jobs"]:
        if job["id"] == job_id:
            return job
    print(f"error: {job_id} is not in catalog.jobs.json", file=sys.stderr)
    sys.exit(1)


def find_group_name(job_id: str) -> str:
    """The longest image_group name job_id is prefixed by, or exit 1 if none
    match.

    Args:
        job_id: catalog job id whose image-group prefix is resolved.
    Returns:
        The longest matching image-group name.
    Raises:
        SystemExit: job_id matches no image_group prefix.
    """
    # longest match wins, avoids a shorter group name matching as a false prefix
    candidates = [
        name
        for name in CATALOG["image_groups"]
        if job_id == name or job_id.startswith(name + "-")
    ]
    if not candidates:
        print(f"error: {job_id} matches no image_group prefix", file=sys.stderr)
        sys.exit(1)
    return max(candidates, key=len)


def _entry_paths(job_id: str, group_name: str) -> tuple[str, str, str]:
    """Package name, entry file, and entry module derived from a job id.

    Args:
        job_id: catalog job id.
        group_name: the image_group name job belongs to.
    Returns:
        (package, entry_file, entry_module).
    Raises:
        None.
    """
    verb = job_id[len(group_name) + 1 :] if job_id != group_name else ""
    package = group_name.replace("-", "_")
    verb_module = verb.replace("-", "_")
    entry_file = f"{package}/jobs/{verb_module}.py"
    entry_module = f"{package}.jobs.{verb_module}"
    return package, entry_file, entry_module


def _resource_fields(job: dict, group: dict) -> dict[str, str]:
    """CPU, memory, timeout, and task settings, with the job overriding the
    group.

    Args:
        job: the catalog job entry.
        group: the catalog image_group entry.
    Returns:
        The resource SHELL_VAR fields.
    Raises:
        None.
    """
    return {
        "CPU": job.get("cpu", group.get("cpu", "1")),
        "MEMORY": job.get("memory", group.get("memory", "512Mi")),
        "TASK_TIMEOUT": job.get(
            "task_timeout", group.get("task_timeout", "3600s")
        ),
        "TASKS": str(job.get("tasks", group.get("tasks", 1))),
        "PARALLELISM": str(job.get("parallelism", group.get("parallelism", 1))),
        "MAX_RETRIES": str(job.get("max_retries", group.get("max_retries", 0))),
    }


def resolve_fields(job: dict, group_name: str, group: dict) -> dict:
    """Derive every build/deploy field for one job from its id, group, and
    overrides.

    Args:
        job: the catalog job entry (may override cpu/memory/tasks/etc).
        group_name: the image_group name job belongs to.
        group: the catalog image_group entry (image/dockerfile/defaults).
    Returns:
        Every SHELL_VAR=value field this job's deploy step needs.
    Raises:
        None.
    """
    package, entry_file, entry_module = _entry_paths(job["id"], group_name)
    return {
        "JOB_ID": job["id"],
        "IMAGE_GROUP": group_name,
        "IMAGE": group["image"],
        "DOCKERFILE": group["dockerfile"],
        "PACKAGE": package,
        "RUNTIME_SA": group["runtime_sa"],
        "ENTRY_FILE": entry_file,
        "ENTRY_MODULE": entry_module,
        **_resource_fields(job, group),
        "NEEDS_ENTRY_ID": "1" if job.get("needs_entry_id", False) else "0",
        "SCHEDULE": job.get("schedule", ""),
        "REGISTRY": CATALOG["registry"],
        "REGION": CATALOG["region"],
    }


def main() -> int:
    """Print one job's derived fields as shell-eval lines or JSON.

    Args:
        None.
    Returns:
        Always 0, after the job fields have been printed.
    Raises:
        None.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    args = parser.parse_args()

    job = find_job(args.id)
    group_name = find_group_name(job["id"])
    group = CATALOG["image_groups"][group_name]
    out = resolve_fields(job, group_name, group)

    if args.format == "json":
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    # quoted so a caller can safely `eval` this even with spaces in any value
    for key, value in out.items():
        print(f"{key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
