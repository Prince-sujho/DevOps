#!/usr/bin/env python3
"""Local invariants for Cloud Run job labels and the two GitHub forms."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

CATALOG = json.loads((HERE / "catalog.jobs.json").read_text())
PREPROD = (HERE / "workflows" / "cloud-run-preprod-deploy.yaml").read_text()
PROD = (HERE / "workflows" / "cloud-run-prod-deploy.yaml").read_text()
BUILD = (HERE / "templates" / "job-build-deploy.yaml").read_text()
DEPLOY_ONLY = (HERE / "templates" / "job-deploy-only.yaml").read_text()


class CatalogTests(unittest.TestCase):
    def test_pilot_is_the_live_sessions_job(self) -> None:
        self.assertEqual(CATALOG["pilot"], "knowledge-store-sessions")

    def test_every_catalog_id_has_a_job_json(self) -> None:
        for job in CATALOG["jobs"]:
            path = HERE / "manifests" / job["id"] / "job.json"
            self.assertTrue(path.is_file(), path)
            body = json.loads(path.read_text())
            self.assertEqual(body["kind"], "cloudrun-job")
            self.assertEqual(body["id"], job["id"])
            self.assertEqual(body["cloud_run_job"], job["id"])
            self.assertEqual(body["verb"], job["verb"])
            self.assertEqual(body["needs_entry_id"], job["needs_entry_id"])
            self.assertNotIn("secret_values", body)

    def test_lookup_sessions(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(HERE / "scripts" / "lookup_job.py"), "--id", "knowledge-store-sessions"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("CLOUD_RUN_JOB=knowledge-store-sessions", proc.stdout)
        self.assertIn("NEEDS_ENTRY_ID=0", proc.stdout)
        self.assertIn("IMAGE=knowledge-store-jobs", proc.stdout)


class WorkflowTests(unittest.TestCase):
    def test_old_single_form_is_gone(self) -> None:
        self.assertFalse((HERE / "workflows" / "deploy-cloudrun-job.yml").exists())

    def test_manual_form_only(self) -> None:
        for text in (PREPROD, PROD):
            self.assertIn("workflow_dispatch", text)
            self.assertNotIn("pull_request", text)
            self.assertNotIn("push:", text)

    def test_dropdown_lists_all_jobs(self) -> None:
        for text in (PREPROD, PROD):
            for job in CATALOG["jobs"]:
                self.assertIn(f"- {job['id']}", text)

    def test_no_env_or_mode_inputs(self) -> None:
        for text in (PREPROD, PROD):
            self.assertNotIn("${{ inputs.env }}", text)
            self.assertNotIn("${{ inputs.mode }}", text)
            self.assertNotIn("description: GCP project", text)
            self.assertNotIn("build-and-deploy", text)

    def test_no_github_secrets(self) -> None:
        self.assertNotIn("secrets.", PREPROD)
        self.assertNotIn("secrets.", PROD)

    def test_preprod_builds_prod_does_not(self) -> None:
        self.assertIn("sujho-preprod", PREPROD)
        self.assertIn("ci/jobs/job-build-deploy.yaml", PREPROD)
        self.assertNotIn("ci/jobs/job-deploy-only.yaml", PREPROD)
        self.assertNotIn("kaniko", PREPROD)
        self.assertIn("sujho-478914", PROD)
        self.assertIn("ci/jobs/job-deploy-only.yaml", PROD)
        self.assertNotIn("ci/jobs/job-build-deploy.yaml", PROD)
        self.assertNotIn("kaniko", PROD)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_PREPROD", PREPROD)
        self.assertNotIn("GCP_WIF_SERVICE_ACCOUNT_PROD", PREPROD)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_PROD", PROD)
        self.assertNotIn("GCP_WIF_SERVICE_ACCOUNT_PREPROD", PROD)

    def test_preprod_submits_cloud_build_in_sujho_dev(self) -> None:
        submit = PREPROD.split("Execute job once")[0]
        self.assertIn("BUILD_PROJECT: sujho-dev", submit)
        self.assertIn("TARGET_PROJECT: sujho-preprod", submit)
        self.assertIn('--project="$BUILD_PROJECT"', submit)
        self.assertNotIn('--project="$PROJECT"', submit)
        self.assertIn("_TARGET_PROJECT=\"$TARGET_PROJECT\"", submit)

    def test_forms_pass_commit_sha(self) -> None:
        for text in (PREPROD, PROD):
            self.assertIn("_COMMIT_SHA=", text)
            self.assertIn("_SHORT_SHA=", text)
            self.assertIn("inputs.commit || github.sha", text)
            self.assertIn("Refuse unless this run is on main", text)
            self.assertIn('github.ref }}" != "refs/heads/main"', text)

    def test_prod_passes_image_digest_preprod_does_not(self) -> None:
        self.assertIn('PIN_DIGEST: "1"', PROD)
        self.assertIn("_IMAGE_DIGEST=", PROD)
        self.assertIn('PIN_DIGEST: "0"', PREPROD)

    def test_concurrency_does_not_cancel_in_progress(self) -> None:
        for text in (PREPROD, PROD):
            self.assertIn("concurrency:", text)
            self.assertIn("cancel-in-progress: false", text)

    def test_actions_are_sha_pinned(self) -> None:
        pins = json.loads((HERE.parent.parent / "action-pins.json").read_text())["pins"]
        checkout = f"actions/checkout@{pins['actions/checkout']['sha']}"
        for text in (PREPROD, PROD):
            self.assertIn(checkout, text)
            self.assertNotIn("actions/checkout@v4\n", text)
            self.assertNotIn("google-github-actions/auth@v2\n", text)

    def test_generator_is_not_stale(self) -> None:
        import generate_job_workflow as gen

        self.assertEqual(gen.render_preprod(), PREPROD)
        self.assertEqual(gen.render_prod(), PROD)


class YamlTests(unittest.TestCase):
    def test_no_latest_tag(self) -> None:
        self.assertNotIn(":latest", BUILD)
        self.assertNotIn(":latest", DEPLOY_ONLY)

    def test_prod_build_refused(self) -> None:
        self.assertIn("must not target Prod", BUILD)

    def test_deploy_only_uses_preprod_approved(self) -> None:
        self.assertIn("preprod-approved", DEPLOY_ONLY)
        self.assertNotIn("kaniko", DEPLOY_ONLY)
        self.assertIn("${_IMAGE_DIGEST}", DEPLOY_ONLY)
        self.assertIn("Refuse: pass _IMAGE_DIGEST", DEPLOY_ONLY)
        self.assertIn("${_REGISTRY}/$${IMAGE}@$${DIGEST}", DEPLOY_ONLY)

    def test_templates_use_passed_sha_not_trigger_builtins(self) -> None:
        self.assertIn("${_COMMIT_SHA}", BUILD)
        self.assertIn("${_SHORT_SHA}", BUILD)
        self.assertIn("${_COMMIT_SHA}", DEPLOY_ONLY)
        self.assertNotIn("revision: ${COMMIT_SHA}", BUILD)
        self.assertNotIn("revision: ${COMMIT_SHA}", DEPLOY_ONLY)
        self.assertNotIn("sha-${SHORT_SHA}", BUILD)
        self.assertIn("_COMMIT_SHA/_SHORT_SHA empty", BUILD)
        self.assertIn("_COMMIT_SHA empty", DEPLOY_ONLY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
