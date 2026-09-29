#!/usr/bin/env python3
"""Local invariants for job config and derivation — no manifests, no
generators."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CI = HERE.parent / "ci"

CATALOG = json.loads((HERE / "catalog.jobs.json").read_text())
PREPROD = (HERE / "workflows" / "cloud-run-preprod-job.yaml").read_text()
PROD = (HERE / "workflows" / "cloud-run-prod-job.yaml").read_text()
BUILD = (CI / "job-build-deploy.yaml").read_text()
DEPLOY_ONLY = (CI / "job-deploy-only.yaml").read_text()


def lookup(job_id: str) -> dict[str, str]:
    """Shell out to lookup_job.py for one job id's derived fields, as JSON.

    Args:
        job_id: the catalog job id to look up.
    Returns:
        The derived fields as a dict.
    Raises:
        subprocess.CalledProcessError: job_id isn't in the catalog.
    """
    proc = subprocess.run(
        [
            sys.executable,
            str(HERE / "scripts" / "lookup_job.py"),
            "--id",
            job_id,
            "--format=json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


class CatalogTests(unittest.TestCase):
    def test_no_manifests_folder_left(self) -> None:
        """The old manifests/ directory no longer exists.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse(
            (HERE / "manifests").exists(),
            "manifests/ should be gone (design change 3)",
        )

    def test_no_schema_file_left(self) -> None:
        """The old schema.job.json no longer exists.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse(
            (HERE / "schema.job.json").exists(),
            "no manifest to validate against a schema anymore",
        )

    def test_every_job_id_matches_exactly_one_image_group(self) -> None:
        """Every catalog job id resolves via lookup_job.py to itself.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for job in CATALOG["jobs"]:
            data = lookup(job["id"])
            self.assertEqual(data["JOB_ID"], job["id"])

    def test_sessions_is_hourly_and_others_are_run_by_hand(self) -> None:
        """Only the sessions job has a schedule; the rest are run by hand.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        by_id = {j["id"]: j for j in CATALOG["jobs"]}
        self.assertEqual(
            by_id["knowledge-store-sessions"].get("schedule"), "0 * * * *"
        )
        for job_id in (
            "knowledge-store-ingest",
            "knowledge-store-remove",
            "knowledge-store-import-ncert",
            "knowledge-store-import-educart",
        ):
            self.assertNotIn(
                "schedule",
                by_id[job_id],
                f"{job_id} should be run-by-hand only",
            )

    def test_entry_module_derivation(self) -> None:
        """A job's entry module and file are derived correctly from its id.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        cases = {
            "knowledge-store-sessions": "knowledge_store.jobs.sessions",
            "knowledge-store-import-ncert": "knowledge_store.jobs.import_ncert",
            "knowledge-store-import-educart": "knowledge_store.jobs.import_educ"
            "art",
        }
        for job_id, expected_module in cases.items():
            data = lookup(job_id)
            self.assertEqual(data["ENTRY_MODULE"], expected_module)
            self.assertEqual(
                data["ENTRY_FILE"], expected_module.replace(".", "/") + ".py"
            )

    def test_needs_entry_id_only_on_ingest_and_remove(self) -> None:
        """Only ingest and remove require an entry_id; the others don't.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for job_id in ("knowledge-store-ingest", "knowledge-store-remove"):
            self.assertEqual(lookup(job_id)["NEEDS_ENTRY_ID"], "1")
        no_id_jobs = (
            "knowledge-store-sessions",
            "knowledge-store-import-ncert",
            "knowledge-store-import-educart",
        )
        for job_id in no_id_jobs:
            self.assertEqual(lookup(job_id)["NEEDS_ENTRY_ID"], "0")

    def test_ingest_overrides_group_memory(self) -> None:
        # ingest overrides the group's default memory
        """The ingest job's own memory override beats the group default.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertEqual(lookup("knowledge-store-ingest")["MEMORY"], "4Gi")

    def test_unlisted_job_id_refuses(self) -> None:
        """An id not in the catalog makes lookup_job.py exit nonzero.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "scripts" / "lookup_job.py"),
                    "--id",
                    "not-a-real-job",
                ],
                check=True,
                capture_output=True,
                text=True,
            )


class WorkflowTests(unittest.TestCase):
    def test_no_sujho_dev_job_workflow_remains(self) -> None:
        """sujho-dev has no job deploy workflow of its own.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse(
            (HERE / "workflows" / "cloud-run-dev-deploy.yaml").exists(),
            "sujho-dev has no CI (decision 13)",
        )

    def test_manual_form_only(self) -> None:
        """Both job workflows are manual dispatch only, never push/pull_request.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for text in (PREPROD, PROD):
            self.assertIn("workflow_dispatch", text)
            self.assertNotIn("pull_request", text)
            self.assertNotIn("\non:\n  push", text)

    def test_dropdown_lists_all_jobs(self) -> None:
        """Every catalog job id appears in both workflows' dropdown.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for text in (PREPROD, PROD):
            for job in CATALOG["jobs"]:
                self.assertIn(f"- {job['id']}", text)

    def test_preprod_and_prod_check_ancestor_of_main(self) -> None:
        """Both workflows verify the requested commit is an ancestor of main.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for text in (PREPROD, PROD):
            self.assertIn("merge-base --is-ancestor", text)
            self.assertIn("fetch-depth: 0", text)

    def test_prod_has_the_approval_gate_preprod_does_not(self) -> None:
        """Only Prod's workflow requires the production environment gate.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("environment: production", PROD)
        self.assertNotIn("environment: production", PREPROD)

    def test_prod_commit_input_is_required(self) -> None:
        """Prod's commit input is required; Pre-Prod's is intentionally
        optional.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        commit_input = PROD.split("commit:")[1].split("entry_id:")[0]
        self.assertIn("required: true", commit_input)

    def test_preprod_calls_build_prod_calls_deploy_only(self) -> None:
        """Pre-Prod builds; Prod only promotes an existing image.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("ci/job-build-deploy.yaml", PREPROD)
        self.assertNotIn("ci/job-deploy-only.yaml", PREPROD)
        self.assertIn("ci/job-deploy-only.yaml", PROD)
        self.assertNotIn("ci/job-build-deploy.yaml", PROD)

    def test_prod_refuses_unless_image_exists(self) -> None:
        """Prod refuses to deploy an image that was never built.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("Refuse:", PROD)
        self.assertIn("does not exist", PROD)

    def test_concurrency_does_not_cancel_in_progress(self) -> None:
        """Both workflows serialize runs per job without cancelling one in
        flight.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for text in (PREPROD, PROD):
            self.assertIn("concurrency:", text)
            self.assertIn("cancel-in-progress: false", text)

    def test_execute_needs_entry_id_check_present(self) -> None:
        """Both workflows check NEEDS_ENTRY_ID before executing a job.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for text in (PREPROD, PROD):
            self.assertIn("NEEDS_ENTRY_ID", text)
            self.assertIn("needs entry_id to execute", text)


class CloudBuildRecipeTests(unittest.TestCase):
    def test_no_forbidden_patterns(self) -> None:
        """Neither Cloud Build recipe references a retired tag, path, or
        :latest.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        recipes = (
            (BUILD, "job-build-deploy.yaml"),
            (DEPLOY_ONLY, "job-deploy-only.yaml"),
        )
        for body, name in recipes:
            for pattern in (
                ":latest",
                "preprod-approved",
                "prod-live",
                "manifests/",
            ):
                self.assertNotIn(
                    pattern,
                    body,
                    f"{name} contains forbidden pattern: {pattern}",
                )

    def test_deploy_only_never_builds(self) -> None:
        """Only the build recipe invokes Kaniko; deploy-only never does.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertNotIn("kaniko", DEPLOY_ONLY)
        self.assertIn("kaniko", BUILD)

    def test_entry_file_checked_before_build(self) -> None:
        """The entry-file existence check runs before the image build step.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        check_idx = BUILD.index("check-entry-file-exists")
        build_idx = BUILD.index("build-image")
        self.assertLess(check_idx, build_idx)

    def test_fetches_sujho_before_anything_else(self) -> None:
        # --no-source means an empty workspace; fetch-sujho has to be first
        # and inline, since it can't call a script from the unfetched repo
        """fetch-sujho is the first step, inline, before any script call.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("id: fetch-sujho", BUILD)
        fetch_idx = BUILD.index("id: fetch-sujho")
        next_idx = BUILD.index("id: check-entry-file-exists")
        self.assertLess(fetch_idx, next_idx)
        step = BUILD.split("id: fetch-sujho")[1].split(
            "id: check-entry-file-exists"
        )[0]
        self.assertNotIn("python3 ci/", step)
        self.assertIn("git init", step)

    def test_gate_1_installs_git_for_the_secrets_hook_file_list(self) -> None:
        """Gate 1 installs git so the secrets hook can list changed files.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        gate1 = BUILD.split("id: gate-1-static")[1].split("waitFor")[0]
        self.assertIn("apt-get install -y -qq git", gate1)

    def test_gate_1_baselines_against_the_deployed_job_not_a_pr(self) -> None:
        """Gate 1's mypy baseline reads the deployed job's commit, not a PR's.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("mypy_ratchet.py", BUILD)
        self.assertIn("--baseline-commit", BUILD)
        self.assertIn("resolve_baseline.py --kind=jobs", BUILD)

    def test_secrets_baseline_points_at_the_real_file(self) -> None:
        """The secrets baseline path matches the file actually committed.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertIn("tests/ci/.secrets.baseline", BUILD)
        self.assertNotIn("--baseline .secrets.baseline ", BUILD)

    def test_schedule_sync_runs_after_deploy_in_both_recipes(self) -> None:
        """sync-schedule always runs after deploy-job in both recipes.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for body in (BUILD, DEPLOY_ONLY):
            deploy_idx = body.index("deploy-job")
            sync_idx = body.index("sync-schedule")
            self.assertLess(deploy_idx, sync_idx)

    def test_kaniko_step_has_no_bash_entrypoint_override(self) -> None:
        # kaniko's image has no shell — never entrypoint: bash on it
        """The Kaniko step never overrides entrypoint to bash — its image has no
        shell.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        kaniko_step = BUILD.split("build-image")[1].split("waitFor")[0]
        self.assertNotIn("entrypoint: bash", kaniko_step)


if __name__ == "__main__":
    unittest.main(verbosity=2)
