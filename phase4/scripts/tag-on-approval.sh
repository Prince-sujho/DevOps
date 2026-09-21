#!/usr/bin/env bash
# tag-on-approval.sh — the only place preprod-approved is applied.
# Called from approve-preprod (one piece, required commit). Not from weekly eval.
#
# Usage:
#   ./tag-on-approval.sh <commit-sha> <service-id>
#   SUJHO_APPROVE_ALL=1 ./tag-on-approval.sh <commit-sha> --all
#
# --all is refused unless SUJHO_APPROVE_ALL=1 (emergency). One piece per click.
#
# Service ids come from catalog.json when that file is present (DevOps-Plan
# or a copy on sujho). Otherwise REGISTRY / SHORT_LEN / ALLOWLIST env.
# --all also tags knowledge-store-jobs (shared jobs image).
#
# SHORT_SHA is 7 characters — Cloud Build's SHORT_SHA, not a 12-char slice.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATALOG="${CATALOG_JSON:-${HERE}/../catalog.json}"
DRY_RUN=0
ALL=0

ARGS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --all) ALL=1 ;;
    -h|--help)
      echo "usage: $0 [--dry-run] <commit-sha> <service-id|--all>" >&2
      exit 2
      ;;
    *) ARGS+=("$arg") ;;
  esac
done

if [ "${#ARGS[@]}" -lt 1 ]; then
  echo "usage: $0 [--dry-run] <commit-sha> <service-id|--all>" >&2
  exit 2
fi

COMMIT_SHA="${ARGS[0]}"
SERVICE="${ARGS[1]:-}"

if [ "$ALL" -eq 1 ]; then
  if [ "${SUJHO_APPROVE_ALL:-}" != "1" ]; then
    echo "Refuse: --all stamps every image. One piece per click (approve-preprod)." >&2
    echo "Emergency only: SUJHO_APPROVE_ALL=1 $0 --all ..." >&2
    exit 2
  fi
fi
if [ "$ALL" -eq 0 ] && [ -z "$SERVICE" ]; then
  echo "usage: $0 [--dry-run] <commit-sha> <service-id|--all>" >&2
  exit 2
fi
if [ "$SERVICE" = "--all" ]; then
  ALL=1
  if [ "${SUJHO_APPROVE_ALL:-}" != "1" ]; then
    echo "Refuse: --all stamps every image. One piece per click (approve-preprod)." >&2
    echo "Emergency only: SUJHO_APPROVE_ALL=1 $0 --all ..." >&2
    exit 2
  fi
fi

if [ -f "$CATALOG" ]; then
  REGISTRY="$(python3 -c 'import json,pathlib,sys; print(json.loads(pathlib.Path(sys.argv[1]).read_text())["registry"])' "$CATALOG")"
  SHORT_LEN="$(python3 -c 'import json,pathlib,sys; print(json.loads(pathlib.Path(sys.argv[1]).read_text())["short_sha_len"])' "$CATALOG")"
  ALLOW="$(python3 -c 'import json,pathlib,sys; c=json.loads(pathlib.Path(sys.argv[1]).read_text()); print(" ".join(s["id"] for s in c["services"]))' "$CATALOG") knowledge-store-jobs"
else
  REGISTRY="${REGISTRY:-asia-south1-docker.pkg.dev/sujho-dev/services}"
  SHORT_LEN="${SHORT_LEN:-7}"
  ALLOW="${ALLOWLIST:-redirect text users whatsapp document-worker admin knowledge-store-jobs}"
fi

if [ "${#COMMIT_SHA}" -lt "$SHORT_LEN" ]; then
  echo "error: commit sha is shorter than ${SHORT_LEN} characters" >&2
  exit 1
fi

SHORT_SHA="${COMMIT_SHA:0:${SHORT_LEN}}"

if [ "$ALL" -eq 1 ]; then
  TARGETS="$ALLOW"
else
  case " ${ALLOW} " in
    *" ${SERVICE} "*) ;;
    *) echo "error: ${SERVICE} is not a split Cloud Run service (allowlist: ${ALLOW})" >&2; exit 1 ;;
  esac
  TARGETS="$SERVICE"
fi

tag_one() {
  local image_id="$1"
  local image="${REGISTRY}/${image_id}:sha-${SHORT_SHA}"
  echo "Confirming ${image} exists before tagging..."
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN would tag ${image} as preprod-approved"
    return 0
  fi
  local digest
  digest="$(gcloud artifacts docker images describe "$image" --format='value(image_summary.digest)')"
  if [ -z "${digest}" ]; then
    echo "No built image found for ${image_id} at ${SHORT_SHA} — cannot approve" >&2
    return 1
  fi
  echo "Tagging digest ${digest} as preprod-approved for ${image_id}..."
  gcloud artifacts docker tags add \
    "${REGISTRY}/${image_id}@${digest}" \
    "${REGISTRY}/${image_id}:preprod-approved"
  echo "${image_id} @ ${SHORT_SHA} is now eligible for promotion."
}

failed=0
for image_id in $TARGETS; do
  if ! tag_one "$image_id"; then
    failed=1
  fi
done
exit "$failed"
