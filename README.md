# Sujho DevOps Plan

Plan, not live. Code gets checked, built, tested on a practice version,
then sent to real users only with a senior's OK — every step a person
decides, nothing automatic. Meant to be read, not run.

## phase1 — who can merge

Only a senior person can let code in, and they can't approve their own work.

- `CODEOWNERS` — only the two Leads can approve
- `apply-phase1.sh` — turns the rule on in GitHub
- `verify-phase1.sh` — checks it actually applied
- `prove-phase1.sh` — proves the rule can't be bypassed
- `validate.py` — checks the logic locally
- `lib.sh` — shared code the scripts above use

## phase2 — build, deploy, rollback

Building the code, testing it safely, getting sign-off, sending it to
real users, undoing it if something breaks.

- `ci/services.json` — settings per service (memory, CPU, timeout)
- `ci/build-deploy.yaml` — builds + deploys to Pre-Prod, runs the 3 checks first
- `ci/deploy-only.yaml` — promotes the same image to Prod, no rebuild
- `ci/checkout-gitlinks.py` — pulls each repo at the exact commit, never "latest"
- `ci/cleanup-policy.json` — auto-deletes old images after 3 months
- `ci/gates/mypy_ratchet.py` — type-error count can't go up
- `ci/gates/resolve_baseline.py` — reads what's currently live, so checks compare against that, not a PR
- `ci/gates/verify_revision.py` — confirms a deploy is healthy before it takes traffic
- `workflows/*.yaml` — the actual "click here to deploy / roll back" buttons
- `scripts/rollback-cloudrun.sh`, `pick_rollback_revision.py` — roll back to the last version that really worked
- `scripts/provision-projects.sh`, `provision-wif.sh`, `developer-connect-setup.sh`, `pin-submodules.sh` — one-time GCP setup
- `IAM-table.md` — exactly who/what gets which access, done by hand
- `pointer-bump/` — auto-opens a PR when a service repo updates, so nothing gets forgotten
- `jobs/` — same system as above, for background jobs instead of live services

## phase3 — weekly health check (off for now)

A weekly report. Doesn't stop or approve anything — just tells us later
if something's quietly wrong.

- `workflows/mutation.yml`, `scripts/mutation_report.py` — checks if our tests would actually catch a bug
- `workflows/eval-replay.yml`, `scripts/eval_replay.py` — checks the AI hasn't quietly gotten worse
- `apply-phase3.sh`, `verify-phase3.sh`, `validate.py`, `lib.sh` — same setup/check pattern as the other phases

## Other folders

- `tests` — a copy of the checks that prove the product actually works
- `Eval-Suite` — a copy of the checks on how well the AI parts behave. Not decided yet if it's part of this plan.

## What's still left — Arnav, this is for you

This is the plan, not the finished system. Here's what's still open on
my end:

- `sujho-preprod` doesn't exist yet as a project.
- IAM roles aren't granted anywhere — I've written the table, nobody's
  worked through it by hand yet.
- Pre-Prod databases, secrets, and a test WhatsApp number don't exist.
- The Pre-Prod data pipeline (anonymised copy of Prod, one-way) isn't
  designed, let alone built.
- Narrowing the Cloud Build identity itself (`prod-builder`) — I've
  written the design, but nobody's decided when to actually do it.
- Phase 3's weekly checks (mutation testing + eval replay) are ready but
  switched off — waiting on the test suite being committed and a runner
  machine existing.
- None of this has been run against real GCP. Every recipe here has been
  checked for internal consistency, not proven to actually execute — that
  only happens once `sujho-preprod` exists and someone runs it for real.
