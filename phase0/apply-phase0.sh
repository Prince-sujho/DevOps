#!/usr/bin/env bash
# Runs the local-only monorepo merge trial: clone the 8 backend repos,
# rewrite each into its own subdirectory, merge into a working copy of
# sujho, drop the 8 gitlinks, collapse every ci/*.yaml's gitSource blocks.
#
# Never touches GitHub or GCP except read-only clones of the 9 repos.
# Nothing is ever pushed — there is no flag that makes this script push.
#
# Usage: see usage() below — ./apply-phase0.sh --output DIR [--apply] [--at-pinned]
# Arguments: --output DIR — where to build the merged tree (required).
#   --apply — actually run the merge (default: print the plan only).
#   --at-pinned — merge each repo at the commit sujho's gitlink pinned,
#     instead of its branch tip (the drift report shows the difference).
# Exit codes: 0 ok/dry-run; 1 (via die) unknown argument, missing --output,
#   or (with --apply) merge_repos.py / collapse_ci_gitsource.py failed.

usage() {
  cat <<'EOF'
  ./apply-phase0.sh --output DIR          # print the plan; nothing written
  ./apply-phase0.sh --output DIR --apply  # clone, rewrite, merge, collapse CI — local only
  ./apply-phase0.sh --output DIR --apply --at-pinned  # merge the pinned commits, not the tips
EOF
}

# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"


# The parts of a cutover no script can do. Printed both in the plan and after
# a real run, because each item is either irreversible or needs a decision.
cutover_checklist() {
  cat <<'EOF'

BEFORE YOU MERGE THIS ANYWHERE
  1. Freeze. No merges to the 8 backend repos until step 6. Close or finish
     open PRs, let running builds finish, and write down each repo's current
     main SHA — that list is your rollback point.
  2. Know what a history rewrite does not carry over. filter-repo moves
     commits, nothing else: open PRs and issues, tags and GitHub Releases,
     rulesets, Actions secrets/variables, Environments, deploy keys,
     webhooks and per-repo scanning settings all stay behind on the old
     repos. Decide per repo: copy, finish first, or accept losing it.
  3. Scan the merged history for secrets before it is pushed anywhere. Eight
     histories become one, and a credential deleted years ago is still in
     it. A hit means rotate that credential — do not push and hope.
  4. Read the drift report below. DRIFT means that repo's tip is ahead of the
     commit sujho pinned, so merging the tip ships commits production never
     ran. Accept that deliberately, or re-run with --at-pinned.
  5. Read the "GitHub ignores these now" warning below. Workflows and
     CODEOWNERS are only read from the repository root, so each merged repo's
     own copies go inert. Move anything they enforced to the root.

AFTER IT IS MERGED
  6. Repoint everything that still points at the old repos: Cloud Build
     triggers, Developer Connect links, submodule references in www /
     design_system / docs, and any script or doc that clones one of the 8 by
     URL. Tell the team to re-clone.
  7. Run ./verify-phase0.sh --output DIR --remote.
  8. Archive the 8 old repos — do not delete them. Archiving is reversible
     and deleting is not; leave them archived for at least a quarter.
  9. Lift the freeze.

Until step 8 the rollback is "close the PR and unfreeze": the old repos were
never modified by anything here.
EOF
}

parse_apply_flag "$@" || { usage; exit 0; }
[ -n "$OUTPUT" ] || { usage; die "--output DIR is required"; }

REPOS_JSON="${PHASE0_DIR}/repos.json"
SCRATCH="${OUTPUT}.scratch"

echo "plan:"
echo "  org:      ${ORG}"
echo "  scratch:  ${SCRATCH}"
echo "  output:   ${OUTPUT}"
python3 - "$REPOS_JSON" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print(f"  super_repo:      {data['super_repo']}")
print(f"  keep_submodules: {', '.join(data['keep_submodules'])}")
for entry in data["merge_repos"]:
    print(f"  merge:           {entry['github']} -> {entry['target']}/")
PY

if [ "$APPLY" -eq 0 ]; then
  echo
  cutover_checklist
  echo
  echo "dry-run only. Re-run with --apply to actually clone/merge locally."
  exit 0
fi

command -v git-filter-repo >/dev/null \
  || die "git-filter-repo not installed (brew install git-filter-repo)"
command -v gh >/dev/null || die "gh CLI not installed"

MERGE_ARGS=(--org "$ORG" --repos-json "$REPOS_JSON" --scratch "$SCRATCH" --output "$OUTPUT")
if [ "$AT_PINNED" -eq 1 ]; then
  MERGE_ARGS+=(--at-pinned)
fi
python3 "${PHASE0_DIR}/merge_repos.py" "${MERGE_ARGS[@]}"

CI_FILES=("${OUTPUT}"/ci/*.yaml)
if [ -e "${CI_FILES[0]}" ]; then
  python3 "${PHASE0_DIR}/collapse_ci_gitsource.py" "${CI_FILES[@]}"
fi

echo
cutover_checklist
echo
echo "drift report: ${SCRATCH}/drift-report.txt — read it before pushing anything"
echo "merged tree ready at ${OUTPUT}. Next: ./verify-phase0.sh --output ${OUTPUT}"
