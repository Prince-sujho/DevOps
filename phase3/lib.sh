# Phase 3 extras.
#
# Usage: source after phase1/lib.sh — `source "$(dirname "$0")/lib.sh"`.
# Arguments: none; this file only declares constants.
# Exit codes: none of its own — die() and its error conventions come from
#   phase1/lib.sh, which must already be sourced.
#
# Mutation and eval both run from the sujho umbrella: mutmut via
# tests/ci/pipeline.py, eval via Eval-Suite/run.py. Not a merge gate.

PHASE3_MUTATION_REPOS=(sujho)
PHASE3_EVAL_REPOS=(sujho)

PHASE3_SKIP_REPOS=(
  admin
  text-agent
  user-service
  whatsapp-adapter
  document-worker
  redirect-service
  knowledge-store
  sujho-ops-mcp
)

PHASE3_MUTATION_WORKFLOW=".github/workflows/mutation.yml"
PHASE3_EVAL_WORKFLOW=".github/workflows/eval-replay.yml"
PHASE3_MUTATION_SCRIPT="scripts/mutation_report.py"
PHASE3_EVAL_SCRIPT="scripts/eval_replay.py"
PHASE3_BRANCH="chore/phase3-weekly"
