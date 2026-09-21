#!/usr/bin/env python3
"""Checkout service + infra at the gitlink SHAs recorded in sujho.

Cloud Build gitSource of those repos at `revision: main` is the 4b bug:
each dep floats independently of the parent commit. This script reads
`git ls-tree` (mode 160000) and clones those exact SHAs.

Never float past the recorded gitlink SHA.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

GITMODULE_RE = re.compile(
    r"\[submodule \"(?P<name>[^\"]+)\"\]\n"
    r"(?:[^\[]*?)"
    r"path = (?P<path>\S+)\n"
    r"(?:[^\[]*?)"
    r"url = (?P<url>\S+)",
    re.MULTILINE,
)
LS_TREE_RE = re.compile(r"^160000 commit ([0-9a-f]{40})\t(.+)$")
BRANCH_LINE = re.compile(r"^\s*branch\s*=", re.MULTILINE)


def parse_gitmodules(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for m in GITMODULE_RE.finditer(text):
        out[m.group("path")] = {
            "name": m.group("name"),
            "url": m.group("url"),
            "path": m.group("path"),
        }
    return out


def gitlinks_from_ls_tree(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = LS_TREE_RE.match(line)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def github_repo(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url.rsplit("/", 1)[-1]


def dc_link_name(url: str) -> str:
    return f"sujho-{github_repo(url)}"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def ls_tree(repo: Path) -> str:
    return run(
        ["git", "-C", str(repo), "ls-tree", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout


def clone_uri(*, url: str, project: str, region: str, connection: str) -> str:
    """Resolve the Developer Connect clone URI. Never fall back to a public GitHub URL."""
    if not project:
        raise SystemExit(
            "error: --project / PROJECT_ID is required to resolve Developer Connect"
        )
    link = dc_link_name(url)
    try:
        out = run(
            [
                "gcloud",
                "developer-connect",
                "git-repository-links",
                "describe",
                link,
                f"--location={region}",
                f"--connection={connection}",
                f"--project={project}",
                "--format=value(cloneUri)",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
    except FileNotFoundError as exc:
        raise SystemExit(
            "error: gcloud not found; cannot resolve Developer Connect clone URI"
        ) from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(
            f"error: DC link missing ({link} connection={connection} "
            f"project={project}). Do not clone {url} without credentials. {err}"
        ) from exc
    if not out:
        raise SystemExit(
            f"error: DC link missing ({link} connection={connection} "
            f"project={project}): empty cloneUri. Do not clone {url} without credentials."
        )
    return out


def checkout_sha(dest: Path, uri: str, sha: str) -> None:
    if dest.exists() and not (dest / ".git").exists():
        leftover = [p for p in dest.iterdir()]
        if leftover:
            raise SystemExit(f"{dest} is not empty and is not a git checkout")
        dest.rmdir()
    if dest.exists():
        run(["git", "-C", str(dest), "fetch", "origin", sha])
        run(["git", "-C", str(dest), "checkout", "--force", sha])
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "init", str(dest)])
    run(["git", "-C", str(dest), "remote", "add", "origin", uri])
    run(["git", "-C", str(dest), "fetch", "origin", sha])
    run(["git", "-C", str(dest), "checkout", "--force", sha])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".", help="sujho checkout (gitlinks live here)")
    p.add_argument(
        "--paths",
        nargs="+",
        required=True,
        help="gitlink paths to materialize, e.g. redirect_service infra",
    )
    p.add_argument("--project", default=os.environ.get("PROJECT_ID", ""))
    p.add_argument("--region", default=os.environ.get("_REGION", "asia-south1"))
    p.add_argument(
        "--connection",
        default=os.environ.get("_DC_CONNECTION", "sujho-github-dc"),
    )
    p.add_argument("--print-only", action="store_true")
    p.add_argument("--gitmodules-file", default="")
    p.add_argument("--ls-tree-file", default="")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    gitmodules_text = (
        Path(args.gitmodules_file).read_text()
        if args.gitmodules_file
        else (root / ".gitmodules").read_text()
    )
    if BRANCH_LINE.search(gitmodules_text):
        print("error: .gitmodules still has branch = lines (those float)", file=sys.stderr)
        return 1
    gitmodules = parse_gitmodules(gitmodules_text)
    if args.ls_tree_file:
        tree = Path(args.ls_tree_file).read_text()
    else:
        tree = ls_tree(root)
    links = gitlinks_from_ls_tree(tree)

    for path in args.paths:
        meta = gitmodules.get(path)
        if not meta:
            print(f"error: {path} is not in .gitmodules", file=sys.stderr)
            return 1
        sha = links.get(path)
        if not sha:
            print(f"error: {path} is not a gitlink on HEAD (160000)", file=sys.stderr)
            return 1
        link = dc_link_name(meta["url"])
        if args.print_only:
            print(f"{path} -> {sha} via DC link {link}")
            continue
        uri = clone_uri(
            url=meta["url"],
            project=args.project,
            region=args.region,
            connection=args.connection,
        )
        print(f"{path} -> {sha} from {uri}")
        checkout_sha(root / path, uri, sha)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
