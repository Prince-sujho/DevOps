#!/usr/bin/env bash
# Local by default. --remote reads GitHub (no writes) to re-confirm nothing
# changed there since the plan was made — same inventory check apply-phase0.sh's
# plan step relies on.
#
# Usage: see usage() below — ./verify-phase0.sh --output DIR [--remote]
# Arguments: --output DIR — the merged tree to check (required).
#   --remote — also check GitHub (read-only); default is local-only.
# Exit codes: 0 ok; 1 (via die) unknown argument, missing --output, or a
#   local/remote check failed.

usage() {
  cat <<'EOF'
  ./verify-phase0.sh --output DIR           # local checks only (no GitHub)
  ./verify-phase0.sh --output DIR --remote  # also re-check branches/PRs on GitHub
EOF
}

# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

REMOTE=0
OUTPUT=""
for arg in "$@"; do
  case "$arg" in
    --remote) REMOTE=1 ;;
    --output) NEED_OUTPUT=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [ "${NEED_OUTPUT:-0}" = "1" ]; then OUTPUT="$arg"; NEED_OUTPUT=0
      else die "unknown argument: $arg (allowed: --output DIR --remote)"
      fi
      ;;
  esac
done
[ -n "$OUTPUT" ] || { usage; die "--output DIR is required"; }
[ -d "$OUTPUT" ] || die "${OUTPUT}: no such directory"

python3 "${PHASE0_DIR}/validate.py" || die "local Phase 0 invariants failed"

REPOS_JSON="${PHASE0_DIR}/repos.json"
# Single source of truth for every repo name below — never a second hardcoded
# list, so this script can't silently drift from what merge_repos.py actually did.
MERGE_TARGETS="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(" ".join(e["target"] for e in d["merge_repos"]))
' "$REPOS_JSON")"
KEEP_SUBMODULES="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(" ".join(d["keep_submodules"]))
' "$REPOS_JSON")"
ALL_GITHUB_REPOS="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["super_repo"] + " " + " ".join(e["github"] for e in d["merge_repos"]))
' "$REPOS_JSON")"

fail=0

check_no_dangling_gitlinks() {
  local path
  for path in $MERGE_TARGETS; do
    if git -C "$OUTPUT" ls-tree HEAD -- "$path" | grep -q '^160000'; then
      echo "FAIL: ${path} is still a gitlink (160000) in ${OUTPUT}"
      fail=1
    fi
  done
}

check_kept_submodules_untouched() {
  local path
  for path in $KEEP_SUBMODULES; do
    if ! grep -q "\[submodule \"${path}\"\]" "${OUTPUT}/.gitmodules" 2>/dev/null; then
      echo "FAIL: ${path} missing from ${OUTPUT}/.gitmodules — should be kept as-is"
      fail=1
    fi
  done
}

# www and design_system are not merged and not kept. A pointer to either
# one would still pull them in.
check_left_out_repos() {
  local path
  for path in www design_system; do
    if git -C "$OUTPUT" ls-tree HEAD -- "$path" | grep -q '^160000'; then
      echo "FAIL: ${path} is still a gitlink in ${OUTPUT}"
      fail=1
    fi
    if grep -q "\[submodule \"${path}\"\]" "${OUTPUT}/.gitmodules" 2>/dev/null; then
      echo "FAIL: ${path} is still listed in ${OUTPUT}/.gitmodules"
      fail=1
    fi
  done
}

check_ci_single_gitsource() {
  local f count
  for f in "${OUTPUT}"/ci/*.yaml; do
    [ -e "$f" ] || continue
    count="$(grep -c 'gitSource:' "$f" || true)"
    if [ "$count" -gt 1 ]; then
      echo "FAIL: ${f} still has ${count} gitSource blocks (want 0 or 1)"
      fail=1
    fi
  done
}

check_history_preserved() {
  local path count
  for path in $MERGE_TARGETS; do
    if [ ! -d "${OUTPUT}/${path}" ]; then
      echo "FAIL: ${path}/ missing from ${OUTPUT} — merge did not bring it in"
      fail=1
      continue
    fi
    count="$(git -C "$OUTPUT" log --oneline --no-merges -- "$path" | wc -l | tr -d ' ')"
    if [ "$count" -lt 2 ]; then
      echo "FAIL: ${path} has only ${count} commit(s) after merge — history looks lost"
      fail=1
    fi
  done
}

echo "--- gitlinks removed ---"
check_no_dangling_gitlinks
echo "--- kept submodules untouched ---"
check_kept_submodules_untouched
echo "--- www and design_system left out ---"
check_left_out_repos
echo "--- ci/*.yaml collapsed ---"
check_ci_single_gitsource
echo "--- pre-merge history preserved ---"
check_history_preserved

if [ "$REMOTE" -eq 1 ]; then
  echo "--- remote: no new branches/PRs since planning ---"
  for repo in $ALL_GITHUB_REPOS; do
    branches="$(gh api "repos/${ORG}/${repo}/branches" --jq '.[].name' | tr '\n' ' ')"
    if [ "$branches" != "main " ]; then
      echo "FAIL: ${repo} now has branches: ${branches}(re-run the inventory step)"
      fail=1
    fi
  done
fi

if [ "$fail" -ne 0 ]; then
  die "Phase 0 verification failed"
fi
echo "Phase 0 verification passed."
