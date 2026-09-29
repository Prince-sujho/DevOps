# Shared constants + helpers for Phase 0 scripts.
#
# Usage: source, do not execute — `source "$(dirname "$0")/lib.sh"`.
# Arguments: none; scripts that source this call parse_apply_flag "$@" themselves.
# Exit codes: die() prints to stderr and exits 1.
#
# Unlike phase1/phase2's lib.sh, there is no gh_mutate here: nothing in
# Phase 0 ever writes to GitHub or GCP. --apply below means "actually
# write the merged tree to --output on local disk", never anything remote.
set -euo pipefail

ORG="Sujho"
PHASE0_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY=0
OUTPUT=""

die() { echo "error: $*" >&2; exit 1; }

parse_apply_flag() {
  APPLY=0
  OUTPUT=""
  local arg
  while [ $# -gt 0 ]; do
    case "$1" in
      --apply) APPLY=1 ;;
      --output)
        shift
        [ $# -gt 0 ] || die "--output needs a path"
        OUTPUT="$1"
        ;;
      -h|--help) return 2 ;;
      *) die "unknown argument: $1 (allowed: --apply --output PATH)" ;;
    esac
    shift
  done
}
