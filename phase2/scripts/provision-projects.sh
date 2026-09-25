#!/usr/bin/env bash
# Creates sujho-preprod + its warehouse. sujho-dev stays untouched, no IAM here.
# Dry-run unless --apply. Fill ORG_ID / BILLING_ACCOUNT_ID first.

set -euo pipefail

ORG_ID="${ORG_ID:-REPLACE_WITH_YOUR_ORG_ID}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-REPLACE_WITH_YOUR_BILLING_ACCOUNT_ID}"
REGION="asia-south1"
PREPROD_PROJECT="sujho-preprod"

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      echo "usage: $0 [--apply]"
      echo "Set ORG_ID and BILLING_ACCOUNT_ID in the environment."
      echo "See IAM-table.md for the grants this script deliberately does not make."
      exit 0
      ;;
    *) echo "error: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

run() {
  if [ "$APPLY" -eq 0 ]; then
    printf 'DRY-RUN'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

if [[ "$ORG_ID" == *REPLACE* ]] || [[ "$BILLING_ACCOUNT_ID" == *REPLACE* ]] || [ -z "$ORG_ID" ] || [ -z "$BILLING_ACCOUNT_ID" ]; then
  die "ORG_ID and BILLING_ACCOUNT_ID must be real values, not placeholders"
fi

project_exists() {
  gcloud projects describe "$1" >/dev/null 2>&1
}

ensure_project() {
  local project="$1"
  if project_exists "$project"; then
    echo "${project}: already exists"
    return 0
  fi
  echo "Creating ${project}..."
  run gcloud projects create "$project" \
    --name="Sujho Preprod" \
    --organization="$ORG_ID"
  run gcloud billing projects link "$project" \
    --billing-account="$BILLING_ACCOUNT_ID"
}

enable_apis() {
  local project="$1"
  run gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    developerconnect.googleapis.com \
    secretmanager.googleapis.com \
    cloudscheduler.googleapis.com \
    --project="$project"
}

ensure_project "$PREPROD_PROJECT"
enable_apis "$PREPROD_PROJECT"

if [ "$APPLY" -eq 0 ] || ! gcloud artifacts repositories describe services --location="$REGION" --project="$PREPROD_PROJECT" >/dev/null 2>&1; then
  echo "Artifact Registry ${PREPROD_PROJECT}/services — the warehouse"
  run gcloud artifacts repositories create services \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PREPROD_PROJECT"
else
  echo "Artifact Registry ${PREPROD_PROJECT}/services already exists"
fi

echo
echo "resources created, no IAM granted yet — work through IAM-table.md next"
echo "Developer Connect still needs its one-time browser step — see developer-connect-setup.sh"
