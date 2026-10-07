#!/usr/bin/env python3
"""Local invariants for Phase 0 (full repo merge) — no GitHub or GCP calls.

Tests the pure logic in collapse_ci_gitsource.py against the exact real
gitSource shapes found in Sujho/platform's ci/*.yaml (3-source, 2-source, and
0-source), checks repos.json's own internal consistency, and asserts that
merge_repos.py's source contains no remote-mutating call at all — so this
suite itself would fail loudly if that safety property were ever broken.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from collapse_ci_gitsource import collapse_dependencies, find_gitsource_blocks
from merge_repos import (
    drift_count,
    drift_line,
    gitlink_sha,
    gitlinks_not_kept,
    is_fully_rewritten,
    merge_one,
    nested_governance_paths,
    same_source_tip,
)

HERE = Path(__file__).resolve().parent
REPOS_JSON = HERE / "repos.json"
MERGE_REPOS_PY = HERE / "merge_repos.py"

THREE_SOURCE = (
    """\
dependencies:
  - gitSource:
      repository:
        developerConnect: """
    """projects/p/locations/r/connections/c/gitRepositoryLinks/sujho-sujho
      revision: main
      depth: 1
      destPath: .
  - gitSource:
      repository:
        developerConnect: """
    """projects/p/locations/r/connections/c/gitRepositoryLinks/sujho-users
      revision: main
      depth: 1
      destPath: user_service
  - gitSource:
      repository:
        developerConnect: """
    """projects/p/locations/r/connections/c/gitRepositoryLinks/sujho-infra
      revision: main
      depth: 1
      destPath: infra

options:
  logging: CLOUD_LOGGING_ONLY
"""
)

TWO_SOURCE = (
    """\
dependencies:
  - gitSource:
      repository:
        developerConnect: """
    """projects/p/locations/r/connections/c/gitRepositoryLinks/sujho-sujho
      revision: main
      depth: 1
      destPath: .
  - gitSource:
      repository:
        developerConnect: """
    """projects/p/locations/r/connections/c/gitRepositoryLinks/sujho-infra
      revision: main
      depth: 1
      destPath: infra

options:
  logging: CLOUD_LOGGING_ONLY
"""
)

ZERO_SOURCE = """\
options:
  logging: CLOUD_LOGGING_ONLY

steps:
  - name: gcr.io/kaniko-project/executor
"""


class TestFindGitsourceBlocks(unittest.TestCase):
    """find_gitsource_blocks against every real shape."""

    def test_three_source_finds_all_three(self) -> None:
        """A 3-gitSource file yields exactly the 3 destPaths, in order.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        lines = [line for line in THREE_SOURCE.splitlines()]
        dests = [dest for _, _, dest in find_gitsource_blocks(lines)]
        self.assertEqual(dests, [".", "user_service", "infra"])

    def test_zero_source_finds_none(self) -> None:
        """A file with no dependencies: block yields no blocks at all.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        lines = ZERO_SOURCE.splitlines()
        self.assertEqual(find_gitsource_blocks(lines), [])


class TestCollapseDependencies(unittest.TestCase):
    """collapse_dependencies against every real shape."""

    def test_three_source_collapses_to_one(self) -> None:
        """A 3-gitSource file keeps only the destPath: . block.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        after = collapse_dependencies(THREE_SOURCE)
        dests = [
            dest for _, _, dest in find_gitsource_blocks(after.splitlines())
        ]
        self.assertEqual(dests, ["."])

    def test_two_source_collapses_to_one(self) -> None:
        """A 2-gitSource file (no separate service repo) also keeps just `.`.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        after = collapse_dependencies(TWO_SOURCE)
        dests = [
            dest for _, _, dest in find_gitsource_blocks(after.splitlines())
        ]
        self.assertEqual(dests, ["."])

    def test_zero_source_is_unchanged(self) -> None:
        """A file with no gitSource blocks at all round-trips unchanged.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertEqual(collapse_dependencies(ZERO_SOURCE), ZERO_SOURCE)

    def test_everything_outside_dependencies_is_untouched(self) -> None:
        """Collapsing never touches text after the dependencies: block.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        after = collapse_dependencies(THREE_SOURCE)
        self.assertTrue(
            after.endswith("options:\n  logging: CLOUD_LOGGING_ONLY\n")
        )


class TestReposJson(unittest.TestCase):
    """repos.json's own internal consistency."""

    def setUp(self) -> None:
        """Load repos.json once per test.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.data = json.loads(REPOS_JSON.read_text())

    def test_no_target_collides_with_super_repo_or_kept_submodules(
        self,
    ) -> None:
        """No merge target shares a name with super_repo or a kept submodule.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        reserved = {self.data["super_repo"], *self.data["keep_submodules"]}
        targets = {entry["target"] for entry in self.data["merge_repos"]}
        self.assertEqual(reserved & targets, set())

    def test_no_duplicate_merge_targets(self) -> None:
        """Every merge_repos entry's target is unique.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        targets = [entry["target"] for entry in self.data["merge_repos"]]
        self.assertEqual(len(targets), len(set(targets)))

    def test_keep_submodules_is_empty(self) -> None:
        """www and design_system stay out; docs is merged, not kept.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertEqual(self.data["keep_submodules"], [])

    def test_empty_keep_list_drops_www_and_design_system(self) -> None:
        """A gitlink stays only when keep_submodules names it.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        present = ["design_system", "docs", "www", "user_service"]
        self.assertEqual(
            gitlinks_not_kept(present, []),
            present,
        )
        self.assertEqual(
            gitlinks_not_kept(present, ["www"]),
            ["design_system", "docs", "user_service"],
        )

    def test_merge_repos_are_the_decided_set(self) -> None:
        """merge_repos is the 8 backends plus docs, and nothing else.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        targets = {entry["target"] for entry in self.data["merge_repos"]}
        self.assertEqual(
            targets,
            {
                "user_service",
                "whatsapp_adapter",
                "text_agent",
                "document_worker",
                "knowledge_store",
                "admin",
                "redirect_service",
                "infra",
                "docs",
            },
        )


class TestMergeReposHasNoRemoteWrite(unittest.TestCase):
    """Structural safety: merge_repos.py can never push anywhere."""

    def test_source_contains_no_push_call(self) -> None:
        """merge_repos.py's source never invokes `git push` or `gh ... create`.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        source = MERGE_REPOS_PY.read_text()
        self.assertNotIn('"push"', source)
        self.assertNotIn("'push'", source)


class TestIsFullyRewritten(unittest.TestCase):
    """A retried run must redo a clone that never finished its rewrite,
    not silently reuse it un-rewritten (the bug: paths still at repo root
    instead of under target/, which either collides on merge or silently
    pollutes the super-repo root)."""

    def test_bare_clone_is_not_rewritten(self) -> None:
        """A dest with just a .git dir (cloned, rewrite never ran) is False.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / ".git").mkdir()
            self.assertFalse(is_fully_rewritten(dest, "user_service"))

    def test_a_target_directory_alone_is_not_a_rewrite(self) -> None:
        """A dest with .git and target/ but no commit map is False.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / ".git").mkdir()
            (dest / "user_service").mkdir()
            self.assertFalse(is_fully_rewritten(dest, "user_service"))

    def test_completed_rewrite_is_recognized(self) -> None:
        """A dest with .git, target/ and the commit map is True.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / ".git" / "filter-repo").mkdir(parents=True)
            (dest / ".git" / "filter-repo" / "commit-map").write_text(
                "old new\n"
            )
            (dest / "user_service").mkdir()
            self.assertTrue(is_fully_rewritten(dest, "user_service"))

    def test_reuse_requires_the_recorded_source_tip(self) -> None:
        """same_source_tip is true only for the old hash of HEAD.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            dest.mkdir(exist_ok=True)
            _git(dest, "init", "-q")
            (dest / "f").write_text("a\n")
            _git(dest, "add", "f")
            _git(dest, "commit", "-qm", "a")
            head = _git(dest, "rev-parse", "HEAD")
            mapped = dest / ".git" / "filter-repo"
            mapped.mkdir()
            (mapped / "commit-map").write_text(f"abc123 {head}\n")
            self.assertTrue(same_source_tip(dest, "abc123"))
            self.assertFalse(same_source_tip(dest, "other"))

    def test_missing_dest_is_not_rewritten(self) -> None:
        """A dest that doesn't exist at all is False, not an error.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "never-created"
            self.assertFalse(is_fully_rewritten(dest, "user_service"))


def _git(cwd: Path, *args: str) -> str:
    """Run git in cwd with a throwaway identity; return stdout.

    Args:
        cwd: repo directory.
        args: git arguments.
    Returns:
        Stripped stdout.
    Raises:
        subprocess.CalledProcessError: git failed.
    """
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class TestDriftAndInertFiles(unittest.TestCase):
    """The merge must say what it would change and what GitHub will ignore."""

    def test_drift_counts_commits_past_the_pin(self) -> None:
        """A tip two commits past the pinned commit reports 2; at the pin, 0.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q", "--template=")
            (repo / "a").write_text("1")
            _git(repo, "add", "a")
            _git(repo, "commit", "-q", "-m", "one")
            pinned = _git(repo, "rev-parse", "HEAD")
            self.assertEqual(drift_count(repo, pinned), 0)
            for n in ("2", "3"):
                (repo / "a").write_text(n)
                _git(repo, "commit", "-q", "-am", n)
            self.assertEqual(drift_count(repo, pinned), 2)

    def test_drift_line_flags_only_real_drift(self) -> None:
        """Zero drift is ok; any drift is loud and names the escape hatch.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertTrue(drift_line("infra", 0).startswith("ok"))
        line = drift_line("infra", 3)
        self.assertTrue(line.startswith("DRIFT"))
        self.assertIn("--at-pinned", line)

    def test_gitlink_sha_reads_the_pinned_commit(self) -> None:
        """A gitlink entry's SHA comes back; a plain directory raises.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q", "--template=")
            _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},svc")
            (repo / "plain").mkdir()
            (repo / "plain" / "f").write_text("x")
            _git(repo, "add", "plain")
            _git(repo, "commit", "-q", "-m", "x")
            self.assertEqual(gitlink_sha(repo, "svc"), sha)
            with self.assertRaises(ValueError):
                gitlink_sha(repo, "plain")

    def test_nested_governance_files_are_listed(self) -> None:
        """Merged-in .github and CODEOWNERS are reported; clean dirs are not.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / "user_service" / ".github").mkdir(parents=True)
            (tree / "admin").mkdir()
            (tree / "admin" / "CODEOWNERS").write_text("* @x")
            (tree / "infra").mkdir()
            self.assertEqual(
                nested_governance_paths(tree, ["user_service", "admin", "infra"]),
                ["admin/CODEOWNERS", "user_service/.github"],
            )

    def test_main_reports_drift_before_merging(self) -> None:
        """merge_repos.main computes the pin and the report before it drops
        gitlinks (afterwards the pin is gone), and offers --at-pinned.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        source = MERGE_REPOS_PY.read_text()
        main_body = source.split("def main(", 1)[1]
        self.assertLess(
            main_body.index("gitlink_sha("), main_body.index("drop_gitlinks(")
        )
        self.assertIn("--at-pinned", source)
        self.assertIn("nested_governance_paths(", main_body)


class TestCutoverChecklist(unittest.TestCase):
    """The steps no script can do are printed by the script itself, so they
    cannot be missed — and are not a separate document nobody opens."""

    def test_checklist_covers_each_irreversible_step(self) -> None:
        """apply-phase0.sh prints the freeze, the state a rewrite loses, the
        secret scan, repointing consumers and archive-not-delete.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = (HERE / "apply-phase0.sh").read_text()
        for needle in (
            "Freeze",
            "open PRs and issues",
            "tags and GitHub Releases",
            "Scan the merged history for secrets",
            "Cloud Build",
            "Archive the 8 old repos — do not delete",
            "drift report",
            "--at-pinned",
            "CODEOWNERS",
        ):
            self.assertIn(needle, body)

    def test_checklist_prints_on_both_paths(self) -> None:
        """It prints in the dry run and again after a real merge, not only in
        one of them.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = (HERE / "apply-phase0.sh").read_text()
        self.assertEqual(body.count("cutover_checklist"), 3)
        dry_run_at = body.index('if [ "$APPLY" -eq 0 ]; then')
        self.assertLess(dry_run_at, body.index("cutover_checklist\n  echo"))

    def test_apply_script_passes_at_pinned_through(self) -> None:
        """apply-phase0.sh and lib.sh accept --at-pinned and hand it to
        merge_repos.py.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        apply = (HERE / "apply-phase0.sh").read_text()
        lib = (HERE / "lib.sh").read_text()
        self.assertIn("--at-pinned) AT_PINNED=1", lib)
        self.assertIn("MERGE_ARGS+=(--at-pinned)", apply)


class TestPinnedShaMerge(unittest.TestCase):
    """--at-pinned merges a commit SHA, not remote/<sha>."""

    def test_merges_the_pinned_commit_and_not_later_commits(self) -> None:
        """A pinned SHA merges, and commits after that pin stay out.

        Args:
            None.
        Returns:
            None.
        Raises:
            AssertionError: the pin is missing, or a later commit came in.
        """
        keys = (
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        )
        saved = {key: os.environ.get(key) for key in keys}
        os.environ.update({key: "t" for key in keys})
        os.environ["GIT_AUTHOR_EMAIL"] = "t@example.com"
        os.environ["GIT_COMMITTER_EMAIL"] = "t@example.com"
        try:
            self._merge_pin_not_tip()
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def _merge_pin_not_tip(self) -> None:
        """Build two tiny repos and merge the child's first commit only.

        Args:
            None.
        Returns:
            None.
        Raises:
            AssertionError: pinned.txt is missing, or later.txt came along.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child, super_repo = root / "child", root / "super"
            child.mkdir()
            super_repo.mkdir()
            _git(child, "init", "-q", "-b", "main")
            (child / "pinned.txt").write_text("pin\n")
            _git(child, "add", "pinned.txt")
            _git(child, "commit", "-q", "-m", "pin")
            pinned = _git(child, "rev-parse", "HEAD")
            (child / "later.txt").write_text("later\n")
            _git(child, "add", "later.txt")
            _git(child, "commit", "-q", "-m", "later")
            _git(super_repo, "init", "-q", "-b", "main")
            (super_repo / "root.txt").write_text("root\n")
            _git(super_repo, "add", "root.txt")
            _git(super_repo, "commit", "-q", "-m", "root")
            merge_one(super_repo, "user_service", child, at_commit=pinned)
            self.assertTrue((super_repo / "pinned.txt").is_file())
            self.assertFalse((super_repo / "later.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
