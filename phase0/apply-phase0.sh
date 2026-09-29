#!/usr/bin/env bash
# Runs the local-only monorepo merge trial: clone the 8 backend repos,
# rewrite each into its own subdirectory, merge into a working copy of
# sujho, drop the 8 gitlinks, collapse every ci/*.yaml's gitSource blocks.
#
# Never touches GitHub or GCP except read-only clones of the 9 repos.
# Nothing is ever pushed — there is no flag that makes this script push.
#
# Usage: see usage() below — ./apply-phase0.sh --output DIR [--apply]
# Arguments: --output DIR — where to build the merged tree (required).
#   --apply — actually run the merge (default: print the plan only).
# Exit codes: 0 ok/dry-run; 1 (via die) unknown argument, missing --output,
#   or (with --apply) merge_repos.py / collapse_ci_gitsource.py failed.

usage() {
  cat <<'EOF'
  ./apply-phase0.sh --output DIR          # print the plan; nothing written
  ./apply-phase0.sh --output DIR --apply  # clone, rewrite, merge, collapse CI — local only
EOF
}

# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

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
  echo "dry-run only. Re-run with --apply to actually clone/merge locally."
  exit 0
fi

command -v git-filter-repo >/dev/null \
  || die "git-filter-repo not installed (brew install git-filter-repo)"
command -v gh >/dev/null || die "gh CLI not installed"

python3 "${PHASE0_DIR}/merge_repos.py" \
  --org "$ORG" --repos-json "$REPOS_JSON" --scratch "$SCRATCH" --output "$OUTPUT"

CI_FILES=("${OUTPUT}"/ci/*.yaml)
if [ -e "${CI_FILES[0]}" ]; then
  python3 "${PHASE0_DIR}/collapse_ci_gitsource.py" "${CI_FILES[@]}"
fi

echo
echo "merged tree ready at ${OUTPUT}. Next: ./verify-phase0.sh --output ${OUTPUT}"
