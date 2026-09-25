#!/usr/bin/env python3
"""Local invariants for Phase 2 — no GitHub, no GCP, static files only."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CI = HERE / "ci"
WORKFLOWS = HERE / "workflows"
SCRIPTS = HERE / "scripts"

REQUIRED_SERVICE_KEYS = {"dockerfile", "gitlinks", "verify"}
FORBIDDEN_ANYWHERE_IN_CI = [
    ":latest", "--set-env-vars", "preprod-approved", "prod-live",
    "--set-annotations",  # unverified round-trip — read RELEASE_COMMIT_SHA from env instead
    "--fail-on-unaudited",  # not a real detect-secrets flag
]
# checked separately — comments can legitimately name sujho-dev to say it's unused
FORBIDDEN_PROJECT_REFS = ['"sujho-dev"', "=sujho-dev", ": sujho-dev"]


def read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing file: {path}")
    return path.read_text()


class ServicesJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.services = json.loads(read(CI / "services.json"))

    def test_not_empty(self) -> None:
        self.assertGreater(len(self.services), 0)

    def test_every_service_has_required_keys(self) -> None:
        for service_id, cfg in self.services.items():
            missing = REQUIRED_SERVICE_KEYS - cfg.keys()
            self.assertFalse(missing, f"{service_id} missing keys: {missing}")

    def test_gitlinks_always_include_infra(self) -> None:
        for service_id, cfg in self.services.items():
            self.assertIn("infra", cfg["gitlinks"], f"{service_id} does not fetch infra")

    def test_verify_method_is_health_or_revision(self) -> None:
        for service_id, cfg in self.services.items():
            self.assertIn(cfg["verify"], ("health", "revision"), service_id)

    def test_admin_is_the_one_revision_verified_service(self) -> None:
        # admin is IAP-only, the one legitimate exception to the HTTP check
        for service_id, cfg in self.services.items():
            if cfg["verify"] == "revision":
                self.assertEqual(service_id, "admin", f"unexpected revision-verify on {service_id}")


class CloudBuildRecipeTests(unittest.TestCase):
    def test_build_deploy_has_no_forbidden_patterns(self) -> None:
        body = read(CI / "build-deploy.yaml")
        for pattern in FORBIDDEN_ANYWHERE_IN_CI:
            self.assertNotIn(pattern, body, f"build-deploy.yaml contains forbidden pattern: {pattern}")

    def test_build_deploy_never_targets_sujho_dev(self) -> None:
        # naming sujho-dev in a comment is fine, using it as a value isn't
        body = read(CI / "build-deploy.yaml")
        for pattern in FORBIDDEN_PROJECT_REFS:
            self.assertNotIn(pattern, body, f"build-deploy.yaml actually targets sujho-dev via: {pattern}")

    def test_deploy_only_has_no_forbidden_patterns(self) -> None:
        body = read(CI / "deploy-only.yaml")
        for pattern in FORBIDDEN_ANYWHERE_IN_CI:
            self.assertNotIn(pattern, body, f"deploy-only.yaml contains forbidden pattern: {pattern}")

    def test_build_deploy_never_moves_traffic_before_verify(self) -> None:
        body = read(CI / "build-deploy.yaml")
        no_traffic_idx = body.index("--no-traffic")
        verify_idx = body.index("verify_revision.py")
        shift_idx = body.index("update-traffic")
        self.assertLess(no_traffic_idx, verify_idx, "deploys with traffic before verifying")
        self.assertLess(verify_idx, shift_idx, "moves traffic before verify runs")

    def test_deploy_only_never_moves_traffic_before_verify(self) -> None:
        body = read(CI / "deploy-only.yaml")
        no_traffic_idx = body.index("--no-traffic")
        verify_idx = body.index("verify_revision.py")
        shift_idx = body.index("update-traffic")
        self.assertLess(no_traffic_idx, verify_idx)
        self.assertLess(verify_idx, shift_idx)

    def test_both_recipes_label_served_true_after_shifting_traffic(self) -> None:
        for name in ("build-deploy.yaml", "deploy-only.yaml"):
            body = read(CI / name)
            shift_idx = body.index("update-traffic")
            served_idx = body.index("served=true")
            self.assertLess(shift_idx, served_idx, f"{name}: served=true written before traffic actually moves")

    def test_deploy_only_has_no_build_step(self) -> None:
        body = read(CI / "deploy-only.yaml")
        self.assertNotIn("kaniko", body, "deploy-only.yaml must never build — it promotes an existing image")

    def test_deploy_only_refuses_if_image_missing(self) -> None:
        body = read(CI / "deploy-only.yaml")
        self.assertIn("Refuse:", body)
        self.assertIn("does not exist", body)

    def test_gates_run_before_build_in_build_deploy(self) -> None:
        body = read(CI / "build-deploy.yaml")
        gate1 = body.index("gate-1-static")
        gate2 = body.index("gate-2-invariants")
        gate3 = body.index("gate-3-guardrails")
        build = body.index("build-image")
        self.assertLess(gate1, gate2)
        self.assertLess(gate2, gate3)
        self.assertLess(gate3, build)

    def test_semgrep_and_mypy_baseline_against_deployed_commit_not_pr(self) -> None:
        body = read(CI / "build-deploy.yaml")
        self.assertIn("baseline-commit", body)
        self.assertIn("baseline-sha", body)
        # ancestor check belongs to the workflow, not this recipe
        self.assertNotIn("git merge-base", body)

    def test_baseline_reads_env_var_not_annotation(self) -> None:
        body = read(CI / "build-deploy.yaml")
        self.assertIn("resolve_baseline.py", body)
        self.assertNotIn('annotations."release-commit-sha"', body)

    def test_gate_1_installs_git_for_mypy_worktree_and_semgrep_baseline(self) -> None:
        body = read(CI / "build-deploy.yaml")
        gate1 = body.split("id: gate-1-static")[1].split("waitFor")[0]
        self.assertIn("apt-get install -y -qq git", gate1)

    def test_gate_1_uses_the_real_detect_secrets_gate(self) -> None:
        for name in ("build-deploy.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            self.assertIn("detect-secrets-hook", body)
            self.assertIn("git ls-files", body)

    def test_no_recipe_calls_a_script_before_fetching_sujho(self) -> None:
        # --no-source means the workspace starts empty; nothing from this
        # repo (including any ci/*.py helper) exists until fetch-sujho runs
        for name in ("build-deploy.yaml", "deploy-only.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            self.assertIn("id: fetch-sujho", body, f"{name} never fetches the base repo")
            fetch_idx = body.index("id: fetch-sujho")
            first_py_call = min(
                (body.index(needle) for needle in ("ci/checkout-gitlinks.py", "ci/gates/") if needle in body),
                default=None,
            )
            if first_py_call is not None:
                self.assertLess(fetch_idx, first_py_call, f"{name} references a repo script before fetch-sujho")

    def test_fetch_sujho_step_is_inline_not_a_script_call(self) -> None:
        # the step that bootstraps the workspace can't call a script that
        # lives inside the very repo it hasn't fetched yet — circular
        for name in ("build-deploy.yaml", "deploy-only.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            step = body.split("id: fetch-sujho")[1].split("\n\n")[0]
            self.assertNotIn("python3 ci/", step, f"{name}: fetch-sujho calls a script from the unfetched repo")
            self.assertIn("git init", step)

    def test_job_build_deploy_marks_the_skipped_invariant_gate_visibly(self) -> None:
        body = read(CI / "job-build-deploy.yaml")
        self.assertIn("id: gate-2-invariants", body)
        self.assertIn("known gap, not run", body)

    def test_secrets_baseline_points_at_the_file_that_actually_exists(self) -> None:
        # the only baseline anywhere in this repo is tests/ci/.secrets.baseline
        self.assertTrue((HERE.parent / "tests" / "ci" / ".secrets.baseline").is_file())
        for name in ("build-deploy.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            self.assertIn("tests/ci/.secrets.baseline", body)
            self.assertNotIn("--baseline .secrets.baseline ", body)

    def test_job_build_deploy_has_the_same_baselining_as_the_service_recipe(self) -> None:
        body = read(CI / "job-build-deploy.yaml")
        self.assertIn("mypy_ratchet.py", body)
        self.assertIn("--baseline-commit", body)
        self.assertIn("resolve_baseline.py", body)
        self.assertIn("--kind=jobs", body)


class WorkflowTests(unittest.TestCase):
    def test_no_sujho_dev_workflows_remain(self) -> None:
        names = {p.name for p in WORKFLOWS.glob("*.yaml")}
        for forbidden in ("cloud-run-dev-service.yaml", "cloud-run-dev-rollback.yaml"):
            self.assertNotIn(forbidden, names, "sujho-dev has no CI (decision 13)")

    def test_preprod_and_prod_service_forms_check_ancestor_of_main(self) -> None:
        for name in ("cloud-run-preprod-service.yaml", "cloud-run-prod-service.yaml"):
            body = read(WORKFLOWS / name)
            self.assertIn("merge-base --is-ancestor", body, f"{name} missing bug-4 ancestor check")
            self.assertIn("fetch-depth: 0", body, f"{name} needs full history for the ancestor check")

    def test_prod_service_form_has_the_approval_gate(self) -> None:
        body = read(WORKFLOWS / "cloud-run-prod-service.yaml")
        self.assertIn("environment: production", body)
        # validate job must exist independently of the gated deploy job
        self.assertIn("validate:", body)
        self.assertIn("needs: validate", body)

    def test_prod_service_form_types_commit_once_and_requires_it(self) -> None:
        body = read(WORKFLOWS / "cloud-run-prod-service.yaml")
        self.assertIn("required: true", body)

    def test_preprod_service_form_allows_blank_commit(self) -> None:
        body = read(WORKFLOWS / "cloud-run-preprod-service.yaml")
        self.assertIn('default: ""', body)

    def test_rollback_workflows_reference_served_true_not_ready(self) -> None:
        for name in ("cloud-run-preprod-rollback.yaml", "cloud-run-prod-rollback.yaml"):
            body = read(WORKFLOWS / name)
            self.assertIn("served=true", body)
            self.assertNotIn("Ready revision", body)

    def test_rollback_uses_its_own_narrower_account_not_the_deploy_one(self) -> None:
        # rollback gets its own narrower account, never the deploy one
        preprod = read(WORKFLOWS / "cloud-run-preprod-rollback.yaml")
        prod = read(WORKFLOWS / "cloud-run-prod-rollback.yaml")
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_PREPROD_ROLLBACK", preprod)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_PROD_ROLLBACK", prod)

    def test_concurrency_group_prevents_overlapping_runs_per_service(self) -> None:
        for name in WORKFLOWS.glob("*.yaml"):
            body = read(name)
            self.assertIn("concurrency:", body, f"{name.name} has no concurrency guard")


def _rev(name: str, ts: str, served: bool = False) -> dict:
    labels = {"served": "true"} if served else {}
    return {"metadata": {"name": name, "creationTimestamp": ts, "labels": labels}}


def _serving(name: str, percent: int = 100) -> dict:
    return {"status": {"traffic": [{"revisionName": name, "percent": percent}]}}


class RollbackPickerTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import pick_rollback_revision as mod  # type: ignore
        self.mod = mod

    def test_picks_newest_served_true_older_than_serving(self) -> None:
        service = _serving("redirect-00102")
        revisions = [
            _rev("redirect-00100", "2026-01-01T00:00:00Z", served=True),
            _rev("redirect-00101", "2026-01-02T00:00:00Z", served=False),  # failed verify, never served
            _rev("redirect-00102", "2026-01-03T00:00:00Z", served=True),  # currently serving
        ]
        self.assertEqual(self.mod.pick_previous(service, revisions), "redirect-00100")

    def test_refuses_if_serving_revision_itself_is_not_served_true(self) -> None:
        service = _serving("redirect-00102")
        revisions = [
            _rev("redirect-00100", "2026-01-01T00:00:00Z", served=True),
            _rev("redirect-00102", "2026-01-03T00:00:00Z", served=False),
        ]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, revisions)

    def test_refuses_if_no_older_served_true_revision_exists(self) -> None:
        service = _serving("redirect-00100")
        revisions = [_rev("redirect-00100", "2026-01-01T00:00:00Z", served=True)]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, revisions)

    def test_refuses_if_traffic_is_split(self) -> None:
        service = {"status": {"traffic": [
            {"revisionName": "redirect-00100", "percent": 50},
            {"revisionName": "redirect-00101", "percent": 50},
        ]}}
        revisions = [_rev("redirect-00100", "2026-01-01T00:00:00Z", served=True)]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, revisions)


class ResolveBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("resolve_baseline", CI / "gates" / "resolve_baseline.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_services_path_reads_the_revision_template_containers(self) -> None:
        data = {"spec": {"template": {"spec": {"containers": [{"env": [{"name": "X"}]}]}}}}
        self.assertEqual(self.mod.container_path(data, "services"), [{"env": [{"name": "X"}]}])

    def test_jobs_path_reads_one_level_deeper(self) -> None:
        data = {"spec": {"template": {"spec": {"template": {"spec": {"containers": [{"env": [{"name": "X"}]}]}}}}}}
        self.assertEqual(self.mod.container_path(data, "jobs"), [{"env": [{"name": "X"}]}])
        # confirms the services path alone would miss it — that's the actual difference
        self.assertEqual(self.mod.container_path(data, "services"), [])


class CleanupPolicyTests(unittest.TestCase):
    def test_valid_json_and_keeps_recent(self) -> None:
        policy = json.loads(read(CI / "cleanup-policy.json"))
        actions = {rule["name"]: rule["action"]["type"] for rule in policy}
        self.assertEqual(actions.get("keep-recent"), "Keep")
        self.assertEqual(actions.get("delete-stale"), "Delete")

    def test_no_stale_reference_to_removed_tags(self) -> None:
        body = read(CI / "cleanup-policy.json")
        self.assertNotIn("preprod-approved", body)
        self.assertNotIn("prod-live", body)


class DistributionTests(unittest.TestCase):
    """Files that exist but were never wired into anything that ships them."""

    def test_pr_template_and_dependabot_are_in_the_push_list(self) -> None:
        lib = read(HERE / "lib.sh")
        self.assertIn(".github/PULL_REQUEST_TEMPLATE.md", lib)
        self.assertIn(".github/dependabot.yml", lib)

    def test_resolve_baseline_is_in_the_push_list(self) -> None:
        lib = read(HERE / "lib.sh")
        self.assertIn("ci/gates/resolve_baseline.py", lib)

    def test_pr_template_is_not_gitignored(self) -> None:
        gitignore = read(HERE.parent / ".gitignore")
        self.assertNotIn("PULL_REQUEST_TEMPLATE.md", gitignore)


class IamTableTests(unittest.TestCase):
    def test_mentions_the_four_narrow_accounts(self) -> None:
        body = read(HERE / "IAM-table.md")
        for account in (
            "github-deploy-preprod",
            "github-rollback-preprod",
            "github-deploy-prod",
            "github-rollback-prod",
        ):
            self.assertIn(account, body)

    def test_mentions_the_narrow_builder_key(self) -> None:
        body = read(HERE / "IAM-table.md")
        self.assertIn("prod-builder", body)

    def test_mentions_the_production_environment(self) -> None:
        body = read(HERE / "IAM-table.md")
        self.assertIn("production", body)
        self.assertIn("Prevent self-review", body)


if __name__ == "__main__":
    unittest.main()
