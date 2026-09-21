#!/usr/bin/env bash
# Local by default. --remote reads GitHub (no writes).
# Remote CODEOWNERS is judged by validate.py --check-stdin, the same rules
# as the local test suite.

usage() {
  cat <<'EOF'
  ./verify-phase1.sh           # validate.py only (no GitHub)
  ./verify-phase1.sh --remote  # CODEOWNERS + main ruleset + no extra branch rulesets
EOF
}

# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

REMOTE=0
for arg in "$@"; do
  case "$arg" in
    --remote) REMOTE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg (allowed: --remote)" ;;
  esac
done

python3 "${PHASE1_DIR}/validate.py"

if [ "$REMOTE" -eq 0 ]; then
  echo "local invariants ok. re-run with --remote after a Lead applies."
  exit 0
fi

fail=0
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/phase1-verify.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

ruleset_id() {
  local repo="$1" ruleset_name="$2"
  gh api "repos/${ORG}/${repo}/rulesets" --jq \
    ".[] | select(.name==\"${ruleset_name}\") | .id" | head -n1
}

echo "--- CODEOWNERS on main (shared validator) ---"
for REPO in "${FULL_TREATMENT_REPOS[@]}"; do
  body="$(codeowners_body_on_ref "$REPO" main)"
  if [ -z "$body" ]; then
    echo "FAIL ${REPO}@main: missing ${CODEOWNERS_DEST}"
    fail=1
    continue
  fi
  if printf '%s' "$body" | python3 "${PHASE1_DIR}/validate.py" --check-stdin; then
    echo "ok   ${REPO}@main"
  else
    echo "FAIL ${REPO}@main: CODEOWNERS failed validate.py --check-stdin"
    fail=1
  fi
done

echo "--- full-treatment rulesets ---"
for REPO in "${FULL_TREATMENT_REPOS[@]}"; do
  main_id="$(ruleset_id "$REPO" "Sujho Phase 1 — protect main")"
  dev_id="$(ruleset_id "$REPO" "Sujho Phase 1 — protect dev")"
  pre_id="$(ruleset_id "$REPO" "Sujho Phase 1 — protect pre-prod")"
  if [ -n "$dev_id" ]; then
    echo "FAIL ${REPO}: GitHub dev ruleset still exists (#${dev_id}) — delete it"
    fail=1
  fi
  if [ -n "$pre_id" ]; then
    echo "FAIL ${REPO}: GitHub pre-prod ruleset still exists (#${pre_id}) — delete it"
    fail=1
  fi
  if [ -z "$main_id" ]; then
    echo "FAIL ${REPO}: main ruleset missing"
    fail=1
    continue
  fi
  gh api "repos/${ORG}/${REPO}/rulesets/${main_id}" > "${WORKDIR}/main.json"
  if python3 - "${WORKDIR}/main.json" <<'PY'
import json, sys

def load(path):
    return json.loads(open(path).read())

def pr(data):
    for rule in data["rules"]:
        if rule.get("type") == "pull_request":
            return rule["parameters"]
    sys.exit("no pull_request rule")

def bypass(data):
    if "bypass_actors" not in data:
        return None
    return [(a.get("actor_type"), a.get("bypass_mode")) for a in data.get("bypass_actors") or []]

main = load(sys.argv[1])
m_pr = pr(main)
ok = (
    m_pr.get("require_code_owner_review") is True
    and m_pr.get("allowed_merge_methods") == ["merge"]
)
if not ok:
    print("pull_request parameters mismatch", file=sys.stderr)
    sys.exit(1)

m_actors = bypass(main)
if m_actors is None:
    print("warn main: bypass_actors hidden (need admin to confirm hotfix bypass)", file=sys.stderr)
elif any(mode == "always" for _, mode in m_actors):
    print("main allows always (direct-push) bypass", file=sys.stderr)
    sys.exit(1)
elif m_actors and m_actors != [("OrganizationAdmin", "pull_request")]:
    print(f"main bypass {m_actors}, want OrganizationAdmin:pull_request", file=sys.stderr)
    sys.exit(1)
PY
  then
    echo "ok   ${REPO}: Code Owners on main, merge-only, no always-bypass"
  else
    echo "FAIL ${REPO}: ruleset parameters do not match Phase 1"
    fail=1
  fi
done

echo "--- light-touch rulesets ---"
for REPO in "${LIGHT_TOUCH_REPOS[@]}"; do
  id="$(ruleset_id "$REPO" "Sujho Phase 1 — protect main (light-touch)")"
  if [ -z "$id" ]; then
    echo "FAIL ${REPO}: light-touch ruleset missing"
    fail=1
    continue
  fi
  gh api "repos/${ORG}/${REPO}/rulesets/${id}" > "${WORKDIR}/lt.json"
  if python3 - "${WORKDIR}/lt.json" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1]).read())
pr = next(r["parameters"] for r in data["rules"] if r.get("type") == "pull_request")
if pr.get("require_code_owner_review"):
    sys.exit(1)
if any(a.get("bypass_mode") == "always" for a in data.get("bypass_actors") or []):
    sys.exit(1)
PY
  then
    echo "ok   ${REPO}: PR required, Code Owners off"
  else
    echo "FAIL ${REPO}: light-touch ruleset is too strict or allows always-bypass"
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  die "remote Phase 1 verification failed"
fi
echo "remote Phase 1 verification passed. Next: ./prove-phase1.sh"
