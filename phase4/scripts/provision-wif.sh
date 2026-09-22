#!/usr/bin/env bash
# provision-wif.sh — GitHub Actions → GCP login (Workload Identity Federation).
#
# Paper / laptop script. Dry-run unless you pass --apply.
# --apply mutates GCP (pool, provider, service accounts, IAM). It does NOT
# touch GitHub. Set GitHub Variables by hand after a Lead has applied.
#
# Why this exists: "create WIF; bind to Sujho/sujho" is not enough.
# If the provider only checks assertion.repository == 'Sujho/sujho', a
# different GitHub org that names a repo the same way can impersonate.
# Pin the numeric GitHub owner id (stable). Then bind each SA to the
# repos it is allowed to come from.
#
# Deploy/review identities — not one shared account:
#   github-ai-review        — Secret Manager for the review key only
#   github-deploy-dev       — Cloud Build / Cloud Run in sujho-dev only
#   github-deploy-preprod   — Cloud Build in sujho-dev, Cloud Run in sujho-preprod
#   github-deploy-prod      — Cloud Build / Cloud Run in sujho-478914 only
#   github-eval             — eval secrets on Sujho/sujho only
# Dev's SA must have zero roles in Pre-Prod and Prod. Pre-Prod's SA must have
# zero roles in Prod. Separate workflow files are not a permission boundary
# without this.
#
# Does not create GitHub Environments. Does not auto-deploy.
# Needs Owner on WIF_PROJECT for --apply. Fill GITHUB_OWNER_ID first:
#   gh api orgs/Sujho --jq .id
# That read is optional and not done by this script.

set -euo pipefail

WIF_PROJECT="${WIF_PROJECT:-sujho-dev}"
PROD_PROJECT="sujho-478914"
PREPROD_PROJECT="sujho-preprod"
DEV_PROJECT="sujho-dev"
REGION="asia-south1"
POOL_ID="github-pool"
PROVIDER_ID="github-provider"
GITHUB_ORG="Sujho"
GITHUB_OWNER_ID="${GITHUB_OWNER_ID:-REPLACE_WITH_GITHUB_ORG_NUMERIC_ID}"

# Full-treatment repos that run AI review (not light-touch).
AI_REVIEW_REPOS=(
  sujho
  text-agent
  user-service
  whatsapp-adapter
  admin
  document-worker
  redirect-service
  knowledge-store
  sujho-ops-mcp
)

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      cat <<'EOF'
usage: GITHUB_OWNER_ID=<digits> [WIF_PROJECT=sujho-dev] ./provision-wif.sh [--apply]

Default is dry-run (prints gcloud, changes nothing).
--apply creates the pool/provider/SAs in GCP. It never calls gh.
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
  echo "${1}@${WIF_PROJECT}.iam.gserviceaccount.com"
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
  local number="$1" repo="$2"
  echo "principalSet://iam.googleapis.com/$(pool_resource "$number")/attribute.repository/${GITHUB_ORG}/${repo}"
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
  secretmanager.googleapis.com \
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

for id in github-ai-review github-deploy-dev github-deploy-preprod github-deploy-prod github-eval; do
  run gcloud iam service-accounts create "$id" \
    --project="$WIF_PROJECT" \
    --display-name="$id"
done

if [ "$APPLY" -eq 1 ]; then
  WIF_NUMBER="$(gcloud projects describe "$WIF_PROJECT" --format='value(projectNumber)')"
  [ -n "$WIF_NUMBER" ] || die "could not read project number for ${WIF_PROJECT}"
else
  WIF_NUMBER="PROJECT_NUMBER"
fi

bind_repo() {
  local sa_id="$1" repo="$2"
  run gcloud iam service-accounts add-iam-policy-binding "$(sa_email "$sa_id")" \
    --project="$WIF_PROJECT" \
    --role="roles/iam.workloadIdentityUser" \
    --member="$(repo_member "$WIF_NUMBER" "$repo")"
}

for repo in "${AI_REVIEW_REPOS[@]}"; do
  bind_repo github-ai-review "$repo"
done
bind_repo github-deploy-dev sujho
bind_repo github-deploy-preprod sujho
bind_repo github-deploy-prod sujho
bind_repo github-eval sujho

# --- what each SA may do in GCP (the trust boundary) ---

run gcloud secrets add-iam-policy-binding ai-review-anthropic-key \
  --project="$WIF_PROJECT" \
  --member="serviceAccount:$(sa_email github-ai-review)" \
  --role="roles/secretmanager.secretAccessor"

# Dev deploy: build and run only inside sujho-dev. Zero roles on Pre-Prod and Prod.
# GitHub SA does not push images — Cloud Build's SA does.
run gcloud projects add-iam-policy-binding "$DEV_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-dev)" \
  --role="roles/cloudbuild.builds.editor"
run gcloud projects add-iam-policy-binding "$DEV_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-dev)" \
  --role="roles/run.developer"
run gcloud artifacts repositories add-iam-policy-binding services \
  --location="$REGION" \
  --project="$DEV_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-dev)" \
  --role="roles/artifactregistry.reader"

# Pre-Prod deploy: submit Cloud Build in sujho-dev (Kaniko writes the
# registry). Deploy/execute in sujho-preprod. Zero roles on Prod.
# GitHub SA does not push images — Cloud Build's SA does.
run gcloud projects add-iam-policy-binding "$DEV_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-preprod)" \
  --role="roles/cloudbuild.builds.editor"
run gcloud projects add-iam-policy-binding "$PREPROD_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-preprod)" \
  --role="roles/run.developer"
run gcloud artifacts repositories add-iam-policy-binding services \
  --location="$REGION" \
  --project="$DEV_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-preprod)" \
  --role="roles/artifactregistry.reader"

# Prod deploy: deploy-only in prod, pull images. Zero roles on Pre-Prod.
run gcloud projects add-iam-policy-binding "$PROD_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-prod)" \
  --role="roles/cloudbuild.builds.editor"
run gcloud projects add-iam-policy-binding "$PROD_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-prod)" \
  --role="roles/run.developer"
run gcloud artifacts repositories add-iam-policy-binding services \
  --location="$REGION" \
  --project="$DEV_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-prod)" \
  --role="roles/artifactregistry.reader"

for secret in eval-openai-key eval-gemini-key eval-neo4j-uri eval-neo4j-user eval-neo4j-password; do
  run gcloud secrets add-iam-policy-binding "$secret" \
    --project="$WIF_PROJECT" \
    --member="serviceAccount:$(sa_email github-eval)" \
    --role="roles/secretmanager.secretAccessor"
done

# Runtime SAs the deploy identity must be allowed to act as (Cloud Run --service-account).
# Repeat per service runtime SA. knowledge-store is the jobs example.
run gcloud iam service-accounts add-iam-policy-binding \
  "knowledge-store-run@${DEV_PROJECT}.iam.gserviceaccount.com" \
  --project="$DEV_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-dev)" \
  --role="roles/iam.serviceAccountUser"
run gcloud iam service-accounts add-iam-policy-binding \
  "knowledge-store-run@${PREPROD_PROJECT}.iam.gserviceaccount.com" \
  --project="$PREPROD_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-preprod)" \
  --role="roles/iam.serviceAccountUser"
run gcloud iam service-accounts add-iam-policy-binding \
  "knowledge-store-run@${PROD_PROJECT}.iam.gserviceaccount.com" \
  --project="$PROD_PROJECT" \
  --member="serviceAccount:$(sa_email github-deploy-prod)" \
  --role="roles/iam.serviceAccountUser"

echo
echo "Do NOT grant github-deploy-dev any role on ${PREPROD_PROJECT} or ${PROD_PROJECT}."
echo "Do NOT grant github-deploy-preprod any role on ${PROD_PROJECT}."
echo "Do NOT grant github-deploy-prod any role on ${PREPROD_PROJECT}."
echo "Do NOT grant github-ai-review or github-eval Cloud Run / Cloud Build."
echo
echo "After a Lead runs --apply, set GitHub Variables by hand (Settings → Actions → Variables)."
echo "Never GitHub Secrets for these. Never paste keys."
echo
echo "  On every AI-review repo:"
echo "    GCP_WIF_PROVIDER=$(provider_resource "$WIF_NUMBER")"
echo "    GCP_WIF_SERVICE_ACCOUNT_AI_REVIEW=$(sa_email github-ai-review)"
echo
echo "  On ${GITHUB_ORG}/sujho (deploy + eval + promotion):"
echo "    GCP_WIF_PROVIDER=$(provider_resource "$WIF_NUMBER")"
echo "    GCP_WIF_SERVICE_ACCOUNT_DEV=$(sa_email github-deploy-dev)"
echo "    GCP_WIF_SERVICE_ACCOUNT_PREPROD=$(sa_email github-deploy-preprod)"
echo "    GCP_WIF_SERVICE_ACCOUNT_PROD=$(sa_email github-deploy-prod)"
echo "    GCP_WIF_SERVICE_ACCOUNT_EVAL=$(sa_email github-eval)"
echo
echo "Do not set a single GCP_WIF_SERVICE_ACCOUNT that can reach both Pre-Prod and Prod."
echo "iam.serviceAccountUser is listed for knowledge-store-run only — add the other Cloud Run runtime SAs the same way."
echo "Done."
