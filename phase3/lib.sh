# Phase 3 extras. Source after phase1/lib.sh.
#
# AI review runs on every full-treatment PR into `main` so the Lead sees the
# bot comment on the same page as Approve. Lead Approve is still required.
# Not a substitute for the Lead.

PHASE3_REPOS=(
  sujho
  text-agent
  user-service
  whatsapp-adapter
  admin
  document-worker
  redirect-service
  knowledge-store
  sujho-ops-mcp
)

# Repos that also have Phase 2 `pr-checks`. Required-check ruleset for these
# lists both jobs. Other repos must require `ai-review` only (no pr-checks job).
PHASE3_WITH_PR_CHECKS=(
  sujho
  admin
)

PHASE3_WORKFLOW_DEST=".github/workflows/ai-review.yml"
PHASE3_SCRIPT_DEST="scripts/ai_review.py"
PHASE3_REVIEW_DEST="REVIEW.md"
PHASE3_BRANCH="chore/phase3-ai-review"
PHASE3_REQUIRED_CHECK="ai-review"
