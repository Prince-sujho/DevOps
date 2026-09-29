#!/usr/bin/env python3
"""Shared paths and package lists for tests/ci/pipeline.py.

Written against the post-phase0 merged layout (see phase0/repos.json) —
per-service paths below (user_service/, admin/, etc.) only exist once that
merge has actually landed in the real repo. Until then, every path here is
a plan, not a fact: _install_requirement_files already skips a requirements
file that doesn't exist yet, so pipeline.py degrades gracefully rather than
crashing when run against a checkout that predates the merge.
"""
from __future__ import annotations

import os
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent

# Every backend service's own requirements.txt, post-phase0 paths.
SERVICE_REQUIREMENTS = (
    "user_service/app/requirements.txt",
    "whatsapp_adapter/app/requirements.txt",
    "text_agent/app/requirements.txt",
    "document_worker/requirements.txt",
    "admin/app/requirements.txt",
    "redirect_service/app/requirements.txt",
    "knowledge_store/requirements.txt",
)

TEST_REQUIREMENTS = ("tests/requirements.txt",)

# infra is installed editable, not from a requirements.txt.
ROOT_PACKAGES = ("-e", "./infra")

MUTATION_PACKAGES = ("mutmut",)
# user_service is mutmut's target package (see stage_install_mutation).
MUTATION_REQUIREMENTS = ("user_service/app/requirements.txt", *TEST_REQUIREMENTS)

# Matches the baseline already used by build-deploy.yaml/job-build-deploy.yaml.
SECRET_EXCLUDE = r"(^|/)\.venv/|(^|/)node_modules/|(^|/)mutants/"


def workspace_root() -> Path:
    """The product checkout to run pipeline stages against.

    Args:
        None.
    Returns:
        $SUJHO_ROOT if set, else the repo root two levels above this file
        (tests/ci/paths.py -> tests/ci -> tests -> repo root).
    Raises:
        None.
    """
    override = os.environ.get("SUJHO_ROOT")
    return Path(override).resolve() if override else TESTS_ROOT.parent
