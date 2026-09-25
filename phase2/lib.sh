# Phase 2 extras. Source after phase1/lib.sh.

PHASE2_REPO="sujho"
PHASE2_BRANCH="chore/phase2-promotion"
PHASE2_PILOT="redirect"
PHASE2_SKIP_PREREQ=0
PHASE2_ALL=0

# Every file this phase puts on Sujho/sujho, dest path -> local source path.
# No generators: these are the actual files, committed as-is.
PHASE2_FILE_MAP=(
  "ci/services.json:${BASH_SOURCE%/*}/ci/services.json"
  "ci/build-deploy.yaml:${BASH_SOURCE%/*}/ci/build-deploy.yaml"
  "ci/deploy-only.yaml:${BASH_SOURCE%/*}/ci/deploy-only.yaml"
  "ci/checkout-gitlinks.py:${BASH_SOURCE%/*}/ci/checkout-gitlinks.py"
  "ci/gates/verify_revision.py:${BASH_SOURCE%/*}/ci/gates/verify_revision.py"
  "ci/gates/mypy_ratchet.py:${BASH_SOURCE%/*}/ci/gates/mypy_ratchet.py"
  "ci/gates/resolve_baseline.py:${BASH_SOURCE%/*}/ci/gates/resolve_baseline.py"
  "ci/cleanup-policy.json:${BASH_SOURCE%/*}/ci/cleanup-policy.json"
  "ci/job-build-deploy.yaml:${BASH_SOURCE%/*}/ci/job-build-deploy.yaml"
  "ci/job-deploy-only.yaml:${BASH_SOURCE%/*}/ci/job-deploy-only.yaml"
  "scripts/rollback-cloudrun.sh:${BASH_SOURCE%/*}/scripts/rollback-cloudrun.sh"
  "scripts/pick_rollback_revision.py:${BASH_SOURCE%/*}/scripts/pick_rollback_revision.py"
  ".github/workflows/cloud-run-preprod-service.yaml:${BASH_SOURCE%/*}/workflows/cloud-run-preprod-service.yaml"
  ".github/workflows/cloud-run-prod-service.yaml:${BASH_SOURCE%/*}/workflows/cloud-run-prod-service.yaml"
  ".github/workflows/cloud-run-preprod-rollback.yaml:${BASH_SOURCE%/*}/workflows/cloud-run-preprod-rollback.yaml"
  ".github/workflows/cloud-run-prod-rollback.yaml:${BASH_SOURCE%/*}/workflows/cloud-run-prod-rollback.yaml"
  "jobs/catalog.jobs.json:${BASH_SOURCE%/*}/jobs/catalog.jobs.json"
  "jobs/scripts/lookup_job.py:${BASH_SOURCE%/*}/jobs/scripts/lookup_job.py"
  ".github/workflows/cloud-run-preprod-job.yaml:${BASH_SOURCE%/*}/jobs/workflows/cloud-run-preprod-deploy.yaml"
  ".github/workflows/cloud-run-prod-job.yaml:${BASH_SOURCE%/*}/jobs/workflows/cloud-run-prod-deploy.yaml"
  "IAM-table.md:${BASH_SOURCE%/*}/IAM-table.md"
  ".github/PULL_REQUEST_TEMPLATE.md:${BASH_SOURCE%/*}/../.github/PULL_REQUEST_TEMPLATE.md"
  ".github/dependabot.yml:${BASH_SOURCE%/*}/../.github/dependabot.yml"
)
