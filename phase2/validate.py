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

REQUIRED_SERVICE_KEYS = {"dockerfile", "verify"}
FORBIDDEN_ANYWHERE_IN_CI = [
    ":latest",
    "--set-env-vars",
    "preprod-approved",
    "prod-live",
    "--set-annotation"
    "s",  # unverified round-trip — read RELEASE_COMMIT_SHA from env instead
    "--fail-on-unaudited",  # not a real detect-secrets flag
]
# checked separately — comments can legitimately name sujho-dev to say it's
# unused
FORBIDDEN_PROJECT_REFS = ['"sujho-dev"', "=sujho-dev", ": sujho-dev"]


def read(path: Path) -> str:
    """A file's text, or raise if it's missing — clearer failure than a bare
    read_text().

    Args:
        path: the file to read.
    Returns:
        Its text content.
    Raises:
        AssertionError: path doesn't exist.
    """
    if not path.is_file():
        raise AssertionError(f"missing file: {path}")
    return path.read_text()


class ServicesJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        """Load the file this test class checks, fresh for every test.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.services = json.loads(read(CI / "services.json"))

    def test_not_empty(self) -> None:
        """services.json declares at least one service.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertGreater(len(self.services), 0)

    def test_every_service_has_required_keys(self) -> None:
        """Every service has dockerfile and verify.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for service_id, cfg in self.services.items():
            missing = REQUIRED_SERVICE_KEYS - cfg.keys()
            self.assertFalse(missing, f"{service_id} missing keys: {missing}")

    def test_verify_method_is_health_or_revision(self) -> None:
        """Every service's verify method is health or revision, nothing else.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for service_id, cfg in self.services.items():
            self.assertIn(cfg["verify"], ("health", "revision"), service_id)

    def test_admin_is_the_one_revision_verified_service(self) -> None:
        # admin is IAP-only, the one legitimate exception to the HTTP check
        """Only admin uses revision-verify; every other service uses HTTP
        health.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for service_id, cfg in self.services.items():
            if cfg["verify"] == "revision":
                self.assertEqual(
                    service_id,
                    "admin",
                    f"unexpected revision-verify on {service_id}",
                )


class CloudBuildRecipeTests(unittest.TestCase):
    def test_build_deploy_has_no_forbidden_patterns(self) -> None:
        """build-deploy.yaml contains none of the retired/forbidden patterns.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        for pattern in FORBIDDEN_ANYWHERE_IN_CI:
            msg = f"build-deploy.yaml contains forbidden pattern: {pattern}"
            self.assertNotIn(pattern, body, msg)

    def test_build_deploy_never_targets_sujho_dev(self) -> None:
        # naming sujho-dev in a comment is fine, using it as a value isn't
        """build-deploy.yaml never uses sujho-dev as an actual value.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        for pattern in FORBIDDEN_PROJECT_REFS:
            msg = f"build-deploy.yaml actually targets sujho-dev via: {pattern}"
            self.assertNotIn(pattern, body, msg)

    def test_deploy_only_has_no_forbidden_patterns(self) -> None:
        """deploy-only.yaml contains none of the retired/forbidden patterns.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "deploy-only.yaml")
        for pattern in FORBIDDEN_ANYWHERE_IN_CI:
            msg = f"deploy-only.yaml contains forbidden pattern: {pattern}"
            self.assertNotIn(pattern, body, msg)

    def test_build_deploy_never_moves_traffic_before_verify(self) -> None:
        """build-deploy.yaml deploys with no traffic, verifies, then shifts.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        no_traffic_idx = body.index("--no-traffic")
        verify_idx = body.index("verify_revision.py")
        shift_idx = body.index("update-traffic")
        self.assertLess(
            no_traffic_idx, verify_idx, "deploys with traffic before verifying"
        )
        self.assertLess(
            verify_idx, shift_idx, "moves traffic before verify runs"
        )

    def test_deploy_only_never_moves_traffic_before_verify(self) -> None:
        """deploy-only.yaml deploys with no traffic, verifies, then shifts.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "deploy-only.yaml")
        no_traffic_idx = body.index("--no-traffic")
        verify_idx = body.index("verify_revision.py")
        shift_idx = body.index("update-traffic")
        self.assertLess(no_traffic_idx, verify_idx)
        self.assertLess(verify_idx, shift_idx)

    def test_both_recipes_label_served_true_after_shifting_traffic(
        self,
    ) -> None:
        """served=true is written only after traffic actually moves.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("build-deploy.yaml", "deploy-only.yaml"):
            body = read(CI / name)
            shift_idx = body.index("update-traffic")
            served_idx = body.index("served=true")
            msg = f"{name}: served=true written before traffic actually moves"
            self.assertLess(shift_idx, served_idx, msg)

    def test_deploy_only_has_no_build_step(self) -> None:
        """deploy-only.yaml never invokes Kaniko — it only promotes an existing
        image.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "deploy-only.yaml")
        msg = (
            "deploy-only.yaml must never build — it promotes an existing image"
        )
        self.assertNotIn("kaniko", body, msg)

    def test_deploy_only_refuses_if_image_missing(self) -> None:
        """deploy-only.yaml refuses to promote an image that doesn't exist.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "deploy-only.yaml")
        self.assertIn("Refuse:", body)
        self.assertIn("does not exist", body)

    def test_gates_run_before_build_in_build_deploy(self) -> None:
        """All three gates run, in order, before the image build step.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        gate1 = body.index("gate-1-static")
        gate2 = body.index("gate-2-invariants")
        gate3 = body.index("gate-3-guardrails")
        build = body.index("build-image")
        self.assertLess(gate1, gate2)
        self.assertLess(gate2, gate3)
        self.assertLess(gate3, build)

    def test_semgrep_and_mypy_baseline_against_deployed_commit_not_pr(
        self,
    ) -> None:
        """Semgrep/mypy baseline against the deployed commit, not a PR SHA.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        self.assertIn("baseline-commit", body)
        self.assertIn("baseline-sha", body)
        # ancestor check belongs to the workflow, not this recipe
        self.assertNotIn("git merge-base", body)

    def test_baseline_reads_env_var_not_annotation(self) -> None:
        """The baseline commit comes from resolve_baseline.py, not a revision
        annotation.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        self.assertIn("resolve_baseline.py", body)
        self.assertNotIn('annotations."release-commit-sha"', body)

    def test_gate_1_installs_git_for_mypy_worktree_and_semgrep_baseline(
        self,
    ) -> None:
        """Gate 1 installs git for the mypy worktree and Semgrep baseline diff.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        gate1 = body.split("id: gate-1-static")[1].split("waitFor")[0]
        self.assertIn("apt-get install -y -qq git", gate1)

    def test_gate_1_uses_the_real_detect_secrets_gate(self) -> None:
        """Gate 1 runs the real detect-secrets hook over git ls-files.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("build-deploy.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            self.assertIn("detect-secrets-hook", body)
            self.assertIn("git ls-files", body)

    def test_no_recipe_calls_a_script_before_fetching_sujho(self) -> None:
        # --no-source means the workspace starts empty; nothing from this
        # repo (including any ci/*.py helper) exists until fetch-sujho runs
        """No recipe calls a repo script before fetch-sujho has run.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in (
            "build-deploy.yaml",
            "deploy-only.yaml",
            "job-build-deploy.yaml",
        ):
            body = read(CI / name)
            self.assertIn(
                "id: fetch-sujho", body, f"{name} never fetches the base repo"
            )
            fetch_idx = body.index("id: fetch-sujho")
            needles = ("ci/gates/",)
            first_py_call = min(
                (body.index(needle) for needle in needles if needle in body),
                default=None,
            )
            if first_py_call is not None:
                msg = f"{name} references a repo script before fetch-sujho"
                self.assertLess(fetch_idx, first_py_call, msg)

    def test_fetch_sujho_step_is_inline_not_a_script_call(self) -> None:
        # the step that bootstraps the workspace can't call a script that
        # lives inside the very repo it hasn't fetched yet — circular
        """fetch-sujho is inline shell, not a call to a script from the
        unfetched repo.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in (
            "build-deploy.yaml",
            "deploy-only.yaml",
            "job-build-deploy.yaml",
        ):
            body = read(CI / name)
            step = body.split("id: fetch-sujho")[1].split("\n\n")[0]
            msg = f"{name}: fetch-sujho calls a script from the unfetched repo"
            self.assertNotIn("python3 ci/", step, msg)
            self.assertIn("git init", step)

    def test_job_build_deploy_marks_the_skipped_invariant_gate_visibly(
        self,
    ) -> None:
        """The skipped invariant gate in job-build-deploy.yaml is labeled as a
        known gap.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "job-build-deploy.yaml")
        self.assertIn("id: gate-2-invariants", body)
        self.assertIn("known gap, not run", body)

    def test_secrets_baseline_points_at_the_file_that_actually_exists(
        self,
    ) -> None:
        # the only baseline anywhere in this repo is tests/ci/.secrets.baseline
        """The secrets baseline path matches the file actually committed.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertTrue(
            (HERE.parent / "tests" / "ci" / ".secrets.baseline").is_file()
        )
        for name in ("build-deploy.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            self.assertIn("tests/ci/.secrets.baseline", body)
            self.assertNotIn("--baseline .secrets.baseline ", body)

    def test_job_build_deploy_has_the_same_baselining_as_the_service_recipe(
        self,
    ) -> None:
        """job-build-deploy.yaml baselines mypy the same way the service recipe
        does.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "job-build-deploy.yaml")
        self.assertIn("mypy_ratchet.py", body)
        self.assertIn("--baseline-commit", body)
        self.assertIn("resolve_baseline.py", body)
        self.assertIn("--kind=jobs", body)


class WorkflowTests(unittest.TestCase):
    def test_no_sujho_dev_workflows_remain(self) -> None:
        """No sujho-dev-specific workflow files remain.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        names = {p.name for p in WORKFLOWS.glob("*.yaml")}
        for forbidden in (
            "cloud-run-dev-service.yaml",
            "cloud-run-dev-rollback.yaml",
        ):
            self.assertNotIn(
                forbidden, names, "sujho-dev has no CI (decision 13)"
            )

    def test_preprod_and_prod_service_forms_check_ancestor_of_main(
        self,
    ) -> None:
        """Both service deploy forms verify the commit is an ancestor of main.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in (
            "cloud-run-preprod-service.yaml",
            "cloud-run-prod-service.yaml",
        ):
            body = read(WORKFLOWS / name)
            self.assertIn(
                "merge-base --is-ancestor",
                body,
                f"{name} missing bug-4 ancestor check",
            )
            self.assertIn(
                "fetch-depth: 0",
                body,
                f"{name} needs full history for the ancestor check",
            )

    def test_prod_service_form_has_the_approval_gate(self) -> None:
        """Prod's form requires the production environment and an independent
        validate job.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(WORKFLOWS / "cloud-run-prod-service.yaml")
        self.assertIn("environment: production", body)
        # validate job must exist independently of the gated deploy job
        self.assertIn("validate:", body)
        self.assertIn("needs: validate", body)

    def test_prod_service_form_types_commit_once_and_requires_it(self) -> None:
        """Prod's commit input is required.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(WORKFLOWS / "cloud-run-prod-service.yaml")
        self.assertIn("required: true", body)

    def test_preprod_service_form_allows_blank_commit(self) -> None:
        """Pre-Prod's commit input defaults to blank (build from HEAD).

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(WORKFLOWS / "cloud-run-preprod-service.yaml")
        self.assertIn('default: ""', body)

    def test_rollback_workflows_reference_served_true_not_ready(self) -> None:
        """Rollback picks by served=true, never by Ready revision alone.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in (
            "cloud-run-preprod-rollback.yaml",
            "cloud-run-prod-rollback.yaml",
        ):
            body = read(WORKFLOWS / name)
            self.assertIn("served=true", body)
            self.assertNotIn("Ready revision", body)

    def test_rollback_script_defaults_to_dry_run(self) -> None:
        """rollback-cloudrun.sh never shifts traffic unless --apply is passed.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(SCRIPTS / "rollback-cloudrun.sh")
        self.assertIn('APPLY=0', body)
        self.assertNotIn("DRY_RUN=0", body)

    def test_rollback_workflows_pass_apply(self) -> None:
        """Both rollback workflows explicitly pass --apply to the script.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in (
            "cloud-run-preprod-rollback.yaml",
            "cloud-run-prod-rollback.yaml",
        ):
            body = read(WORKFLOWS / name)
            self.assertIn("rollback-cloudrun.sh", body)
            self.assertIn("--apply", body)

    def test_rollback_uses_its_own_narrower_account_not_the_deploy_one(
        self,
    ) -> None:
        # rollback gets its own narrower account, never the deploy one
        """Rollback uses its own narrower service account, never the deploy one.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        preprod = read(WORKFLOWS / "cloud-run-preprod-rollback.yaml")
        prod = read(WORKFLOWS / "cloud-run-prod-rollback.yaml")
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_PREPROD_ROLLBACK", preprod)
        self.assertIn("GCP_WIF_SERVICE_ACCOUNT_PROD_ROLLBACK", prod)

    def test_concurrency_group_prevents_overlapping_runs_per_service(
        self,
    ) -> None:
        """Every workflow declares a concurrency group.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in WORKFLOWS.glob("*.yaml"):
            body = read(name)
            self.assertIn(
                "concurrency:", body, f"{name.name} has no concurrency guard"
            )


def _rev(name: str, ts: str, served: bool = False) -> dict:
    """A minimal Cloud Run revision fixture: name, creation time, and served
    label.

    Args:
        name: the revision name.
        ts: its creationTimestamp.
        served: whether to attach the served=true label.
    Returns:
        The fixture dict.
    Raises:
        None.
    """
    labels = {"served": "true"} if served else {}
    return {
        "metadata": {"name": name, "creationTimestamp": ts, "labels": labels}
    }


def _serving(name: str, percent: int = 100) -> dict:
    """A minimal Cloud Run service fixture with one revision at the given
    traffic percent.

    Args:
        name: the revision name to put at percent traffic.
        percent: the traffic percent to assign it.
    Returns:
        The fixture dict.
    Raises:
        None.
    """
    return {"status": {"traffic": [{"revisionName": name, "percent": percent}]}}


class RollbackPickerTests(unittest.TestCase):
    def setUp(self) -> None:
        """Load the file this test class checks, fresh for every test.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        sys.path.insert(0, str(SCRIPTS))
        import pick_rollback_revision as mod  # type: ignore

        self.mod = mod

    def test_picks_newest_served_true_older_than_serving(self) -> None:
        """Picks the newest served=true revision older than the one currently
        serving.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _serving("redirect-00102")
        revisions = [
            _rev("redirect-00100", "2026-01-01T00:00:00Z", served=True),
            # failed verify, never served
            _rev("redirect-00101", "2026-01-02T00:00:00Z", served=False),
            _rev(
                "redirect-00102", "2026-01-03T00:00:00Z", served=True
            ),  # currently serving
        ]
        self.assertEqual(
            self.mod.pick_previous(service, revisions), "redirect-00100"
        )

    def test_refuses_if_serving_revision_itself_is_not_served_true(
        self,
    ) -> None:
        """Refuses if the currently-serving revision itself was never
        served=true.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _serving("redirect-00102")
        revisions = [
            _rev("redirect-00100", "2026-01-01T00:00:00Z", served=True),
            _rev("redirect-00102", "2026-01-03T00:00:00Z", served=False),
        ]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, revisions)

    def test_refuses_if_no_older_served_true_revision_exists(self) -> None:
        """Refuses if there's no served=true revision older than the current
        one.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _serving("redirect-00100")
        revisions = [
            _rev("redirect-00100", "2026-01-01T00:00:00Z", served=True)
        ]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, revisions)

    def test_refuses_if_traffic_is_split(self) -> None:
        """Refuses if traffic is split across more than one revision.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = {
            "status": {
                "traffic": [
                    {"revisionName": "redirect-00100", "percent": 50},
                    {"revisionName": "redirect-00101", "percent": 50},
                ]
            }
        }
        revisions = [
            _rev("redirect-00100", "2026-01-01T00:00:00Z", served=True)
        ]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, revisions)


class ResolveBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        """Load the file this test class checks, fresh for every test.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        import importlib.util

        path = CI / "gates" / "resolve_baseline.py"
        spec = importlib.util.spec_from_file_location("resolve_baseline", path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_services_path_reads_the_revision_template_containers(self) -> None:
        """The services container path reads spec.template.spec.containers.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        data = {
            "spec": {
                "template": {"spec": {"containers": [{"env": [{"name": "X"}]}]}}
            }
        }
        self.assertEqual(
            self.mod.container_path(data, "services"),
            [{"env": [{"name": "X"}]}],
        )

    def test_jobs_path_reads_one_level_deeper(self) -> None:
        """The jobs container path reads one level deeper than services.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        containers = [{"env": [{"name": "X"}]}]
        data = {
            "spec": {
                "template": {
                    "spec": {"template": {"spec": {"containers": containers}}}
                }
            }
        }
        self.assertEqual(self.mod.container_path(data, "jobs"), containers)
        # confirms the services path alone would miss it — that's the actual
        # difference
        self.assertEqual(self.mod.container_path(data, "services"), [])


class CleanupPolicyTests(unittest.TestCase):
    def test_no_cleanup_policy_file_or_wiring_remains(self) -> None:
        """Dropped on purpose: no rule protected the image Prod is currently
        running, and removing prod-live/preprod-approved tags removed the
        keep-rule that used to anchor that protection. Simplest fix: nothing
        auto-deletes images. See README.md's phase2 section, not
        'What's still left' — this is a decision, not an open item.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse((CI / "cleanup-policy.json").exists())
        self.assertNotIn("cleanup-policy.json", read(HERE / "lib.sh"))


class DistributionTests(unittest.TestCase):
    """Files that exist but were never wired into anything that ships them."""

    def test_pr_template_and_dependabot_are_in_the_push_list(self) -> None:
        """The PR template and dependabot config are both in lib.sh's push list.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        lib = read(HERE / "lib.sh")
        self.assertIn(".github/PULL_REQUEST_TEMPLATE.md", lib)
        self.assertIn(".github/dependabot.yml", lib)

    def test_resolve_baseline_is_in_the_push_list(self) -> None:
        """resolve_baseline.py is in lib.sh's push list.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        lib = read(HERE / "lib.sh")
        self.assertIn("ci/gates/resolve_baseline.py", lib)

    def test_pr_template_is_not_gitignored(self) -> None:
        """The PR template isn't excluded by .gitignore.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        gitignore = read(HERE.parent / ".gitignore")
        self.assertNotIn("PULL_REQUEST_TEMPLATE.md", gitignore)


class IamTableTests(unittest.TestCase):
    def test_mentions_the_four_narrow_accounts(self) -> None:
        """IAM-table.md names all four narrow deploy/rollback service accounts.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(HERE / "IAM-table.md")
        for account in (
            "github-deploy-preprod",
            "github-rollback-preprod",
            "github-deploy-prod",
            "github-rollback-prod",
        ):
            self.assertIn(account, body)

    def test_mentions_the_narrow_builder_key(self) -> None:
        """IAM-table.md names the narrow prod-builder key.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(HERE / "IAM-table.md")
        self.assertIn("prod-builder", body)

    def test_mentions_the_production_environment(self) -> None:
        """IAM-table.md documents the production environment's self-review
        prevention.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(HERE / "IAM-table.md")
        self.assertIn("production", body)
        self.assertIn("Prevent self-review", body)


if __name__ == "__main__":
    unittest.main()
