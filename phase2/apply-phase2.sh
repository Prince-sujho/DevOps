#!/usr/bin/env bash
# Promotion pipeline files — build/deploy recipes, service config, rollback,
# IAM table. Lands on Sujho/sujho via PR; nothing here deploys by itself.

usage() {
  cat <<'EOF'
  ./apply-phase2.sh              # validate locally, plan the sujho PR (dry-run)
  ./apply-phase2.sh --apply      # open the PR onto Sujho/sujho for real

This phase never touches sujho-dev, sujho-preprod, or sujho-478914 directly —
it only writes files to GitHub. The GCP-side setup (creating projects, IAM
grants, the production Environment) is IAM-table.md, followed by hand.
EOF
}

PHASE2_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../phase1/lib.sh
source "${PHASE2_DIR}/../phase1/lib.sh"
# shellcheck source=lib.sh
source "${PHASE2_DIR}/lib.sh"

for arg in "$@"; do
  case "$arg" in
    --apply|-h|--help) ;;
    *) die "unknown argument: $arg" ;;
  esac
done
if ! parse_apply_flag "$@"; then
  usage
  exit 0
fi

python3 "${PHASE2_DIR}/validate.py" || die "Phase 2 local invariants failed"
python3 "${PHASE2_DIR}/jobs/validate.py" || die "Phase 2 jobs local invariants failed"

if [ "$APPLY" -eq 0 ]; then
  echo "DRY-RUN (pass --apply to open the PR onto ${ORG}/${PHASE2_REPO})"
  echo
  echo "Would open PR ${ORG}/${PHASE2_REPO} ${PHASE2_BRANCH} -> main with:"
  for entry in "${PHASE2_FILE_MAP[@]}"; do
    echo "  ${entry%%:*}"
  done
  exit 0
fi

put_file() {
  local dest="$1" src="$2"
  [ -f "$src" ] || die "missing local file: $src"
  local b64 existing
  b64="$(python3 -c 'import base64, pathlib, sys; print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())' "$src")"
  existing="$(gh api "repos/${ORG}/${PHASE2_REPO}/contents/${dest}?ref=${PHASE2_BRANCH}" --jq .sha 2>/dev/null || true)"
  local args=(gh api -X PUT "repos/${ORG}/${PHASE2_REPO}/contents/${dest}"
    -f message="Phase 2: ${dest}" -f content="$b64" -f branch="$PHASE2_BRANCH")
  if [ -n "$existing" ]; then
    args+=(-f sha="$existing")
  fi
  "${args[@]}" >/dev/null
  echo "put ${dest}"
}

ensure_branch_from_main "$PHASE2_REPO" "$PHASE2_BRANCH" || true

for entry in "${PHASE2_FILE_MAP[@]}"; do
  put_file "${entry%%:*}" "${entry#*:}"
done

n="$(gh pr list --repo "${ORG}/${PHASE2_REPO}" --base main --head "$PHASE2_BRANCH" --json number --jq '.[0].number' || true)"
if [ -n "$n" ]; then
  echo "${PHASE2_REPO}: Phase 2 PR already open (#${n}) — a Lead must merge it"
else
  gh pr create --repo "${ORG}/${PHASE2_REPO}" --base main --head "$PHASE2_BRANCH" \
    --title "Phase 2: promotion pipeline (Pre-Prod -> Prod, no auto-deploy)" \
    --body "One build recipe, one deploy-only recipe, one services.json. Prod deploy pauses on the production Environment instead of a separate approve step. Warehouse lives in sujho-preprod, sujho-dev untouched. GCP-side setup: IAM-table.md, by hand."
fi
