#!/usr/bin/env bash
# GitHub Actions -> GCP login (WIF). Creates the pool/provider and six narrow
# account identities (see IAM-table.md) — no role granted here, that's by hand.
# Dry-run unless --apply. Fill GITHUB_OWNER_ID first: gh api orgs/Sujho --jq .id

set -euo pipefail

WIF_PROJECT="${WIF_PROJECT:-sujho-preprod}"
PROD_PROJECT="sujho-478914"
PREPROD_PROJECT="sujho-preprod"
GITHUB_ORG="Sujho"
GITHUB_OWNER_ID="${GITHUB_OWNER_ID:-REPLACE_WITH_GITHUB_ORG_NUMERIC_ID}"
POOL_ID="github-pool"
PROVIDER_ID="github-provider"

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      cat <<'EOF'
usage: GITHUB_OWNER_ID=<digits> [WIF_PROJECT=sujho-preprod] ./provision-wif.sh [--apply]

Default is dry-run (prints gcloud, changes nothing).
--apply creates the pool/provider/account identities in GCP. It never
grants a role and never calls gh. Roles come from IAM-table.md, by hand.
EOF
      exit 0
      ;;
    *) echo "error: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

if [[ "$GITHUB_OWNER_ID" == *REPLACE* ]] || [ -z "$GITHUB_OWNER_ID" ]; then
  die "GITHUB_OWNER_ID must be the numeric GitHub org id, not a placeholder (gh api orgs/Sujho --jq .id)"
fi
if ! [[ "$GITHUB_OWNER_ID" =~ ^[0-9]+$ ]]; then
  die "GITHUB_OWNER_ID must be digits only (GitHub org id), got: ${GITHUB_OWNER_ID}"
fi

run() {
  if [ "$APPLY" -eq 0 ]; then
    printf 'DRY-RUN'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

sa_email() {
  local id="$1" project="$2"
  echo "${id}@${project}.iam.gserviceaccount.com"
}

pool_resource() {
  local number="$1"
  echo "projects/${number}/locations/global/workloadIdentityPools/${POOL_ID}"
}

provider_resource() {
  local number="$1"
  echo "$(pool_resource "$number")/providers/${PROVIDER_ID}"
}

repo_member() {
  local number="$1"
  echo "principalSet://iam.googleapis.com/$(pool_resource "$number")/attribute.repository/${GITHUB_ORG}/sujho"
}

echo "WIF host project: ${WIF_PROJECT}"
echo "GitHub owner id (pinned): ${GITHUB_OWNER_ID}"
echo "Provider condition: assertion.repository_owner_id == '${GITHUB_OWNER_ID}'"
if [ "$APPLY" -eq 0 ]; then
  echo "DRY-RUN — no GCP changes. Pass --apply only when a Lead asks."
fi

run gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project="$WIF_PROJECT"

run gcloud iam workload-identity-pools create "$POOL_ID" \
  --project="$WIF_PROJECT" \
  --location=global \
  --display-name="GitHub Actions"

run gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project="$WIF_PROJECT" \
  --location=global \
  --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository_owner_id == '${GITHUB_OWNER_ID}'"

# these only ask Cloud Build to run something, never run it themselves
run gcloud iam service-accounts create github-deploy-preprod \
  --project="$PREPROD_PROJECT" --display-name="github-deploy-preprod"
run gcloud iam service-accounts create github-rollback-preprod \
  --project="$PREPROD_PROJECT" --display-name="github-rollback-preprod"
run gcloud iam service-accounts create github-deploy-prod \
  --project="$PROD_PROJECT" --display-name="github-deploy-prod"
run gcloud iam service-accounts create github-rollback-prod \
  --project="$PROD_PROJECT" --display-name="github-rollback-prod"

# the narrow key the build machine itself runs as — see IAM-table.md section 2
run gcloud iam service-accounts create prod-builder \
  --project="$PREPROD_PROJECT" --display-name="prod-builder (writes the warehouse)"
run gcloud iam service-accounts create prod-builder \
  --project="$PROD_PROJECT" --display-name="prod-builder (reads the warehouse only)"

if [ "$APPLY" -eq 1 ]; then
  WIF_NUMBER="$(gcloud projects describe "$WIF_PROJECT" --format='value(projectNumber)')"
  [ -n "$WIF_NUMBER" ] || die "could not read project number for ${WIF_PROJECT}"
else
  WIF_NUMBER="PROJECT_NUMBER"
fi

bind_repo() {
  local sa_id="$1" project="$2"
  run gcloud iam service-accounts add-iam-policy-binding "$(sa_email "$sa_id" "$project")" \
    --project="$project" \
    --role="roles/iam.workloadIdentityUser" \
    --member="$(repo_member "$WIF_NUMBER")"
}

bind_repo github-deploy-preprod "$PREPROD_PROJECT"
bind_repo github-rollback-preprod "$PREPROD_PROJECT"
bind_repo github-deploy-prod "$PROD_PROJECT"
bind_repo github-rollback-prod "$PROD_PROJECT"

echo
echo "identities created, no roles granted — work through IAM-table.md next"
echo
echo "then set GitHub Variables by hand on ${GITHUB_ORG}/sujho (never Secrets):"
echo "  GCP_WIF_PROVIDER=$(provider_resource "$WIF_NUMBER")"
echo "  GCP_WIF_SERVICE_ACCOUNT_PREPROD=$(sa_email github-deploy-preprod "$PREPROD_PROJECT")"
echo "  GCP_WIF_SERVICE_ACCOUNT_PREPROD_ROLLBACK=$(sa_email github-rollback-preprod "$PREPROD_PROJECT")"
echo "  GCP_WIF_SERVICE_ACCOUNT_PROD=$(sa_email github-deploy-prod "$PROD_PROJECT")"
echo "  GCP_WIF_SERVICE_ACCOUNT_PROD_ROLLBACK=$(sa_email github-rollback-prod "$PROD_PROJECT")"
