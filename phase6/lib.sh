# Phase 6 extras. Source after phase1/lib.sh.
#
# Mutation and eval both run from the sujho umbrella: mutmut via
# tests/ci/pipeline.py, eval via Eval-Suite/run.py. Not a merge gate.

PHASE6_MUTATION_REPOS=(sujho)
PHASE6_EVAL_REPOS=(sujho)

PHASE6_SKIP_REPOS=(
  admin
  text-agent
  user-service
  whatsapp-adapter
  document-worker
  redirect-service
  knowledge-store
  sujho-ops-mcp
)

PHASE6_MUTATION_WORKFLOW=".github/workflows/mutation.yml"
PHASE6_EVAL_WORKFLOW=".github/workflows/eval-replay.yml"
PHASE6_MUTATION_SCRIPT="scripts/mutation_report.py"
PHASE6_EVAL_SCRIPT="scripts/eval_replay.py"
PHASE6_BRANCH="chore/phase6-weekly"
