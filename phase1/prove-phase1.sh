#!/usr/bin/env bash
# Config checks (verify --remote) cannot prove the gate. This is the human
# proof: a dummy PR into main after apply has finished.
#
# Pilot is sujho itself, not a service repo — post-phase0 that's the only
# repo anyone actually merges into.
#
# Usage: see usage() below — ./prove-phase1.sh [--apply]
# Arguments: --apply — actually open the PR on GitHub (default: print the plan only).
# Exit codes: 0 ok/dry-run; 1 (via die) --help/unknown argument, or (with
#   --apply) the pilot repo has no main branch to open the PR from.

usage() {
  cat <<'EOF'
  ./prove-phase1.sh          # print the dummy-PR recipe; no GitHub
  ./prove-phase1.sh --apply  # open one PR on sujho into main

PR into `main` as Prince
   Lead Code-Owner review is required. Prince approving himself is not enough.
   Squash must not be offered.

If it merges on Prince's approval, the Lead gate is fake.
EOF
}

# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

if ! parse_apply_flag "$@" ; then
  usage
  exit 0
fi

PILOT="sujho"
STAMP="$(date +%Y%m%d%H%M%S)"
MAIN_BRANCH="prove/phase1-main-${STAMP}"

create_dummy_pr() {
  local repo="$1" branch="$2" base="$3" title="$4" body="$5"
  local sha blob base_tree tree commit
  sha="$(ref_sha "$repo" "$base")"
  [ -n "$sha" ] || die "${repo}: no ${base} to branch from"
  gh api "repos/${ORG}/${repo}/git/refs" -f ref="refs/heads/${branch}" -f sha="$sha" >/dev/null
  blob="$(
    gh api "repos/${ORG}/${repo}/git/blobs" \
      -f content="phase1 prove ${base} ${STAMP}" -f encoding=utf-8 --jq .sha
  )"
  base_tree="$(gh api "repos/${ORG}/${repo}/git/commits/${sha}" --jq .tree.sha)"
  tree="$(jq -n --arg base "$base_tree" --arg blob "$blob" \
    '{base_tree:$base, tree:[{path:".phase1-prove", mode:"100644", type:"blob", sha:$blob}]}' \
    | gh api "repos/${ORG}/${repo}/git/trees" --input - --jq .sha)"
  commit="$(jq -n --arg msg "chore: Phase 1 prove PR against ${base}" \
    --arg tree "$tree" --arg parent "$sha" \
    '{message:$msg, tree:$tree, parents:[$parent]}' \
    | gh api "repos/${ORG}/${repo}/git/commits" --input - --jq .sha)"
  gh api -X PATCH "repos/${ORG}/${repo}/git/refs/heads/${branch}" -f sha="$commit" >/dev/null
  gh pr create --repo "${ORG}/${repo}" --base "$base" --head "$branch" \
    --title "$title" --body "$body"
}

if [ "$APPLY" -eq 0 ]; then
  cat <<EOF
DRY-RUN (pass --apply to open a PR on ${PILOT})

Pilot repo: ${ORG}/${PILOT}
Do this only after verify-phase1.sh --remote passes.

    open PR base=main  head=${MAIN_BRANCH}
    Expect: Prince cannot merge. A Lead Code-Owner review is required.
    Expect: only "Create a merge commit" is offered, not squash.

Close the PR unmerged when done, and delete the prove/* branch.
EOF
  exit 0
fi

echo "Opening prove PR on ${ORG}/${PILOT}"
PROVE_BODY="Prince approval must NOT be enough. A Lead must approve."
PROVE_BODY+=" Squash must not be offered. Close unmerged after the check."
create_dummy_pr "$PILOT" "$MAIN_BRANCH" "main" \
  "Phase 1 prove: Lead gate into main" "$PROVE_BODY"
echo "Opened. Close when done."
