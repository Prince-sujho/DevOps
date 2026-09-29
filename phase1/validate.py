#!/usr/bin/env python3
"""Local invariants for Phase 1 — no GitHub calls.

Also usable as: python3 validate.py --check-stdin  < CODEOWNERS
so verify-phase1.sh judges remote files with the same rules as this suite.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODEOWNERS = HERE / "CODEOWNERS"
RULESETS = HERE / "rulesets"

LEADS = frozenset({"@arnavtayal", "@abhishektayal2802"})
NOT_LEAD = "@Prince-sujho"
CATCHALL = re.compile(r"^(\*|\*\*)$")


def parse_codeowners(text: str) -> list[tuple[str, list[str]]]:
    """Parse CODEOWNERS text into (pattern, owners) rules in file order.

    Args:
        text: CODEOWNERS file contents to parse.
    Returns:
        The (pattern, owners) rules in file order.
    Raises:
        ValueError: the CODEOWNERS text contains no rules.
    """
    rules: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        rules.append((parts[0], parts[1:]))
    if not rules:
        raise ValueError("CODEOWNERS has no rules")
    return rules


def pattern_matches(pattern: str, path: str) -> bool:
    """True if a CODEOWNERS glob pattern covers the given path.

    Args:
        pattern: a CODEOWNERS glob, such as `*`, `docs/`, or `docs/*`.
        path: repository path to test, with or without a leading slash.
    Returns:
        True if pattern is `*` or `**`, or if path equals the pattern or sits
        under it; otherwise False.
    Raises:
        None.
    """
    path = path.lstrip("/")
    if pattern in {"*", "**"}:
        return True
    p = pattern.lstrip("/")
    if p.endswith("/"):
        return path == p.rstrip("/") or path.startswith(p)
    if p.endswith("/*"):
        return path.startswith(p[:-1])
    return path == p or path.startswith(p + "/")


def owners_for(rules: list[tuple[str, list[str]]], path: str) -> list[str]:
    """Owners for a path: the last matching rule wins, same as GitHub.

    Args:
        rules: (pattern, owners) pairs in CODEOWNERS file order.
        path: the path to resolve owners for.
    Returns:
        The owners list from the last rule whose pattern matches path.
    Raises:
        None.
    """
    matched: list[str] = []
    for pattern, owners in rules:
        if pattern_matches(pattern, path):
            matched = owners
    return matched


def load_ruleset(name: str) -> dict:
    """Load a ruleset JSON file from the rulesets/ directory by name.

    Args:
        name: ruleset filename stem under rulesets/, without .json.
    Returns:
        The ruleset file parsed as a dict.
    Raises:
        None.
    """
    return json.loads((RULESETS / name).read_text())


def pull_request_rule(ruleset: dict) -> dict:
    """The ruleset's pull_request rule parameters; raises if none exists.

    Args:
        ruleset: a parsed ruleset object whose rules list is searched.
    Returns:
        The parameters dict of the matching pull_request rule.
    Raises:
        AssertionError: the ruleset has no pull_request rule.
    """
    for rule in ruleset["rules"]:
        if rule.get("type") == "pull_request":
            return rule["parameters"]
    raise AssertionError(f"{ruleset.get('name')} has no pull_request rule")


def branch_name_rule(ruleset: dict) -> dict:
    """The ruleset's branch_name_pattern rule parameters; raises if none exists.

    Args:
        ruleset: a parsed ruleset object whose rules list is searched.
    Returns:
        The parameters dict of the matching branch_name_pattern rule.
    Raises:
        AssertionError: the ruleset has no branch_name_pattern rule.
    """
    for rule in ruleset["rules"]:
        if rule.get("type") == "branch_name_pattern":
            return rule["parameters"]
    raise AssertionError(f"{ruleset.get('name')} has no branch_name_pattern rule")


def is_exempt(ruleset: dict, branch: str) -> bool:
    """True if the ruleset's ref_name excludes cover this branch.

    Args:
        ruleset: a parsed ruleset JSON document.
        branch: a branch name, without refs/heads/.
    Returns:
        Whether any exclude pattern matches refs/heads/<branch>.
    Raises:
        None.
    """
    ref = f"refs/heads/{branch}"
    excludes = ruleset["conditions"]["ref_name"]["exclude"]
    return any(fnmatch.fnmatchcase(ref, pattern) for pattern in excludes)


def script_branches() -> list[str]:
    """Every branch name the phase scripts create on GitHub, read from them.

    Args:
        None.
    Returns:
        The branch names (prove-phase1.sh's is given a sample stamp).
    Raises:
        AssertionError: a script's branch variable could not be found.
    """
    sources = {
        HERE / "lib.sh": "CODEOWNERS_BRANCH",
        HERE.parent / "phase2" / "lib.sh": "PHASE2_BRANCH",
        HERE.parent / "phase3" / "lib.sh": "PHASE3_BRANCH",
        HERE / "prove-phase1.sh": "MAIN_BRANCH",
    }
    branches = []
    for path, var in sources.items():
        found = re.search(rf'^{var}="([^"]+)"', path.read_text(), re.MULTILINE)
        if not found:
            raise AssertionError(f"{var} not found in {path}")
        branches.append(found.group(1).replace("${STAMP}", "20260929-2100"))
    return branches


def _catchall_errors(rules: list[tuple[str, list[str]]]) -> list[str]:
    """Errors in the single catch-all CODEOWNERS rule.

    Args:
        rules: parsed (pattern, owners) CODEOWNERS rules.
    Returns:
        Errors when the * rule is missing, duplicated, or not the leads.
    Raises:
        None.
    """
    stars = [owners for pattern, owners in rules if CATCHALL.match(pattern)]
    if len(stars) != 1:
        return [f"need exactly one * rule, found {len(stars)}"]
    if frozenset(stars[0]) != LEADS:
        return [f"* owners are {stars[0]}, want {sorted(LEADS)}"]
    return []


def _lead_path_errors(rules: list[tuple[str, list[str]]]) -> list[str]:
    """Errors for paths that must be owned exactly by the leads.

    Args:
        rules: parsed (pattern, owners) CODEOWNERS rules.
    Returns:
        One error per required path whose owners are not the leads.
    Raises:
        None.
    """
    errors: list[str] = []
    for path in (
        "text_agent/app.py",
        "ci/text-deploy.yaml",
        ".github/workflows/pr-checks.yml",
    ):
        got = frozenset(owners_for(rules, path))
        if got != LEADS:
            errors.append(
                f"{path} owners are {sorted(got)}, want {sorted(LEADS)}"
            )
    return errors


def codeowners_text_is_valid(text: str) -> list[str]:
    """Errors that would make the production Lead gate a no-op. Empty = ok.

    Args:
        text: raw CODEOWNERS file content.
    Returns:
        Every validation error found; empty means text is valid.
    Raises:
        None.
    """
    try:
        rules = parse_codeowners(text)
    except ValueError as exc:
        return [str(exc)]

    errors = _catchall_errors(rules)
    for pattern, owners in rules:
        if NOT_LEAD in owners:
            errors.append(
                f"{pattern} lists {NOT_LEAD}; that breaks the Lead gate on main"
            )
    errors.extend(_lead_path_errors(rules))
    return errors


def bypass_is_org_admin_pr_only(ruleset: dict) -> bool:
    """True if the only bypass actor is an org admin gated to pull_request mode.

    Args:
        ruleset: a parsed ruleset JSON document.
    Returns:
        Whether the ruleset's single bypass actor is org-admin/pull_request
        only.
    Raises:
        None.
    """
    bypass = ruleset.get("bypass_actors") or []
    if len(bypass) != 1:
        return False
    actor = bypass[0]
    return (
        actor.get("actor_type") == "OrganizationAdmin"
        and actor.get("bypass_mode") == "pull_request"
        and actor.get("bypass_mode") != "always"
    )


class CodeownersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Parse the real CODEOWNERS file once for every test in this class.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        cls.rules = parse_codeowners(CODEOWNERS.read_text())

    def test_catchall_is_leads_only(self) -> None:
        """The catch-all (*) rule exists exactly once and names only the Leads.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        stars = [
            owners for pattern, owners in self.rules if CATCHALL.match(pattern)
        ]
        self.assertEqual(len(stars), 1, "exactly one * rule")
        self.assertEqual(frozenset(stars[0]), LEADS)
        self.assertNotIn(NOT_LEAD, stars[0])

    def test_prince_is_not_a_code_owner_of_any_path(self) -> None:
        """No rule lists NOT_LEAD as an owner anywhere.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for pattern, owners in self.rules:
            self.assertNotIn(
                NOT_LEAD,
                owners,
                f"{pattern} lists {NOT_LEAD}; that breaks the Lead gate on "
                f"main",
            )

    def test_last_match_for_app_code_is_leads(self) -> None:
        """App code paths resolve to the Leads via the catch-all rule.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in (
            "text_agent/app.py",
            "user_service/foo.py",
            "README.md",
            "run_text_agent.py",
        ):
            self.assertEqual(
                frozenset(owners_for(self.rules, path)), LEADS, path
            )

    def test_last_match_for_pipeline_paths_is_leads(self) -> None:
        """Pipeline config paths resolve to the Leads.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in ("ci/text-deploy.yaml", ".github/workflows/pr-checks.yml"):
            self.assertEqual(
                frozenset(owners_for(self.rules, path)), LEADS, path
            )

    def test_on_disk_file_passes_shared_validator(self) -> None:
        """The real CODEOWNERS file has no validator errors.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertEqual(codeowners_text_is_valid(CODEOWNERS.read_text()), [])

    def test_prince_on_catchall_fails_shared_validator(self) -> None:
        """Adding NOT_LEAD to the catch-all rule is caught by the validator.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        broken = "*       @arnavtayal @abhishektayal2802 @Prince-sujho\n"
        errors = codeowners_text_is_valid(broken)
        self.assertTrue(errors)
        self.assertTrue(any(NOT_LEAD in e for e in errors))
        self.assertIn(
            NOT_LEAD, owners_for(parse_codeowners(broken), "text_agent/app.py")
        )


class RulesetTests(unittest.TestCase):
    def test_main_requires_code_owners_and_merge_commits(self) -> None:
        """main.json requires code owner review, one approval, and merge commits
        only.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        pr = pull_request_rule(load_ruleset("main.json"))
        self.assertTrue(pr["require_code_owner_review"])
        self.assertEqual(pr["allowed_merge_methods"], ["merge"])
        self.assertTrue(pr["require_last_push_approval"])
        self.assertTrue(pr["dismiss_stale_reviews_on_push"])
        self.assertEqual(pr["required_approving_review_count"], 1)

    def test_no_github_dev_or_preprod_ruleset_files(self) -> None:
        """No dev.json or pre-prod.json ruleset exists on disk.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse((RULESETS / "dev.json").exists())
        self.assertFalse((RULESETS / "pre-prod.json").exists())

    def test_light_touch_does_not_require_code_owners(self) -> None:
        """light-touch-main.json does not require code owner review.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        pr = pull_request_rule(load_ruleset("light-touch-main.json"))
        self.assertFalse(pr["require_code_owner_review"])

    def test_no_empty_status_check_rule(self) -> None:
        """Neither ruleset declares a required_status_checks rule.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("main.json", "light-touch-main.json"):
            types = [r["type"] for r in load_ruleset(name)["rules"]]
            self.assertNotIn("required_status_checks", types, name)

    def test_main_hotfix_bypass_is_org_admin_pr_only(self) -> None:
        """main.json's bypass is restricted to org admins in pull_request mode.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertTrue(bypass_is_org_admin_pr_only(load_ruleset("main.json")))

    def test_no_ruleset_allows_direct_push_bypass(self) -> None:
        """No ruleset's bypass actor allows an always (direct push) bypass.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("main.json", "light-touch-main.json", "branch-naming.json"):
            for actor in load_ruleset(name).get("bypass_actors") or []:
                self.assertNotEqual(
                    actor.get("bypass_mode"),
                    "always",
                    f"{name} allows a direct-push bypass",
                )

    def test_rulesets_target_main(self) -> None:
        """Both rulesets' ref_name condition targets only refs/heads/main.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("main.json", "light-touch-main.json"):
            include = load_ruleset(name)["conditions"]["ref_name"]["include"]
            self.assertEqual(include, ["refs/heads/main"], name)


class BranchNamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Load branch-naming.json and compile its pattern once.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        cls.ruleset = load_ruleset("branch-naming.json")
        rule = branch_name_rule(cls.ruleset)
        cls.rule = rule
        cls.pattern = re.compile(rule["pattern"])

    def test_rule_is_a_regex_that_must_match(self) -> None:
        """The rule requires a match (not negated) and is a regex.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertEqual(self.rule["operator"], "regex")
        self.assertFalse(self.rule["negate"])

    def test_accepts_fb_person_work_date(self) -> None:
        """Well-formed fb-<person>-<work>-<dd-mm-yy> names are allowed.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in (
            "fb-prince-redirect-404-24-09-26",
            "fb-arnav-gifting-31-12-26",
            "fb-abhishek2802-fix-session-gap-01-01-27",
        ):
            self.assertRegex(name, self.pattern)

    def test_rejects_anything_else(self) -> None:
        """Wrong prefix, missing parts, bad dates and uppercase are refused.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in (
            "feature/redirect-404",
            "fb-prince-24-09-26",
            "fb-prince-redirect-404",
            "fb-prince-redirect-32-09-26",
            "fb-prince-redirect-24-13-26",
            "fb-prince-redirect-24-09-2026",
            "fb-Prince-redirect-24-09-26",
            "fb-prince-redirect_404-24-09-26",
        ):
            self.assertNotRegex(name, self.pattern)

    def test_main_and_script_branches_are_exempt(self) -> None:
        """main, Dependabot and every branch the phase scripts create skip the rule.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for branch in ["main", "dependabot/pip/infra/requests-2.33.0", *script_branches()]:
            self.assertTrue(is_exempt(self.ruleset, branch), branch)

    def test_engineer_branches_are_not_exempt(self) -> None:
        """An ordinary branch is covered by the rule, not excluded from it.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for branch in ("fb-prince-redirect-404-24-09-26", "chore/cleanup", "prove/other"):
            self.assertFalse(is_exempt(self.ruleset, branch), branch)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--check-stdin":
        errors = codeowners_text_is_valid(sys.stdin.read())
        for item in errors:
            print(item, file=sys.stderr)
        sys.exit(1 if errors else 0)
    unittest.main(verbosity=2)
