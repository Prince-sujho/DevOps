#!/usr/bin/env bash
# Phase 5 checker/templates were cut. They hid a real gap: a digest check
# is not a Lead testing Pre-Prod. Stamp is approve-preprod (Phase 4).
# Weekly eval does not stamp. This script must not put the cut files back.

usage() {
  cat <<'EOF'
  ./apply-phase5.sh                  # validate + explain; no GitHub
  ./apply-phase5.sh --apply          # refused — nothing to land

Phase 5 is not a merge gate. Deploys stay manual Cloud Build.
A Lead stamps one image with approve-preprod after they tested it.
EOF
}

PHASE5_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE5_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE5_DIR}/lib.sh"

ARGS=()
for arg in "$@"; do
  case "$arg" in
    --require-checks) die "Phase 5 is not a merge gate — deploys are manual Cloud Build" ;;
    --apply|-h|--help) ARGS+=("$arg") ;;
    *) die "unknown argument: $arg" ;;
  esac
done
if ! parse_apply_flag "${ARGS[@]+"${ARGS[@]}"}" ; then
  usage
  exit 0
fi

python3 "${PHASE5_DIR}/validate.py" || die "Phase 5 local invariants failed"

if [ "$APPLY" -eq 1 ]; then
  die "Phase 5 checker/templates were cut. Stamp with approve-preprod (Phase 4). Eval does not stamp."
fi

cat <<EOF
DRY-RUN (nothing to land; --apply is refused on purpose)

Promotion is not a GitHub digest-check workflow.
After a Lead tests one piece on Pre-Prod they open:
  Actions → Approve Pre-Prod image → piece + commit → Run
That calls tag-on-approval.sh for that piece only.

skip: ${PHASE5_SKIP_REPOS[*]}
      (builds tag the sujho commit, not each service-repo SHA)

Manual Cloud Build per service: Dev build in sujho-dev, deploy to Pre-Prod,
then deploy-only Prod. Same digest. Merge does not deploy.
EOF
