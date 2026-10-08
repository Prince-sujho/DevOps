#!/usr/bin/env python3
"""Local invariants for Phase 2 — no GitHub, no GCP, static files only."""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
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
    # unverified round-trip — read RELEASE_COMMIT_SHA from env instead
    "--set-annotations",
    "--fail-on-unaudited",  # not a real detect-secrets flag
]
# checked separately — comments can legitimately name sujho-dev to say it's
# unused
ALL_RECIPES = (
    "build-deploy.yaml",
    "deploy-only.yaml",
    "job-build-deploy.yaml",
    "job-deploy-only.yaml",
)
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


def gitignore_rules() -> list[str]:
    """The repo .gitignore's active rules, comments and blanks dropped.

    Args:
        None.
    Returns:
        The rule lines.
    Raises:
        None.
    """
    return [
        line.strip()
        for line in read(HERE.parent / ".gitignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


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

    def test_every_service_declares_a_runtime_identity(self) -> None:
        # A missing one means the container runs as the project's default
        # compute account, which can read every bucket and secret in it.
        """Every service names a `<service>-run` runtime account, matching the
        per-service accounts in IAM-table.md section 3.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        iam_table = read(HERE / "IAM-table.md")
        for service_id, cfg in self.services.items():
            expected = "jobs-run" if service_id == "probe" else f"{service_id}-run"
            self.assertEqual(cfg.get("runtime_sa"), expected)
            self.assertIn(f"`{expected}`", iam_table)

    def test_no_service_config_can_break_the_substitutions_string(
        self,
    ) -> None:
        # --substitutions is one comma-separated KEY=VALUE string, so a comma
        # anywhere in a value silently becomes another substitution.
        """No run_args entry contains a comma, and secrets/env are lists so
        the workflow can join them with ';' instead.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for service_id, cfg in self.services.items():
            for key in ("secrets", "env", "run_args"):
                self.assertIsInstance(cfg.get(key), list, f"{service_id}.{key}")
            for arg in cfg["run_args"]:
                self.assertNotIn(",", arg, f"{service_id}: {arg}")
            for entry in (*cfg["secrets"], *cfg["env"]):
                self.assertNotIn(",", entry, f"{service_id}: {entry}")
                self.assertNotIn(";", entry, f"{service_id}: {entry}")

    def test_overrides_are_per_environment_and_only_known_keys(self) -> None:
        """Overrides exist only for preprod/prod and only for keys a deploy
        actually reads, so a typo cannot silently do nothing.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        overridable = {
            "cpu",
            "memory",
            "timeout",
            "min_instances",
            "max_instances",
            "run_args",
            "secrets",
            "env",
        }
        for service_id, cfg in self.services.items():
            overrides = cfg.get("overrides")
            self.assertIsInstance(overrides, dict, service_id)
            self.assertLessEqual(
                set(overrides), {"preprod", "prod"}, service_id
            )
            for env, block in overrides.items():
                self.assertLessEqual(
                    set(block), overridable, f"{service_id}.{env}"
                )

    def test_both_service_workflows_resolve_their_own_environment(
        self,
    ) -> None:
        """Each service workflow merges the overrides block for its own
        environment and passes the runtime identity, secrets and env through.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name, env in (
            ("cloud-run-preprod-service.yaml", "preprod"),
            ("cloud-run-prod-service.yaml", "prod"),
        ):
            body = read(WORKFLOWS / name)
            self.assertIn(f'--arg env {env} ', body, name)
            self.assertIn(
                "(.[$s] | del(.overrides)) * (.[$s].overrides[$env] // {})",
                body,
                name,
            )
            self.assertIn('SUBS+=",_RUNTIME_SA=$RUNTIME_SA"', body, name)
            self.assertIn('SUBS+=",_SECRETS=$SECRETS"', body, name)
            self.assertIn('SUBS+=",_ENV_VARS=$ENV_VARS"', body, name)
            self.assertIn('if [ -z "$RUNTIME_SA" ]; then', body, name)
            self.assertIn("*,*)", body, name)

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
        """admin and the throwaway probe use revision-verify; other
        services use HTTP health.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for service_id, cfg in self.services.items():
            if cfg["verify"] == "revision":
                self.assertIn(
                    service_id,
                    {"admin", "probe"},
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

    def test_both_recipes_record_the_marker_only_after_traffic_moves(
        self,
    ) -> None:
        # The order is what makes the marker mean something: lkg is written
        # after the traffic shift returned, so a revision that failed to take
        # traffic is never recorded as good.
        """The traffic shift, prev, lkg and the build-tag removal are one
        update-traffic call, and prev is read before that call.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("build-deploy.yaml", "deploy-only.yaml"):
            body = read(CI / name)
            read_lkg = body.index('PREVIOUS_GOOD="$(tag_revision lkg)"')
            assign = body.index('TAGS="lkg=$$REVISION"')
            keep_prev = body.index('TAGS="prev=$$PREVIOUS_GOOD,$$TAGS"')
            shift = body.index('--to-revisions="$$REVISION=100"')
            set_tags = body.index('--update-tags="$$TAGS"')
            drop_build = body.index('--remove-tags="build-')
            self.assertLess(read_lkg, assign, name)
            self.assertLess(assign, keep_prev, name)
            self.assertLess(keep_prev, shift, name)
            self.assertLess(shift, set_tags, name)
            self.assertLess(set_tags, drop_build, name)
            self.assertEqual(body.count("update-traffic"), 1, name)

    def test_no_recipe_or_script_calls_a_command_gcloud_does_not_have(
        self,
    ) -> None:
        # `gcloud run revisions update` does not exist (only describe / list /
        # delete), and a revision's labels are fixed at creation anyway. The
        # old design called it, so every step after it would have failed while
        # traffic had already moved.
        """Nothing shells out to `gcloud run revisions update`, and the only
        revision subcommands used are read-only ones.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        allowed = {"describe", "list"}
        files = [
            *CI.glob("*.yaml"),
            *SCRIPTS.glob("*.sh"),
            *WORKFLOWS.glob("*.yaml"),
            *(HERE / "jobs" / "workflows").glob("*.yaml"),
        ]
        for path in files:
            body = read(path)
            self.assertNotIn("run revisions update", body, path.name)
            self.assertNotIn("--update-labels", body, path.name)
            for chunk in body.split("gcloud run revisions ")[1:]:
                self.assertIn(chunk.split()[0], allowed, path.name)

    def test_deploys_never_touch_the_services_iam_policy(self) -> None:
        # --allow-unauthenticated / --no-allow-unauthenticated both call
        # setIamPolicy, which needs run.admin; the builder has run.developer,
        # so a deploy passing either would fail after the image was built.
        """No recipe or service config passes an allow-unauthenticated flag.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in (*CI.glob("*.yaml"), CI / "services.json"):
            self.assertNotIn("allow-unauthenticated", read(path), path.name)

    def test_both_recipes_pin_the_runtime_identity_and_never_strip_config(
        self,
    ) -> None:
        """Both service recipes deploy with an explicit runtime service
        account, refuse without one, and only ever add env/secrets.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("build-deploy.yaml", "deploy-only.yaml"):
            body = read(CI / name)
            self.assertIn(
                '--service-account="${_RUNTIME_SA}@${_TARGET_PROJECT}'
                '.iam.gserviceaccount.com"',
                body,
                name,
            )
            self.assertIn('if [ -z "${_RUNTIME_SA}" ]; then', body, name)
            self.assertIn("--update-env-vars=", body, name)
            self.assertIn("--update-secrets=", body, name)
            for destructive in (
                "--clear-secrets",
                "--set-secrets",
                "--set-env-vars",
                "--clear-env-vars",
            ):
                self.assertNotIn(destructive, body, f"{name}: {destructive}")

    def test_verify_checks_the_image_digest_not_just_the_commit(self) -> None:
        # Comparing RELEASE_COMMIT_SHA on its own is circular: the same deploy
        # set it. The digest is read back off the running revision.
        """Both recipes pass --expect-digest, and the gate requires it.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("build-deploy.yaml", "deploy-only.yaml"):
            body = read(CI / name)
            self.assertIn(
                '--expect-digest="$(cat /workspace/.digest)"', body, name
            )
        gate = read(CI / "gates" / "verify_revision.py")
        self.assertIn(
            '"--expect-digest is required unless --print-revision"', gate
        )
        self.assertIn('image.endswith(f"@{expect_digest}")', gate)

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

    def test_no_recipe_fetches_anything_from_github(self) -> None:
        # The workflow uploads the exact checkout as real source. A recipe
        # that fetched from GitHub itself would need a credential inside Cloud
        # Build (a bare cloneUri has none) — and sujho-478914 has no
        # Developer Connect link at all.
        """None of the four Cloud Build recipes fetches from GitHub or names a
        Developer Connect link.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ALL_RECIPES:
            body = read(CI / name)
            for needle in (
                "fetch-sujho",
                "developer-connect",
                "_DC_CONNECTION",
                "git remote add",
                "git fetch",
                "git init",
            ):
                self.assertNotIn(needle, body, f"{name} still has {needle!r}")

    def test_preprod_recipes_resolve_baseline_without_a_remote(self) -> None:
        """The baseline step needs only the uploaded history: no unshallow
        fetch, an explicit override, and an explicit first-deploy mode.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("build-deploy.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            self.assertNotIn("--unshallow", body, name)
            self.assertIn('_BASELINE_SHA: ""', body, name)
            self.assertIn('BASE_SHA="${_BASELINE_SHA}"', body, name)
            self.assertIn("mypy_ratchet.py --absolute", body, name)
            self.assertIn("semgrep scan --config=p/ci --error\n", body, name)
            # the old silent "baseline = HEAD" fallback must never come back
            self.assertNotIn('BASE_SHA="${_COMMIT_SHA}"', body, name)

    def test_bash_variables_are_escaped_for_cloud_build(self) -> None:
        # Cloud Build scans the whole args string for $NAME: a bare $URI,
        # $DIGEST or $PATH is rejected at submit time unless written $$NAME.
        # Only _USER substitutions and the built-in names may stay single-$.
        """Every bash variable in every recipe is written $$NAME, except user
        substitutions (_NAME) and Cloud Build built-ins.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        builtins = {
            "PROJECT_ID", "PROJECT_NUMBER", "BUILD_ID", "LOCATION",
            "COMMIT_SHA", "SHORT_SHA", "REPO_NAME", "BRANCH_NAME",
            "TAG_NAME", "REVISION_ID", "TRIGGER_NAME", "REF_NAME",
        }
        pattern = re.compile(r"(?<!\$)\$\{?([A-Za-z][A-Za-z0-9_]*)")
        for name in ALL_RECIPES:
            for lineno, line in enumerate(read(CI / name).splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for var in pattern.findall(line):
                    if var in builtins:
                        continue
                    self.fail(f"{name}:{lineno} bare ${var} — write $${var}")

    def test_prod_only_promotes_what_preprod_verified(self) -> None:
        # build-image writes candidate-<sha>; the sha-<sha> tag Prod resolves
        # is only added by publish-verified-tag, after the last Pre-Prod check.
        """Pre-Prod builds push candidate-, deploy by digest, and publish the
        sha- tag only after verification.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        expected_last = {
            "build-deploy.yaml": "shift-traffic",
            "job-build-deploy.yaml": "sync-schedule",
        }
        for name, last_step in expected_last.items():
            body = read(CI / name)
            dest = [
                line for line in body.splitlines() if "--destination=" in line
            ]
            self.assertEqual(len(dest), 1, name)
            self.assertIn(":candidate-${_SHORT_SHA}", dest[0], name)
            self.assertNotIn(":sha-", dest[0], name)
            self.assertIn("--digest-file=/workspace/.digest", body, name)
            self.assertIn("@$${DIGEST}", body, name)
            self.assertNotIn("=pending", body, name)
            publish = body.split("id: publish-verified-tag")[1]
            self.assertIn("gcloud artifacts docker tags add", publish, name)
            self.assertIn(f'waitFor: ["{last_step}"]', publish, name)
            self.assertIn(":sha-${_SHORT_SHA}", publish, name)
            self.assertEqual(body.count(":sha-${_SHORT_SHA}"), 1, name)

    def test_gate_2_runs_whole_directories_not_a_hand_picked_list(
        self,
    ) -> None:
        # gate-3's check_test_count.py collects the whole directory tree, so
        # a new test file raises the collected count with no alarm — but if
        # gate-2 only runs a hand-picked file list, that new test never
        # actually executes. Whole-directory pytest calls close that gap.
        """gate-2-invariants runs whole test directories, not individual
        hand-picked files.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(CI / "build-deploy.yaml")
        self.assertIn("pytest -q tests/unit tests/api", body)
        self.assertIn("pytest -q tests/integration", body)
        self.assertIn("pytest -q tests/e2e", body)
        self.assertNotIn("tests/unit/whatsapp_adapter/test_flow_crypto.py", body)

    def test_gate_tooling_is_pinned_not_floating(self) -> None:
        # An unpinned tool version or --config=auto changes behavior between
        # runs with no diff in this repo to explain why — the opposite of a
        # reproducible gate. python:3.12-slim without a digest is the same
        # problem for the image itself.
        """Static-gate tool versions, the semgrep ruleset, and the gate
        image are all pinned, not floating tags.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for name in ("build-deploy.yaml", "job-build-deploy.yaml"):
            body = read(CI / name)
            self.assertIn("ruff==", body)
            self.assertIn("mypy==", body)
            self.assertIn("semgrep==", body)
            self.assertIn("detect-secrets==", body)
            self.assertNotIn("--config=auto", body)
            self.assertNotIn("python:3.12-slim\n", body)
            self.assertIn("python:3.12-slim@sha256:", body)
        build = read(CI / "build-deploy.yaml")
        self.assertNotIn("gcr.io/cloud-builders/npm\n", build)
        self.assertIn("gcr.io/cloud-builders/npm@sha256:", build)

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

    def test_prod_service_submits_real_source_not_no_source(self) -> None:
        # sujho-478914 has no Developer Connect link — Cloud Build can't
        # fetch source there itself, so the already-checked-out commit must
        # be uploaded as real source, not discarded with --no-source.
        """Prod's Cloud Build call submits the checked-out commit as source.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(WORKFLOWS / "cloud-run-prod-service.yaml")
        self.assertNotIn("--no-source", body)
        self.assertIn("gcloud builds submit .", body)

    def test_commit_input_never_interpolated_raw_into_shell(self) -> None:
        # `${{ inputs.commit }}` substituted straight into a `run:` block is
        # a script-injection vector — GitHub replaces it with raw text before
        # bash ever sees it. Every use here must be a plain YAML key:value
        # (an env: or with: assignment), never embedded in a longer shell
        # command string.
        """Every `${{ inputs.commit }}` use is a bare YAML key assignment, not
        shell-string interpolation.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        needle = "${{ inputs.commit }}"
        pattern = re.compile(r"^\s*[\w.]+:\s*" + re.escape(needle) + r"\s*$")
        for path in list(WORKFLOWS.glob("*.yaml")) + list(
            (HERE / "jobs" / "workflows").glob("*.yaml")
        ):
            body = read(path)
            for line in body.splitlines():
                if needle in line:
                    self.assertRegex(
                        line,
                        pattern,
                        f"{path.name}: raw inputs.commit interpolation in "
                        f"a shell string: {line.strip()!r}",
                    )

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

    def test_rollback_workflows_describe_the_marker_they_actually_use(
        self,
    ) -> None:
        """Both rollback workflows say they roll to the `prev` marker, not to
        the newest Ready revision.

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
            self.assertIn("`prev` tag", body)
            self.assertNotIn("served=true", body)
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

    def test_rollback_script_repoints_the_markers_after_shifting(
        self,
    ) -> None:
        # Without this, the revision just fled stays the recorded rollback
        # target, and the next rollback (fleeing a different bad deploy) lands
        # straight back on it.
        """rollback-cloudrun.sh moves lkg onto the revision it rolled to and
        drops prev, in that order, after the traffic shift.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(SCRIPTS / "rollback-cloudrun.sh")
        self.assertIn("--print-current", body)
        self.assertIn("--print-tag prev", body)
        shift = body.index('--to-revisions="${REVISION}=100"')
        set_lkg = body.index('--update-tags="lkg=${REVISION}"')
        drop_prev = body.index("--remove-tags=prev")
        self.assertLess(body.index("OLD_SERVING="), shift)
        self.assertLess(shift, set_lkg)
        self.assertLess(set_lkg, drop_prev)

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


def _rev(name: str, ready: bool = True) -> dict:
    """A minimal Cloud Run revision fixture: a name and a Ready condition.

    Args:
        name: the revision name.
        ready: whether its Ready condition is True.
    Returns:
        The fixture dict.
    Raises:
        None.
    """
    return {
        "metadata": {"name": name},
        "status": {
            "conditions": [
                {"type": "Ready", "status": "True" if ready else "False"}
            ]
        },
    }


def _service(
    serving: str,
    lkg: str | None = None,
    prev: str | None = None,
    percent: int = 100,
) -> dict:
    """A service fixture: one revision taking traffic, plus the 0% tagged
    entries Cloud Run adds for the lkg/prev rollback markers.

    Args:
        serving: the revision name at percent traffic.
        lkg: the revision the lkg tag points at, if any.
        prev: the revision the prev tag points at, if any.
        percent: the traffic percent on serving.
    Returns:
        The fixture dict.
    Raises:
        None.
    """
    traffic: list[dict] = [{"revisionName": serving, "percent": percent}]
    for tag, name in (("lkg", lkg), ("prev", prev)):
        if name:
            traffic.append(
                {"revisionName": name, "percent": 0, "tag": tag}
            )
    return {"status": {"traffic": traffic}}


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

    def test_picks_the_revision_the_prev_marker_records(self) -> None:
        """The rollback target is the prev marker, even when a newer revision
        exists that never took traffic.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _service(
            "redirect-00102", lkg="redirect-00102", prev="redirect-00100"
        )
        revisions = [
            _rev("redirect-00100"),
            # started fine but failed verify, so it never took traffic
            _rev("redirect-00101"),
            _rev("redirect-00102"),
        ]
        self.assertEqual(
            self.mod.pick_previous(service, revisions), "redirect-00100"
        )

    def test_print_current_reports_the_serving_revision(self) -> None:
        """serving_revision() returns the one revision at 100% traffic, and
        ignores the 0% marker entries.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _service(
            "redirect-00102", lkg="redirect-00102", prev="redirect-00100"
        )
        self.assertEqual(self.mod.serving_revision(service), "redirect-00102")

    def test_a_revision_rolled_away_from_cannot_be_picked_again(self) -> None:
        # The sequence: 00103 was good (lkg), 00104 deployed and was bad, a
        # rollback moved traffic to 00103, set lkg=00103 and dropped prev.
        # Deploying 00105 then records prev=00103 — never 00104.
        """After a rollback drops prev, the bad revision it fled is not a
        candidate; the next deploy records the revision it rolled to instead.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        rolled_back = _service("redirect-00103", lkg="redirect-00103")
        revisions = [
            _rev("redirect-00103"),
            _rev("redirect-00104"),
        ]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(rolled_back, revisions)
        after_next_deploy = _service(
            "redirect-00105", lkg="redirect-00105", prev="redirect-00103"
        )
        self.assertEqual(
            self.mod.pick_previous(
                after_next_deploy, [*revisions, _rev("redirect-00105")]
            ),
            "redirect-00103",
        )

    def test_refuses_when_nothing_is_recorded_as_previously_good(self) -> None:
        """A first deploy (lkg set, no prev) refuses rather than guessing.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _service("redirect-00100", lkg="redirect-00100")
        with self.assertRaises(SystemExit) as caught:
            self.mod.pick_previous(service, [_rev("redirect-00100")])
        self.assertIn("--revision", str(caught.exception))

    def test_refuses_when_prev_is_already_serving(self) -> None:
        """Refuses when the prev marker points at the revision already taking
        traffic — there is nothing to roll to.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _service("redirect-00100", prev="redirect-00100")
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, [_rev("redirect-00100")])

    def test_refuses_when_prev_is_no_longer_ready(self) -> None:
        """Refuses when the recorded revision exists but is not Ready, rather
        than shifting traffic onto something that cannot serve.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _service(
            "redirect-00102", lkg="redirect-00102", prev="redirect-00100"
        )
        revisions = [
            _rev("redirect-00100", ready=False),
            _rev("redirect-00102"),
        ]
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, revisions)

    def test_tagged_revision_is_none_when_the_marker_is_unset(self) -> None:
        """tagged_revision() returns None for a tag nothing carries.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = _service("redirect-00100", lkg="redirect-00100")
        self.assertIsNone(self.mod.tagged_revision(service, "prev"))
        self.assertEqual(
            self.mod.tagged_revision(service, "lkg"), "redirect-00100"
        )

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
        with self.assertRaises(SystemExit):
            self.mod.pick_previous(service, [_rev("redirect-00100")])


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

    def test_revision_containers_reads_the_flat_spec(self) -> None:
        """A revision describe has no template wrapper — spec.containers
        directly, unlike a service's own spec.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        data = {"spec": {"containers": [{"env": [{"name": "X"}]}]}}
        self.assertEqual(
            self.mod.revision_containers(data), [{"env": [{"name": "X"}]}]
        )

    def test_serving_revision_name_requires_a_clean_100_percent(self) -> None:
        """Only a single revision at exactly 100% traffic counts as serving.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        clean = {
            "status": {"traffic": [{"revisionName": "redirect-00102", "percent": 100}]}
        }
        split = {
            "status": {
                "traffic": [
                    {"revisionName": "redirect-00100", "percent": 50},
                    {"revisionName": "redirect-00101", "percent": 50},
                ]
            }
        }
        none_yet = {"status": {}}
        self.assertEqual(
            self.mod.serving_revision_name(clean), "redirect-00102"
        )
        self.assertIsNone(self.mod.serving_revision_name(split))
        self.assertIsNone(self.mod.serving_revision_name(none_yet))

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

    @staticmethod
    def _done(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess:
        """One fake gcloud result.

        Args:
            code: the process exit code.
            out: stdout.
            err: stderr.
        Returns:
            The completed process.
        Raises:
            None.
        """
        return subprocess.CompletedProcess([], code, out, err)

    def _main(self, results: list[subprocess.CompletedProcess]) -> int:
        """Run main() with scripted gcloud results.

        Args:
            results: one result per gcloud call, in order.
        Returns:
            main()'s exit code.
        Raises:
            None.
        """
        from unittest import mock

        argv = sys.argv
        try:
            sys.argv = [
                "resolve_baseline.py",
                "--name=redirect",
                "--project=p",
                "--region=r",
            ]
            with mock.patch.object(
                self.mod.subprocess, "run", side_effect=results
            ):
                return self.mod.main()
        finally:
            sys.argv = argv

    def test_a_missing_service_is_a_first_deploy(self) -> None:
        """NOT_FOUND prints nothing and exits 0.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        missing = self._done(1, err="NOT_FOUND: no such service")
        self.assertEqual(self._main([missing]), 0)

    def test_a_failed_lookup_is_not_a_first_deploy(self) -> None:
        """A permission or network error stops the build.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        denied = self._done(1, err="PERMISSION_DENIED")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self._main([denied]), 1)

    def test_a_live_service_without_one_revision_stops_the_build(self) -> None:
        """A service that exists with split traffic is not a first deploy.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        split = {
            "status": {
                "traffic": [
                    {"revisionName": "a", "percent": 50},
                    {"revisionName": "b", "percent": 50},
                ]
            }
        }
        live = self._done(0, out=json.dumps(split))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self._main([live]), 1)

    def test_a_live_service_must_carry_the_release_sha(self) -> None:
        """A serving revision with no RELEASE_COMMIT_SHA stops the build,
        and one that has it is printed.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        service = {
            "status": {
                "traffic": [{"revisionName": "redirect-1", "percent": 100}]
            }
        }
        bare = {"spec": {"containers": [{"env": []}]}}
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                self._main(
                    [
                        self._done(0, out=json.dumps(service)),
                        self._done(0, out=json.dumps(bare)),
                    ]
                ),
                1,
            )
        tagged = {
            "spec": {
                "containers": [
                    {
                        "env": [
                            {"name": "RELEASE_COMMIT_SHA", "value": "abc"}
                        ]
                    }
                ]
            }
        }
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self._main(
                [
                    self._done(0, out=json.dumps(service)),
                    self._done(0, out=json.dumps(tagged)),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "abc")


class MypyRatchetTests(unittest.TestCase):
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

        path = CI / "gates" / "mypy_ratchet.py"
        spec = importlib.util.spec_from_file_location("mypy_ratchet", path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_signature_drops_line_number_keeps_message(self) -> None:
        """Two errors at different lines with the same message share one
        signature (counted twice) — a line shift elsewhere in the file isn't
        a new error, but a second copy of an error is.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        stdout = (
            'a/b.py:10: error: Incompatible types  [assignment]\n'
            'a/b.py:40: error: Incompatible types  [assignment]\n'
        )
        self.assertEqual(
            dict(self.mod.parse_error_signatures(stdout)),
            {"a/b.py: Incompatible types  [assignment]": 2},
        )

    def test_a_second_copy_of_an_existing_error_is_new(self) -> None:
        """Adding a duplicate of a baseline error is caught, not hidden by a
        set's de-duplication.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        one = "a/b.py:10: error: Incompatible types  [assignment]\n"
        baseline = self.mod.parse_error_signatures(one)
        head = self.mod.parse_error_signatures(one + one.replace("10", "50"))
        self.assertEqual(sum((head - baseline).values()), 1)

    def test_absolute_mode_needs_no_baseline_arguments(self) -> None:
        """--absolute is accepted alone; without it both baseline arguments
        are required.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        import contextlib
        import io
        import sys

        argv = sys.argv
        try:
            sys.argv = ["mypy_ratchet.py", "--absolute"]
            self.assertTrue(self.mod._parse_args().absolute)
            sys.argv = ["mypy_ratchet.py"]
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                SystemExit
            ):
                self.mod._parse_args()
        finally:
            sys.argv = argv

    def test_a_mypy_crash_is_a_failure_not_zero_errors(self) -> None:
        """mypy exiting 2 or more raises instead of reading as no errors.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        import subprocess
        from unittest import mock

        crashed = subprocess.CompletedProcess([], 2, "", "config error")
        with mock.patch.object(
            self.mod.subprocess, "run", return_value=crashed
        ), self.assertRaises(RuntimeError):
            self.mod.error_signatures(Path("."))

    def test_swapping_one_error_for_a_different_one_is_not_silent(
        self,
    ) -> None:
        # This is the exact gap a count-only ratchet has: fix one error,
        # introduce a different one, the total count never moves.
        """Fixing one error while introducing a different one is a new
        signature, not a wash.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        baseline = self.mod.parse_error_signatures(
            "a/b.py:10: error: Missing return statement  [return]\n"
        )
        head = self.mod.parse_error_signatures(
            "a/c.py:5: error: Incompatible types  [assignment]\n"
        )
        self.assertEqual(len(baseline), len(head))
        self.assertTrue(head - baseline)

    def test_identical_error_set_has_nothing_new(self) -> None:
        """The same errors on both sides introduce nothing new.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        stdout = "a/b.py:10: error: Missing return statement  [return]\n"
        baseline = self.mod.parse_error_signatures(stdout)
        head = self.mod.parse_error_signatures(stdout)
        self.assertFalse(head - baseline)


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

    def test_dependabot_watches_every_service_requirements_file(self) -> None:
        # "/" alone watched the root only, so a vulnerable pin inside a
        # service's own requirements.txt — the ones that end up in a deployed
        # image — was never reported.
        """Every directory holding a requirements file that the build installs
        is listed in dependabot.yml, taken from tests/ci/paths.py.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        config = read(HERE.parent / ".github" / "dependabot.yml")
        paths = read(HERE.parent / "tests" / "ci" / "paths.py")
        service_files = re.findall(r'"([^"]+/requirements\.txt)"', paths)
        self.assertGreater(len(service_files), 5)
        for req in service_files:
            directory = f"/{req.rsplit('/', 1)[0]}"
            self.assertIn(f'- "{directory}"', config, req)
        self.assertIn("npm", config)

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

    def test_nothing_pushed_is_gitignored(self) -> None:
        # A file in the push list that git never tracked is a file
        # apply-phase2.sh cannot read on a fresh clone.
        """No path in lib.sh's push list matches an active .gitignore rule.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        ignored = gitignore_rules()
        sources = re.findall(
            r":\$\{BASH_SOURCE%/\*\}/(\S+?)\"", read(HERE / "lib.sh")
        )
        self.assertGreater(len(sources), 10)
        for source in sources:
            name = source.rsplit("/", 1)[-1]
            self.assertNotIn(name, ignored, source)
            self.assertNotIn(f"phase2/{source}", ignored, source)

    def test_no_gitignore_rule_names_a_file_that_is_already_tracked(
        self,
    ) -> None:
        # git only ignores files it is not already following, so such a rule
        # reads as "this is not pushed" while the file is pushed on every
        # clone. Either the rule or the tracking has to go.
        """Every active .gitignore rule names something git is not tracking.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        listed = subprocess.run(
            ["git", "ls-files"],
            cwd=HERE.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode != 0:
            self.skipTest("not a git checkout")
        tracked = set(listed.stdout.split())
        for rule in gitignore_rules():
            if rule.endswith("/") or rule.startswith(("!", "*")):
                continue
            self.assertNotIn(rule, tracked, rule)


    def test_the_tracked_runbook_does_not_lean_on_an_ignored_file(
        self,
    ) -> None:
        # IAM-table.md is tracked; the jobs notes beside it are not. A reader
        # who clones this repo has the first and not the second, so the first
        # cannot say "see the second" for anything that matters.
        """IAM-table.md points at no .gitignore'd file.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(HERE / "IAM-table.md")
        for rule in gitignore_rules():
            name = rule.rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".md"):
                self.assertNotIn(name, body, rule)


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
        """IAM-table.md documents that a Lead must start a production run.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(HERE / "IAM-table.md")
        self.assertIn("production", body)
        self.assertIn("started by a Lead", body)
        self.assertIn("no required reviewers", body)


JOBS_WORKFLOWS = HERE / "jobs" / "workflows"
DEPLOY_WORKFLOW_FILES = (
    WORKFLOWS / "cloud-run-preprod-service.yaml",
    WORKFLOWS / "cloud-run-prod-service.yaml",
    WORKFLOWS / "cloud-run-preprod-rollback.yaml",
    WORKFLOWS / "cloud-run-prod-rollback.yaml",
    JOBS_WORKFLOWS / "cloud-run-preprod-job.yaml",
    JOBS_WORKFLOWS / "cloud-run-prod-job.yaml",
)
PROD_SOURCE_UPLOADERS = (
    WORKFLOWS / "cloud-run-prod-service.yaml",
    JOBS_WORKFLOWS / "cloud-run-prod-job.yaml",
)
PREPROD_SOURCE_UPLOADERS = (
    WORKFLOWS / "cloud-run-preprod-service.yaml",
    JOBS_WORKFLOWS / "cloud-run-preprod-job.yaml",
)


def run_blocks(text: str) -> list[str]:
    """Every `run: |` shell body in a workflow file, as one string each.

    Args:
        text: a workflow file's text.
    Returns:
        The shell bodies, comments included.
    Raises:
        None.
    """
    blocks: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = re.match(r"^(\s*)(?:- )?run: \|\s*$", lines[i])
        if not match:
            i += 1
            continue
        indent = len(match.group(1))
        body: list[str] = []
        i += 1
        while i < len(lines) and (
            not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent
        ):
            body.append(lines[i])
            i += 1
        blocks.append("\n".join(body))
    return blocks


class WorkflowHardeningTests(unittest.TestCase):
    def test_no_github_expression_inside_any_shell_body(self) -> None:
        # ${{ }} is pasted into the script text before bash parses it, so a
        # typed input becomes code. Inputs reach shell only through env:.
        """No ${{ }} expression appears inside a run: body in any workflow.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in DEPLOY_WORKFLOW_FILES:
            for block in run_blocks(read(path)):
                self.assertNotIn("${{", block, f"{path.name}: {block[:80]!r}")

    def test_every_checkout_drops_the_stored_github_token(self) -> None:
        """Every actions/checkout sets persist-credentials: false, so no
        GitHub token sits in .git (which Pre-Prod uploads to Cloud Build).

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in DEPLOY_WORKFLOW_FILES:
            text = read(path)
            for chunk in text.split("actions/checkout@")[1:]:
                head = chunk.split("\n      - ")[0]
                self.assertIn("persist-credentials: false", head, path.name)

    def test_source_upload_uses_an_ignore_file_that_drops_credentials(
        self,
    ) -> None:
        """Every workflow that uploads source excludes the auth step's
        gha-creds file; Prod also excludes .git, Pre-Prod keeps it.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in (*PROD_SOURCE_UPLOADERS, *PREPROD_SOURCE_UPLOADERS):
            text = read(path)
            self.assertIn("gcloud builds submit .", text, path.name)
            self.assertNotIn("--no-source", text, path.name)
            self.assertIn("--ignore-file=", text, path.name)
            self.assertIn("gha-creds-*.json", text, path.name)
            self.assertIn("--gcs-source-staging-dir=gs://", text, path.name)
        for path in PROD_SOURCE_UPLOADERS:
            self.assertIn("'.git' 'gha-creds-*.json'", read(path), path.name)
        for path in PREPROD_SOURCE_UPLOADERS:
            self.assertIn("fetch-depth: 0", read(path), path.name)

    def test_prod_workflows_take_a_full_sha_and_hold_no_credential_early(
        self,
    ) -> None:
        """Prod takes only a full 40-character SHA, and nothing authenticates
        to GCP before the production Environment approves.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in PROD_SOURCE_UPLOADERS:
            text = read(path)
            self.assertIn("[0-9a-f]{40}", text, path.name)
            before_approval = text.split("environment: production")[0]
            self.assertNotIn(
                "google-github-actions/auth", before_approval, path.name
            )
            self.assertNotIn("artifacts docker images", before_approval)

    def test_preprod_workflows_normalise_the_commit(self) -> None:
        """Pre-Prod validates a typed commit's shape and resolves it to the
        full SHA before anything uses it; an optional baseline must be a full
        SHA that is an ancestor of the commit.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in PREPROD_SOURCE_UPLOADERS:
            text = read(path)
            self.assertIn("[0-9a-f]{7,40}", text, path.name)
            self.assertIn('git rev-parse --verify "${COMMIT_INPUT}^{commit}"', text)
            self.assertIn("baseline:", text, path.name)
            self.assertIn('git merge-base --is-ancestor "$BASELINE_INPUT"', text)
            self.assertIn("_BASELINE_SHA=$BASELINE", text, path.name)

    def test_short_sha_is_12_characters_everywhere(self) -> None:
        """Image tags use a 12-character SHA, not 7 (7 collides at real
        repo sizes).

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in DEPLOY_WORKFLOW_FILES:
            text = read(path)
            self.assertNotIn("cut -c1-7", text, path.name)
        for path in (*PROD_SOURCE_UPLOADERS, *PREPROD_SOURCE_UPLOADERS):
            self.assertIn("cut -c1-12", read(path), path.name)

    def test_prod_rollback_has_its_own_environment(self) -> None:
        """Prod rollback is gated by the production-rollback Environment, the
        Pre-Prod one has no Environment, and the main-only check reads
        $GITHUB_REF.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        prod = read(WORKFLOWS / "cloud-run-prod-rollback.yaml")
        preprod = read(WORKFLOWS / "cloud-run-preprod-rollback.yaml")
        self.assertIn("environment: production-rollback", prod)
        self.assertNotIn("environment:", preprod)
        for text in (prod, preprod):
            self.assertIn('"$GITHUB_REF" != "refs/heads/main"', text)

    def test_nothing_this_phase_ships_runs_on_a_pull_request(self) -> None:
        # Decision 11: merging deploys nothing, so there is nothing to protect
        # at merge time. Every gate lives in the Pre-Prod build instead. A
        # pull_request-triggered workflow would also run the PR's own copy of
        # itself, which is a gate an author can edit.
        """No workflow this phase pushes triggers on a pull request, and no
        required-status-check ruleset is shipped with it.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in DEPLOY_WORKFLOW_FILES:
            text = read(path)
            self.assertNotIn("pull_request", text, path.name)
            self.assertIn("workflow_dispatch:", text, path.name)
        self.assertFalse((HERE / "rulesets").exists())
        self.assertFalse((WORKFLOWS / "pr-checks.yaml").exists())
        lib = read(HERE / "lib.sh")
        self.assertNotIn("pr-checks", lib)
        self.assertNotIn("required_status_checks", lib)
        apply = read(HERE / "apply-phase2.sh")
        self.assertNotIn("--require-checks", apply)
        self.assertIn("nothing runs on a pull request", apply)


# Every gcloud command this repo is allowed to call, group and verb. The point
# is not tidiness: `gcloud run revisions update` was used for months and does
# not exist, so the step calling it would have failed every single deploy —
# after traffic had already moved. Any new command has to be added here
# deliberately, which is the moment to check it is real.
ALLOWED_GCLOUD = (
    ("artifacts", "docker", "images"),
    ("artifacts", "docker", "tags"),
    ("artifacts", "repositories", "create"),
    ("artifacts", "repositories", "describe"),
    ("billing", "projects", "link"),
    ("builds", "submit"),
    ("components", "install"),
    ("iam", "service-accounts", "add-iam-policy-binding"),
    ("iam", "service-accounts", "create"),
    ("iam", "workload-identity-pools", "create"),
    ("iam", "workload-identity-pools", "providers"),
    ("projects", "create"),
    ("projects", "describe"),
    ("run", "deploy"),
    ("run", "jobs", "deploy"),
    ("run", "jobs", "describe"),
    ("run", "jobs", "execute"),
    ("run", "revisions", "describe"),
    ("run", "revisions", "list"),
    ("run", "services", "add-iam-policy-binding"),
    ("run", "services", "describe"),
    ("run", "services", "update-traffic"),
    ("scheduler", "jobs", "create"),
    ("scheduler", "jobs", "describe"),
    ("scheduler", "jobs", "update"),
    ("secrets", "versions", "access"),
    ("services", "enable"),
    ("storage", "buckets", "create"),
    ("storage", "buckets", "describe"),
)


def shipped_files() -> list[Path]:
    """Every recipe, workflow, script and gate this phase ships.

    Args:
        None.
    Returns:
        The file paths.
    Raises:
        None.
    """
    return [
        *CI.glob("*.yaml"),
        *(CI / "gates").glob("*.py"),
        *(p for p in SCRIPTS.glob("*") if p.is_file()),
        *WORKFLOWS.glob("*.yaml"),
        *(HERE / "jobs" / "workflows").glob("*.yaml"),
        *(HERE / "jobs" / "scripts").glob("*.py"),
    ]


def _words_until_flag(tokens: list[str]) -> tuple[str, ...]:
    """The leading command words of one invocation, stopping at the first
    token that is a flag, an argument or a variable.

    Args:
        tokens: the whitespace- or quote-separated tokens after "gcloud".
    Returns:
        Up to three command words.
    Raises:
        None.
    """
    words: list[str] = []
    for token in tokens:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", token) or len(words) == 3:
            break
        words.append(token)
    return tuple(words)


def gcloud_invocations(
    text: str, python: bool = False
) -> list[tuple[str, ...]]:
    """The gcloud command words invoked in this file.

    Shell and YAML are read as command lines with comment lines dropped;
    Python is read as argv lists ("gcloud", "run", ...), so that prose in a
    docstring is never mistaken for a command.

    Args:
        text: the file's text.
        python: parse argv lists instead of command lines.
    Returns:
        One tuple of command words per invocation, flags and arguments
        dropped.
    Raises:
        None.
    """
    if python:
        return [
            words
            for tail in text.split('"gcloud",')[1:]
            if (words := _words_until_flag(re.findall(r'"([^"\n]*)"', tail)))
        ]
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    return [
        words
        for tail in re.split(r'["\s(]gcloud["\s,]', code)[1:]
        if (words := _words_until_flag(re.split(r'[\s",\]]+', tail)))
    ]


class RemoteVerifierTests(unittest.TestCase):
    def test_it_greps_for_what_the_recipes_actually_do(self) -> None:
        # verify-phase2.sh --remote reads the recipes off main and greps them.
        # A pattern that no longer appears would make every remote run fail
        # (or, worse, a dropped check would pass silently).
        """Every recipe pattern verify-phase2.sh greps for is present in the
        local recipes, and it no longer looks for the retired label.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        verifier = read(HERE / "verify-phase2.sh")
        self.assertNotIn("served=true", verifier)
        self.assertEqual(verifier.count("check_main_only "), 2)
        self.assertIn("deployment-branch-policies", verifier)
        for pattern in (
            "--to-revisions=",
            "--update-tags=",
            "--remove-tags=",
            "--expect-digest=",
        ):
            self.assertIn(pattern, verifier)
            for name in ("build-deploy.yaml", "deploy-only.yaml"):
                self.assertIn(pattern, read(CI / name), name)


class GcloudSurfaceTests(unittest.TestCase):
    def test_every_gcloud_command_used_is_one_that_exists(self) -> None:
        """Nothing calls a gcloud command outside the reviewed allow-list.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for path in shipped_files():
            invocations = gcloud_invocations(
                read(path), python=path.suffix == ".py"
            )
            for words in invocations:
                matched = any(
                    words[: len(allowed)] == allowed
                    for allowed in ALLOWED_GCLOUD
                )
                self.assertTrue(
                    matched, f"{path.name}: gcloud {' '.join(words)}"
                )

    def test_the_scan_would_notice_the_bug_it_exists_for(self) -> None:
        # Guards the guard: a parser that silently matched nothing would make
        # the test above pass for ever.
        """gcloud_invocations() finds a real invocation and ignores one that
        is only mentioned in a comment.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        sample = (
            "        # gcloud run revisions update is not a command\n"
            '        gcloud run revisions update "$$REV" --update-labels=a=b\n'
        )
        self.assertEqual(
            gcloud_invocations(sample), [("run", "revisions", "update")]
        )
        self.assertEqual(
            gcloud_invocations(
                '    run(["gcloud", "run", "revisions", "update", name])',
                python=True,
            ),
            [("run", "revisions", "update")],
        )
        self.assertNotIn(
            ("run", "revisions", "update"),
            [
                words[:3]
                for words in gcloud_invocations(
                    "# gcloud run revisions update, mentioned only\n"
                )
            ],
        )


class VerifyRevisionTests(unittest.TestCase):
    """The gate's own logic, called directly — not grepped for."""

    def setUp(self) -> None:
        """Import the gate module fresh for every test.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        sys.path.insert(0, str(CI / "gates"))
        import verify_revision as mod  # type: ignore

        self.mod = mod

    @staticmethod
    def _revision(
        digest: str = "sha256:aa", sha: str = "c" * 40, ready: bool = True
    ) -> dict:
        """A minimal Cloud Run revision describe payload.

        Args:
            digest: the digest its image is pinned to.
            sha: its RELEASE_COMMIT_SHA env value.
            ready: whether its Ready condition is True.
        Returns:
            The fixture dict.
        Raises:
            None.
        """
        return {
            "status": {
                "conditions": [
                    {"type": "Ready", "status": "True" if ready else "False"}
                ]
            },
            "spec": {
                "containers": [
                    {
                        "image": f"reg/svc@{digest}",
                        "env": [{"name": "RELEASE_COMMIT_SHA", "value": sha}],
                    }
                ]
            },
        }

    def test_a_different_image_fails_even_with_the_right_commit(self) -> None:
        # The check that has teeth: the same commit can produce a different
        # image, and a stale revision can answer on a reused tag.
        """A digest mismatch fails; the matching digest passes.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        revision = self._revision(digest="sha256:aa")
        self.assertTrue(
            self.mod.revision_is_ready_at(revision, "c" * 40, "sha256:aa")
        )
        self.assertFalse(
            self.mod.revision_is_ready_at(revision, "c" * 40, "sha256:bb")
        )

    def test_a_partial_digest_match_is_not_a_match(self) -> None:
        """A digest that is only a prefix of the running one fails.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        revision = self._revision(digest="sha256:aabbcc")
        self.assertFalse(
            self.mod.revision_is_ready_at(revision, "c" * 40, "sha256:aabb")
        )

    def test_not_ready_fails_whatever_it_is_running(self) -> None:
        """A revision that is not Ready fails even with both values right.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        revision = self._revision(ready=False)
        self.assertFalse(
            self.mod.revision_is_ready_at(revision, "c" * 40, "sha256:aa")
        )

    def test_the_digest_is_required_unless_only_printing(self) -> None:
        """--expect-digest is mandatory for a check and ignored for
        --print-revision.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        common = [
            "--service=redirect",
            "--project=p",
            "--region=r",
            "--tag=build-abc",
        ]
        argv = sys.argv
        try:
            sys.argv = ["verify_revision.py", *common, "--expect-sha=abc"]
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                SystemExit
            ):
                self.mod.parse_args()
            sys.argv = ["verify_revision.py", *common, "--print-revision"]
            self.assertTrue(self.mod.parse_args().print_revision)
        finally:
            sys.argv = argv


class WifBindingTests(unittest.TestCase):
    def test_every_github_account_trusts_one_subject_not_the_repo(self) -> None:
        """provision-wif.sh binds exact OIDC subjects; no repo-wide principalSet
        is left, and the provider pins the repository too.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(SCRIPTS / "provision-wif.sh")
        self.assertNotIn("principalSet", body)
        self.assertNotIn("attribute.repository/", body)
        self.assertIn("principal://", body)
        self.assertIn('SUBJECT_MAIN="ref:refs/heads/main"', body)
        self.assertIn('SUBJECT_PROD="environment:production"', body)
        self.assertIn(
            'SUBJECT_PROD_ROLLBACK="environment:production-rollback"', body
        )
        self.assertIn("assertion.repository == ", body)
        for line in (
            'bind_subject github-deploy-preprod "$PREPROD_PROJECT" "$SUBJECT_MAIN"',
            'bind_subject github-deploy-prod "$PROD_PROJECT" "$SUBJECT_PROD"',
            'bind_subject github-rollback-prod "$PROD_PROJECT" "$SUBJECT_PROD_ROLLBACK"',
            'bind_subject github-eval "$PREPROD_PROJECT" "$SUBJECT_MAIN"',
        ):
            self.assertIn(line, body)

    def test_environment_names_match_between_workflows_and_bindings(
        self,
    ) -> None:
        """The Environment names GCP trusts are exactly the ones the prod
        workflows declare.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        wif = read(SCRIPTS / "provision-wif.sh")
        for path in PROD_SOURCE_UPLOADERS:
            self.assertIn("environment: production\n", read(path))
        self.assertIn("environment:production\"", wif)
        rollback = read(WORKFLOWS / "cloud-run-prod-rollback.yaml")
        self.assertIn("environment: production-rollback", rollback)
        self.assertIn("environment:production-rollback", wif)

    def test_no_developer_connect_script_is_left(self) -> None:
        """No pipeline fetches through Developer Connect any more, so its
        setup script is gone too.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.assertFalse((SCRIPTS / "developer-connect-setup.sh").exists())


class IamTableHardeningTests(unittest.TestCase):
    def test_table_covers_every_grant_the_pipeline_needs(self) -> None:
        """IAM-table.md names each grant the workflows and recipes rely on:
        source upload, actAs on the builder, the Cloud Run service agent's
        cross-project pull, the eval account, and both Environments.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        body = read(HERE / "IAM-table.md")
        for needle in (
            "github-eval",
            "roles/storage.objectUser",
            "build-source",
            "roles/iam.serviceAccountUser` on `prod-builder@sujho-preprod",
            "serverless-robot-prod",
            "roles/run.jobsExecutorWithOverrides",
            "roles/logging.viewer",
            "production-rollback",
            "repo:Sujho/platform:environment:production",
            "repo:Sujho/platform:ref:refs/heads/main",
        ):
            self.assertIn(needle, body)

    def test_iam_table_is_tracked_and_not_pushed(self) -> None:
        """IAM-table.md isn't gitignored and isn't in the push list."""
        gitignore = read(HERE.parent / ".gitignore")
        active = [
            line
            for line in gitignore.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertNotIn("phase2/IAM-table.md", active)
        self.assertNotIn("IAM-table.md:", read(HERE / "lib.sh"))


if __name__ == "__main__":
    unittest.main()
