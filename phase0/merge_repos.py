#!/usr/bin/env python3
"""Merge the 8 backend repos' full history into a local copy of Sujho/sujho.

Local only, by construction: every git operation here reads (`clone`,
`fetch` from a local path) or writes to `--output`, a path this script
requires the caller to name explicitly. There is no code path that adds
a remote pointing at GitHub for anything but the initial clone, and
nothing here ever calls `git push`. See docs/full-repo-merge-plan.md for
the full procedure this implements and why.

Steps, per repo in repos.json's merge_repos list:
  1. `git clone` it fresh into a scratch directory.
  2. `git filter-repo --to-subdirectory-filter <target>/` so its entire
     history now lives under that one subdirectory — this is what makes
     the later merge conflict-free, since no two repos' rewritten
     histories can ever touch the same path.
  3. Remove its gitlink entry (and matching .gitmodules stanza) from the
     working copy of the super-repo.
  4. `git merge --allow-unrelated-histories` its rewritten history in,
     one commit per repo.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPOS_JSON = HERE / "repos.json"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run with check=True, so a failed git/gh call raises loudly.

    Args:
        cmd: the argv to run.
        kwargs: passed through to subprocess.run (e.g. cwd, capture_output).
    Returns:
        The completed process.
    Raises:
        subprocess.CalledProcessError: cmd exited nonzero.
    """
    return subprocess.run(cmd, check=True, **kwargs)


def load_repos(path: Path) -> dict:
    """Parse repos.json into its super_repo/keep_submodules/merge_repos shape.

    Args:
        path: the repos.json file to read.
    Returns:
        The parsed dict, as authored in repos.json.
    Raises:
        ValueError: a merge_repos entry's target collides with super_repo or
            a kept submodule, or two merge_repos entries share a target.
    """
    data = json.loads(path.read_text())
    reserved = {data["super_repo"], *data["keep_submodules"]}
    seen: set[str] = set()
    for entry in data["merge_repos"]:
        target = entry["target"]
        if target in reserved:
            raise ValueError(
                f"{target!r} collides with super_repo/keep_submodules"
            )
        if target in seen:
            raise ValueError(f"duplicate merge target {target!r}")
        seen.add(target)
    return data


def clone_repo(org: str, github_name: str, dest: Path) -> None:
    """Fresh, shallow-free clone of one GitHub repo, read-only.

    Args:
        org: the GitHub organization the repo belongs to.
        github_name: the repo's name under that org.
        dest: local path to clone into; must not already exist.
    Returns:
        None.
    Raises:
        subprocess.CalledProcessError: the clone failed (auth, network,
            or the repo doesn't exist).
    """
    run(
        [
            "gh",
            "repo",
            "clone",
            f"{org}/{github_name}",
            str(dest),
            "--",
            "--quiet",
        ]
    )


def is_fully_rewritten(dest: Path, target: str) -> bool:
    """True if dest is a clone that rewrite_to_subdirectory already finished.

    filter-repo either finishes cleanly or leaves the clone in an
    unrecognizable partial state — there's no safe way to resume a half-done
    rewrite, only to detect it and start over. A finished rewrite always has
    its own target/ subdirectory at the clone root; a clone that was only
    cloned, or crashed mid-rewrite, never does.

    Args:
        dest: the clone directory to check.
        target: the subdirectory name rewrite_to_subdirectory moves paths under.
    Returns:
        True if dest looks like a completed rewrite.
    Raises:
        None.
    """
    return (dest / ".git").is_dir() and (dest / target).is_dir()


def rewrite_to_subdirectory(repo_dir: Path, target: str) -> None:
    """Rewrite a repo's entire history so it lives under target/.

    Args:
        repo_dir: the repo's local clone, rewritten in place.
        target: the subdirectory every commit's paths move under.
    Returns:
        None.
    Raises:
        subprocess.CalledProcessError: git-filter-repo failed.
    """
    run(
        [
            "git",
            "filter-repo",
            "--to-subdirectory-filter",
            f"{target}/",
            "--force",
        ],
        cwd=repo_dir,
    )


def default_branch(repo_dir: Path) -> str:
    """The repo's current branch name (its default, right after a fresh clone).

    Args:
        repo_dir: a git checkout, freshly cloned and not yet detached.
    Returns:
        The branch name.
    Raises:
        subprocess.CalledProcessError: git rev-parse failed.
    """
    result = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _remove_gitmodules_sections(
    super_repo_dir: Path, targets: list[str]
) -> None:
    """Delete each target's stanza from .gitmodules and stage the file.

    Args:
        super_repo_dir: the super-repo's working copy.
        targets: subdirectory names whose submodule sections are removed.
    Returns:
        None.
    Raises:
        subprocess.CalledProcessError: a git command failed.
    """
    for target in targets:
        run(
            [
                "git",
                "config",
                "-f",
                ".gitmodules",
                "--remove-section",
                f"submodule.{target}",
            ],
            cwd=super_repo_dir,
        )
    run(["git", "add", ".gitmodules"], cwd=super_repo_dir)


def _unstage_gitlinks(super_repo_dir: Path, targets: list[str]) -> None:
    """Unstage each gitlink and remove an empty placeholder directory.

    Args:
        super_repo_dir: the super-repo's working copy.
        targets: subdirectory names to unstage.
    Returns:
        None.
    Raises:
        subprocess.CalledProcessError: git rm failed.
    """
    for target in targets:
        run(["git", "rm", "--cached", target], cwd=super_repo_dir)
        placeholder = super_repo_dir / target
        if placeholder.exists() and not any(placeholder.iterdir()):
            placeholder.rmdir()


def drop_gitlinks(super_repo_dir: Path, targets: list[str]) -> None:
    """Remove every merge target's gitlink entry and .gitmodules stanza.

    Args:
        super_repo_dir: the super-repo's working copy.
        targets: the subdirectory names to remove (e.g. "user_service").
    Returns:
        None.
    Raises:
        subprocess.CalledProcessError: a git command failed.
    """
    _remove_gitmodules_sections(super_repo_dir, targets)
    _unstage_gitlinks(super_repo_dir, targets)
    run(
        ["git", "commit", "-m", "drop submodules for the merged backend repos"],
        cwd=super_repo_dir,
    )


def _merge_fetched(
    super_repo_dir: Path, target: str, branch: str
) -> None:
    """Fetch a temporary remote and merge its branch into the super-repo.

    Args:
        super_repo_dir: the super-repo's working copy.
        target: temporary remote name.
        branch: branch on that remote to merge.
    Returns:
        None.
    Raises:
        subprocess.CalledProcessError: fetch or merge failed.
    """
    run(["git", "fetch", target], cwd=super_repo_dir)
    run(
        [
            "git",
            "merge",
            "--allow-unrelated-histories",
            f"{target}/{branch}",
            "-m",
            f"merge {target} into monorepo",
        ],
        cwd=super_repo_dir,
    )


def merge_one(
    super_repo_dir: Path, target: str, rewritten_repo_dir: Path
) -> None:
    """Merge one rewritten repo's history into the super-repo working copy.

    Args:
        super_repo_dir: the super-repo's working copy, merged into in place.
        target: this repo's merge target name, used as the temporary remote
            name and in the merge commit message.
        rewritten_repo_dir: the repo's local clone, already rewritten by
            rewrite_to_subdirectory.
    Returns:
        None.
    Raises:
        subprocess.CalledProcessError: fetch or merge failed (a real merge
            conflict is not expected here — rewrite_to_subdirectory makes
            every repo's paths disjoint by construction — so a failure here
            means an assumption was violated and needs investigating, not
            blindly resolving).
    """
    branch = default_branch(rewritten_repo_dir)
    run(
        ["git", "remote", "add", target, str(rewritten_repo_dir)],
        cwd=super_repo_dir,
    )
    try:
        _merge_fetched(super_repo_dir, target, branch)
    finally:
        run(["git", "remote", "remove", target], cwd=super_repo_dir)


def build_parser() -> argparse.ArgumentParser:
    """CLI parser: where to build the merged tree, and from what.

    Args:
        None.
    Returns:
        The configured parser.
    Raises:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--org", default="Sujho", help="GitHub org every repo belongs to"
    )
    parser.add_argument("--repos-json", type=Path, default=DEFAULT_REPOS_JSON)
    parser.add_argument(
        "--scratch",
        type=Path,
        required=True,
        help="local directory to clone every repo into (created if missing)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="local directory for the merged super-repo working copy "
        "(created by cloning --org/super_repo here)",
    )
    return parser


def _rewritten_clones(
    org: str, scratch: Path, merge_repos: list[dict]
) -> dict[str, Path]:
    """Clone each merge repo into scratch and rewrite it into its subdirectory.

    Args:
        org: GitHub org every repo belongs to.
        scratch: directory the clones are written under.
        merge_repos: repos.json merge_repos entries.
    Returns:
        Map of target subdirectory name to the rewritten clone path.
    Raises:
        subprocess.CalledProcessError: clone or rewrite failed.
    """
    rewritten: dict[str, Path] = {}
    for entry in merge_repos:
        dest = scratch / entry["github"]
        target = entry["target"]
        if dest.exists() and not is_fully_rewritten(dest, target):
            print(f"{dest}: present but not fully rewritten, redoing")
            shutil.rmtree(dest)
        if not dest.exists():
            clone_repo(org, entry["github"], dest)
            rewrite_to_subdirectory(dest, target)
        else:
            print(f"{dest}: already present, reusing as-is")
        rewritten[target] = dest
    return rewritten


def main(argv: list[str] | None = None) -> int:
    """Clone, rewrite, and merge every repos.json entry into --output.

    Args:
        argv: CLI arguments, or None to use sys.argv.
    Returns:
        0 on success.
    Raises:
        subprocess.CalledProcessError: any underlying git/gh command failed.
        ValueError: repos.json itself is malformed (see load_repos).
    """
    args = build_parser().parse_args(argv)
    data = load_repos(args.repos_json)

    args.scratch.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit(f"refuse to overwrite existing --output {args.output}")
    clone_repo(args.org, data["super_repo"], args.output)

    rewritten = _rewritten_clones(
        args.org, args.scratch, data["merge_repos"]
    )
    drop_gitlinks(args.output, list(rewritten))
    for target, repo_dir in rewritten.items():
        print(f"=== merging {target} ===")
        merge_one(args.output, target, repo_dir)

    print(f"done: merged tree at {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
