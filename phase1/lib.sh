# Shared constants + helpers for Phase 1 scripts.
#
# Usage: source, do not execute — `source "$(dirname "$0")/lib.sh"`.
# Arguments: none; scripts that source this call parse_apply_flag "$@" themselves.
# Exit codes: die() prints to stderr and exits 1. ensure_branch_from_main
#   returns 2 for "diverged, left alone" as a normal (non-fatal) signal to
#   the caller. sync_codeowners_to_main returns 3 for "PR opened, waiting
#   on a Lead" as a normal signal, not an error.
#
# Assumes phase0's merge already landed: text-agent, user-service,
# whatsapp-adapter, admin, document-worker, redirect-service,
# knowledge-store, and infra no longer exist as separate repos — they're
# folders inside sujho, already covered by sujho's own CODEOWNERS/ruleset.
# Like phase2, this is a design not yet applied to the real repos.
set -euo pipefail

ORG="Sujho"

LEADS=(arnavtayal abhishektayal2802)
NOT_LEAD="Prince-sujho"

FULL_TREATMENT_REPOS=(
  sujho
  sujho-ops-mcp
)

LIGHT_TOUCH_REPOS=(
  design-system
  docs
  hiring
  www
)

# GitHub: `main` only. Dev / Pre-Prod / Prod are GCP projects, not branches.

CODEOWNERS_DEST=".github/CODEOWNERS"
CODEOWNERS_BRANCH="chore/phase1-codeowners"

PHASE1_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY=0

die() { echo "error: $*" >&2; exit 1; }

parse_apply_flag() {
  APPLY=0
  local arg
  for arg in "$@"; do
    case "$arg" in
      --apply) APPLY=1 ;;
      -h|--help) return 2 ;;
      *) die "unknown argument: $arg (allowed: --apply)" ;;
    esac
  done
}

gh_mutate() {
  if [ "$APPLY" -eq 0 ]; then
    printf 'DRY-RUN' >&2
    printf ' %q' "$@" >&2
    printf '\n' >&2
    return 0
  fi
  "$@"
}

ref_sha() {
  local repo="$1" ref="$2"
  gh api "repos/${ORG}/${repo}/git/refs/heads/${ref}" --jq .object.sha 2>/dev/null || true
}

compare_status() {
  local repo="$1" base="$2" head="$3"
  gh api "repos/${ORG}/${repo}/compare/${base}...${head}" --jq .status
}

# Create branch from main, or fast-forward it to main if it has not diverged.
# Diverged / unique commits: leave it alone and return 2 so the caller can warn.
ensure_branch_from_main() {
  local repo="$1" branch="$2"
  local main_sha branch_sha status
  main_sha="$(ref_sha "$repo" main)"
  [ -n "$main_sha" ] || die "${repo}: no main branch"

  branch_sha="$(ref_sha "$repo" "$branch")"
  if [ -z "$branch_sha" ]; then
    echo "${repo}: create ${branch} at ${main_sha:0:12}"
    gh_mutate gh api "repos/${ORG}/${repo}/git/refs" \
      -f ref="refs/heads/${branch}" -f sha="$main_sha" >/dev/null
    return 0
  fi

  if [ "$branch_sha" = "$main_sha" ]; then
    echo "${repo}: ${branch} already at main ${main_sha:0:12}"
    return 0
  fi

  status="$(compare_status "$repo" "$branch" main)"
  case "$status" in
    ahead|identical)
      echo "${repo}: fast-forward ${branch} -> main ${main_sha:0:12} (was ${branch_sha:0:12})"
      gh_mutate gh api -X PATCH "repos/${ORG}/${repo}/git/refs/heads/${branch}" \
        -f sha="$main_sha" -F force=false >/dev/null
      ;;
    behind|diverged)
      echo "${repo}: SKIP ${branch} — ${status} from main" \
        "(${branch_sha:0:12}); will not force-update" >&2
      return 2
      ;;
    *)
      die "${repo}: unexpected compare status '${status}' for ${branch}...main"
      ;;
  esac
}

repo_admin() {
  local repo="$1"
  gh api "repos/${ORG}/${repo}" --jq '.permissions.admin'
}

codeowners_b64() {
  python3 -c '
import base64, pathlib, sys
p = pathlib.Path(sys.argv[1])
print(base64.b64encode(p.read_bytes()).decode())
' "${PHASE1_DIR}/CODEOWNERS"
}

codeowners_body_on_ref() {
  local repo="$1" ref="$2"
  gh api "repos/${ORG}/${repo}/contents/${CODEOWNERS_DEST}?ref=${ref}" \
    --jq .content 2>/dev/null \
    | python3 -c '
import sys, base64
data = sys.stdin.read().replace("\n", "")
print(base64.b64decode(data).decode() if data else "")
' \
    || true
}

codeowners_ok_on_ref() {
  local repo="$1" ref="$2"
  local body
  body="$(codeowners_body_on_ref "$repo" "$ref")"
  [ -n "$body" ] || return 1
  printf '%s' "$body" | python3 "${PHASE1_DIR}/validate.py" --check-stdin
}

codeowners_on_ref() {
  local repo="$1" ref="$2"
  gh api "repos/${ORG}/${repo}/contents/${CODEOWNERS_DEST}?ref=${ref}" --jq .sha 2>/dev/null || true
}

ensure_codeowners_pr() {
  local repo="$1"
  local existing
  existing="$(
    gh pr list --repo "${ORG}/${repo}" --base main --head "$CODEOWNERS_BRANCH" \
      --json number --jq '.[0].number' 2>/dev/null || true
  )"
  if [ -n "$existing" ]; then
    echo "${repo}: CODEOWNERS PR already open (#${existing}) — a Lead must merge it"
    return 0
  fi
  gh pr create --repo "${ORG}/${repo}" \
    --base main --head "$CODEOWNERS_BRANCH" \
    --title "Phase 1: add CODEOWNERS (Lead gate)" \
    --body "A Lead must merge this onto main. After merge, re-run apply-phase1.sh --apply \
to install the main ruleset. Rulesets are not installed until CODEOWNERS is on main."
}

# Try a direct commit of CODEOWNERS to main.
# Args: repo, b64 (file content), existing (current file sha on main, or "").
# Returns: 0 committed; 1 the commit was blocked (stderr left for the caller
# to show, since a ruleset-blocked push is expected, not a real error).
_try_commit_codeowners_to_main() {
  local repo="$1" b64="$2" existing="$3"
  local err args
  err="$(mktemp "${TMPDIR:-/tmp}/phase1-codeowners.XXXXXX")"
  args=(gh api -X PUT "repos/${ORG}/${repo}/contents/${CODEOWNERS_DEST}"
    -f message="Add CODEOWNERS so production merges require a Lead."
    -f content="$b64"
    -f branch=main)
  if [ -n "$existing" ]; then
    args+=(-f sha="$existing")
  fi
  if "${args[@]}" >/dev/null 2>"$err"; then
    rm -f "$err"
    return 0
  fi
  cat "$err" >&2 || true
  rm -f "$err"
  return 1
}

# Put CODEOWNERS on the CODEOWNERS_BRANCH and open the Lead-merge PR for it.
# Args: repo, b64 (file content).
_open_codeowners_branch_pr() {
  local repo="$1" b64="$2"
  local main_sha existing args
  main_sha="$(ref_sha "$repo" main)"
  if [ -z "$(ref_sha "$repo" "$CODEOWNERS_BRANCH")" ]; then
    gh api "repos/${ORG}/${repo}/git/refs" \
      -f ref="refs/heads/${CODEOWNERS_BRANCH}" -f sha="$main_sha" >/dev/null
  fi
  existing="$(codeowners_on_ref "$repo" "$CODEOWNERS_BRANCH")"
  args=(gh api -X PUT "repos/${ORG}/${repo}/contents/${CODEOWNERS_DEST}"
    -f message="Add CODEOWNERS so production merges require a Lead."
    -f content="$b64"
    -f branch="$CODEOWNERS_BRANCH")
  if [ -n "$existing" ]; then
    args+=(-f sha="$existing")
  fi
  "${args[@]}" >/dev/null
  ensure_codeowners_pr "$repo"
}

# Land CODEOWNERS on main. Returns:
#   0  file on main and valid
#   3  waiting on a PR (do not FF branches or install rulesets yet)
sync_codeowners_to_main() {
  local repo="$1"
  local b64 existing

  if codeowners_ok_on_ref "$repo" main; then
    echo "${repo}: CODEOWNERS already valid on main"
    return 0
  fi

  b64="$(codeowners_b64)"
  existing="$(codeowners_on_ref "$repo" main)"
  echo "${repo}: put ${CODEOWNERS_DEST} on main"

  if _try_commit_codeowners_to_main "$repo" "$b64" "$existing"; then
    echo "${repo}: CODEOWNERS committed on main"
    return 0
  fi

  echo "${repo}: direct commit to main blocked" \
    "(expected under owner-only org ruleset); using ${CODEOWNERS_BRANCH}"
  _open_codeowners_branch_pr "$repo" "$b64"
  return 3
}

upsert_ruleset() {
  local repo="$1" json_file="$2"
  local name id
  name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$json_file")"
  id="$(
    gh api "repos/${ORG}/${repo}/rulesets" --jq ".[] | select(.name==\"${name}\") | .id" \
      | head -n1 || true
  )"
  if [ -n "$id" ]; then
    echo "${repo}: update ruleset ${name} (#${id})"
    gh_mutate gh api -X PUT "repos/${ORG}/${repo}/rulesets/${id}" --input "$json_file" >/dev/null
  else
    echo "${repo}: create ruleset ${name}"
    gh_mutate gh api -X POST "repos/${ORG}/${repo}/rulesets" --input "$json_file" >/dev/null
  fi
}
