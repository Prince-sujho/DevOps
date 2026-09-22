#!/usr/bin/env bash
# Phase 4: SHA-pinned deps, GCP projects, split Cloud Build, dispatch forms.
# Default: validate + plan for the redirect-service pilot. No GitHub, no GCP.
# Configs land in the sujho monorepo via a PR into `main`.

usage() {
  cat <<'EOF'
  ./apply-phase4.sh                 # validate + plan; redirect pilot only
  ./apply-phase4.sh --all           # plan every Cloud Run split (still dry-run)
  ./apply-phase4.sh --4b            # submodule pin check (needs a sujho checkout)
  ./apply-phase4.sh --4c            # print provision + Developer Connect steps
  ./apply-phase4.sh --4d            # plan the sujho/main PR
  ./apply-phase4.sh --apply --4c    # create sujho-dev / sujho-preprod (needs ORG_ID)
  ./apply-phase4.sh --apply --4d    # open the sujho PR into main

4a/path-filters are gone. Turn leftover push triggers off in Cloud Build.
Do not pass --all on the first apply. Pilot is redirect-service.
EOF
}

PHASE4_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE4_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE4_DIR}/lib.sh"

WANT_4B=0
WANT_4C=0
WANT_4D=0
EXPLICIT=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --4a) die "4a/path-filters are gone. Turn leftover push triggers off in the Cloud Build console." ;;
    --4b) WANT_4B=1; EXPLICIT=1 ;;
    --4c) WANT_4C=1; EXPLICIT=1 ;;
    --4d) WANT_4D=1; EXPLICIT=1 ;;
    --all) PHASE4_ALL=1 ;;
    --skip-prereq) PHASE4_SKIP_PREREQ=1 ;;
    --apply|-h|--help) ARGS+=("$arg") ;;
    *) die "unknown argument: $arg" ;;
  esac
done
if ! parse_apply_flag "${ARGS[@]+"${ARGS[@]}"}" ; then
  usage
  exit 0
fi

python3 "${PHASE4_DIR}/generate_cloudbuild.py" >/dev/null
python3 "${PHASE4_DIR}/generate_rollback.py" >/dev/null
python3 "${PHASE4_DIR}/generate_service_workflow.py" >/dev/null
python3 "${PHASE4_DIR}/generate_approve.py" >/dev/null
python3 "${PHASE4_DIR}/jobs/generate_job_workflow.py" >/dev/null
python3 "${PHASE4_DIR}/validate.py" || die "Phase 4 local invariants failed"
python3 "${PHASE4_DIR}/jobs/validate.py" || die "Phase 4 jobs local invariants failed"

services() {
  if [ "$PHASE4_ALL" -eq 1 ]; then
    python3 -c 'import json,pathlib; c=json.loads(pathlib.Path("'"${PHASE4_DIR}"'/catalog.json").read_text()); print(" ".join(s["id"] for s in c["services"]))'
  else
    echo "$PHASE4_PILOT"
  fi
}

if [ "$EXPLICIT" -eq 0 ]; then
  if [ "$APPLY" -eq 1 ]; then
    # --apply alone is the GitHub PR (4d). 4c mutates GCP — require --4c.
    WANT_4D=1
  else
    WANT_4B=1
    WANT_4C=1
    WANT_4D=1
  fi
fi

if [ "$APPLY" -eq 0 ]; then
  cat <<EOF
DRY-RUN (pass --apply to mutate GitHub or GCP)

Pilot: ${PHASE4_PILOT}   (pass --all to include every Cloud Run service)
Monorepo: ${ORG}/${PHASE4_REPO}  files land on a PR into \`main\`
Skip: firestore docker-split
No auto-deploy. Dispatch forms on sujho. Turn leftover push triggers off in Cloud Build (not this script).

EOF
fi

if [ "$WANT_4B" -eq 1 ]; then
  echo "--- 4b gitlink pins ---"
  SUJHO_ROOT="${SUJHO_ROOT:-}"
  if [ -n "$SUJHO_ROOT" ] && [ -f "${SUJHO_ROOT}/.gitmodules" ]; then
    "${PHASE4_DIR}/scripts/pin-submodules.sh" "$SUJHO_ROOT"
  else
    echo "no SUJHO_ROOT; checking generated YAML only (no revision: main, no --remote)"
    if grep -R --include='*.yaml' -n 'revision: main' "${PHASE4_DIR}/ci" >/dev/null; then
      die "generated YAML still has revision: main"
    fi
    echo "ok: generated YAML does not float gitSource at main"
  fi
fi

if [ "$WANT_4C" -eq 1 ]; then
  echo "--- 4c projects + Developer Connect ---"
  if [ "$APPLY" -eq 1 ]; then
    "${PHASE4_DIR}/scripts/provision-projects.sh" --apply
  else
    echo "provision-projects.sh needs ORG_ID and BILLING_ACCOUNT_ID (refuses placeholders)."
    echo "provision-wif.sh needs GITHUB_OWNER_ID (numeric org id; refuses placeholders)."
    echo "developer-connect-setup.sh prints commands only:"
    "${PHASE4_DIR}/scripts/developer-connect-setup.sh"
    echo "WIF (dry-run; does not call gcloud unless --apply on provision-wif.sh later):"
    echo "  GITHUB_OWNER_ID=<digits> ${PHASE4_DIR}/scripts/provision-wif.sh"
  fi
fi

if [ "$WANT_4D" -eq 0 ]; then
  exit 0
fi

echo "--- 4d split configs ---"
ids="$(services)"
echo "services: ${ids}"

if [ "$APPLY" -eq 0 ]; then
  echo "Would open PR ${ORG}/${PHASE4_REPO} ${PHASE4_BRANCH} -> main with:"
  echo "  ci/checkout-gitlinks.py"
  echo "  scripts/tag-on-approval.sh"
  echo "  scripts/rollback-cloudrun.sh"
  echo "  scripts/pick_rollback_revision.py"
  echo "  jobs/scripts/lookup_job.py"
  echo "  jobs/catalog.jobs.json"
  echo "  ci/jobs/job-build-deploy.yaml"
  echo "  ci/jobs/job-deploy-only.yaml"
  echo "  jobs/manifests/*/job.json"
  echo "  .github/workflows/cloud-run-preprod-rollback.yaml"
  echo "  .github/workflows/cloud-run-prod-rollback.yaml"
  echo "  .github/workflows/cloud-run-preprod-service.yaml"
  echo "  .github/workflows/cloud-run-prod-service.yaml"
  echo "  .github/workflows/approve-preprod.yaml"
  echo "  .github/workflows/cloud-run-preprod-deploy.yaml"
  echo "  .github/workflows/cloud-run-prod-deploy.yaml"
  for id in $ids; do
    echo "  ci/${id}-build-deploy.yaml"
    echo "  ci/${id}-deploy-only.yaml"
  done
  echo "Refuses --apply unless sujho-dev exists or you pass --skip-prereq."
  exit 0
fi

if [ "$PHASE4_SKIP_PREREQ" -eq 0 ]; then
  if ! gcloud projects describe sujho-dev >/dev/null 2>&1; then
    die "sujho-dev does not exist (4c first), or pass --skip-prereq to open the GitHub PR anyway"
  fi
fi

put_file() {
  local dest="$1" src="$2" branch="$3" message="$4"
  local b64 existing
  b64="$(python3 -c 'import base64, pathlib, sys; print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())' "$src")"
  existing="$(gh api "repos/${ORG}/${PHASE4_REPO}/contents/${dest}?ref=${branch}" --jq .sha 2>/dev/null || true)"
  local args=(gh api -X PUT "repos/${ORG}/${PHASE4_REPO}/contents/${dest}"
    -f message="$message" -f content="$b64" -f branch="$branch")
  if [ -n "$existing" ]; then
    args+=(-f sha="$existing")
  fi
  "${args[@]}" >/dev/null
}

ensure_branch_from() {
  local branch="$1" from="$2"
  local sha
  sha="$(ref_sha "$PHASE4_REPO" "$from")"
  [ -n "$sha" ] || die "${PHASE4_REPO}: no ${from}"
  if [ -z "$(ref_sha "$PHASE4_REPO" "$branch")" ]; then
    gh api "repos/${ORG}/${PHASE4_REPO}/git/refs" -f ref="refs/heads/${branch}" -f sha="$sha" >/dev/null
  fi
}

ensure_branch_from "$PHASE4_BRANCH" main
put_file "ci/checkout-gitlinks.py" "${PHASE4_DIR}/ci/checkout-gitlinks.py" "$PHASE4_BRANCH" \
  "Phase 4: checkout service and infra at gitlink SHAs."
put_file "scripts/tag-on-approval.sh" "${PHASE4_DIR}/scripts/tag-on-approval.sh" "$PHASE4_BRANCH" \
  "Phase 4: stamp preprod-approved for one image after a Lead tested it."
put_file "scripts/rollback-cloudrun.sh" "${PHASE4_DIR}/scripts/rollback-cloudrun.sh" "$PHASE4_BRANCH" \
  "Phase 4: shift Cloud Run traffic to a previous revision."
put_file "scripts/pick_rollback_revision.py" "${PHASE4_DIR}/scripts/pick_rollback_revision.py" "$PHASE4_BRANCH" \
  "Phase 4: refuse unverified newer revisions on empty rollback."
put_file ".github/workflows/cloud-run-preprod-rollback.yaml" \
  "${PHASE4_DIR}/workflows/cloud-run-preprod-rollback.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Pre-Prod Cloud Run service rollback form."
put_file ".github/workflows/cloud-run-prod-rollback.yaml" \
  "${PHASE4_DIR}/workflows/cloud-run-prod-rollback.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Prod Cloud Run service rollback form."
put_file ".github/workflows/cloud-run-dev-service.yaml" \
  "${PHASE4_DIR}/workflows/cloud-run-dev-service.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Dev Cloud Run service deploy form (sujho-dev only)."
put_file ".github/workflows/cloud-run-dev-rollback.yaml" \
  "${PHASE4_DIR}/workflows/cloud-run-dev-rollback.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Dev Cloud Run service rollback form."
put_file ".github/workflows/cloud-run-preprod-service.yaml" \
  "${PHASE4_DIR}/workflows/cloud-run-preprod-service.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Pre-Prod Cloud Run service deploy form."
put_file ".github/workflows/cloud-run-prod-service.yaml" \
  "${PHASE4_DIR}/workflows/cloud-run-prod-service.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Prod Cloud Run service deploy form."
put_file ".github/workflows/approve-preprod.yaml" \
  "${PHASE4_DIR}/workflows/approve-preprod.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Lead stamps preprod-approved for one image."
put_file ".github/workflows/cloud-run-dev-deploy.yaml" \
  "${PHASE4_DIR}/jobs/workflows/cloud-run-dev-deploy.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Dev Cloud Run job deploy form (sujho-dev only)."
put_file ".github/workflows/cloud-run-preprod-deploy.yaml" \
  "${PHASE4_DIR}/jobs/workflows/cloud-run-preprod-deploy.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Pre-Prod Cloud Run job deploy form."
put_file ".github/workflows/cloud-run-prod-deploy.yaml" \
  "${PHASE4_DIR}/jobs/workflows/cloud-run-prod-deploy.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Prod Cloud Run job deploy form."
put_file "ci/jobs/job-build-deploy.yaml" \
  "${PHASE4_DIR}/jobs/templates/job-build-deploy.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Cloud Build job build+deploy (runs in sujho-dev)."
put_file "ci/jobs/job-deploy-only.yaml" \
  "${PHASE4_DIR}/jobs/templates/job-deploy-only.yaml" "$PHASE4_BRANCH" \
  "Phase 4: Cloud Build job deploy-only (same digest)."
put_file "jobs/scripts/lookup_job.py" \
  "${PHASE4_DIR}/jobs/scripts/lookup_job.py" "$PHASE4_BRANCH" \
  "Phase 4: read job.json for Cloud Build / execute."
put_file "jobs/catalog.jobs.json" \
  "${PHASE4_DIR}/jobs/catalog.jobs.json" "$PHASE4_BRANCH" \
  "Phase 4: Cloud Run job catalog."
for manifest in "${PHASE4_DIR}/jobs/manifests"/*/job.json; do
  id="$(basename "$(dirname "$manifest")")"
  put_file "jobs/manifests/${id}/job.json" "$manifest" "$PHASE4_BRANCH" \
    "Phase 4: Cloud Run job label ${id}."
done
for id in $ids; do
  put_file "ci/${id}-build-deploy.yaml" "${PHASE4_DIR}/ci/${id}-build-deploy.yaml" "$PHASE4_BRANCH" \
    "Phase 4: ${id} build+deploy (manual Cloud Build, sha tag, not latest)."
  put_file "ci/${id}-deploy-only.yaml" "${PHASE4_DIR}/ci/${id}-deploy-only.yaml" "$PHASE4_BRANCH" \
    "Phase 4: ${id} deploy-only (manual, same digest, Pre-Prod or Prod)."
done

n="$(gh pr list --repo "${ORG}/${PHASE4_REPO}" --base main --head "$PHASE4_BRANCH" --json number --jq '.[0].number' || true)"
if [ -n "$n" ]; then
  echo "${PHASE4_REPO}: Phase 4 PR already open (#${n})"
else
  gh pr create --repo "${ORG}/${PHASE4_REPO}" --base main --head "$PHASE4_BRANCH" \
    --title "Phase 4: split Cloud Build for $(echo $ids | tr ' ' ',')" \
    --body "Pilot-first. Manual Cloud Build per service. Pre-Prod builds run in sujho-dev. Build tags \`sha-<SHORT_SHA>\` (7 chars). Deploy-only resolves \`preprod-approved\`. Approve is one piece via approve-preprod. No auto-deploy, no \`:latest\`, no \`--set-env-vars\`."
fi
