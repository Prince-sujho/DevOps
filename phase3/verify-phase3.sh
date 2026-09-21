#!/usr/bin/env bash
usage() {
  cat <<'EOF'
  ./verify-phase3.sh           # validate.py only
  ./verify-phase3.sh --remote  # workflow on `main` + required-check safety
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
  echo "local invariants ok. --remote after the workflow PRs merge to main."
  exit 0
fi

fail=0

echo "--- workflow + rubric on main ---"
for REPO in "${PHASE3_REPOS[@]}"; do
  wf="$(gh api "repos/${ORG}/${REPO}/contents/${PHASE3_WORKFLOW_DEST}?ref=main" --jq .path 2>/dev/null || true)"
  script="$(gh api "repos/${ORG}/${REPO}/contents/${PHASE3_SCRIPT_DEST}?ref=main" --jq .path 2>/dev/null || true)"
  rubric="$(gh api "repos/${ORG}/${REPO}/contents/${PHASE3_REVIEW_DEST}?ref=main" --jq .path 2>/dev/null || true)"
  if [ -z "$wf" ] || [ -z "$script" ] || [ -z "$rubric" ]; then
    echo "FAIL ${REPO}: missing on main wf=${wf:-no} script=${script:-no} REVIEW.md=${rubric:-no}"
    fail=1
  else
    echo "ok   ${REPO}"
  fi
done

echo "--- required checks must not require review without the gate job ---"
for REPO in "${PHASE3_REPOS[@]}"; do
  ctx="$(
    gh api "repos/${ORG}/${REPO}/rulesets" --jq \
      '.[] | select(.conditions.ref_name.include[]? == "refs/heads/main") | .id' \
      | while read -r id; do
          [ -n "$id" ] || continue
          gh api "repos/${ORG}/${REPO}/rulesets/${id}" --jq \
            '.rules[]? | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
        done | sort -u | tr '\n' ' '
  )"
  if echo "$ctx" | grep -qw review && ! echo "$ctx" | grep -qw "$PHASE3_REQUIRED_CHECK"; then
    echo "FAIL ${REPO}: required 'review' would hang/skip-fail — require \`${PHASE3_REQUIRED_CHECK}\` only"
    fail=1
    continue
  fi
  if echo "$ctx" | grep -qw "$PHASE3_REQUIRED_CHECK"; then
    echo "ok   ${REPO}: required ${PHASE3_REQUIRED_CHECK}"
  else
    echo "note ${REPO}: ${PHASE3_REQUIRED_CHECK} not required yet"
  fi
done

if [ "$fail" -ne 0 ]; then
  die "remote Phase 3 verification failed"
fi
echo "remote Phase 3 verification passed"
