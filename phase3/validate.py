#!/usr/bin/env python3
"""Local invariants for Phase 3 — no GitHub and no Anthropic calls."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import ai_review  # noqa: E402

WORKFLOW = (HERE / "workflows" / "ai-review.yml").read_text()
PINS = json.loads((HERE.parent / "action-pins.json").read_text())["pins"]
REVIEW_MD = (HERE / "REVIEW.md").read_text()
RULESET = json.loads((HERE / "rulesets" / "main-required-checks.json").read_text())
AI_ONLY = json.loads((HERE / "rulesets" / "main-required-ai-only.json").read_text())
LIB = (HERE / "lib.sh").read_text()
PHASE2_RULESET = json.loads(
    (HERE.parent / "phase2" / "rulesets" / "main-required-checks.json").read_text()
)


class WorkflowTests(unittest.TestCase):
    def test_targets_main_not_extra_github_branches(self) -> None:
        self.assertIn("branches: [main]", WORKFLOW)
        self.assertNotIn("branches: [dev]", WORKFLOW)
        self.assertNotIn("branches: [pre-prod]", WORKFLOW)

    def test_skips_trivial_and_draft_prs(self) -> None:
        self.assertIn("skip=true", WORKFLOW)
        self.assertIn("draft == false", WORKFLOW)

    def test_gate_job_is_named_ai_review(self) -> None:
        self.assertIn("name: ai-review", WORKFLOW)
        self.assertIn("if: always()", WORKFLOW)

    def test_fail_open_does_not_fail_the_gate(self) -> None:
        self.assertIn('data.get("fail_open")', WORKFLOW)
        self.assertIn("continue-on-error: true", WORKFLOW)

    def test_no_github_secrets_for_the_api_key(self) -> None:
        self.assertNotIn("secrets.", WORKFLOW)
        self.assertIn("ai-review-anthropic-key", WORKFLOW)
        self.assertIn(
            f"google-github-actions/auth@{PINS['google-github-actions/auth']['sha']}",
            WORKFLOW,
        )
        self.assertNotIn("google-github-actions/auth@v2\n", WORKFLOW)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_AI_REVIEW", WORKFLOW)

    def test_does_not_use_break_system_packages(self) -> None:
        self.assertNotIn("--break-system-packages", WORKFLOW)

    def test_bandit_skips_when_there_are_no_python_files(self) -> None:
        self.assertIn("changed_py=", WORKFLOW)
        self.assertIn('echo \'{"results":[]}\' > bandit-results.json', WORKFLOW)

    def test_comment_is_updated_not_spammed(self) -> None:
        self.assertIn("phase3-ai-review", WORKFLOW)
        self.assertIn("updateComment", WORKFLOW)

    def test_collect_has_no_credentials_or_review_script(self) -> None:
        collect = WORKFLOW.split("\n  collect:")[1].split("\n  review:")[0]
        review = WORKFLOW.split("\n  review:")[1].split("\n  ai-review:")[0]
        self.assertNotIn("google-github-actions/auth", collect)
        self.assertNotIn("ANTHROPIC_API_KEY", collect)
        self.assertNotIn("id-token: write", collect)
        self.assertNotIn("scripts/ai_review.py", collect)
        self.assertIn("persist-credentials: false", collect)
        self.assertIn("refs/pull/", collect)
        self.assertIn("google-github-actions/auth", review)
        self.assertIn("scripts/ai_review.py", review)
        self.assertIn("id-token: write", review)
        self.assertIn("pull_request.base.sha", review)
        self.assertNotIn("head.sha", review)
        self.assertNotIn("refs/pull/", review)

    def test_api_key_is_masked_before_github_env(self) -> None:
        fetch = WORKFLOW.split("Fetch Anthropic API key from Secret Manager")[1]
        mask_at = fetch.find("::add-mask::")
        env_at = fetch.find("GITHUB_ENV")
        self.assertNotEqual(mask_at, -1)
        self.assertNotEqual(env_at, -1)
        self.assertLess(mask_at, env_at)

    def test_does_not_fall_back_to_dev_branch(self) -> None:
        self.assertNotIn("'dev'", WORKFLOW)
        self.assertIn("github.event.repository.default_branch", WORKFLOW)

    def test_semgrep_is_scoped_to_the_diff(self) -> None:
        self.assertIn("--baseline-commit", WORKFLOW)

    def test_collect_failure_is_fail_open(self) -> None:
        gate = WORKFLOW.split("\n  ai-review:")[1]
        self.assertIn("collect failed — fail-open", gate)
        self.assertIn('collect" = "failure"', gate)
        self.assertIn("exit 0", gate)
        self.assertNotIn("git fetch --depth=50", WORKFLOW)


class RubricTests(unittest.TestCase):
    def test_blocks_on_important_not_nits(self) -> None:
        self.assertIn("Always escalate to Important", REVIEW_MD)
        self.assertIn("Nit only, never blocks merge", REVIEW_MD)

    def test_prompt_says_users_not_students_and_teachers_as_the_label(self) -> None:
        self.assertIn('Call them "users" only', ai_review.PASS1_SYSTEM)
        self.assertIn("never \"students and teachers\" in findings", ai_review.PASS1_SYSTEM)


class ScriptTests(unittest.TestCase):
    def test_parse_json_inside_fences(self) -> None:
        text = '```json\n{"review_findings": []}\n```'
        self.assertEqual(ai_review.parse_model_json(text)["review_findings"], [])

    def test_nits_are_capped_and_do_not_become_important(self) -> None:
        findings = [{"severity": "nit", "file": f"f{i}", "issue": str(i)} for i in range(9)]
        findings.append({"severity": "important", "file": "a.py", "issue": "x"})
        out = ai_review.cap_nits(findings)
        self.assertEqual(sum(1 for f in out if f["severity"] == "nit"), 5)
        self.assertEqual(sum(1 for f in out if f["severity"] == "important"), 1)

    def test_pass2_does_not_repeat_pass1(self) -> None:
        pass1 = {
            "review_findings": [{"severity": "important", "file": "a.py", "issue": "dup"}],
            "static_triage": [],
        }
        pass2 = {
            "missed_findings": [
                {"severity": "important", "file": "a.py", "issue": "dup"},
                {"severity": "important", "file": "b.py", "issue": "new"},
            ]
        }
        merged = ai_review.merge_passes(pass1, pass2)
        issues = [f["issue"] for f in merged]
        self.assertEqual(issues.count("dup"), 1)
        self.assertIn("new", issues)

    def test_confirmed_static_finding_is_important(self) -> None:
        pass1 = {
            "review_findings": [],
            "static_triage": [
                {"verdict": "true_positive", "tool": "bandit", "rule_id": "B101", "reasoning": "assert"}
            ],
        }
        out = ai_review.merge_passes(pass1, {})
        self.assertEqual(out[0]["severity"], "important")

    def test_spend_cap_writes_fail_open_without_calling_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, {"SPEND_CAP_INR": "4500", "SPEND_SO_FAR_INR": "4500"}):
                    with mock.patch.object(ai_review, "call_claude") as mocked:
                        self.assertEqual(ai_review.main(), 0)
                        mocked.assert_not_called()
                data = json.loads(Path("review-result.json").read_text())
                self.assertTrue(data["fail_open"])
                self.assertEqual(data["findings"], [])
            finally:
                os.chdir(cwd)

    def test_missing_api_key_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                env = {"SPEND_CAP_INR": "4500"}
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(ai_review.main(), 0)
                data = json.loads(Path("review-result.json").read_text())
                self.assertTrue(data["fail_open"])
            finally:
                os.chdir(cwd)

    def test_claude_exception_fails_open_not_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("pr.diff").write_text("diff")
                with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}):
                    with mock.patch.object(ai_review, "call_claude", side_effect=RuntimeError("billing")):
                        self.assertEqual(ai_review.main(), 0)
                data = json.loads(Path("review-result.json").read_text())
                self.assertTrue(data["fail_open"])
                self.assertEqual(data["findings"], [])
            finally:
                os.chdir(cwd)


def _contexts(ruleset: dict) -> list[str]:
    for rule in ruleset["rules"]:
        if rule.get("type") == "required_status_checks":
            return [c["context"] for c in rule["parameters"]["required_status_checks"]]
    raise AssertionError("no required_status_checks")


class RepoListTests(unittest.TestCase):
    def test_ai_runs_on_sujho_and_every_full_treatment_repo(self) -> None:
        self.assertIn("sujho", LIB)
        self.assertIn("sujho-ops-mcp", LIB)
        self.assertNotIn("PHASE3_SKIP_REPOS", LIB)


class RulesetTests(unittest.TestCase):
    def test_requires_ai_review_and_keeps_pr_checks(self) -> None:
        self.assertEqual(_contexts(RULESET), ["pr-checks", "ai-review"])

    def test_service_repos_require_ai_only_not_pr_checks(self) -> None:
        self.assertEqual(_contexts(AI_ONLY), ["ai-review"])

    def test_keeps_code_owners_on_main(self) -> None:
        pr = next(r["parameters"] for r in RULESET["rules"] if r["type"] == "pull_request")
        self.assertTrue(pr["require_code_owner_review"])
        p2 = next(r["parameters"] for r in PHASE2_RULESET["rules"] if r["type"] == "pull_request")
        self.assertTrue(p2["require_code_owner_review"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
