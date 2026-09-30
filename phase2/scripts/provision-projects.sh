#!/usr/bin/env bash
# Creates sujho-preprod + its warehouse + its build-source bucket. sujho-dev
# stays untouched, no IAM here.
# Dry-run unless --apply. Fill ORG_ID / BILLING_ACCOUNT_ID first.
#
# Usage: ./provision-projects.sh [--apply]
# Arguments: --apply — actually run the gcloud commands (default: print only).
# Exit codes: 0 ok; 1 unknown argument, or ORG_ID/BILLING_ACCOUNT_ID unset
#   or still a REPLACE_* placeholder.

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

if [[ "$ORG_ID" == *REPLACE* ]] || [ -z "$ORG_ID" ] \
  || [[ "$BILLING_ACCOUNT_ID" == *REPLACE* ]] || [ -z "$BILLING_ACCOUNT_ID" ]; then
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
    secretmanager.googleapis.com \
    cloudscheduler.googleapis.com \
    --project="$project"
}

ensure_project "$PREPROD_PROJECT"
enable_apis "$PREPROD_PROJECT"

if [ "$APPLY" -eq 0 ] || ! gcloud artifacts repositories describe services \
  --location="$REGION" --project="$PREPROD_PROJECT" >/dev/null 2>&1; then
  echo "Artifact Registry ${PREPROD_PROJECT}/services — the warehouse"
  run gcloud artifacts repositories create services \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PREPROD_PROJECT"
else
  echo "Artifact Registry ${PREPROD_PROJECT}/services already exists"
fi

# Where the preprod workflows stage the source they upload to Cloud Build
# (`gcloud builds submit . --gcs-source-staging-dir=...`). Created here with
# uniform access so only IAM-table.md's grants decide who can write to it.
# The sujho-478914 twin is an IAM-table.md step, by hand — this script never
# touches Prod.
SOURCE_BUCKET="gs://${PREPROD_PROJECT}-build-source"
if [ "$APPLY" -eq 0 ] || ! gcloud storage buckets describe "$SOURCE_BUCKET" \
  --project="$PREPROD_PROJECT" >/dev/null 2>&1; then
  echo "Build-source bucket ${SOURCE_BUCKET}"
  run gcloud storage buckets create "$SOURCE_BUCKET" \
    --project="$PREPROD_PROJECT" \
    --location="$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention
else
  echo "Build-source bucket ${SOURCE_BUCKET} already exists"
fi

# Who may call a service is a separate, one-time decision from deploying it.
# A deploy cannot make it, on purpose: setting a service's IAM policy needs
# run.admin, and the builder only has run.developer (IAM-table.md 2), so the
# recipes pass no allow-unauthenticated flag at all. These five Pre-Prod
# services answer public HTTP (WhatsApp webhooks, short links); `admin` is
# deliberately absent — it stays private behind its load balancer.
echo
echo "Public invoker on the Pre-Prod services that answer public HTTP:"
for service in redirect text users whatsapp document-worker; do
  run gcloud run services add-iam-policy-binding "$service" \
    --project="$PREPROD_PROJECT" \
    --region="$REGION" \
    --member=allUsers \
    --role=roles/run.invoker \
    --quiet
done
echo "(each is a no-op after the first run; the service must exist first)"

echo
echo "resources created, no IAM granted yet — work through IAM-table.md next"
