#!/usr/bin/env bash
# Local by default. --remote reads GitHub (no writes).
# Remote CODEOWNERS is judged by validate.py --check-stdin, the same rules
# as the local test suite.
#
# Usage: see usage() below — ./verify-phase1.sh [--remote]
# Arguments: --remote — also check GitHub (read-only); default is local-only.
# Exit codes: 0 ok; 1 unknown argument, or (via die) remote verification found
#   a failure.

usage() {
  cat <<'EOF'
  ./verify-phase1.sh           # validate.py only (no GitHub)
  ./verify-phase1.sh --remote  # CODEOWNERS + main + branch-naming rulesets, no extra branch rulesets
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

# Compares a live ruleset against the local JSON apply-phase1.sh installed:
# same branches targeted, every rule type still present, every rule
# parameter unchanged. bypass=exact also requires the single
# OrganizationAdmin:pull_request actor.
ruleset_matches() {
  local remote="$1" local_json="$2" bypass="$3"
  python3 - "$remote" "$local_json" "$bypass" <<'PY'
import json, sys

remote = json.load(open(sys.argv[1]))
want = json.load(open(sys.argv[2]))
bypass_mode = sys.argv[3]
errors = []

def rules(data):
    return {r["type"]: r.get("parameters", {}) for r in data.get("rules", [])}

def same(got, value):
    if isinstance(value, list):
        return sorted(got or []) == sorted(value)
    return got == value

have_refs = remote.get("conditions", {}).get("ref_name", {})
for key, value in want["conditions"]["ref_name"].items():
    if not same(have_refs.get(key), value):
        errors.append(f"ref_name.{key} is {have_refs.get(key)!r}, want {value!r}")

have_rules, want_rules = rules(remote), rules(want)
for rule_type, params in want_rules.items():
    if rule_type not in have_rules:
        errors.append(f"rule {rule_type} missing")
        continue
    for key, value in params.items():
        got = have_rules[rule_type].get(key)
        if not same(got, value):
            errors.append(f"{rule_type}.{key} is {got!r}, want {value!r}")

if "bypass_actors" not in remote:
    print("warn: bypass_actors hidden (need admin to confirm hotfix bypass)", file=sys.stderr)
else:
    actors = [(a.get("actor_type"), a.get("bypass_mode")) for a in remote["bypass_actors"] or []]
    if any(mode == "always" for _, mode in actors):
        errors.append("allows always (direct-push) bypass")
    elif bypass_mode == "exact" and actors and actors != [("OrganizationAdmin", "pull_request")]:
        errors.append(f"bypass {actors}, want OrganizationAdmin:pull_request")

for error in errors:
    print(error, file=sys.stderr)
sys.exit(1 if errors else 0)
PY
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
  if ruleset_matches "${WORKDIR}/main.json" "${PHASE1_DIR}/rulesets/main.json" exact; then
    echo "ok   ${REPO}: main ruleset matches rulesets/main.json, no always-bypass"
  else
    echo "FAIL ${REPO}: ruleset parameters do not match Phase 1"
    fail=1
  fi
  naming_id="$(ruleset_id "$REPO" "Sujho Phase 1 — branch naming")"
  if [ -z "$naming_id" ]; then
    echo "FAIL ${REPO}: branch naming ruleset missing"
    fail=1
    continue
  fi
  gh api "repos/${ORG}/${REPO}/rulesets/${naming_id}" > "${WORKDIR}/naming.json"
  if ruleset_matches "${WORKDIR}/naming.json" "${PHASE1_DIR}/rulesets/branch-naming.json" any; then
    echo "ok   ${REPO}: branch naming ruleset matches rulesets/branch-naming.json"
  else
    echo "FAIL ${REPO}: branch naming ruleset does not match rulesets/branch-naming.json"
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
  if ruleset_matches "${WORKDIR}/lt.json" "${PHASE1_DIR}/rulesets/light-touch-main.json" any; then
    echo "ok   ${REPO}: light-touch ruleset matches rulesets/light-touch-main.json"
  else
    echo "FAIL ${REPO}: light-touch ruleset does not match rulesets/light-touch-main.json"
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  die "remote Phase 1 verification failed"
fi
echo "remote Phase 1 verification passed. Next: ./prove-phase1.sh"
