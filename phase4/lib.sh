# Phase 4 extras. Source after phase1/lib.sh.

PHASE4_REPO="sujho"
PHASE4_BRANCH="chore/phase4-promotion"
PHASE4_PILOT="redirect"
PHASE4_SKIP_PREREQ=0
PHASE4_ALL=0

# Configs live in the monorepo, not in each service repo.
PHASE4_SUJHO_FILES=(
  ci/checkout-gitlinks.py
  scripts/tag-on-approval.sh
)
