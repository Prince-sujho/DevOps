#!/usr/bin/env python3
"""Local invariants for Phase 3 — no GitHub, GCP, OpenAI, or mutmut."""
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
import eval_replay as ev  # noqa: E402
import mutation_report as mut  # noqa: E402

MUT_WF = (HERE / "workflows" / "mutation.yml").read_text()
EVAL_WF = (HERE / "workflows" / "eval-replay.yml").read_text()
PINS = json.loads((HERE.parent / "action-pins.json").read_text())["pins"]
APPLY = (HERE / "apply-phase3.sh").read_text()
LIB = (HERE / "lib.sh").read_text()


class MutationWorkflowTests(unittest.TestCase):
    def test_self_hosted_not_github_hosted(self) -> None:
        self.assertIn("runs-on: [self-hosted, mutation]", MUT_WF)
        self.assertNotIn("runs-on: ubuntu-latest", MUT_WF)

    def test_weekly_not_on_pull_request(self) -> None:
        self.assertIn("cron:", MUT_WF)
        self.assertIn("workflow_dispatch", MUT_WF)
        self.assertNotIn("pull_request", MUT_WF)

    def test_not_a_merge_gate(self) -> None:
        self.assertIn("timeout-minutes: 720", MUT_WF)
        self.assertIn("continue-on-error: true", MUT_WF)
        self.assertIn("tests/ci/pipeline.py mutation", MUT_WF)

    def test_posts_to_an_issue_not_a_pr_check(self) -> None:
        self.assertIn("issues: write", MUT_WF)
        self.assertIn("MUTATION_TRACKING_ISSUE", MUT_WF)

    def test_checks_out_submodules(self) -> None:
        self.assertIn("submodules: recursive", MUT_WF)


class EvalWorkflowTests(unittest.TestCase):
    def test_weekly_not_a_merge_gate(self) -> None:
        self.assertIn("cron:", EVAL_WF)
        self.assertNotIn("pull_request", EVAL_WF)

    def test_no_stale_spend_cap(self) -> None:
        self.assertNotIn("SPEND_CAP_INR", EVAL_WF)
        self.assertNotIn("SPEND_SO_FAR_INR", EVAL_WF)

    def test_no_github_secrets(self) -> None:
        self.assertNotIn("secrets.", EVAL_WF)
        self.assertIn(
            f"google-github-actions/auth@{PINS['google-github-actions/auth']['sha']}",
            EVAL_WF,
        )
        self.assertNotIn("google-github-actions/auth@v2\n", EVAL_WF)
        self.assertIn(f"actions/checkout@{PINS['actions/checkout']['sha']}", MUT_WF)
        self.assertIn(f"actions/checkout@{PINS['actions/checkout']['sha']}", EVAL_WF)
        self.assertIn("continue-on-error: true", EVAL_WF)
        self.assertIn("::add-mask::", EVAL_WF)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_EVAL", EVAL_WF)

    def test_eval_history_is_restored_and_uploaded(self) -> None:
        self.assertIn("eval-history.json", EVAL_WF)
        self.assertIn("gh run download", EVAL_WF)
        self.assertIn("Restore eval-history", EVAL_WF)

    def test_eval_never_touches_the_approval_mechanism(self) -> None:
        self.assertNotIn("tag-on-approval.sh", EVAL_WF)
        self.assertNotIn("tag-preprod-approved", EVAL_WF)
        self.assertNotIn("preprod-approved", EVAL_WF)
        self.assertNotIn("approve-preprod", EVAL_WF)
        self.assertNotIn("GCP_WIF_SERVICE_ACCOUNT_PREPROD", EVAL_WF)

    def test_points_at_eval_suite_not_anthropic(self) -> None:
        self.assertIn("Eval-Suite/run.py", EVAL_WF + Path(HERE / "scripts" / "eval_replay.py").read_text())
        self.assertIn("eval-openai-key", EVAL_WF)
        self.assertNotIn("ANTHROPIC_API_KEY", EVAL_WF)
        self.assertIn("submodules: recursive", EVAL_WF)

    def test_fail_open_auth(self) -> None:
        self.assertIn("continue-on-error: true", EVAL_WF)


class MutationScriptTests(unittest.TestCase):
    def test_placeholder_paths_file_is_gone(self) -> None:
        self.assertFalse((HERE / "mutation-paths.txt").exists())

    def test_missing_report_skips_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                self.assertEqual(mut.main(["--report", "missing.json"]), 0)
                data = json.loads(Path("mutation-result.json").read_text())
                self.assertTrue(data["skipped"])
                self.assertTrue(data["flag_review"])
            finally:
                os.chdir(cwd)

    def test_score_drop_flags_but_exits_zero(self) -> None:
        self.assertTrue(mut.should_flag(0.95))
        self.assertFalse(mut.should_flag(0.98))
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("mutmut-cicd-stats.json").write_text(
                    json.dumps({"killed": 95, "survived": 5, "total": 100})
                )
                self.assertEqual(mut.main(["--report", "mutmut-cicd-stats.json"]), 0)
                data = json.loads(Path("mutation-result.json").read_text())
                self.assertTrue(data["flag_review"])
                self.assertFalse(data["skipped"])
                self.assertEqual(data["score"], 0.95)
            finally:
                os.chdir(cwd)

    def test_corrupt_report_still_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("mutmut-cicd-stats.json").write_text("{not json")
                self.assertEqual(mut.main(["--report", "mutmut-cicd-stats.json"]), 0)
                self.assertTrue(json.loads(Path("mutation-result.json").read_text())["skipped"])
            finally:
                os.chdir(cwd)


class EvalScriptTests(unittest.TestCase):
    def test_placeholder_golden_set_is_gone(self) -> None:
        self.assertFalse((HERE / "eval" / "golden-set.json").exists())
        self.assertFalse((HERE / "eval" / "golden-set.schema.json").exists())
        self.assertFalse((HERE / "eval" / "scenarios.md").exists())

    def test_escalate_only_after_two_weak_weeks(self) -> None:
        this = {"a": "fail", "b": "pass", "c": "xpass"}
        hist = {"last_week": {"a": "fail", "b": "fail", "c": "pass"}}
        esc = ev.persist_and_escalate(this, hist)
        self.assertEqual(esc, ["a"])
        self.assertEqual(hist["last_week"]["b"], "pass")

    def test_no_spend_cap_function_left(self) -> None:
        self.assertFalse(hasattr(ev, "spend_cap_hit"))

    def test_missing_key_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(ev.main(), 0)
                data = json.loads(Path("eval-result.json").read_text())
                self.assertTrue(data["fail_open"])
                self.assertIn("OPENAI_API_KEY", data["reason"])
            finally:
                os.chdir(cwd)

    def test_missing_runner_skips(self) -> None:
        env = {name: "x" for name in ev.REQUIRED_ENV}
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(ev.main(), 0)
                data = json.loads(Path("eval-result.json").read_text())
                self.assertTrue(data["skipped"])
                self.assertIn("Eval-Suite/run.py", data["reason"])
            finally:
                os.chdir(cwd)

    def test_suite_results_are_recorded_and_job_stays_green(self) -> None:
        env = {name: "x" for name in ev.REQUIRED_ENV}
        report = {
            "run_id": "20260915-000000",
            "counts": {"pass": 58, "fail": 2, "xfail": 0, "xpass": 0},
            "results": [
                {"case_id": "s1", "status": "pass"},
                {"case_id": "s2", "status": "fail"},
                {"case_id": "s3", "status": "fail"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("Eval-Suite/reports").mkdir(parents=True)
                Path("Eval-Suite/run.py").write_text("print('ok')\n")
                Path("Eval-Suite/reports/20260915-000000.json").write_text(json.dumps(report))
                Path("eval-history.json").write_text(
                    json.dumps({"last_week": {"s2": "fail", "s3": "pass"}})
                )
                with mock.patch.dict(os.environ, env, clear=True):
                    with mock.patch.object(ev, "run_suite", return_value=1):
                        self.assertEqual(ev.main(), 0)
                data = json.loads(Path("eval-result.json").read_text())
                self.assertFalse(data["skipped"])
                self.assertTrue(data["flag_review"])
                self.assertFalse(data["full_pass"])
                self.assertEqual(data["escalate"], ["s2"])
            finally:
                os.chdir(cwd)

    def test_clean_eval_is_a_full_pass_and_writes_history(self) -> None:
        env = {name: "x" for name in ev.REQUIRED_ENV}
        report = {
            "run_id": "20260921-000000",
            "counts": {"pass": 3, "fail": 0, "xfail": 0, "xpass": 0},
            "results": [
                {"case_id": "s1", "status": "pass"},
                {"case_id": "s2", "status": "pass"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("Eval-Suite/reports").mkdir(parents=True)
                Path("Eval-Suite/run.py").write_text("print('ok')\n")
                Path("Eval-Suite/reports/20260921-000000.json").write_text(json.dumps(report))
                Path("eval-history.json").write_text(json.dumps({"last_week": {"s1": "pass"}}))
                with mock.patch.dict(os.environ, env, clear=True):
                    with mock.patch.object(ev, "run_suite", return_value=0):
                        self.assertEqual(ev.main(), 0)
                data = json.loads(Path("eval-result.json").read_text())
                self.assertTrue(data["full_pass"])
                self.assertFalse(data["flag_review"])
                hist = json.loads(Path("eval-history.json").read_text())
                self.assertEqual(hist["last_week"]["s1"], "pass")
                self.assertEqual(hist["last_week"]["s2"], "pass")
            finally:
                os.chdir(cwd)


class ApplyTests(unittest.TestCase):
    def test_umbrella_only_not_service_repos(self) -> None:
        self.assertIn("PHASE3_MUTATION_REPOS=(sujho)", LIB)
        self.assertIn("PHASE3_EVAL_REPOS=(sujho)", LIB)
        skip = LIB.split("PHASE3_SKIP_REPOS")[1].split(")")[0]
        self.assertIn("admin", skip)
        self.assertIn("text-agent", skip)
        self.assertNotIn("mutation-paths.txt", APPLY)
        self.assertNotIn("golden-set.json", APPLY)
        self.assertNotIn("tag-on-approval.sh", APPLY)
        self.assertNotIn("PHASE3_TAG_SCRIPT", LIB)
        self.assertNotIn("preprod-approved is stamped", APPLY)

    def test_apply_refuses_required_checks(self) -> None:
        self.assertIn('die "Phase 3 is not a merge gate', APPLY)

    def test_no_phase3_rulesets(self) -> None:
        self.assertFalse((HERE / "rulesets").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
