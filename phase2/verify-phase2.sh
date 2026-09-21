#!/usr/bin/env bash
# Local by default. --remote reads GitHub (no writes).

usage() {
  cat <<'EOF'
  ./verify-phase2.sh           # validate.py only
  ./verify-phase2.sh --remote  # workflow on `main` + required-check safety
EOF
}

PHASE2_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE2_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE2_DIR}/lib.sh"

REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --remote) REMOTE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg (allowed: --remote)" ;;
  esac
done

python3 "${PHASE2_DIR}/validate.py"

if [ "$REMOTE" -eq 0 ]; then
  echo "local invariants ok. --remote after the workflow PRs merge to main."
  exit 0
fi

fail=0

workflow_on_dev() {
  local repo="$1"
  gh api "repos/${ORG}/${repo}/contents/${PHASE2_WORKFLOW_DEST}?ref=main" --jq .path 2>/dev/null || true
}

required_contexts() {
  local repo="$1"
  gh api "repos/${ORG}/${repo}/rulesets" --jq \
    '.[] | select(.conditions.ref_name.include[]? == "refs/heads/main") | .id' \
    | while read -r id; do
        [ -n "$id" ] || continue
        gh api "repos/${ORG}/${repo}/rulesets/${id}" --jq \
          '.rules[]? | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
      done
}

echo "--- workflow lives on main (PR base) ---"
for REPO in "${PHASE2_CHECK_REPOS[@]}"; do
  if [ -z "$(workflow_on_dev "$REPO")" ]; then
    echo "FAIL ${REPO}: ${PHASE2_WORKFLOW_DEST} not on main"
    fail=1
  else
    echo "ok   ${REPO}: workflow on main"
  fi
done

echo "--- skip list must not get the umbrella Python suite ---"
for REPO in "${PHASE2_SKIP_REPOS[@]}"; do
  echo "skip ${REPO} (intentional — suite is ${PHASE2_UMBRELLA_REPO}/tests)"
done

echo "--- required checks: only pr-checks, and only if it has run ---"
for REPO in "${PHASE2_CHECK_REPOS[@]}"; do
  ctx="$(required_contexts "$REPO" | sort -u | tr '\n' ' ')"
  if echo "$ctx" | grep -qw lint || echo "$ctx" | grep -qw unit-tests; then
    echo "FAIL ${REPO}: required lint/unit-tests will hang on docs-only PRs — require \`pr-checks\` only"
    fail=1
    continue
  fi
  if echo "$ctx" | grep -qw "$PHASE2_REQUIRED_CHECK"; then
    echo "ok   ${REPO}: required ${PHASE2_REQUIRED_CHECK}"
  else
    echo "note ${REPO}: ${PHASE2_REQUIRED_CHECK} not required yet (expected until --require-checks)"
  fi
done

if [ "$fail" -ne 0 ]; then
  die "remote Phase 2 verification failed"
fi
echo "remote Phase 2 verification passed"
