#!/usr/bin/env bash
# Apply Phase 1:
#   CODEOWNERS on main → ruleset on main.
#   Everyone PRs into main. Leads are Code Owners. No GitHub `dev` / `pre-prod`.
#
# Usage: see usage() below — ./apply-phase1.sh [--apply]
# Arguments: --apply — actually mutate GitHub (default: dry-run/plan only).
# Exit codes: 0 dry-run, or apply finished with no waiting/no-admin repos;
#   1 (via die) an unknown argument or a hard failure; 1 (explicit) apply
#   finished with repos still waiting on a CODEOWNERS PR merge or lacking admin.

usage() {
  cat <<'EOF'
  ./apply-phase1.sh          # validate locally, print the plan; no GitHub
  ./apply-phase1.sh --apply  # mutate GitHub (Lead/admin for CODEOWNERS + rulesets)
EOF
}

# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

if ! parse_apply_flag "$@" ; then
  usage
  exit 0
fi

python3 "${PHASE1_DIR}/validate.py" \
  || die "local Phase 1 invariants failed — refusing to continue"

if [ "$APPLY" -eq 0 ]; then
  cat <<EOF
DRY-RUN (pass --apply to mutate GitHub)

Per full-treatment repo, in order, stopping that repo if a step is not ready:
  1. Put ${CODEOWNERS_DEST} on main.
     If the owner-only org ruleset 403s, open ${CODEOWNERS_BRANCH} + PR and STOP.
     Do not install rulesets until a Lead merges that PR.
  2. If this actor is admin on that repo, upsert:
       main.json           Code Owners ON, merge-only, NO bypass actor at all
       branch-naming.json  new branches must be fb-<person>-<work>-<dd-mm-yy>
                           (main, dependabot/**, chore/phase*, prove/phase1-* exempt)
     No GitHub dev or pre-prod ruleset.

Light-touch (${LIGHT_TOUCH_REPOS[*]}): ruleset only, Code Owners off, per-repo admin.

Then: ./verify-phase1.sh --remote
      ./prove-phase1.sh          # dummy PR into main that proves the gate
EOF
  exit 0
fi

login="$(gh api user --jq .login)"
echo "actor=${login}  apply=1"

waiting=0
no_admin=0

apply_full_repo() {
  local repo="$1"
  local rc

  echo "==== ${repo} ===="
  set +e
  sync_codeowners_to_main "$repo"
  rc=$?
  set -e
  if [ "$rc" -eq 3 ]; then
    echo "${repo}: WAITING — merge the CODEOWNERS PR, then re-run. Skipping rulesets."
    waiting=1
    return 0
  fi
  if [ "$rc" -ne 0 ]; then
    die "${repo}: CODEOWNERS sync failed (exit ${rc})"
  fi

  if ! codeowners_ok_on_ref "$repo" main; then
    echo "${repo}: WAITING — ${CODEOWNERS_DEST} not valid on main yet. Not installing rulesets."
    waiting=1
    return 0
  fi

  if [ "$(repo_admin "$repo")" != "true" ]; then
    echo "${repo}: admin=false — skip rulesets (Lead must run this repo)"
    no_admin=1
    return 0
  fi

  upsert_ruleset "$repo" "${PHASE1_DIR}/rulesets/main.json"
  upsert_ruleset "$repo" "${PHASE1_DIR}/rulesets/branch-naming.json"
}

apply_light_touch() {
  local repo="$1"
  echo "==== ${repo} (light-touch) ===="
  if [ "$(repo_admin "$repo")" != "true" ]; then
    echo "${repo}: admin=false — skip ruleset"
    no_admin=1
    return 0
  fi
  upsert_ruleset "$repo" "${PHASE1_DIR}/rulesets/light-touch-main.json"
}

for REPO in "${FULL_TREATMENT_REPOS[@]}"; do
  apply_full_repo "$REPO"
done
for REPO in "${LIGHT_TOUCH_REPOS[@]}"; do
  apply_light_touch "$REPO"
done

if [ "$waiting" -ne 0 ] || [ "$no_admin" -ne 0 ]; then
  echo "Phase 1 apply incomplete:" >&2
  [ "$waiting" -ne 0 ] \
    && echo "  - one or more CODEOWNERS PRs still need a Lead merge; re-run after" >&2
  [ "$no_admin" -ne 0 ] && echo "  - rulesets skipped on repos where ${login} is not admin" >&2
  exit 1
fi

echo "Phase 1 apply finished. Next: ./verify-phase1.sh --remote && ./prove-phase1.sh"
