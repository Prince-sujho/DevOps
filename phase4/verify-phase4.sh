#!/usr/bin/env bash
usage() {
  cat <<'EOF'
  ./verify-phase4.sh           # validate.py only
  ./verify-phase4.sh --remote  # split YAML on sujho/main; no extra GitHub branches
EOF
}

PHASE4_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE4_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE4_DIR}/lib.sh"

REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --remote) REMOTE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg (allowed: --remote)" ;;
  esac
done

python3 "${PHASE4_DIR}/generate_cloudbuild.py" >/dev/null
python3 "${PHASE4_DIR}/generate_rollback.py" >/dev/null
python3 "${PHASE4_DIR}/generate_service_workflow.py" >/dev/null
python3 "${PHASE4_DIR}/generate_approve.py" >/dev/null
python3 "${PHASE4_DIR}/jobs/generate_job_workflow.py" >/dev/null
python3 "${PHASE4_DIR}/validate.py"
python3 "${PHASE4_DIR}/jobs/validate.py"

if [ "$REMOTE" -eq 0 ]; then
  echo "local invariants ok. --remote after the sujho PR merges to main."
  exit 0
fi

fail=0
for f in ci/checkout-gitlinks.py ci/${PHASE4_PILOT}-build-deploy.yaml ci/${PHASE4_PILOT}-deploy-only.yaml scripts/tag-on-approval.sh; do
  path="$(gh api "repos/${ORG}/${PHASE4_REPO}/contents/${f}?ref=main" --jq .path 2>/dev/null || true)"
  if [ -z "$path" ]; then
    echo "FAIL ${PHASE4_REPO}: missing on main ${f}"
    fail=1
  else
    echo "ok   ${f}"
  fi
done

body="$(gh api "repos/${ORG}/${PHASE4_REPO}/contents/ci/${PHASE4_PILOT}-build-deploy.yaml?ref=main" --jq .content 2>/dev/null \
  | python3 -c 'import sys,base64; d=sys.stdin.read().replace("\n",""); print(base64.b64decode(d).decode() if d else "")')"
if echo "$body" | grep -q ':latest'; then
  echo "FAIL build-deploy on main still contains :latest"
  fail=1
fi
if echo "$body" | grep -q -- '--set-env-vars'; then
  echo "FAIL build-deploy on main uses --set-env-vars"
  fail=1
fi
if echo "$body" | grep -q 'preprod-approved'; then
  echo "FAIL build-deploy on main writes preprod-approved"
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
  die "remote Phase 4 verification failed"
fi
echo "remote Phase 4 verification passed"
