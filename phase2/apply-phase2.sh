#!/usr/bin/env bash
# Put Phase 2 workflow files on `main` via a PR. Does not turn on required
# checks — GitHub cannot require a check that has never run.
# Dry-run unless you pass --apply.

usage() {
  cat <<'EOF'
  ./apply-phase2.sh                 # validate + plan; no GitHub
  ./apply-phase2.sh --apply         # open PRs into `main`
  ./apply-phase2.sh --require-checks
      # AFTER pr-checks has run once on a repo, upsert the main ruleset
      # that requires the `pr-checks` job. Refuses if the check name has
      # never appeared. Separate on purpose.

Umbrella (sujho): tests/ci/pipeline.py — the 836-test suite.
admin: Node workflow.
Service repos are skipped — they do not hold this suite.
EOF
}

PHASE2_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE2_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE2_DIR}/lib.sh"

REQUIRE_CHECKS=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --require-checks) REQUIRE_CHECKS=1 ;;
    --apply|-h|--help) ARGS+=("$arg") ;;
    *) die "unknown argument: $arg" ;;
  esac
done
if ! parse_apply_flag "${ARGS[@]+"${ARGS[@]}"}" ; then
  usage
  exit 0
fi

python3 "${PHASE2_DIR}/validate.py" || die "Phase 2 local invariants failed"

if [ "$APPLY" -eq 0 ] && [ "$REQUIRE_CHECKS" -eq 0 ]; then
  cat <<EOF
DRY-RUN (pass --apply to mutate GitHub)

PRs into \`main\` (workflow must live on the PR base):
  ${PHASE2_UMBRELLA_REPO}: ${PHASE2_WORKFLOW_DEST}
    (python tests/ci/pipeline.py — unit/api/gates/coverage; integration/e2e best-effort)
  admin: workflows/pr-checks-admin.yml → ${PHASE2_WORKFLOW_DEST}
  skip: ${PHASE2_SKIP_REPOS[*]}
    (suite is the umbrella tree, not per-service tests/)

Do not pass --require-checks until \`pr-checks\` has shown up on a PR.
Then: ./apply-phase2.sh --require-checks --apply
EOF
  exit 0
fi

put_file() {
  local repo="$1" dest="$2" src="$3" branch="$4" message="$5"
  local b64 existing
  b64="$(python3 -c 'import base64, pathlib, sys; print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())' "$src")"
  existing="$(gh api "repos/${ORG}/${repo}/contents/${dest}?ref=${branch}" --jq .sha 2>/dev/null || true)"
  local args=(gh api -X PUT "repos/${ORG}/${repo}/contents/${dest}"
    -f message="$message" -f content="$b64" -f branch="$branch")
  if [ -n "$existing" ]; then
    args+=(-f sha="$existing")
  fi
  "${args[@]}" >/dev/null
}

ensure_branch_from() {
  local repo="$1" branch="$2" from="$3"
  local sha
  sha="$(ref_sha "$repo" "$from")"
  [ -n "$sha" ] || die "${repo}: no ${from} (Phase 1 branches first)"
  if [ -z "$(ref_sha "$repo" "$branch")" ]; then
    gh api "repos/${ORG}/${repo}/git/refs" -f ref="refs/heads/${branch}" -f sha="$sha" >/dev/null
  fi
}

open_dev_pr() {
  local repo="$1" title="$2" body="$3"
  local n
  n="$(gh pr list --repo "${ORG}/${repo}" --base main --head "$PHASE2_BRANCH" --json number --jq '.[0].number' || true)"
  if [ -n "$n" ]; then
    echo "${repo}: Phase 2 PR already open (#${n})"
    return 0
  fi
  gh pr create --repo "${ORG}/${repo}" --base main --head "$PHASE2_BRANCH" \
    --title "$title" --body "$body"
}

check_has_run() {
  local repo="$1"
  gh api "repos/${ORG}/${repo}/commits/main/status" --jq '.statuses[].context' 2>/dev/null \
    | grep -qx "$PHASE2_REQUIRED_CHECK" && return 0
  gh api "repos/${ORG}/${repo}/commits/main/check-runs" --jq '.check_runs[].name' 2>/dev/null \
    | grep -qx "$PHASE2_REQUIRED_CHECK"
}

if [ "$REQUIRE_CHECKS" -eq 1 ]; then
  if [ "$APPLY" -eq 0 ]; then
    echo "DRY-RUN --require-checks: would upsert phase2/rulesets/main-required-checks.json on ${PHASE2_CHECK_REPOS[*]}, only if ${PHASE2_REQUIRED_CHECK} has already run."
    exit 0
  fi
  refused=0
  for REPO in "${PHASE2_CHECK_REPOS[@]}"; do
    if ! check_has_run "$REPO"; then
      echo "${REPO}: REFUSING required checks — '${PHASE2_REQUIRED_CHECK}' has never run on main"
      refused=1
      continue
    fi
    if [ "$(repo_admin "$REPO")" != "true" ]; then
      echo "${REPO}: admin=false — skip ruleset"
      continue
    fi
    upsert_ruleset "$REPO" "${PHASE2_DIR}/rulesets/main-required-checks.json"
  done
  [ "$refused" -eq 0 ] || die "one or more repos are not ready for required checks"
  exit 0
fi

login="$(gh api user --jq .login)"
echo "actor=${login} apply=1 (workflow PRs into main)"

echo "==== ${PHASE2_UMBRELLA_REPO} (umbrella suite) ===="
[ -n "$(ref_sha "$PHASE2_UMBRELLA_REPO" main)" ] || die "${PHASE2_UMBRELLA_REPO}: no main branch"
ensure_branch_from "$PHASE2_UMBRELLA_REPO" "$PHASE2_BRANCH" main
put_file "$PHASE2_UMBRELLA_REPO" "$PHASE2_WORKFLOW_DEST" "${PHASE2_DIR}/workflows/pr-checks.yml" \
  "$PHASE2_BRANCH" "Add Phase 2 PR checks workflow (umbrella pipeline.py)."
open_dev_pr "$PHASE2_UMBRELLA_REPO" \
  "Phase 2: PR checks via tests/ci/pipeline.py" \
  "Adds the \`pr-checks\` gate on PRs into \`main\`. Runs the umbrella suite (\`python tests/ci/pipeline.py\`), not a per-service tests folder. Merge does not deploy. Do not require this check until it has run once. After merge, run a dummy PR, then \`apply-phase2.sh --require-checks --apply\`."

for REPO in "${ADMIN_REPOS[@]}"; do
  echo "==== ${REPO} (node) ===="
  [ -n "$(ref_sha "$REPO" main)" ] || die "${REPO}: no main branch"
  ensure_branch_from "$REPO" "$PHASE2_BRANCH" main
  put_file "$REPO" "$PHASE2_WORKFLOW_DEST" "${PHASE2_DIR}/workflows/pr-checks-admin.yml" \
    "$PHASE2_BRANCH" "Add Phase 2 PR checks workflow (Node)."
  open_dev_pr "$REPO" \
    "Phase 2: PR lint + unit tests" \
    "Adds the \`pr-checks\` gate on PRs into \`main\`. Merge does not deploy. Do not require this check until it has run once. After merge, run a dummy PR, then \`apply-phase2.sh --require-checks --apply\`."
done

echo "skip: ${PHASE2_SKIP_REPOS[*]} (suite lives in ${PHASE2_UMBRELLA_REPO}/tests)"
echo "Next: merge those PRs, run a dummy PR so pr-checks appears, then --require-checks"
