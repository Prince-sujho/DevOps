#!/usr/bin/env bash
# provision-projects.sh — 4c. Creates sujho-dev / sujho-preprod, enables APIs,
# creates the shared Artifact Registry, grants cross-project readers.
# Dry-run unless you pass --apply. Needs Owner on the org + billing.
#
# Fill these in before --apply (gcloud organizations list /
# gcloud billing accounts list). The script refuses placeholders.

set -euo pipefail

ORG_ID="${ORG_ID:-REPLACE_WITH_YOUR_ORG_ID}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-REPLACE_WITH_YOUR_BILLING_ACCOUNT_ID}"
REGION="asia-south1"
PROD_PROJECT="sujho-478914"
DEV_PROJECT="sujho-dev"
PREPROD_PROJECT="sujho-preprod"

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      echo "usage: $0 [--apply]"
      echo "Set ORG_ID and BILLING_ACCOUNT_ID in the environment."
      exit 0
      ;;
    *) echo "error: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

project_display_name() {
  case "$1" in
    sujho-dev) echo "Sujho Dev" ;;
    sujho-preprod) echo "Sujho Preprod" ;;
    *) echo "$1" ;;
  esac
}

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
    --name="$(project_display_name "$project")" \
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
    --project="$project"
}

grant_reader() {
  local target_project="$1"
  local number
  if [ "$APPLY" -eq 0 ]; then
    echo "DRY-RUN would grant Cloud Run agent on ${target_project} roles/artifactregistry.reader on ${DEV_PROJECT}/services"
    return 0
  fi
  number="$(gcloud projects describe "$target_project" --format='value(projectNumber)')"
  local agent="service-${number}@serverless-robot-prod.iam.gserviceaccount.com"
  echo "Granting ${agent} read access to ${DEV_PROJECT}'s registry..."
  gcloud artifacts repositories add-iam-policy-binding services \
    --location="$REGION" \
    --project="$DEV_PROJECT" \
    --member="serviceAccount:${agent}" \
    --role="roles/artifactregistry.reader"
}

# New projects often have no NUM@cloudbuild.gserviceaccount.com (legacy SA).
# Use Cloud Build's default SA; fall back to the Cloud Build service agent.
cloudbuild_sa_email() {
  local project="$1"
  if [ "$APPLY" -eq 0 ]; then
    echo "cloudbuild-default-sa@${project}"
    return 0
  fi
  local raw email num
  raw="$(gcloud builds get-default-service-account --project="$project" 2>/dev/null || true)"
  email="$(printf '%s\n' "$raw" | grep -Eo '[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+' | head -1 || true)"
  if [ -n "$email" ]; then
    echo "$email"
    return 0
  fi
  num="$(gcloud projects describe "$project" --format='value(projectNumber)')"
  echo "service-${num}@gcp-sa-cloudbuild.iam.gserviceaccount.com"
}

grant_ar() {
  local member_sa="$1" role="$2"
  run gcloud artifacts repositories add-iam-policy-binding services \
    --location="$REGION" \
    --project="$DEV_PROJECT" \
    --member="serviceAccount:${member_sa}" \
    --role="$role"
}

grant_run_in_project() {
  local project="$1" member_sa="$2"
  run gcloud projects add-iam-policy-binding "$project" \
    --member="serviceAccount:${member_sa}" \
    --role="roles/cloudbuild.builds.editor"
  run gcloud projects add-iam-policy-binding "$project" \
    --member="serviceAccount:${member_sa}" \
    --role="roles/run.developer"
  run gcloud projects add-iam-policy-binding "$project" \
    --member="serviceAccount:${member_sa}" \
    --role="roles/iam.serviceAccountUser"
}

ensure_project "$DEV_PROJECT"
ensure_project "$PREPROD_PROJECT"
enable_apis "$DEV_PROJECT"
enable_apis "$PREPROD_PROJECT"

if [ "$APPLY" -eq 0 ] || ! gcloud artifacts repositories describe services --location="$REGION" --project="$DEV_PROJECT" >/dev/null 2>&1; then
  echo "Artifact Registry ${DEV_PROJECT}/services"
  run gcloud artifacts repositories create services \
    --repository-format=docker \
    --location="$REGION" \
    --project="$DEV_PROJECT"
else
  echo "Artifact Registry ${DEV_PROJECT}/services already exists"
fi

grant_reader "$PREPROD_PROJECT"
grant_reader "$PROD_PROJECT"

DEV_CB="$(cloudbuild_sa_email "$DEV_PROJECT")"
PREPROD_CB="$(cloudbuild_sa_email "$PREPROD_PROJECT")"
PROD_CB="$(cloudbuild_sa_email "$PROD_PROJECT")"
echo "Cloud Build SAs: dev=${DEV_CB} preprod=${PREPROD_CB} prod=${PROD_CB}"

# Builder in sujho-dev pushes images and deploys to Pre-Prod.
# Prod workers run deploy-only in Prod (pull only). Do not use
# NUM@cloudbuild.gserviceaccount.com as the only identity.
grant_ar "$DEV_CB" "roles/artifactregistry.writer"
grant_ar "$PROD_CB" "roles/artifactregistry.reader"

# Cross-project: Dev Cloud Build SA deploys into Pre-Prod.
# Prod Cloud Build SA deploys into Prod. Pre-Prod SA does not push.
grant_run_in_project "$PREPROD_PROJECT" "$DEV_CB"
grant_run_in_project "$PROD_PROJECT" "$PROD_CB"

echo "Done. Developer Connect still needs a one-time browser step — see developer-connect-setup.sh."
echo "WIF identities are provision-wif.sh (separate). Runtime SAs still need iam.serviceAccountUser per service."
