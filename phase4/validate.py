#!/usr/bin/env python3
"""Local invariants for Phase 4 — no GitHub, GCP, or gcloud required."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scripts"))
import generate_cloudbuild  # noqa: E402
import generate_rollback  # noqa: E402
import generate_service_workflow  # noqa: E402
import generate_approve  # noqa: E402
import pick_rollback_revision  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "checkout_gitlinks", HERE / "ci" / "checkout-gitlinks.py"
)
checkout_gitlinks = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(checkout_gitlinks)

CATALOG = json.loads((HERE / "catalog.json").read_text())
PHASE1_MAIN = json.loads((HERE.parent / "phase1" / "rulesets" / "main.json").read_text())
APPLY = (HERE / "apply-phase4.sh").read_text()
TAG = (HERE / "scripts" / "tag-on-approval.sh").read_text()
PROVISION = (HERE / "scripts" / "provision-projects.sh").read_text()
WIF = (HERE / "scripts" / "provision-wif.sh").read_text()
DC_SETUP = (HERE / "scripts" / "developer-connect-setup.sh").read_text()
PIN = (HERE / "scripts" / "pin-submodules.sh").read_text()
CHECKOUT = (HERE / "ci" / "checkout-gitlinks.py").read_text()


def _merge_methods(ruleset: dict) -> list[str]:
    for rule in ruleset["rules"]:
        if rule.get("type") == "pull_request":
            return rule["parameters"]["allowed_merge_methods"]
    raise AssertionError("no pull_request rule")


def _all_yaml() -> dict[str, str]:
    out = {}
    for path in sorted((HERE / "ci").glob("*.yaml")):
        out[path.name] = path.read_text()
    return out


def _rev(name: str, ts: str, ready: bool = True) -> dict:
    return {
        "metadata": {"name": name, "creationTimestamp": ts},
        "status": {
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]
        },
    }


def _serving(name: str, percent: int = 100) -> dict:
    return {"status": {"traffic": [{"revisionName": name, "percent": percent}]}}


def _rollback_yaml_forms(text: str) -> tuple[str, str]:
    """The exact bash line and extra=() the generated form emits."""
    submit = extra = ""
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("bash scripts/rollback-cloudrun.sh"):
            submit = s
        if s.startswith("extra=("):
            extra = s
    return submit, extra


class CatalogTests(unittest.TestCase):
    def test_pilot_is_redirect_only(self) -> None:
        self.assertEqual(CATALOG["pilot"], "redirect")
        pilots = [s["id"] for s in CATALOG["services"] if s.get("pilot")]
        self.assertEqual(pilots, ["redirect"])

    def test_firestore_and_jobs_are_not_docker_split(self) -> None:
        self.assertIn("firestore", CATALOG["skip_split"])
        self.assertIn("knowledge-store-jobs", CATALOG["skip_split"])
        ids = {s["id"] for s in CATALOG["services"]}
        self.assertNotIn("firestore", ids)
        self.assertNotIn("knowledge-store-jobs", ids)

    def test_live_dockerfile_paths(self) -> None:
        by_id = {s["id"]: s for s in CATALOG["services"]}
        self.assertEqual(by_id["redirect"]["dockerfile"], "redirect_service/app/Dockerfile")
        self.assertEqual(by_id["text"]["dockerfile"], "text_agent/app/Dockerfile")
        self.assertEqual(by_id["users"]["dockerfile"], "user_service/app/Dockerfile")
        self.assertEqual(by_id["whatsapp"]["dockerfile"], "whatsapp_adapter/app/Dockerfile")
        self.assertEqual(by_id["admin"]["dockerfile"], "admin/app/Dockerfile")
        self.assertEqual(by_id["document-worker"]["dockerfile"], "document_worker/Dockerfile")

    def test_short_sha_matches_cloud_build(self) -> None:
        self.assertEqual(CATALOG["short_sha_len"], 7)

    def test_infra_on_every_cloudrun_filter(self) -> None:
        for svc in CATALOG["services"]:
            self.assertIn("infra/**", svc["included_files"])

    def test_4a_fields_are_gone(self) -> None:
        self.assertNotIn("path_filter_only", CATALOG)
        self.assertNotIn("never_trigger", CATALOG)
        self.assertFalse((HERE / "scripts" / "path_filters.py").exists())
        self.assertFalse((HERE / "scripts" / "path-filters.sh").exists())
        for svc in CATALOG["services"]:
            self.assertNotIn("included_files_4a", svc)
            self.assertNotIn("trigger_now", svc)


class GeneratedYamlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        generate_cloudbuild.write_all(HERE)
        cls.files = generate_cloudbuild.render_all()
        cls.yaml = _all_yaml()

    def test_on_disk_matches_renderer(self) -> None:
        for rel, body in self.files.items():
            on_disk = (HERE / rel).read_text()
            expected = body if body.endswith("\n") else body + "\n"
            self.assertEqual(on_disk, expected, rel)

    def test_no_latest_destination(self) -> None:
        for name, body in self.yaml.items():
            for line in body.splitlines():
                if "--destination=" in line:
                    self.assertNotIn(":latest", line, name)

    def test_no_set_env_vars(self) -> None:
        for name, body in self.yaml.items():
            self.assertNotIn("--set-env-vars", body, name)
            self.assertIn("--update-env-vars", body, name)

    def test_deploy_only_has_no_kaniko(self) -> None:
        for name, body in self.yaml.items():
            if name.endswith("-deploy-only.yaml"):
                self.assertNotIn("kaniko-project", body, name)
                self.assertIn("preprod-approved", body, name)
                self.assertIn("prod-live", body, name)
                self.assertIn("COMMIT_SHA", body, name)
                self.assertNotIn("HEAD^2", body, name)

    def test_build_deploy_does_not_write_promotion_tag(self) -> None:
        for name, body in self.yaml.items():
            if name.endswith("-build-deploy.yaml"):
                self.assertNotIn("preprod-approved", body, name)
                self.assertNotIn("prod-live", body, name)
                self.assertIn("sha-${_SHORT_SHA}", body, name)
                self.assertIn("kaniko", body.lower(), name)

    def test_no_floating_gitsource_main(self) -> None:
        for name, body in self.yaml.items():
            self.assertNotIn("revision: main", body, name)
            self.assertIn("revision: ${_COMMIT_SHA}", body, name)

    def test_no_submodule_remote(self) -> None:
        for path in sorted((HERE / "ci").glob("*.yaml")):
            self.assertNotIn("submodule update --remote", path.read_text(), path.name)
        self.assertNotIn("submodule update --remote", (HERE / "generate_cloudbuild.py").read_text())
        self.assertNotIn("submodule update --remote", CHECKOUT)

    def test_images_are_sha256_pinned(self) -> None:
        for name, body in self.yaml.items():
            self.assertIn(CATALOG["gcloud"], body, name)
            if name.endswith("-build-deploy.yaml"):
                self.assertIn(CATALOG["kaniko"], body, name)
            self.assertNotIn("gcr.io/kaniko-project/executor:latest", body, name)
            self.assertNotIn("gcr.io/cloud-builders/gcloud\n", body, name)

    def test_runtime_sa_is_not_copied_from_prod(self) -> None:
        for name, body in self.yaml.items():
            self.assertNotIn("sujho-478914.iam.gserviceaccount.com", body, name)

    def test_no_trigger_guard(self) -> None:
        for name, body in self.yaml.items():
            self.assertNotIn("id: trigger-guard", body, name)
            self.assertNotIn("_EXPECTED_TRIGGER_NAME", body, name)
            self.assertNotIn("_BUILD_CONFIG_PATH", body, name)
            self.assertNotIn("_ENV:", body, name)
            self.assertIn("_COMMIT_SHA", body, name)
            self.assertIn("_SHORT_SHA", body, name)
        src = (HERE / "generate_cloudbuild.py").read_text()
        self.assertNotIn("def guard_script", src)

    def test_prod_live_follows_target_project_not_env_knob(self) -> None:
        for name, body in self.yaml.items():
            if name.endswith("-deploy-only.yaml"):
                self.assertIn('"${_TARGET_PROJECT}" = "sujho-478914"', body, name)
                self.assertNotIn('"${_ENV}" = "prod"', body, name)

    def test_block_scripts_stay_indented(self) -> None:
        for name, body in self.yaml.items():
            self.assertNotIn("\n- |\nset ", body, name)
            self.assertIn("      - |\n        set -euo pipefail", body, name)

    def test_pilot_files_exist(self) -> None:
        self.assertIn("ci/redirect-build-deploy.yaml", self.files)
        self.assertIn("ci/redirect-deploy-only.yaml", self.files)

    def test_verify_before_user_traffic(self) -> None:
        src = (HERE / "generate_cloudbuild.py").read_text()
        self.assertIn("--no-traffic", src)
        self.assertIn("update-traffic", src)
        self.assertIn("shift-traffic", src)
        for name, body in self.yaml.items():
            self.assertIn("--no-traffic", body, name)
            self.assertIn("id: shift-traffic", body, name)
            self.assertIn("--to-revisions=", body, name)
            self.assertIn("deploy.revision", body, name)
            self.assertIn("Traffic was not shifted", body, name)
        health = self.yaml["redirect-build-deploy.yaml"]
        self.assertIn("$$REV_URL/health", health)
        self.assertNotIn("$$SERVICE_URL/health", health)
        self.assertIn("waitFor: [shift-traffic]", self.yaml["redirect-deploy-only.yaml"])

    def test_deploy_only_pins_sha_digest_not_a_floating_tag(self) -> None:
        src = (HERE / "generate_cloudbuild.py").read_text()
        self.assertIn("_IMAGE_DIGEST", src)
        self.assertIn("TOCTOU", src)
        for name, body in self.yaml.items():
            if not name.endswith("-deploy-only.yaml"):
                continue
            self.assertIn("sha-$$SHORT", body, name)
            self.assertIn("/workspace/deploy.digest", body, name)
            self.assertIn("@$${DEPLOY_DIGEST}", body, name)
            self.assertNotIn(":preprod-approved --quiet", body, name)

    def test_preprod_min_instances_is_zero(self) -> None:
        src = (HERE / "generate_cloudbuild.py").read_text()
        self.assertIn('MIN_INSTANCES=0', src)
        for name, body in self.yaml.items():
            self.assertIn("--min-instances=$$MIN_INSTANCES", body, name)

    def test_default_target_is_preprod_not_dev(self) -> None:
        for name, body in self.yaml.items():
            self.assertIn("  _TARGET_PROJECT: sujho-preprod", body, name)
            self.assertNotIn("  _TARGET_PROJECT: sujho-dev", body, name)
            self.assertNotIn("  _TARGET_PROJECT: sujho-478914", body, name)


class ScriptTests(unittest.TestCase):
    def test_tag_script_uses_seven_char_sha(self) -> None:
        self.assertNotIn("${COMMIT_SHA:0:12}", TAG)
        self.assertIn("SHORT_LEN", TAG)
        self.assertIn("preprod-approved", TAG)
        self.assertIn("cannot approve", TAG)

    def test_tag_on_approval_empty_digest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "gcloud"
            fake.write_text("#!/bin/sh\necho ''\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            env = os.environ.copy()
            env["PATH"] = tmp + ":" + env["PATH"]
            proc = subprocess.run(
                ["bash", str(HERE / "scripts" / "tag-on-approval.sh"), "abcdef1234567", "redirect"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("cannot approve", proc.stderr)

    def test_tag_on_approval_rejects_unknown_service(self) -> None:
        proc = subprocess.run(
            ["bash", str(HERE / "scripts" / "tag-on-approval.sh"), "abcdef1234567", "firestore"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("allowlist", proc.stderr)

    def test_tag_on_approval_all_is_refused_without_override(self) -> None:
        proc = subprocess.run(
            [
                "bash",
                str(HERE / "scripts" / "tag-on-approval.sh"),
                "--dry-run",
                "abcdef1234567",
                "--all",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("Refuse: --all", proc.stderr)
        self.assertNotIn("preprod-approved", proc.stdout)

    def test_tag_on_approval_all_dry_run_with_override_includes_jobs_image(self) -> None:
        env = os.environ.copy()
        env["SUJHO_APPROVE_ALL"] = "1"
        proc = subprocess.run(
            [
                "bash",
                str(HERE / "scripts" / "tag-on-approval.sh"),
                "--dry-run",
                "abcdef1234567",
                "--all",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("redirect", proc.stdout)
        self.assertIn("knowledge-store-jobs", proc.stdout)
        self.assertIn("preprod-approved", proc.stdout)
        self.assertNotIn("firestore", proc.stdout)

    def test_provision_refuses_placeholders(self) -> None:
        self.assertNotIn("${PROJECT^}", PROVISION)
        env = os.environ.copy()
        env["ORG_ID"] = "REPLACE_WITH_YOUR_ORG_ID"
        env["BILLING_ACCOUNT_ID"] = "REPLACE_WITH_YOUR_BILLING_ACCOUNT_ID"
        proc = subprocess.run(
            ["bash", str(HERE / "scripts" / "provision-projects.sh")],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("placeholders", proc.stderr)

    def test_wif_pins_owner_id_and_splits_identities(self) -> None:
        self.assertIn("repository_owner_id", WIF)
        self.assertIn("github-deploy-preprod", WIF)
        self.assertIn("github-deploy-prod", WIF)
        self.assertIn("github-ai-review", WIF)
        self.assertIn("github-eval", WIF)
        self.assertIn("Do NOT grant github-deploy-preprod any role on ${PROD_PROJECT}", WIF)
        self.assertNotIn("gh variable", WIF)
        self.assertNotIn("secrets.", WIF)
        env = os.environ.copy()
        env["GITHUB_OWNER_ID"] = "REPLACE_WITH_GITHUB_ORG_NUMERIC_ID"
        proc = subprocess.run(
            ["bash", str(HERE / "scripts" / "provision-wif.sh")],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("placeholder", proc.stderr)

    def test_wif_dry_run_prints_and_does_not_need_gcloud(self) -> None:
        env = os.environ.copy()
        env["GITHUB_OWNER_ID"] = "123456789"
        proc = subprocess.run(
            ["bash", str(HERE / "scripts" / "provision-wif.sh")],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        self.assertIn("assertion.repository_owner_id == '123456789'", proc.stdout)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_PROD", proc.stdout)
        self.assertNotIn("fatal", proc.stdout.lower())

    def test_developer_connect_prints_and_does_not_create(self) -> None:
        self.assertNotIn("gcloud builds connections create", DC_SETUP.split("echo", 1)[0])
        self.assertIn("This script only prints commands", DC_SETUP)
        self.assertIn("echo \"  gcloud builds connections create", DC_SETUP)
        proc = subprocess.run(
            ["bash", str(HERE / "scripts" / "developer-connect-setup.sh")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("gcloud builds connections create github sujho-github-dc", proc.stdout)

    def test_pin_submodules_refuses_branch_and_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitmodules").write_text(
                '[submodule "infra"]\n\tpath = infra\n\turl = https://github.com/Sujho/infra.git\n\tbranch = main\n'
            )
            proc = subprocess.run(
                ["bash", str(HERE / "scripts" / "pin-submodules.sh"), tmp],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("branch =", proc.stderr)

    def test_checkout_parses_gitlinks(self) -> None:
        gm = '[submodule "redirect_service"]\n\tpath = redirect_service\n\turl = https://github.com/Sujho/redirect-service.git\n'
        tree = "160000 commit 0123456789abcdef0123456789abcdef01234567\tredirect_service\n"
        self.assertEqual(
            checkout_gitlinks.parse_gitmodules(gm)["redirect_service"]["url"],
            "https://github.com/Sujho/redirect-service.git",
        )
        self.assertEqual(
            checkout_gitlinks.gitlinks_from_ls_tree(tree)["redirect_service"],
            "0123456789abcdef0123456789abcdef01234567",
        )
        self.assertEqual(
            checkout_gitlinks.dc_link_name("https://github.com/Sujho/redirect-service.git"),
            "sujho-redirect-service",
        )
        with tempfile.TemporaryDirectory() as tmp:
            gmf = Path(tmp) / "gm"
            lsf = Path(tmp) / "ls"
            gmf.write_text(gm)
            lsf.write_text(tree)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "ci" / "checkout-gitlinks.py"),
                    "--gitmodules-file",
                    str(gmf),
                    "--ls-tree-file",
                    str(lsf),
                    "--print-only",
                    "--paths",
                    "redirect_service",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("0123456789abcdef0123456789abcdef01234567", proc.stdout)
            self.assertIn("sujho-redirect-service", proc.stdout)
            self.assertIn("DC link", proc.stdout)

    def test_checkout_does_not_fall_back_to_public_https(self) -> None:
        self.assertIn("DC link missing", CHECKOUT)
        self.assertIn("Never fall back", CHECKOUT)
        self.assertNotIn("except (subprocess.CalledProcessError, FileNotFoundError):\n        pass", CHECKOUT)
        with self.assertRaises(SystemExit) as ctx:
            checkout_gitlinks.clone_uri(
                url="https://github.com/Sujho/redirect-service.git",
                project="",
                region="asia-south1",
                connection="sujho-github-dc",
            )
        self.assertIn("PROJECT_ID", str(ctx.exception))
        with mock.patch.object(
            checkout_gitlinks,
            "run",
            side_effect=subprocess.CalledProcessError(1, "gcloud", stderr="NOT_FOUND"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                checkout_gitlinks.clone_uri(
                    url="https://github.com/Sujho/redirect-service.git",
                    project="sujho-dev",
                    region="asia-south1",
                    connection="sujho-github-dc",
                )
            self.assertIn("DC link missing", str(ctx.exception))
            self.assertIn("Do not clone", str(ctx.exception))

    def test_provision_uses_cloud_build_default_sa_not_legacy_only(self) -> None:
        self.assertIn("get-default-service-account", PROVISION)
        self.assertIn("gcp-sa-cloudbuild.iam.gserviceaccount.com", PROVISION)
        self.assertIn("roles/run.developer", PROVISION)
        self.assertIn("roles/cloudbuild.builds.editor", PROVISION)
        self.assertIn("NUM@cloudbuild.gserviceaccount.com as the only identity", PROVISION)
        self.assertIn('grant_run_in_project "$PREPROD_PROJECT" "$DEV_CB"', PROVISION)
        self.assertNotIn('grant_run_in_project "$PREPROD_PROJECT" "$PREPROD_CB"', PROVISION)
        self.assertIn('grant_ar "$DEV_CB" "roles/artifactregistry.writer"', PROVISION)
        self.assertIn('grant_ar "$PROD_CB" "roles/artifactregistry.reader"', PROVISION)
        self.assertNotIn('grant_ar "$PREPROD_CB"', PROVISION)

    def test_wif_preprod_is_ar_reader_not_writer(self) -> None:
        self.assertRegex(
            WIF,
            r'github-deploy-preprod\)" \\\n  --role="roles/artifactregistry.reader"',
        )
        self.assertNotRegex(
            WIF,
            r'github-deploy-preprod\)" \\\n  --role="roles/artifactregistry.writer"',
        )
        self.assertIn("roles/cloudbuild.builds.editor", WIF)
        self.assertIn('gcloud projects add-iam-policy-binding "$DEV_PROJECT"', WIF)

    def test_rollback_yaml_equals_form_is_what_the_script_runs(self) -> None:
        generate_rollback.main()
        pre = (HERE / "workflows" / "cloud-run-preprod-rollback.yaml").read_text()
        submit, extra = _rollback_yaml_forms(pre)
        self.assertTrue(submit, "workflow is missing the rollback script line")
        self.assertIn('--project="$PROJECT"', submit)
        self.assertIn('--service="$SERVICE"', submit)
        self.assertNotIn('--project "$PROJECT"', submit)
        self.assertNotIn('--service "$SERVICE"', submit)
        self.assertIn('--revision="$REVISION"', extra)
        self.assertNotIn('--revision "$REVISION"', extra)

        script = HERE / "scripts" / "rollback-cloudrun.sh"
        empty = subprocess.run(
            [
                "bash",
                str(script),
                "--dry-run",
                "--project=sujho-preprod",
                "--service=redirect",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(empty.returncode, 0, empty.stderr + empty.stdout)
        self.assertIn("WOULD_QUERY", empty.stdout)
        self.assertIn("update-traffic", empty.stdout)
        self.assertIn("--project=sujho-preprod", empty.stdout)

        named = subprocess.run(
            [
                "bash",
                str(script),
                "--dry-run",
                "--project=sujho-preprod",
                "--service=redirect",
                "--revision=redirect-00002",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(named.returncode, 0, named.stderr + named.stdout)
        self.assertIn("redirect-00002=100", named.stdout)
        self.assertNotIn("WOULD_QUERY", named.stdout)

    def test_rollback_forms_are_two_files_and_pinned(self) -> None:
        generate_rollback.main()
        pre = (HERE / "workflows" / "cloud-run-preprod-rollback.yaml").read_text()
        prod = (HERE / "workflows" / "cloud-run-prod-rollback.yaml").read_text()
        pins = json.loads((HERE.parent / "action-pins.json").read_text())["pins"]
        checkout = f"actions/checkout@{pins['actions/checkout']['sha']}"
        self.assertIn("sujho-preprod", pre)
        self.assertNotIn("sujho-478914", pre)
        self.assertIn("sujho-478914", prod)
        self.assertNotIn("sujho-preprod", prod)
        for text in (pre, prod):
            self.assertIn("workflow_dispatch", text)
            self.assertIn("concurrency:", text)
            self.assertIn("cancel-in-progress: false", text)
            self.assertIn(checkout, text)
            self.assertIn("Refuse unless this run is on main", text)
            self.assertIn('github.ref }}" != "refs/heads/main"', text)
            self.assertNotIn("actions/checkout@v4\n", text)
            self.assertNotIn("secrets.", text)
            self.assertIn("rollback-cloudrun.sh", text)
        self.assertEqual(generate_rollback.render(
            "Rollback Cloud Run service (Pre-Prod)",
            "sujho-preprod",
            "GCP_WIF_SERVICE_ACCOUNT_PREPROD",
        ), pre)

    def test_pick_rollback_takes_older_ready_not_newer_unverified(self) -> None:
        older = _rev("redirect-00001", "2026-09-01T00:00:00Z")
        serving = _rev("redirect-00002", "2026-09-02T00:00:00Z")
        newer = _rev("redirect-00003", "2026-09-03T00:00:00Z")
        self.assertEqual(
            pick_rollback_revision.pick_previous(
                _serving("redirect-00002"), [older, serving]
            ),
            "redirect-00001",
        )
        with self.assertRaises(SystemExit) as ctx:
            pick_rollback_revision.pick_previous(
                _serving("redirect-00002"), [older, serving, newer]
            )
        self.assertIn("newer than the one serving users", str(ctx.exception))
        self.assertIn("redirect-00003", str(ctx.exception))
        with self.assertRaises(SystemExit) as ctx:
            pick_rollback_revision.pick_previous(
                {
                    "status": {
                        "traffic": [
                            {"revisionName": "redirect-00001", "percent": 50},
                            {"revisionName": "redirect-00002", "percent": 50},
                        ]
                    }
                },
                [older, serving],
            )
        self.assertIn("not 100%", str(ctx.exception))

    def test_service_forms_build_in_dev_deploy_to_env(self) -> None:
        generate_service_workflow.main()
        pre = (HERE / "workflows" / "cloud-run-preprod-service.yaml").read_text()
        prod = (HERE / "workflows" / "cloud-run-prod-service.yaml").read_text()
        self.assertEqual(generate_service_workflow.render_preprod(), pre)
        self.assertEqual(generate_service_workflow.render_prod(), prod)
        self.assertIn("BUILD_PROJECT: sujho-dev", pre)
        self.assertIn("TARGET_PROJECT: sujho-preprod", pre)
        self.assertIn('--project="$BUILD_PROJECT"', pre)
        self.assertIn("ci/${SERVICE}-build-deploy.yaml", pre)
        self.assertNotIn("sujho-478914", pre)
        self.assertIn("BUILD_PROJECT: sujho-478914", prod)
        self.assertIn("TARGET_PROJECT: sujho-478914", prod)
        self.assertIn("ci/${SERVICE}-deploy-only.yaml", prod)
        self.assertIn('PIN_DIGEST: "1"', prod)
        self.assertIn('PIN_DIGEST: "0"', pre)
        for text in (pre, prod):
            self.assertIn("inputs.commit", text)
            self.assertIn("inputs.commit || github.sha", text)
            self.assertIn("Refuse unless this run is on main", text)
            self.assertIn("_COMMIT_SHA=", text)
            self.assertIn("_SHORT_SHA=", text)
            self.assertNotIn("secrets.", text)
            self.assertNotIn("${{ inputs.env }}", text)

    def test_approve_preprod_is_one_piece_required_commit(self) -> None:
        generate_approve.main()
        text = (HERE / "workflows" / "approve-preprod.yaml").read_text()
        self.assertEqual(generate_approve.render(), text)
        self.assertIn("bash scripts/tag-on-approval.sh \"$COMMIT\" \"$PIECE\"", text)
        self.assertNotIn("--all", text)
        self.assertIn("required: true", text)
        self.assertIn("knowledge-store-jobs", text)
        self.assertIn("Refuse: commit is required", text)
        self.assertIn("Refuse unless this run is on main", text)
        self.assertNotIn("secrets.", text)

    def test_old_html_is_gone(self) -> None:
        root = HERE.parent
        self.assertFalse((root / "DevOps-HTML").exists())
        self.assertFalse((root / "archive").exists())


class ApplyAndPhase1Tests(unittest.TestCase):
    def test_apply_defaults_to_redirect_pilot(self) -> None:
        lib = (HERE / "lib.sh").read_text()
        self.assertIn('PHASE4_PILOT="redirect"', lib)
        self.assertIn('PHASE4_BRANCH="chore/phase4-promotion"', lib)
        self.assertIn("echo \"$PHASE4_PILOT\"", APPLY)
        self.assertIn("Do not pass --all on the first apply", APPLY)
        self.assertIn("--skip-prereq", APPLY)
        self.assertIn("--base main", APPLY)
        self.assertNotIn("--base dev", APPLY)
        self.assertIn("generate_rollback.py", APPLY)
        self.assertIn("generate_service_workflow.py", APPLY)
        self.assertIn("generate_approve.py", APPLY)
        self.assertIn("generate_job_workflow.py", APPLY)
        self.assertIn("cloud-run-preprod-rollback.yaml", APPLY)
        self.assertIn("cloud-run-preprod-service.yaml", APPLY)
        self.assertIn("approve-preprod.yaml", APPLY)
        self.assertIn("rollback-cloudrun.sh", APPLY)
        self.assertIn("pick_rollback_revision.py", APPLY)
        self.assertIn("ci/jobs/job-build-deploy.yaml", APPLY)
        self.assertIn("jobs/scripts/lookup_job.py", APPLY)

    def test_apply_does_not_mutate_gcp_on_bare_apply(self) -> None:
        self.assertIn("require --4c", APPLY)

    def test_main_is_merge_only(self) -> None:
        self.assertEqual(_merge_methods(PHASE1_MAIN), ["merge"])


if __name__ == "__main__":
    generate_cloudbuild.write_all(HERE)
    unittest.main(verbosity=2)
