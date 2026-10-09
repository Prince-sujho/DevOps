#!/usr/bin/env python3
"""Local invariants for Phase 3 — no GitHub, GCP, OpenAI, or mutmut."""

from __future__ import annotations

import json
import os
import subprocess
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
        """Mutation runs on a self-hosted runner, never ubuntu-latest.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("runs-on: [self-hosted, mutation]", MUT_WF)
        self.assertNotIn("runs-on: ubuntu-latest", MUT_WF)

    def test_weekly_not_on_pull_request(self) -> None:
        """Mutation is cron + manual dispatch, never a pull_request trigger.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("cron:", MUT_WF)
        self.assertIn("workflow_dispatch", MUT_WF)
        self.assertNotIn("pull_request", MUT_WF)

    def test_not_a_merge_gate(self) -> None:
        """Mutation has a long timeout, continues on error, and calls the real
        runner.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("timeout-minutes: 720", MUT_WF)
        self.assertIn("continue-on-error: true", MUT_WF)
        self.assertIn("tests/ci/pipeline.py mutation", MUT_WF)

    def test_threshold_lives_only_in_mutation_report(self) -> None:
        """The workflow never restates the baseline — mutation_report.py's
        BASELINE is the single source, so the two cannot drift.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertNotIn("BASELINE", MUT_WF)
        self.assertNotIn(str(mut.BASELINE), MUT_WF)

    def test_pipeline_py_actually_imports(self) -> None:
        """tests/ci/pipeline.py imports cleanly — it must, before mutmut can
        ever run.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        workspace = HERE.parent
        result = subprocess.run(
            [sys.executable, "-c", "import tests.ci.pipeline"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mutation_stage_does_not_reference_a_missing_directory(
        self,
    ) -> None:
        """stage_mutation never shells out to a tests/mutation/ path — that
        directory does not exist; scripts/mutation_report.py is the real
        reporting step, called separately by the workflow.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        pipeline_src = (HERE.parent / "tests" / "ci" / "pipeline.py").read_text()
        self.assertNotIn('"mutation" / "render_report.py"', pipeline_src)
        self.assertNotIn('"mutation" / "check_threshold.py"', pipeline_src)

    def test_posts_to_an_issue_not_a_pr_check(self) -> None:
        """Mutation posts results to a tracking issue, not a PR check.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("issues: write", MUT_WF)
        self.assertIn("MUTATION_TRACKING_ISSUE", MUT_WF)

    def test_does_not_check_out_submodules(self) -> None:
        # Post-phase0, platform has no submodules — the 8 backend repos are
        # plain subdirectories now, not gitlinks.
        """Mutation does not ask for submodules that no longer exist.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertNotIn("submodules: recursive", MUT_WF)


class EvalWorkflowTests(unittest.TestCase):
    def test_weekly_not_a_merge_gate(self) -> None:
        """Eval is cron only, never a pull_request trigger.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("cron:", EVAL_WF)
        self.assertNotIn("pull_request", EVAL_WF)

    def test_no_stale_spend_cap(self) -> None:
        """No leftover spend-cap env vars remain in the eval workflow.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertNotIn("SPEND_CAP_INR", EVAL_WF)
        self.assertNotIn("SPEND_SO_FAR_INR", EVAL_WF)

    def test_no_github_secrets(self) -> None:
        """Eval auths via WIF, not GitHub secrets, and pins its actions.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertNotIn("secrets.", EVAL_WF)
        self.assertIn(
            f"google-github-actions/auth@{
                PINS['google-github-actions/auth']['sha']
            }",
            EVAL_WF,
        )
        self.assertNotIn("google-github-actions/auth@v2\n", EVAL_WF)
        self.assertIn(
            f"actions/checkout@{PINS['actions/checkout']['sha']}", MUT_WF
        )
        self.assertIn(
            f"actions/checkout@{PINS['actions/checkout']['sha']}", EVAL_WF
        )
        self.assertIn("continue-on-error: true", EVAL_WF)
        self.assertIn("::add-mask::", EVAL_WF)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_EVAL", EVAL_WF)

    def test_eval_history_is_restored_and_uploaded(self) -> None:
        """Eval restores and re-uploads eval-history.json across runs.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("eval-history.json", EVAL_WF)
        self.assertIn("gh run download", EVAL_WF)
        self.assertIn("Restore eval-history", EVAL_WF)

    def test_eval_never_touches_the_approval_mechanism(self) -> None:
        """Eval never references the Pre-Prod approval scripts or secrets.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertNotIn("tag-on-approval.sh", EVAL_WF)
        self.assertNotIn("tag-preprod-approved", EVAL_WF)
        self.assertNotIn("preprod-approved", EVAL_WF)
        self.assertNotIn("approve-preprod", EVAL_WF)
        self.assertNotIn("GCP_WIF_SERVICE_ACCOUNT_PREPROD", EVAL_WF)

    def test_points_at_eval_suite_not_anthropic(self) -> None:
        """The eval workflow and script both point at Eval-Suite, never
        Anthropic.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        script = Path(HERE / "scripts" / "eval_replay.py").read_text()
        self.assertIn("Eval-Suite/run.py", EVAL_WF + script)
        self.assertIn("eval-openai-key", EVAL_WF)
        self.assertNotIn("ANTHROPIC_API_KEY", EVAL_WF)
        # Post-phase0, platform has no submodules to recurse into.
        self.assertNotIn("submodules: recursive", EVAL_WF)

    def test_fail_open_auth(self) -> None:
        """Eval's auth step continues on error rather than failing the job.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("continue-on-error: true", EVAL_WF)


def _step_block(text: str, name: str) -> str:
    """The text of one workflow step, from its `- name:` line to the next step.

    Args:
        text: the workflow file's text.
        name: the step's name, after `- name: `.
    Returns:
        The step's text.
    Raises:
        AssertionError: if no such step exists.
    """
    marker = f"- name: {name}"
    assert marker in text, name
    return text.split(marker, 1)[1].split("\n      - ", 1)[0]


class LoudFailureTests(unittest.TestCase):
    def test_configured_eval_setup_fails_loudly(self) -> None:
        # Unconfigured (no WIF variable) is a clean skip. Configured but
        # broken must not look like "nothing to do".
        """Auth, gcloud setup, secret fetch and install have no
        continue-on-error, and the cloud steps run only when configured.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        auth = EVAL_WF.split("google-github-actions/auth@", 1)[1].split(
            "\n      - ", 1
        )[0]
        setup = EVAL_WF.split("google-github-actions/setup-gcloud@", 1)[1].split(
            "\n      - ", 1
        )[0]
        fetch = _step_block(EVAL_WF, "Fetch Eval-Suite secrets from Secret Manager")
        install = _step_block(EVAL_WF, "Install product + test requirements")
        for label, block in (
            ("auth", auth),
            ("setup-gcloud", setup),
            ("fetch", fetch),
            ("install", install),
        ):
            self.assertNotIn("continue-on-error", block, label)
        for label, block in (("auth", auth), ("setup", setup), ("fetch", fetch)):
            self.assertIn("vars.GCP_WIF_PROVIDER != ''", block, label)

    def test_only_best_effort_steps_may_continue_on_error(self) -> None:
        """Only the history restore and the tracking-issue post are
        best-effort in the eval workflow.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        steps = EVAL_WF.split("\n      - ")
        soft = [
            step.splitlines()[0]
            for step in steps
            if "continue-on-error: true" in step
        ]
        self.assertEqual(len(soft), 2, soft)
        self.assertTrue(any("Restore eval-history" in line for line in soft))
        self.assertTrue(any("Post on the tracking issue" in line for line in soft))

    def test_secret_fetch_names_its_project(self) -> None:
        """gcloud is told which project holds the secrets instead of
        relying on whatever default the runner has.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        fetch = _step_block(EVAL_WF, "Fetch Eval-Suite secrets from Secret Manager")
        self.assertIn('--project="$SECRETS_PROJECT"', fetch)
        self.assertIn("SECRETS_PROJECT: sujho-preprod", fetch)

    def test_no_workflow_keeps_a_github_token_in_git(self) -> None:
        """Both scheduled workflows check out with persist-credentials off.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for text in (EVAL_WF, MUT_WF):
            head = text.split("actions/checkout@", 1)[1].split("\n      - ", 1)[0]
            self.assertIn("persist-credentials: false", head)

    def test_a_crashed_mutmut_run_is_annotated(self) -> None:
        """A failed mutmut run still lets the job finish but leaves a
        visible warning annotation.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        step = _step_block(MUT_WF, "Say so if mutmut itself failed")
        self.assertIn("steps.mutmut.outcome == 'failure'", step)
        self.assertIn("::warning", step)


class MutationScriptTests(unittest.TestCase):
    def test_placeholder_paths_file_is_gone(self) -> None:
        """The old mutation-paths.txt placeholder no longer exists.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse((HERE / "mutation-paths.txt").exists())

    def test_missing_report_skips_and_exits_zero(self) -> None:
        """A missing mutmut report skips with flag_review, exit 0.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
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
        """A score under baseline flags for review but still exits 0.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertTrue(mut.should_flag(0.95))
        self.assertFalse(mut.should_flag(0.98))
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("mutmut-cicd-stats.json").write_text(
                    json.dumps({"killed": 95, "survived": 5, "total": 100})
                )
                self.assertEqual(
                    mut.main(["--report", "mutmut-cicd-stats.json"]), 0
                )
                data = json.loads(Path("mutation-result.json").read_text())
                self.assertTrue(data["flag_review"])
                self.assertFalse(data["skipped"])
                self.assertEqual(data["score"], 0.95)
            finally:
                os.chdir(cwd)

    def test_corrupt_report_still_exits_zero(self) -> None:
        """An unparseable mutmut report skips cleanly, exit 0.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("mutmut-cicd-stats.json").write_text("{not json")
                self.assertEqual(
                    mut.main(["--report", "mutmut-cicd-stats.json"]), 0
                )
                self.assertTrue(
                    json.loads(Path("mutation-result.json").read_text())[
                        "skipped"
                    ]
                )
            finally:
                os.chdir(cwd)


def _write_eval_inputs(report: dict, history: dict) -> None:
    """Write the fake suite entrypoint, one report, and eval history.

    Args:
        report: eval report document; its run_id names the report file.
        history: the eval-history.json document to seed.
    Returns:
        None.
    Raises:
        None.
    """
    Path("Eval-Suite/reports").mkdir(parents=True)
    Path("Eval-Suite/run.py").write_text("print('ok')\n")
    name = f"Eval-Suite/reports/{report['run_id']}.json"
    Path(name).write_text(json.dumps(report))
    Path("eval-history.json").write_text(json.dumps(history))


def _recorded_eval(
    env: dict, report: dict, history: dict, suite_code: int
) -> tuple[int, dict, dict]:
    """Stage a report, run the eval job, and return its outputs.

    Args:
        env: environment variables installed for the job.
        report: eval report placed under Eval-Suite/reports.
        history: eval-history.json document seeded before the run.
        suite_code: exit code the stubbed run_suite returns.
    Returns:
        (exit code, eval-result.json, eval-history.json after the run).
    Raises:
        None.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path.cwd()
        os.chdir(tmp)
        try:
            _write_eval_inputs(report, history)
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(
                    ev, "run_suite", return_value=suite_code
                ):
                    code = ev.main()
            data = json.loads(Path("eval-result.json").read_text())
            after = json.loads(Path("eval-history.json").read_text())
            return code, data, after
        finally:
            os.chdir(cwd)


class EvalScriptTests(unittest.TestCase):
    def test_placeholder_golden_set_is_gone(self) -> None:
        """The old golden-set placeholder files no longer exist.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse((HERE / "eval" / "golden-set.json").exists())
        self.assertFalse((HERE / "eval" / "golden-set.schema.json").exists())
        self.assertFalse((HERE / "eval" / "scenarios.md").exists())

    def test_escalate_only_after_two_weak_weeks(self) -> None:
        """A case only escalates if it was weak this week and last week.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        this = {"a": "fail", "b": "pass", "c": "xpass"}
        hist = {"last_week": {"a": "fail", "b": "fail", "c": "pass"}}
        esc = ev.persist_and_escalate(this, hist)
        self.assertEqual(esc, ["a"])
        self.assertEqual(hist["last_week"]["b"], "pass")

    def test_no_spend_cap_function_left(self) -> None:
        """The old spend_cap_hit function no longer exists on the module.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse(hasattr(ev, "spend_cap_hit"))

    def test_missing_key_fails_open(self) -> None:
        """A missing required env var fails open with the var named in the
        reason.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
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
        """A missing Eval-Suite/run.py skips with that path named in the reason.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
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
        """A weak week's results are recorded and escalated, job still exits 0.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
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
        code, data, _after = _recorded_eval(
            env, report, {"last_week": {"s2": "fail", "s3": "pass"}}, 1
        )
        self.assertEqual(code, 0)
        self.assertFalse(data["skipped"])
        self.assertTrue(data["flag_review"])
        self.assertFalse(data["full_pass"])
        self.assertEqual(data["escalate"], ["s2"])

    def test_clean_eval_is_a_full_pass_and_writes_history(self) -> None:
        """An all-pass week is a full_pass and updates eval-history.json.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        env = {name: "x" for name in ev.REQUIRED_ENV}
        report = {
            "run_id": "20260921-000000",
            "counts": {"pass": 3, "fail": 0, "xfail": 0, "xpass": 0},
            "results": [
                {"case_id": "s1", "status": "pass"},
                {"case_id": "s2", "status": "pass"},
            ],
        }
        code, data, hist = _recorded_eval(
            env, report, {"last_week": {"s1": "pass"}}, 0
        )
        self.assertEqual(code, 0)
        self.assertTrue(data["full_pass"])
        self.assertFalse(data["flag_review"])
        self.assertEqual(hist["last_week"]["s1"], "pass")
        self.assertEqual(hist["last_week"]["s2"], "pass")


class ApplyTests(unittest.TestCase):
    def test_umbrella_only_not_service_repos(self) -> None:
        """Phase3 only ever touches the umbrella repo, never a service repo.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("PHASE3_MUTATION_REPOS=(platform)", LIB)
        self.assertIn("PHASE3_EVAL_REPOS=(platform)", LIB)
        skip = LIB.split("PHASE3_SKIP_REPOS")[1].split(")")[0]
        self.assertIn("admin", skip)
        self.assertIn("text-agent", skip)
        self.assertNotIn("mutation-paths.txt", APPLY)
        self.assertNotIn("golden-set.json", APPLY)
        self.assertNotIn("tag-on-approval.sh", APPLY)
        self.assertNotIn("PHASE3_TAG_SCRIPT", LIB)
        self.assertNotIn("preprod-approved is stamped", APPLY)

    def test_apply_refuses_required_checks(self) -> None:
        """apply-phase3.sh refuses to register phase3 as a required status
        check.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn('die "Phase 3 is not a merge gate', APPLY)

    def test_no_phase3_rulesets(self) -> None:
        """Phase3 ships no rulesets directory of its own.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse((HERE / "rulesets").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
