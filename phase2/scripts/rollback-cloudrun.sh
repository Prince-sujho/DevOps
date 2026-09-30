#!/usr/bin/env bash
# Shifts Cloud Run traffic to a previous revision. No rebuild, no retagging.
# Empty --revision: the revision the service's own `prev` tag records as the
# last known good one before the current deploy (pick_rollback_revision.py).
#
# Dry-run by default, matching every other mutating script in this repo —
# --apply is required to actually shift traffic.
#
# Usage: ./rollback-cloudrun.sh --project=P --service=S [--revision=REV] [--apply]
# Arguments: --project, --service required; --revision optional (auto-picked
#   if omitted); --region defaults to asia-south1; --apply actually shifts
#   traffic (default: print the plan only).
# Exit codes: 0 ok; 2 unknown argument, missing --help, or missing
#   --project/--service.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT=""
SERVICE=""
REVISION=""
REGION="asia-south1"
APPLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --project) PROJECT="${2:-}"; shift 2 ;;
    --project=*) PROJECT="${1#*=}"; shift ;;
    --service) SERVICE="${2:-}"; shift 2 ;;
    --service=*) SERVICE="${1#*=}"; shift ;;
    --revision) REVISION="${2:-}"; shift 2 ;;
    --revision=*) REVISION="${1#*=}"; shift ;;
    --region) REGION="${2:-}"; shift 2 ;;
    --region=*) REGION="${1#*=}"; shift ;;
    --apply) APPLY=1; shift ;;
    -h|--help)
      echo "usage: $0 --project=P --service=S [--revision=REV] [--apply]" >&2
      exit 2
      ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$PROJECT" ] || [ -z "$SERVICE" ]; then
  echo "error: --project and --service are required" >&2
  exit 2
fi

run() {
  if [ "$APPLY" -ne 1 ]; then
    printf 'DRY-RUN'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

OLD_SERVING=""
HAD_PREV=""

if [ "$APPLY" -ne 1 ]; then
  if [ -z "$REVISION" ]; then
    echo "DRY-RUN would query GCP for ${SERVICE} in ${PROJECT} and roll to the"
    echo "revision its 'prev' tag records as the last known good one."
    echo "DRY-RUN would refuse if there is no 'prev' tag, if it points at the"
    echo "revision already serving, or if that revision is no longer Ready —"
    echo "in every case asking for an explicit --revision instead of guessing."
    REVISION="WOULD_QUERY"
  fi
  echo "DRY-RUN would then move the 'lkg' tag onto the revision rolled to and"
  echo "drop 'prev', so a later rollback can never land back on the revision"
  echo "this one is fleeing."
else
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/rollback.XXXXXX")"
  trap 'rm -rf "$tmp"' EXIT
  gcloud run services describe "$SERVICE" \
    --project="$PROJECT" --region="$REGION" --format=json \
    > "$tmp/service.json"
  OLD_SERVING="$(
    python3 "${HERE}/pick_rollback_revision.py" --print-current "$tmp/service.json"
  )"
  HAD_PREV="$(
    python3 "${HERE}/pick_rollback_revision.py" --print-tag prev "$tmp/service.json"
  )"
  if [ -z "$REVISION" ]; then
    gcloud run revisions list --service="$SERVICE" \
      --project="$PROJECT" --region="$REGION" --format=json \
      > "$tmp/revisions.json"
    REVISION="$(
      python3 "${HERE}/pick_rollback_revision.py" "$tmp/service.json" "$tmp/revisions.json"
    )"
    echo "Serving revision stays until update-traffic. Rolling to ${REVISION}"
  fi
fi

echo "Rolling ${SERVICE} in ${PROJECT} to ${REVISION}"
run gcloud run services update-traffic "$SERVICE" \
  --project="$PROJECT" \
  --region="$REGION" \
  --to-revisions="${REVISION}=100" \
  --quiet
echo "Traffic is on ${REVISION}."

# Re-point the markers. The revision now serving is the known-good one, and
# there is no longer a recorded good revision older than it — dropping 'prev'
# is what stops a later rollback landing back on ${OLD_SERVING}, the revision
# this rollback is fleeing. The next deploy sets both tags again.
run gcloud run services update-traffic "$SERVICE" \
  --project="$PROJECT" --region="$REGION" \
  --update-tags="lkg=${REVISION}" \
  --quiet
if [ "$APPLY" -ne 1 ] || [ -n "$HAD_PREV" ]; then
  run gcloud run services update-traffic "$SERVICE" \
    --project="$PROJECT" --region="$REGION" \
    --remove-tags=prev \
    --quiet
fi
if [ -n "$OLD_SERVING" ]; then
  echo "lkg is now ${REVISION}; ${OLD_SERVING} is no longer a rollback target."
fi
