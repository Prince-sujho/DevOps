#!/usr/bin/env bash
# Shifts Cloud Run traffic to a previous revision. No rebuild, no retagging.
# Empty --revision: newest served=true revision older than the one serving.
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

if [ -z "$REVISION" ]; then
  if [ "$APPLY" -ne 1 ]; then
    echo "DRY-RUN would query GCP and pick the newest served=true revision of"
    echo "${SERVICE} in ${PROJECT} older than the one currently serving."
    echo "DRY-RUN would refuse if the serving revision has no served=true label,"
    echo "or if no older served=true revision exists."
    REVISION="WOULD_QUERY"
  else
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/rollback.XXXXXX")"
    trap 'rm -rf "$tmp"' EXIT
    gcloud run services describe "$SERVICE" \
      --project="$PROJECT" --region="$REGION" --format=json \
      > "$tmp/service.json"
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
