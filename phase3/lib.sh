# Phase 3 extras. Source after phase1/lib.sh.
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
