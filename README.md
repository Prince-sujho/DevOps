# Sujho DevOps Plan

Code gets checked, built, tested on a practice version,
then sent to real users only with a senior's OK, every step a person
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
- `pointer-bump/` — auto-opens a PR when a service repo updates, so nothing gets forgotten. Template only — not copied into any service repo yet
- `jobs/` — same system as above, for background jobs instead of live services

## phase3 — weekly health check (off for now)

A weekly report. Doesn't stop or approve anything — just tells us later
if something's quietly wrong.

- `workflows/mutation.yml`, `scripts/mutation_report.py` — checks if our tests would actually catch a bug
- `workflows/eval-replay.yml`, `scripts/eval_replay.py` — checks the AI hasn't quietly gotten worse
- `apply-phase3.sh`, `verify-phase3.sh`, `validate.py`, `lib.sh` — same setup/check pattern as the other phases

## Other folders

- `tests` — 65 kept tests plus 19 added for `knowledge_store` (84 total).
  A few of those tests loop over a list (e.g. one test checks every route
  by itself, one by one) — running that one test does 71 checks, not 1.
  Add up all those checks and you get 170, but there are still 84 tests.
  All verified passing, except one known Firestore-emulator limitation,
  not a product bug.
- `Eval-Suite` — a copy of the checks on how well the AI parts behave. Not decided yet if it's part of this plan.

## How to run the tests

```bash
pip install -e ./infra -r tests/requirements.txt
pytest tests/unit tests/api      # no setup needed
pytest tests/integration         # needs gcloud + Java
pytest tests/e2e                 # needs gcloud + Java, run separately from integration
pytest tests/knowledge_store     # needs Docker; pip install its requirements-test.txt first
```
Before merging:
```bash
python3 tests/tooling/check_assertions.py
python3 tests/tooling/check_test_count.py
```
Takes ~30 seconds on a laptop. On the Pre-Prod pipeline, expect ~3–7.5
minutes — mostly a fresh container installing tools, not the tests
themselves. That's an estimate; never timed for real, `sujho-preprod`
doesn't exist yet.

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
- `knowledge_store`'s 10 Docker/Neo4j tests pass locally but aren't wired
  into either pipeline — Cloud Build's containers have no Docker daemon to
  reach. Needs a docker-enabled step or its own worker. Its other 9 tests
  now run for real in `job-build-deploy.yaml`'s gate — that pipeline no
  longer claims `knowledge_store` has zero tests.

