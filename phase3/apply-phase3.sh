#!/usr/bin/env bash
# Put Phase 3 files on `main` via a PR. Does not require the check until
# `ai-review` has run once. Dry-run unless you pass --apply.

usage() {
  cat <<'EOF'
  ./apply-phase3.sh                  # validate + plan; no GitHub
  ./apply-phase3.sh --apply          # open PRs into `main`
  ./apply-phase3.sh --require-checks
      # AFTER ai-review has run once, upsert the main ruleset that requires
      # both pr-checks and ai-review. Refuses if ai-review has never appeared.
EOF
}

PHASE3_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE3_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE3_DIR}/lib.sh"

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

python3 "${PHASE3_DIR}/validate.py" || die "Phase 3 local invariants failed"

if [ "$APPLY" -eq 0 ] && [ "$REQUIRE_CHECKS" -eq 0 ]; then
  cat <<EOF
DRY-RUN (pass --apply to mutate GitHub)

PRs into \`main\` (AI comment on the same PR the Lead Approves):
  ${PHASE3_REPOS[*]}
    ${PHASE3_WORKFLOW_DEST}
    ${PHASE3_SCRIPT_DEST}
    ${PHASE3_REVIEW_DEST}

Needs repo vars GCP_WIF_PROVIDER and GCP_WIF_SERVICE_ACCOUNT_AI_REVIEW, and GCP secret
ai-review-anthropic-key. Missing auth fails open — it must not block merge.
The collect job never receives WIF or the API key. Lead Approve is still required.

Do not pass --require-checks until \`ai-review\` has shown up on a PR.
Then: ./apply-phase3.sh --require-checks --apply
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
  local repo="$1"
  local n
  n="$(gh pr list --repo "${ORG}/${repo}" --base main --head "$PHASE3_BRANCH" --json number --jq '.[0].number' || true)"
  if [ -n "$n" ]; then
    echo "${repo}: Phase 3 PR already open (#${n})"
    return 0
  fi
  gh pr create --repo "${ORG}/${repo}" --base main --head "$PHASE3_BRANCH" \
    --title "Phase 3: AI review gate" \
    --body "Two-pass review on PRs into \`main\`. Fail-open on billing/auth. Merge does not deploy. Do not require \`ai-review\` until it has run once. Secrets stay in GCP (WIF + Secret Manager), never GitHub Secrets."
}

check_has_run() {
  local repo="$1" name="$2"
  gh api "repos/${ORG}/${repo}/commits/main/check-runs" --jq '.check_runs[].name' 2>/dev/null \
    | grep -qx "$name"
}

if [ "$REQUIRE_CHECKS" -eq 1 ]; then
  if [ "$APPLY" -eq 0 ]; then
    echo "DRY-RUN --require-checks: sujho/admin get pr-checks+ai-review; other repos get ai-review only. Refuses if ${PHASE3_REQUIRED_CHECK} has never run."
    exit 0
  fi
  refused=0
  with_pr_checks=" ${PHASE3_WITH_PR_CHECKS[*]} "
  for REPO in "${PHASE3_REPOS[@]}"; do
    if ! check_has_run "$REPO" "$PHASE3_REQUIRED_CHECK"; then
      echo "${REPO}: REFUSING — '${PHASE3_REQUIRED_CHECK}' has never run on main"
      refused=1
      continue
    fi
    if [ "$(repo_admin "$REPO")" != "true" ]; then
      echo "${REPO}: admin=false — skip ruleset"
      continue
    fi
    if echo "$with_pr_checks" | grep -q " ${REPO} "; then
      upsert_ruleset "$REPO" "${PHASE3_DIR}/rulesets/main-required-checks.json"
    else
      upsert_ruleset "$REPO" "${PHASE3_DIR}/rulesets/main-required-ai-only.json"
    fi
  done
  [ "$refused" -eq 0 ] || die "one or more repos are not ready for required checks"
  exit 0
fi

login="$(gh api user --jq .login)"
echo "actor=${login} apply=1 (AI review PRs into main)"

for REPO in "${PHASE3_REPOS[@]}"; do
  echo "==== ${REPO} ===="
  [ -n "$(ref_sha "$REPO" main)" ] || die "${REPO}: no main branch"
  ensure_branch_from "$REPO" "$PHASE3_BRANCH" main
  put_file "$REPO" "$PHASE3_WORKFLOW_DEST" "${PHASE3_DIR}/workflows/ai-review.yml" \
    "$PHASE3_BRANCH" "Add Phase 3 AI review workflow."
  put_file "$REPO" "$PHASE3_SCRIPT_DEST" "${PHASE3_DIR}/scripts/ai_review.py" \
    "$PHASE3_BRANCH" "Add Phase 3 two-pass review script."
  put_file "$REPO" "$PHASE3_REVIEW_DEST" "${PHASE3_DIR}/REVIEW.md" \
    "$PHASE3_BRANCH" "Add Phase 3 review rubric."
  open_dev_pr "$REPO"
done

echo "Next: merge PRs, run a non-trivial PR so ai-review appears, then --require-checks"
