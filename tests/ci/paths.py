"""Locate this tests tree and the Sujho workspace it runs against."""

from __future__ import annotations

import os
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent

SUITE_DIRS = ("unit", "api", "integration", "e2e")

SECRET_EXCLUDE = (
    r"\.venv/|(^|/)\.git/|(^|/)__pycache__/|(^|/)Data/"
    r"|(^|/)evals/reports/|(^|/)\.(mypy|ruff|pytest)_cache/|^\.env$"
)

SERVICE_REQUIREMENTS = (
    "user_service/app/requirements.txt",
    "text_agent/app/requirements.txt",
    "whatsapp_adapter/app/requirements.txt",
    "document_worker/requirements.txt",
    "redirect_service/app/requirements.txt",
    "knowledge_store/requirements.txt",
)

TEST_REQUIREMENTS = (
    "tests/unit/requirements-test.txt",
    "tests/e2e/requirements-test.txt",
)

ROOT_PACKAGES = (
    "mypy",
    "ruff",
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "hypothesis",
    "detect-secrets",
    "diff-cover",
)

MUTATION_PACKAGES = (
    "mutmut",
    "pytest",
    "pytest-asyncio",
    "hypothesis",
)

MUTATION_REQUIREMENTS = (
    "user_service/app/requirements.txt",
    "tests/unit/requirements-test.txt",
)


def workspace_root() -> Path:
    """Sujho umbrella checkout (contains ``user_service/`` and this ``tests/``)."""
    override = os.environ.get("SUJHO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    parent = TESTS_ROOT.parent
    if (parent / "user_service").is_dir() and (parent / "pyproject.toml").is_file():
        return parent
    raise SystemExit(
        "Cannot find the Sujho workspace (need user_service/ and pyproject.toml). "
        "Clone github.com/Sujho/sujho, init submodules, and place this tree at "
        "tests/, or set SUJHO_ROOT to the umbrella checkout."
    )


def suite_test_files() -> list[Path]:
    """Every ``test_*.py`` under the runnable suites (not tooling/ci/mutation)."""
    files: list[Path] = []
    for name in SUITE_DIRS:
        directory = TESTS_ROOT / name
        if directory.is_dir():
            files.extend(sorted(directory.rglob("test_*.py")))
    return files
