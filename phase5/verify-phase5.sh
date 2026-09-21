#!/usr/bin/env bash
usage() {
  cat <<'EOF'
  ./verify-phase5.sh           # validate.py only
  ./verify-phase5.sh --remote  # fail if the cut checker is still on sujho/main
EOF
}

PHASE5_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE5_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE5_DIR}/lib.sh"

REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --remote) REMOTE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg (allowed: --remote)" ;;
  esac
done

python3 "${PHASE5_DIR}/validate.py"

if [ "$REMOTE" -eq 0 ]; then
  echo "local invariants ok. Phase 5 has no files to land."
  exit 0
fi

fail=0

echo "--- cut checker must not be on main ---"
wf="$(gh api "repos/${ORG}/${PHASE5_REPO}/contents/.github/workflows/promotion-tag-check.yml?ref=main" --jq .path 2>/dev/null || true)"
if [ -n "$wf" ]; then
  echo "FAIL ${PHASE5_REPO}: promotion-tag-check.yml is still on main — it was cut"
  fail=1
else
  echo "ok   no promotion-tag-check.yml on main"
fi

echo "--- skip service repos ---"
for REPO in "${PHASE5_SKIP_REPOS[@]}"; do
  wf="$(gh api "repos/${ORG}/${REPO}/contents/.github/workflows/promotion-tag-check.yml?ref=main" --jq .path 2>/dev/null || true)"
  if [ -n "$wf" ]; then
    echo "FAIL ${REPO}: promotion-tag-check should not live here"
    fail=1
  else
    echo "ok   skip ${REPO}"
  fi
done

if [ "$fail" -ne 0 ]; then
  die "remote Phase 5 verification failed"
fi
echo "remote Phase 5 verification passed"
