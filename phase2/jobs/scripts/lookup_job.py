#!/usr/bin/env python3
"""Derives a job's build/deploy fields from catalog.jobs.json.

The image, the entry module, and the runtime account come from the job's
explicit group. The arguments the module reads come from the job's explicit
args list. Nothing is sliced out of the job id.
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


def find_group_name(job: dict) -> str:
    """The job's explicit "group" field, validated against image_groups.

    Args:
        job: the catalog job entry.
    Returns:
        The job's group name.
    Raises:
        SystemExit: the job has no "group" field, or it names no real
            image_group.
    """
    group_name = job.get("group")
    if not group_name:
        print(
            f'error: {job["id"]} has no "group" field in catalog.jobs.json',
            file=sys.stderr,
        )
        sys.exit(1)
    if group_name not in CATALOG["image_groups"]:
        print(
            f"error: {job['id']}'s group {group_name!r} is not in image_groups",
            file=sys.stderr,
        )
        sys.exit(1)
    return group_name


def _package_name(group_name: str) -> str:
    """Package directory for an image group.

    Args:
        group_name: the explicit image_group name.
    Returns:
        group_name with hyphens turned into underscores, matching the
        package directory on the uploaded tree (knowledge-store ->
        knowledge_store).
    Raises:
        None.
    """
    return group_name.replace("-", "_")


def require_entry(owner_name: str, entry: dict) -> tuple[str, str]:
    """An entry module and file. Both are required, and the file
    path must be the module path.

    Args:
        owner_name: catalog group or job name, used only in errors.
        entry: catalog fields containing the entry module and file.
    Returns:
        (entry_file, entry_module).
    Raises:
        SystemExit: entry_module or entry_file is missing, or the file path
            is not the module path with dots turned into slashes.
    """
    entry_module = entry.get("entry_module") or ""
    entry_file = entry.get("entry_file") or ""
    if not entry_module or not entry_file:
        print(
            f'error: {owner_name!r} needs "entry_module" and '
            '"entry_file" in catalog.jobs.json',
            file=sys.stderr,
        )
        sys.exit(1)
    expected = entry_module.replace(".", "/") + ".py"
    if entry_file != expected:
        print(
            f"error: {owner_name!r} entry_file {entry_file!r} "
            f"does not match entry_module {entry_module!r} (expected {expected})",
            file=sys.stderr,
        )
        sys.exit(1)
    return entry_file, entry_module


def require_args(job: dict) -> str:
    """The job's container arguments after the module, ';'-separated so a
    Cloud Build substitution can carry them.

    Args:
        job: the catalog job entry.
    Returns:
        ';'-joined args. An empty list is valid and returns "".
    Raises:
        SystemExit: the job has no "args" field, or an arg is empty or
            contains ',' or ';' (those split substitutions and gcloud --args).
    """
    if "args" not in job:
        print(
            f'error: {job["id"]} has no "args" field in catalog.jobs.json',
            file=sys.stderr,
        )
        sys.exit(1)
    args = job["args"]
    if not isinstance(args, list):
        print(
            f'error: {job["id"]} "args" must be a list',
            file=sys.stderr,
        )
        sys.exit(1)
    for arg in args:
        if not isinstance(arg, str) or not arg or "," in arg or ";" in arg:
            print(
                f'error: {job["id"]} has an args entry that is empty or '
                "contains ',' or ';'",
                file=sys.stderr,
            )
            sys.exit(1)
    return ";".join(args)


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


def _resolve_env(job: dict, env: str) -> str:
    """This job's env vars for one environment, ';'-separated, same shape as
    services.json's env/overrides.

    Args:
        job: the catalog job entry.
        env: "preprod" or "prod".
    Returns:
        ';'-joined KEY=value entries; the environment's override replaces the
        job's base list entirely, it does not merge with it.
    Raises:
        None.
    """
    base = list(job.get("env", []))
    override = job.get("overrides", {}).get(env, {}).get("env")
    if override is not None:
        base = override
    return ";".join(base)


def resolve_fields(job: dict, group_name: str, group: dict, env: str) -> dict:
    """Derive every build/deploy field for one job from its id, group, and
    overrides.

    Args:
        job: the catalog job entry (may override cpu/memory/tasks/etc).
        group_name: the image_group name job belongs to.
        group: the catalog image_group entry (image/dockerfile/defaults).
        env: "preprod" or "prod" — which overrides block applies.
    Returns:
        Every SHELL_VAR=value field this job's deploy step needs.
    Raises:
        None.
    """
    entry = job if "entry_module" in job or "entry_file" in job else group
    entry_owner = f'job {job["id"]}' if entry is job else f"group {group_name!r}"
    entry_file, entry_module = require_entry(entry_owner, entry)
    return {
        "JOB_ID": job["id"],
        "IMAGE_GROUP": group_name,
        "IMAGE": group["image"],
        "DOCKERFILE": group["dockerfile"],
        "PACKAGE": _package_name(group_name),
        "RUNTIME_SA": group["runtime_sa"],
        "ENTRY_FILE": entry_file,
        "ENTRY_MODULE": entry_module,
        "ENTRY_ARGS": require_args(job),
        **_resource_fields(job, group),
        "NEEDS_ENTRY_ID": "1" if job.get("needs_entry_id", False) else "0",
        "SCHEDULE": job.get("schedule", ""),
        "ENV_VARS": _resolve_env(job, env),
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
    parser.add_argument("--env", choices=("preprod", "prod"), required=True)
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    args = parser.parse_args()

    job = find_job(args.id)
    group_name = find_group_name(job)
    group = CATALOG["image_groups"][group_name]
    out = resolve_fields(job, group_name, group, args.env)

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
