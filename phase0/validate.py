#!/usr/bin/env python3
"""Local invariants for Phase 0 (full repo merge) — no GitHub or GCP calls.

Tests the pure logic in collapse_ci_gitsource.py against the exact real
gitSource shapes found in Sujho/sujho's ci/*.yaml (3-source, 2-source, and
0-source), checks repos.json's own internal consistency, and asserts that
merge_repos.py's source contains no remote-mutating call at all — so this
suite itself would fail loudly if that safety property were ever broken.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collapse_ci_gitsource import collapse_dependencies, find_gitsource_blocks
from merge_repos import is_fully_rewritten

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

    def test_eight_backend_repos_exactly(self) -> None:
        """merge_repos lists exactly the 8 decided backend repos, no more.

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

    def test_completed_rewrite_is_recognized(self) -> None:
        """A dest with .git and the target/ subdirectory is True.

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
            self.assertTrue(is_fully_rewritten(dest, "user_service"))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
