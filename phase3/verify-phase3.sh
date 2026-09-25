#!/usr/bin/env bash
usage() {
  cat <<'EOF'
  ./verify-phase3.sh           # validate.py only
  ./verify-phase3.sh --remote  # workflows on sujho/main; must not be required checks
EOF
}

PHASE3_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE3_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE3_DIR}/lib.sh"

REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --remote) REMOTE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg (allowed: --remote)" ;;
  esac
done

python3 "${PHASE3_DIR}/validate.py"

if [ "$REMOTE" -eq 0 ]; then
  echo "local invariants ok. --remote after the weekly-job PRs merge to main."
  exit 0
fi

fail=0

echo "--- mutation workflow on sujho ---"
for REPO in "${PHASE3_MUTATION_REPOS[@]}"; do
  wf="$(gh api "repos/${ORG}/${REPO}/contents/${PHASE3_MUTATION_WORKFLOW}?ref=main" --jq .path 2>/dev/null || true)"
  if [ -z "$wf" ]; then
    echo "FAIL ${REPO}: missing ${PHASE3_MUTATION_WORKFLOW} on main"
    fail=1
  else
    echo "ok   ${REPO}"
  fi
done

echo "--- eval on sujho (Eval-Suite) ---"
for REPO in "${PHASE3_EVAL_REPOS[@]}"; do
  wf="$(gh api "repos/${ORG}/${REPO}/contents/${PHASE3_EVAL_WORKFLOW}?ref=main" --jq .path 2>/dev/null || true)"
  script="$(gh api "repos/${ORG}/${REPO}/contents/${PHASE3_EVAL_SCRIPT}?ref=main" --jq .path 2>/dev/null || true)"
  if [ -z "$wf" ] || [ -z "$script" ]; then
    echo "FAIL ${REPO}: missing eval workflow/script on main"
    fail=1
  else
    echo "ok   ${REPO} eval"
  fi
done

echo "--- skip ---"
for REPO in "${PHASE3_SKIP_REPOS[@]}"; do
  wf="$(gh api "repos/${ORG}/${REPO}/contents/${PHASE3_MUTATION_WORKFLOW}?ref=main" --jq .path 2>/dev/null || true)"
  if [ -n "$wf" ]; then
    echo "FAIL ${REPO}: mutation workflow should not be here"
    fail=1
  else
    echo "ok   skip ${REPO}"
  fi
done

echo "--- must not be required on any branch ---"
for REPO in "${PHASE3_MUTATION_REPOS[@]}"; do
  ctx="$(
    gh api "repos/${ORG}/${REPO}/rulesets" --jq \
      '.[].id' 2>/dev/null \
      | while read -r id; do
          [ -n "$id" ] || continue
          gh api "repos/${ORG}/${REPO}/rulesets/${id}" --jq \
            '.rules[]? | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
        done | sort -u | tr '\n' ' '
  )"
  if echo "$ctx" | grep -Eqw 'mutation|eval-replay'; then
    echo "FAIL ${REPO}: Phase 3 jobs are required checks — they must not be"
    fail=1
  else
    echo "ok   ${REPO}: not required"
  fi
done

if [ "$fail" -ne 0 ]; then
  die "remote Phase 3 verification failed"
fi
echo "remote Phase 3 verification passed"
