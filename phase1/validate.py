#!/usr/bin/env python3
"""Local invariants for Phase 1 — no GitHub calls.

Also usable as: python3 validate.py --check-stdin  < CODEOWNERS
so verify-phase1.sh judges remote files with the same rules as this suite.
"""
from __future__ import annotations

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
    matched: list[str] = []
    for pattern, owners in rules:
        if pattern_matches(pattern, path):
            matched = owners
    return matched


def load_ruleset(name: str) -> dict:
    return json.loads((RULESETS / name).read_text())


def pull_request_rule(ruleset: dict) -> dict:
    for rule in ruleset["rules"]:
        if rule.get("type") == "pull_request":
            return rule["parameters"]
    raise AssertionError(f"{ruleset.get('name')} has no pull_request rule")


def codeowners_text_is_valid(text: str) -> list[str]:
    """Errors that would make the production Lead gate a no-op. Empty = ok."""
    errors: list[str] = []
    try:
        rules = parse_codeowners(text)
    except ValueError as exc:
        return [str(exc)]

    stars = [owners for pattern, owners in rules if CATCHALL.match(pattern)]
    if len(stars) != 1:
        errors.append(f"need exactly one * rule, found {len(stars)}")
    elif frozenset(stars[0]) != LEADS:
        errors.append(f"* owners are {stars[0]}, want {sorted(LEADS)}")

    for pattern, owners in rules:
        if NOT_LEAD in owners:
            errors.append(f"{pattern} lists {NOT_LEAD}; that breaks the Lead gate on main")

    for path in (
        "text_agent/app.py",
        "ci/text-deploy.yaml",
        ".github/workflows/pr-checks.yml",
    ):
        got = frozenset(owners_for(rules, path))
        if got != LEADS:
            errors.append(f"{path} owners are {sorted(got)}, want {sorted(LEADS)}")
    return errors


def bypass_is_org_admin_pr_only(ruleset: dict) -> bool:
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
        cls.rules = parse_codeowners(CODEOWNERS.read_text())

    def test_catchall_is_leads_only(self) -> None:
        stars = [owners for pattern, owners in self.rules if CATCHALL.match(pattern)]
        self.assertEqual(len(stars), 1, "exactly one * rule")
        self.assertEqual(frozenset(stars[0]), LEADS)
        self.assertNotIn(NOT_LEAD, stars[0])

    def test_prince_is_not_a_code_owner_of_any_path(self) -> None:
        for pattern, owners in self.rules:
            self.assertNotIn(
                NOT_LEAD,
                owners,
                f"{pattern} lists {NOT_LEAD}; that breaks the Lead gate on main",
            )

    def test_last_match_for_app_code_is_leads(self) -> None:
        for path in (
            "text_agent/app.py",
            "user_service/foo.py",
            "README.md",
            "run_text_agent.py",
        ):
            self.assertEqual(frozenset(owners_for(self.rules, path)), LEADS, path)

    def test_last_match_for_pipeline_paths_is_leads(self) -> None:
        for path in ("ci/text-deploy.yaml", ".github/workflows/pr-checks.yml"):
            self.assertEqual(frozenset(owners_for(self.rules, path)), LEADS, path)

    def test_on_disk_file_passes_shared_validator(self) -> None:
        self.assertEqual(codeowners_text_is_valid(CODEOWNERS.read_text()), [])

    def test_prince_on_catchall_fails_shared_validator(self) -> None:
        broken = "*       @arnavtayal @abhishektayal2802 @Prince-sujho\n"
        errors = codeowners_text_is_valid(broken)
        self.assertTrue(errors)
        self.assertTrue(any(NOT_LEAD in e for e in errors))
        self.assertIn(NOT_LEAD, owners_for(parse_codeowners(broken), "text_agent/app.py"))


class RulesetTests(unittest.TestCase):
    def test_main_requires_code_owners_and_merge_commits(self) -> None:
        pr = pull_request_rule(load_ruleset("main.json"))
        self.assertTrue(pr["require_code_owner_review"])
        self.assertEqual(pr["allowed_merge_methods"], ["merge"])
        self.assertTrue(pr["require_last_push_approval"])
        self.assertTrue(pr["dismiss_stale_reviews_on_push"])
        self.assertEqual(pr["required_approving_review_count"], 1)

    def test_no_github_dev_or_preprod_ruleset_files(self) -> None:
        self.assertFalse((RULESETS / "dev.json").exists())
        self.assertFalse((RULESETS / "pre-prod.json").exists())

    def test_light_touch_does_not_require_code_owners(self) -> None:
        pr = pull_request_rule(load_ruleset("light-touch-main.json"))
        self.assertFalse(pr["require_code_owner_review"])

    def test_no_empty_status_check_rule(self) -> None:
        for name in ("main.json", "light-touch-main.json"):
            types = [r["type"] for r in load_ruleset(name)["rules"]]
            self.assertNotIn("required_status_checks", types, name)

    def test_main_hotfix_bypass_is_org_admin_pr_only(self) -> None:
        self.assertTrue(bypass_is_org_admin_pr_only(load_ruleset("main.json")))

    def test_no_ruleset_allows_direct_push_bypass(self) -> None:
        for name in ("main.json", "light-touch-main.json"):
            for actor in load_ruleset(name).get("bypass_actors") or []:
                self.assertNotEqual(
                    actor.get("bypass_mode"),
                    "always",
                    f"{name} allows a direct-push bypass",
                )

    def test_rulesets_target_main(self) -> None:
        for name in ("main.json", "light-touch-main.json"):
            include = load_ruleset(name)["conditions"]["ref_name"]["include"]
            self.assertEqual(include, ["refs/heads/main"], name)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--check-stdin":
        errors = codeowners_text_is_valid(sys.stdin.read())
        for item in errors:
            print(item, file=sys.stderr)
        sys.exit(1 if errors else 0)
    unittest.main(verbosity=2)
