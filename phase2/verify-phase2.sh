#!/usr/bin/env bash
# Local by default. --remote reads GitHub (no writes).
#
# Usage: see usage() below — ./verify-phase2.sh [--remote]
# Arguments: --remote — also check the files actually on sujho/main.
# Exit codes: 0 ok; 1 unknown argument, or (via die) remote verification found
#   a failure.
usage() {
  cat <<'EOF'
  ./verify-phase2.sh           # validate.py only
  ./verify-phase2.sh --remote  # also checks the files actually on sujho/main
EOF
}

PHASE2_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE2_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE2_DIR}/lib.sh"

REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --remote) REMOTE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg (allowed: --remote)" ;;
  esac
done

python3 "${PHASE2_DIR}/validate.py"
python3 "${PHASE2_DIR}/jobs/validate.py"

if [ "$REMOTE" -eq 0 ]; then
  echo "local invariants ok. --remote after the sujho PR merges to main."
  exit 0
fi

fail=0
for entry in "${PHASE2_FILE_MAP[@]}"; do
  f="${entry%%:*}"
  path="$(
    gh api "repos/${ORG}/${PHASE2_REPO}/contents/${f}?ref=main" --jq .path 2>/dev/null || true
  )"
  if [ -z "$path" ]; then
    echo "FAIL ${PHASE2_REPO}: missing on main ${f}"
    fail=1
  else
    echo "ok   ${f}"
  fi
done

body_of() {
  gh api "repos/${ORG}/${PHASE2_REPO}/contents/$1?ref=main" --jq .content 2>/dev/null \
    | python3 -c '
import sys, base64
d = sys.stdin.read().replace("\n", "")
print(base64.b64decode(d).decode() if d else "")
'
}

build_body="$(body_of ci/build-deploy.yaml)"
deploy_body="$(body_of ci/deploy-only.yaml)"

for label_body in "build-deploy:$build_body" "deploy-only:$deploy_body"; do
  label="${label_body%%:*}"
  body="${label_body#*:}"
  if echo "$body" | grep -q ':latest'; then
    echo "FAIL ${label} on main still tags :latest"
    fail=1
  fi
  if echo "$body" | grep -q -- '--set-env-vars'; then
    echo "FAIL ${label} on main uses --set-env-vars (must be --update-env-vars)"
    fail=1
  fi
  if echo "$body" | grep -q 'preprod-approved\|prod-live'; then
    echo "FAIL ${label} on main still references a removed approval tag"
    fail=1
  fi
  if echo "$body" | grep -q 'sujho-dev'; then
    echo "FAIL ${label} on main still touches sujho-dev (decision 13: sandbox only, no CI)"
    fail=1
  fi
done

# The rollback target is whatever the 'lkg' traffic tag points at, so a recipe
# that shifts traffic without repointing that tag leaves rollback aiming at a
# revision two releases old.
for label_body in "build-deploy:$build_body" "deploy-only:$deploy_body"; do
  label="${label_body%%:*}"
  body="${label_body#*:}"
  calls="$(echo "$body" | grep -c 'services update-traffic' || true)"
  if [ "$calls" != "1" ]; then
    echo "FAIL ${label} on main shifts traffic in ${calls} calls; want one"
    fail=1
  fi
  if ! echo "$body" | grep -q -- '--to-revisions='; then
    echo "FAIL ${label} on main does not shift traffic"
    fail=1
  fi
  if ! echo "$body" | grep -q -- '--update-tags='; then
    echo "FAIL ${label} on main does not move the lkg tag in that same call"
    fail=1
  fi
  if ! echo "$body" | grep -q -- '--remove-tags='; then
    echo "FAIL ${label} on main does not drop the build tag in that same call"
    fail=1
  fi
  if echo "$body" | grep -q 'run revisions update'; then
    echo "FAIL ${label} on main calls gcloud run revisions update, which does not exist"
    fail=1
  fi
  if echo "$body" | grep -q -- 'allow-unauthenticated'; then
    echo "FAIL ${label} on main sets IAM on deploy (builder has run.developer only)"
    fail=1
  fi
  if ! echo "$body" | grep -q -- '--expect-digest='; then
    echo "FAIL ${label} on main verifies without checking the running image digest"
    fail=1
  fi
done

prod_service_body="$(body_of .github/workflows/cloud-run-prod-service.yaml)"
if ! echo "$prod_service_body" | grep -q 'environment: production'; then
  echo "FAIL cloud-run-prod-service.yaml on main has no production Environment gate"
  fail=1
fi
prod_rollback_body="$(body_of .github/workflows/cloud-run-prod-rollback.yaml)"
if ! echo "$prod_rollback_body" | grep -q 'environment: production-rollback'; then
  echo "FAIL cloud-run-prod-rollback.yaml on main has no production-rollback Environment gate"
  fail=1
fi

# post-phase0, sujho is the only repo anyone merges into
for repo in sujho; do
  methods="$(
    gh api "repos/${ORG}/${repo}/rulesets" --jq \
      '.[] | select(.conditions.ref_name.include[]? == "refs/heads/main") | .id' \
      | while read -r id; do
          [ -n "$id" ] || continue
          gh api "repos/${ORG}/${repo}/rulesets/${id}" --jq \
            '.rules[]? | select(.type=="pull_request") | .parameters.allowed_merge_methods[]?'
        done | sort -u | tr '\n' ' '
  )"
  if echo "$methods" | grep -qw merge && ! echo "$methods" | grep -Eqw 'squash|rebase'; then
    echo "ok   ${repo} main: merge-only"
  elif [ -z "$methods" ]; then
    echo "note ${repo} main: no PR ruleset yet (Phase 1)"
  else
    echo "FAIL ${repo} main: must be merge-only (got: ${methods})"
    fail=1
  fi
done

# The Lead approval lives in GitHub Environment settings, not in any file, and
# GCP trusts these exact Environment names (phase2/scripts/provision-wif.sh).
# Read them back: reviewers must be set, and `production` must forbid
# self-review. production-rollback deliberately allows it (IAM-table.md, 4).
# Output is "<reviewer count> <prevent_self_review>", read-only.
environment_state() {
  gh api "repos/${ORG}/${PHASE2_REPO}/environments/$1" --jq '
    [.protection_rules[]? | select(.type=="required_reviewers")]
    | "\(map(.reviewers | length) | add // 0) \(map(.prevent_self_review) | any)"
  ' 2>/dev/null || echo "missing"
}

check_environment() {
  local name="$1" need_no_self_review="$2"
  local state count prevent
  state="$(environment_state "$name")"
  if [ "$state" = "missing" ]; then
    echo "FAIL Environment ${name}: does not exist on ${PHASE2_REPO}"
    fail=1
    return 0
  fi
  count="${state%% *}"
  prevent="${state##* }"
  if [ "$count" -lt 1 ]; then
    echo "FAIL Environment ${name}: no required reviewers"
    fail=1
  elif [ "$need_no_self_review" = "1" ] && [ "$prevent" != "true" ]; then
    echo "FAIL Environment ${name}: 'Prevent self-review' is off"
    fail=1
  else
    echo "ok   Environment ${name}: ${count} reviewer(s), prevent-self-review=${prevent}"
  fi
}

check_environment production 1
check_environment production-rollback 0

# The Prod OIDC subject is environment:production, with no branch in it, so a
# Lead approving a run from any other branch gets the same identity. The
# limit has to be the Environment's own branch rule.
check_main_only() {
  local name="$1" policy branches
  policy="$(
    gh api "repos/${ORG}/${PHASE2_REPO}/environments/${name}" --jq '
      if .deployment_branch_policy == null then "all"
      elif .deployment_branch_policy.custom_branch_policies != true then "other"
      else "custom"
      end
    ' 2>/dev/null || echo "missing"
  )"
  if [ "$policy" != "custom" ]; then
    echo "FAIL Environment ${name}: deployments are not limited to selected branches"
    fail=1
    return 0
  fi
  branches="$(
    gh api "repos/${ORG}/${PHASE2_REPO}/environments/${name}/deployment-branch-policies" \
      --jq '[(.branch_policies // [])[].name] | join(" ")' 2>/dev/null || echo "missing"
  )"
  if [ "$branches" != "main" ]; then
    echo "FAIL Environment ${name}: deployment branches are '${branches}', want main"
    fail=1
  else
    echo "ok   Environment ${name}: deployments from main only"
  fi
}

check_main_only production
check_main_only production-rollback

if [ "$fail" -ne 0 ]; then
  die "remote Phase 2 verification failed"
fi
echo "remote Phase 2 verification passed"
