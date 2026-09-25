#!/usr/bin/env bash
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
  path="$(gh api "repos/${ORG}/${PHASE2_REPO}/contents/${f}?ref=main" --jq .path 2>/dev/null || true)"
  if [ -z "$path" ]; then
    echo "FAIL ${PHASE2_REPO}: missing on main ${f}"
    fail=1
  else
    echo "ok   ${f}"
  fi
done

body_of() {
  gh api "repos/${ORG}/${PHASE2_REPO}/contents/$1?ref=main" --jq .content 2>/dev/null \
    | python3 -c 'import sys,base64; d=sys.stdin.read().replace("\n",""); print(base64.b64decode(d).decode() if d else "")'
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

if ! echo "$build_body" | grep -q 'served=true'; then
  echo "FAIL build-deploy on main does not label served=true"
  fail=1
fi
if ! echo "$deploy_body" | grep -q 'served=true'; then
  echo "FAIL deploy-only on main does not label served=true"
  fail=1
fi

prod_service_body="$(body_of .github/workflows/cloud-run-prod-service.yaml)"
if ! echo "$prod_service_body" | grep -q 'environment: production'; then
  echo "FAIL cloud-run-prod-service.yaml on main has no production Environment gate"
  fail=1
fi

for repo in sujho redirect-service; do
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

if [ "$fail" -ne 0 ]; then
  die "remote Phase 2 verification failed"
fi
echo "remote Phase 2 verification passed"
