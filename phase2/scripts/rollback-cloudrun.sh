#!/usr/bin/env bash
# Shifts Cloud Run traffic to a previous revision. No rebuild, no retagging.
# Empty --revision: newest served=true revision older than the one serving.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT=""
SERVICE=""
REVISION=""
REGION="asia-south1"
DRY_RUN=0

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
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      echo "usage: $0 --project=P --service=S [--revision=REV] [--dry-run]" >&2
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
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

if [ -z "$REVISION" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN would query GCP and pick an older Ready revision of ${SERVICE} in ${PROJECT}"
    echo "DRY-RUN would refuse if a newer Ready revision has no traffic."
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
    REVISION="$(python3 "${HERE}/pick_rollback_revision.py" "$tmp/service.json" "$tmp/revisions.json")"
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
