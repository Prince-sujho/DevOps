#!/usr/bin/env python3
"""Local invariants for Phase 2 — no GitHub calls."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import coverage_ratchet  # noqa: E402

PY_WORKFLOW = (HERE / "workflows" / "pr-checks.yml").read_text()
ADMIN_WORKFLOW = (HERE / "workflows" / "pr-checks-admin.yml").read_text()
DEV_RULESET = json.loads((HERE / "rulesets" / "main-required-checks.json").read_text())
APPLY = (HERE / "apply-phase2.sh").read_text()
LIB = (HERE / "lib.sh").read_text()
PHASE1_MAIN = json.loads(
    (HERE.parent / "phase1" / "rulesets" / "main.json").read_text()
)
PINS = json.loads((HERE.parent / "action-pins.json").read_text())["pins"]


def _pin(name: str) -> str:
    return f"{name}@{PINS[name]['sha']}"


def _pr(ruleset: dict) -> dict:
    for rule in ruleset["rules"]:
        if rule.get("type") == "pull_request":
            return rule["parameters"]
    raise AssertionError("no pull_request rule")


def _required_checks(ruleset: dict) -> list[str]:
    for rule in ruleset["rules"]:
        if rule.get("type") == "required_status_checks":
            return [c["context"] for c in rule["parameters"]["required_status_checks"]]
    return []


class WorkflowTests(unittest.TestCase):
    def test_python_workflow_targets_main_not_extra_branches(self) -> None:
        self.assertIn("branches: [main]", PY_WORKFLOW)
        self.assertNotIn("branches: [dev]", PY_WORKFLOW)
        self.assertNotIn("branches: [pre-prod]", PY_WORKFLOW)

    def test_runs_umbrella_pipeline_not_per_repo_pytest(self) -> None:
        self.assertIn("python tests/ci/pipeline.py", PY_WORKFLOW)
        self.assertIn("submodules: recursive", PY_WORKFLOW)
        self.assertIn('python-version: "3.13"', PY_WORKFLOW)
        self.assertNotIn("pytest --cov", PY_WORKFLOW)
        self.assertNotIn("--cov=app", PY_WORKFLOW)
        self.assertNotIn("requirements-dev.txt is missing", PY_WORKFLOW)

    def test_umbrella_suite_copy_is_attached(self) -> None:
        root = HERE.parent
        self.assertTrue((root / "tests" / "ci" / "pipeline.py").is_file())
        self.assertTrue((root / "Eval-Suite" / "run.py").is_file())
        self.assertFalse((root / "Test-Suite").exists())
        self.assertIn("DEFAULT_STAGES", (root / "tests" / "ci" / "pipeline.py").read_text())

    def test_does_not_use_break_system_packages(self) -> None:
        self.assertNotIn("--break-system-packages", PY_WORKFLOW)

    def test_gate_job_exists_so_required_checks_do_not_hang(self) -> None:
        self.assertIn("name: pr-checks", PY_WORKFLOW)
        self.assertIn("if: always()", PY_WORKFLOW)
        self.assertIn('code" != "true"', PY_WORKFLOW)

    def test_coverage_comment_is_updated_not_spammed(self) -> None:
        self.assertIn("phase2-coverage", PY_WORKFLOW)
        self.assertIn("updateComment", PY_WORKFLOW)
        self.assertIn("continue-on-error: true", PY_WORKFLOW)

    def test_admin_workflow_is_node_not_python(self) -> None:
        self.assertIn("setup-node", ADMIN_WORKFLOW)
        self.assertNotIn("ruff", ADMIN_WORKFLOW)
        self.assertNotIn("pytest", ADMIN_WORKFLOW)
        self.assertIn("name: pr-checks", ADMIN_WORKFLOW)

    def test_actions_are_sha_pinned(self) -> None:
        for text in (PY_WORKFLOW, ADMIN_WORKFLOW):
            self.assertIn(_pin("actions/checkout"), text)
            self.assertNotIn("actions/checkout@v4\n", text)
            self.assertNotIn("actions/checkout@v4\r", text)
            self.assertNotIn("uses: actions/checkout@v4\n", text)
        self.assertIn(_pin("actions/setup-python"), PY_WORKFLOW)
        self.assertIn(_pin("dorny/paths-filter"), PY_WORKFLOW)
        self.assertIn(_pin("actions/github-script"), PY_WORKFLOW)
        self.assertIn(_pin("actions/setup-node"), ADMIN_WORKFLOW)


class FloorsTests(unittest.TestCase):
    def test_this_folder_does_not_ship_a_second_floors_file(self) -> None:
        self.assertFalse((HERE / "coverage_floors.json").exists())
        self.assertIn("tests/outcomes/pytest/coverage_floors.json", PY_WORKFLOW)
        self.assertNotIn("phase2/coverage_floors.json", PY_WORKFLOW)


class ApplyTests(unittest.TestCase):
    def test_lands_on_sujho_not_service_repos(self) -> None:
        self.assertIn('PHASE2_UMBRELLA_REPO="sujho"', LIB)
        self.assertIn("text-agent", LIB.split("PHASE2_SKIP_REPOS")[1].split(")")[0])
        self.assertNotIn("pytest --cov", APPLY)
        self.assertIn("pipeline.py", APPLY)


class RatchetTests(unittest.TestCase):
    def _cov(self, folder: Path, name: str, pct: float) -> Path:
        path = folder / name
        path.write_text(json.dumps({"totals": {"percent_covered": pct}}))
        return path

    def test_drop_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head, base = self._cov(root, "h.json", 80.0), self._cov(root, "b.json", 90.0)
            self.assertEqual(coverage_ratchet.ratchet(head, base, root / "s.txt"), 1)

    def test_hold_or_rise_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                coverage_ratchet.ratchet(
                    self._cov(root, "h.json", 90.0),
                    self._cov(root, "b.json", 90.0),
                    root / "s.txt",
                ),
                0,
            )
            self.assertEqual(
                coverage_ratchet.ratchet(
                    self._cov(root, "h2.json", 91.0),
                    self._cov(root, "b.json", 90.0),
                    root / "s.txt",
                ),
                0,
            )

    def test_missing_base_is_zero_not_a_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self._cov(root, "h.json", 10.0)
            self.assertEqual(
                coverage_ratchet.ratchet(head, root / "missing.json", root / "s.txt"), 0
            )

    def test_missing_head_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._cov(root, "b.json", 50.0)
            self.assertEqual(
                coverage_ratchet.ratchet(root / "missing.json", base, root / "s.txt"), 1
            )


class RequiredChecksTests(unittest.TestCase):
    def test_phase2_ruleset_keeps_code_owners_on_main(self) -> None:
        self.assertTrue(_pr(DEV_RULESET)["require_code_owner_review"])
        self.assertEqual(
            _pr(DEV_RULESET)["require_code_owner_review"],
            _pr(PHASE1_MAIN)["require_code_owner_review"],
        )

    def test_only_the_gate_job_is_required(self) -> None:
        self.assertEqual(_required_checks(DEV_RULESET), ["pr-checks"])
        self.assertNotIn("lint", _required_checks(DEV_RULESET))
        self.assertNotIn("unit-tests", _required_checks(DEV_RULESET))
        self.assertNotIn("suite", _required_checks(DEV_RULESET))

    def test_phase1_main_ruleset_does_not_require_checks_yet(self) -> None:
        self.assertEqual(_required_checks(PHASE1_MAIN), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
