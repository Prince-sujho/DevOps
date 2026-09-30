#!/usr/bin/env bash
# GitHub Actions -> GCP login (WIF). Creates the pool/provider and seven narrow
# account identities (see IAM-table.md) — no role granted here, that's by hand.
#
# Each GitHub-side account trusts exactly ONE OIDC subject, never "any
# workflow in the repo":
#   preprod deploy/rollback, eval  repo:Sujho/sujho:ref:refs/heads/main
#   prod deploy                    repo:Sujho/sujho:environment:production
#   prod rollback                  repo:Sujho/sujho:environment:production-rollback
# A job only gets an environment:* subject after that GitHub Environment's
# approval, so a workflow on another branch (or one that skips the
# `environment:` line) cannot impersonate a prod account.
# The pool lives in the PROD project, not Pre-Prod. Whoever can administer the
# host project can edit the pool, its provider condition and its bindings — so
# hosting it in Pre-Prod would have let anyone with Pre-Prod admin mint tokens
# for the Prod deploy account. Prod is the more closely held project, so it
# hosts the pool and Pre-Prod trusts it, not the other way round.
# Dry-run unless --apply. Fill GITHUB_OWNER_ID first: gh api orgs/Sujho --jq .id
#
# Usage: GITHUB_OWNER_ID=<digits> [WIF_PROJECT=sujho-478914] ./provision-wif.sh [--apply]
# Arguments: --apply — actually run the gcloud commands (default: print only).
# Exit codes: 0 ok; 1 unknown argument, missing/placeholder/non-numeric
#   GITHUB_OWNER_ID, or (with --apply) a project number lookup failure.

set -euo pipefail

WIF_PROJECT="${WIF_PROJECT:-sujho-478914}"
PROD_PROJECT="sujho-478914"
PREPROD_PROJECT="sujho-preprod"
GITHUB_ORG="Sujho"
GITHUB_REPO="sujho"
GITHUB_OWNER_ID="${GITHUB_OWNER_ID:-REPLACE_WITH_GITHUB_ORG_NUMERIC_ID}"
POOL_ID="github-pool"
PROVIDER_ID="github-provider"

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      cat <<'EOF'
usage: GITHUB_OWNER_ID=<digits> [WIF_PROJECT=sujho-478914] ./provision-wif.sh [--apply]

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
  die "GITHUB_OWNER_ID must be the numeric GitHub org id, not a placeholder" \
    "(gh api orgs/Sujho --jq .id)"
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

# One exact OIDC subject (google.subject = assertion.sub), not the whole repo.
# Args: project number of the WIF host, subject suffix after "repo:ORG/REPO:".
subject_member() {
  local number="$1" suffix="$2"
  local pool
  pool="$(pool_resource "$number")"
  echo "principal://iam.googleapis.com/${pool}/subject/repo:${GITHUB_ORG}/${GITHUB_REPO}:${suffix}"
}

SUBJECT_MAIN="ref:refs/heads/main"
SUBJECT_PROD="environment:production"
SUBJECT_PROD_ROLLBACK="environment:production-rollback"

echo "WIF host project: ${WIF_PROJECT}"
echo "GitHub owner id (pinned): ${GITHUB_OWNER_ID}"
ATTRIBUTE_CONDITION="assertion.repository_owner_id == '${GITHUB_OWNER_ID}'"
ATTRIBUTE_CONDITION+=" && assertion.repository == '${GITHUB_ORG}/${GITHUB_REPO}'"
echo "Provider condition: ${ATTRIBUTE_CONDITION}"
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

ATTRIBUTE_MAPPING="google.subject=assertion.sub"
ATTRIBUTE_MAPPING+=",attribute.actor=assertion.actor"
ATTRIBUTE_MAPPING+=",attribute.repository=assertion.repository"
ATTRIBUTE_MAPPING+=",attribute.repository_owner=assertion.repository_owner"
ATTRIBUTE_MAPPING+=",attribute.repository_owner_id=assertion.repository_owner_id"
ATTRIBUTE_MAPPING+=",attribute.ref=assertion.ref"

run gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project="$WIF_PROJECT" \
  --location=global \
  --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="$ATTRIBUTE_MAPPING" \
  --attribute-condition="$ATTRIBUTE_CONDITION"

# these only ask Cloud Build to run something, never run it themselves
run gcloud iam service-accounts create github-deploy-preprod \
  --project="$PREPROD_PROJECT" --display-name="github-deploy-preprod"
run gcloud iam service-accounts create github-rollback-preprod \
  --project="$PREPROD_PROJECT" --display-name="github-rollback-preprod"
run gcloud iam service-accounts create github-deploy-prod \
  --project="$PROD_PROJECT" --display-name="github-deploy-prod"
run gcloud iam service-accounts create github-rollback-prod \
  --project="$PROD_PROJECT" --display-name="github-rollback-prod"

# Phase 3's weekly eval replay: reads the eval-* secrets, nothing else
run gcloud iam service-accounts create github-eval \
  --project="$PREPROD_PROJECT" --display-name="github-eval"

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

bind_subject() {
  local sa_id="$1" project="$2" suffix="$3"
  run gcloud iam service-accounts add-iam-policy-binding "$(sa_email "$sa_id" "$project")" \
    --project="$project" \
    --role="roles/iam.workloadIdentityUser" \
    --member="$(subject_member "$WIF_NUMBER" "$suffix")"
}

bind_subject github-deploy-preprod "$PREPROD_PROJECT" "$SUBJECT_MAIN"
bind_subject github-rollback-preprod "$PREPROD_PROJECT" "$SUBJECT_MAIN"
bind_subject github-deploy-prod "$PROD_PROJECT" "$SUBJECT_PROD"
bind_subject github-rollback-prod "$PROD_PROJECT" "$SUBJECT_PROD_ROLLBACK"
bind_subject github-eval "$PREPROD_PROJECT" "$SUBJECT_MAIN"

echo
echo "identities created, no roles granted — work through IAM-table.md next"
echo
echo "then set GitHub Variables by hand on ${GITHUB_ORG}/sujho (never Secrets):"
echo "  GCP_WIF_PROVIDER=$(provider_resource "$WIF_NUMBER")"
echo "  GCP_WIF_SERVICE_ACCOUNT_PREPROD=$(sa_email github-deploy-preprod "$PREPROD_PROJECT")"
rollback_preprod_email="$(sa_email github-rollback-preprod "$PREPROD_PROJECT")"
echo "  GCP_WIF_SERVICE_ACCOUNT_PREPROD_ROLLBACK=${rollback_preprod_email}"
echo "  GCP_WIF_SERVICE_ACCOUNT_PROD=$(sa_email github-deploy-prod "$PROD_PROJECT")"
echo "  GCP_WIF_SERVICE_ACCOUNT_PROD_ROLLBACK=$(sa_email github-rollback-prod "$PROD_PROJECT")"
echo "  GCP_WIF_SERVICE_ACCOUNT_EVAL=$(sa_email github-eval "$PREPROD_PROJECT")"
