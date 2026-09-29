#!/usr/bin/env bash
# Put Phase 3 weekly jobs on sujho `main` via a PR. Not a merge gate — there
# is no --require-checks. Dry-run unless you pass --apply.
#
# Mutation: umbrella tests/ci/pipeline.py mutation, self-hosted runner.
# Eval: Eval-Suite/run.py on sujho. Cases stay in Eval-Suite; no transcripts.
#
# Usage: ./apply-phase3.sh [--apply]
# Arguments: --apply — open the PR on GitHub (default: validate + print plan).
# Exit codes: 0 ok/dry-run; 1 (via die) --require-checks passed, an unknown
#   argument, or a local invariants (validate.py) failure.

usage() {
  cat <<'EOF'
  ./apply-phase3.sh                  # validate + plan; no GitHub
  ./apply-phase3.sh --apply          # open a PR into sujho `main`

There is no --require-checks. These jobs post to a tracking issue.
EOF
}

PHASE3_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE3_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE3_DIR}/lib.sh"

ARGS=()
for arg in "$@"; do
  case "$arg" in
    --require-checks) die "Phase 3 is not a merge gate — no --require-checks" ;;
    --apply|-h|--help) ARGS+=("$arg") ;;
    *) die "unknown argument: $arg" ;;
  esac
done
if ! parse_apply_flag "${ARGS[@]+"${ARGS[@]}"}" ; then
  usage
  exit 0
fi

python3 "${PHASE3_DIR}/validate.py" || die "Phase 3 local invariants failed"

if [ "$APPLY" -eq 0 ]; then
  cat <<EOF
DRY-RUN (pass --apply to mutate GitHub)

Mutation + eval PR into \`main\` (${PHASE3_MUTATION_REPOS[*]}):
  ${PHASE3_MUTATION_WORKFLOW}
    python tests/ci/pipeline.py mutation  (self-hosted runner labeled mutation)
  ${PHASE3_MUTATION_SCRIPT}
  ${PHASE3_EVAL_WORKFLOW}
    python Eval-Suite/run.py  (live models, fake eval users; spend limits set at the provider)
  ${PHASE3_EVAL_SCRIPT}
  needs MUTATION_TRACKING_ISSUE, EVAL_TRACKING_ISSUE, GCP_WIF_SERVICE_ACCOUNT_EVAL, eval-* secrets
  This job reports only. It does not stamp preprod-approved.
  A Lead stamps one image via approve-preprod after testing on Pre-Prod.

skip: ${PHASE3_SKIP_REPOS[*]}
  (mutation/eval need the umbrella tree, not a service checkout)
EOF
  exit 0
fi

put_file() {
  local repo="$1" dest="$2" src="$3" branch="$4" message="$5"
  local b64 existing
  b64="$(python3 -c '
import base64, pathlib, sys
print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())
' "$src")"
  existing="$(
    gh api "repos/${ORG}/${repo}/contents/${dest}?ref=${branch}" --jq .sha 2>/dev/null || true
  )"
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
  [ -n "$sha" ] || die "${repo}: no ${from}"
  if [ -z "$(ref_sha "$repo" "$branch")" ]; then
    gh api "repos/${ORG}/${repo}/git/refs" -f ref="refs/heads/${branch}" -f sha="$sha" >/dev/null
  fi
}

open_dev_pr() {
  local repo="$1" title="$2" body="$3"
  local n
  n="$(
    gh pr list --repo "${ORG}/${repo}" --base main --head "$PHASE3_BRANCH" \
      --json number --jq '.[0].number' || true
  )"
  if [ -n "$n" ]; then
    echo "${repo}: Phase 3 PR already open (#${n})"
    return 0
  fi
  gh pr create --repo "${ORG}/${repo}" --base main --head "$PHASE3_BRANCH" \
    --title "$title" --body "$body"
}

login="$(gh api user --jq .login)"
echo "actor=${login} apply=1 (Phase 3 weekly jobs into sujho/main)"

REPO="${PHASE3_MUTATION_REPOS[0]}"
echo "==== ${REPO} mutation + eval ===="
ensure_branch_from "$REPO" "$PHASE3_BRANCH" main
put_file "$REPO" "$PHASE3_MUTATION_WORKFLOW" "${PHASE3_DIR}/workflows/mutation.yml" \
  "$PHASE3_BRANCH" "Phase 3: weekly mutation job (not a merge gate)."
put_file "$REPO" "$PHASE3_MUTATION_SCRIPT" "${PHASE3_DIR}/scripts/mutation_report.py" \
  "$PHASE3_BRANCH" "Phase 3: mutation reporter — drops flag an issue, never fail CI."
put_file "$REPO" "$PHASE3_EVAL_WORKFLOW" "${PHASE3_DIR}/workflows/eval-replay.yml" \
  "$PHASE3_BRANCH" "Phase 3: weekly Eval-Suite replay (not a merge gate)."
put_file "$REPO" "$PHASE3_EVAL_SCRIPT" "${PHASE3_DIR}/scripts/eval_replay.py" \
  "$PHASE3_BRANCH" "Phase 3: eval replay wrapper around Eval-Suite/run.py."
PR_BODY="Mutation via \`tests/ci/pipeline.py mutation\` (self-hosted)."
PR_BODY+=" Eval via \`Eval-Suite/run.py\` (fake eval users, live models; spend limits live at the provider)."
PR_BODY+=" Reports only — never gates a deploy. Not a required check."
PR_BODY+=" Do not check in transcripts."
open_dev_pr "$REPO" "Phase 3: weekly mutation + Eval-Suite" "$PR_BODY"

echo "skip: ${PHASE3_SKIP_REPOS[*]}"
