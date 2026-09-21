#!/usr/bin/env python3
"""Phase 5 is papers only. The digest-check workflow was a fake gate.

Promotion is: Lead tests one piece on Pre-Prod, then clicks approve-preprod
for that piece. Weekly eval does not stamp. Tests here fail if the cut
files come back.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASE1_MAIN = json.loads((HERE.parent / "phase1" / "rulesets" / "main.json").read_text())
APPLY = (HERE / "apply-phase5.sh").read_text()
LIB = (HERE / "lib.sh").read_text()
PHASE4_APPROVE = HERE.parent / "phase4" / "generate_approve.py"


def _merge_methods(ruleset: dict) -> list[str]:
    for rule in ruleset["rules"]:
        if rule.get("type") == "pull_request":
            return rule["parameters"]["allowed_merge_methods"]
    raise AssertionError("no pull_request rule")


class CutTests(unittest.TestCase):
    def test_checker_and_templates_are_gone(self) -> None:
        self.assertFalse((HERE / "workflows" / "promotion-tag-check.yml").exists())
        self.assertFalse((HERE / "scripts" / "promotion_tag_check.py").exists())
        self.assertFalse((HERE / "templates" / "default.md").exists())
        self.assertFalse((HERE / "templates" / "promotion-preprod.md").exists())
        self.assertFalse((HERE / "templates" / "promotion-prod.md").exists())

    def test_apply_does_not_put_cut_files(self) -> None:
        self.assertNotIn("promotion-tag-check.yml", APPLY)
        self.assertNotIn("promotion_tag_check.py", APPLY)
        self.assertNotIn("PULL_REQUEST_TEMPLATE", APPLY)
        self.assertIn("approve-preprod", APPLY)
        self.assertIn("were cut", APPLY)

    def test_lib_does_not_point_at_cut_paths(self) -> None:
        self.assertNotIn("promotion-tag-check", LIB)
        self.assertNotIn("PHASE5_WORKFLOW_DEST", LIB)

    def test_approve_preprod_is_the_stamp_path(self) -> None:
        self.assertTrue(PHASE4_APPROVE.is_file())
        src = PHASE4_APPROVE.read_text()
        self.assertIn("tag-on-approval.sh", src)
        self.assertIn("$PIECE", src)
        self.assertNotIn("--all", src)


class RulesetTests(unittest.TestCase):
    def test_no_phase5_rulesets(self) -> None:
        self.assertFalse((HERE / "rulesets").exists())

    def test_does_not_replace_phase1_merge_only(self) -> None:
        self.assertEqual(_merge_methods(PHASE1_MAIN), ["merge"])
        self.assertTrue(any(r.get("type") == "pull_request" for r in PHASE1_MAIN["rules"]))

    def test_main_still_requires_code_owners(self) -> None:
        pr = next(r["parameters"] for r in PHASE1_MAIN["rules"] if r["type"] == "pull_request")
        self.assertTrue(pr["require_code_owner_review"])


class ApplyTests(unittest.TestCase):
    def test_apply_refuses_to_land_a_fake_gate(self) -> None:
        self.assertIn("--apply", APPLY)
        self.assertIn("not a merge gate", APPLY)
        self.assertIn("were cut", APPLY)
        self.assertNotIn("--base dev", APPLY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
