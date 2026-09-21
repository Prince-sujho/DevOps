# Phase 2 extras. Source after phase1/lib.sh from apply/verify scripts.
#
# The 836-test suite lives in the sujho umbrella (tests/ci/pipeline.py).
# Do not land a generic `pytest tests/` workflow on the service repos.

PHASE2_UMBRELLA_REPO="sujho"
ADMIN_REPOS=(admin)

# Service repos do not hold the suite. sujho-ops-mcp already has its own CI.
PHASE2_SKIP_REPOS=(
  text-agent
  user-service
  whatsapp-adapter
  document-worker
  redirect-service
  knowledge-store
  sujho-ops-mcp
)

PHASE2_CHECK_REPOS=("${PHASE2_UMBRELLA_REPO}" "${ADMIN_REPOS[@]}")

PHASE2_WORKFLOW_DEST=".github/workflows/pr-checks.yml"
PHASE2_BRANCH="chore/phase2-pr-checks"
PHASE2_REQUIRED_CHECK="pr-checks"
