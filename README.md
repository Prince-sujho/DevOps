# Sujho DevOps Plan

Code gets checked, built, tested on a practice version,
then sent to real users only with a senior's OK, every step a person
decides, nothing automatic. Meant to be read, not run.

## Rollout order

phase0, then phase1/phase2 — not interchangeable. phase1 and phase2 are
written for phase0's merged, single-checkout layout; `build-deploy.yaml`'s
folder paths (`redirect_service/app/Dockerfile` etc.) don't exist on the
current live repo (still 9 separate repos). Test phase0 against a separate
cloned copy only — `phase0/apply-phase0.sh --output DIR` already does this,
never against `Sujho/sujho` directly.

## phase0 — merge the 8 backend repos into one

Do this first — phase1-3 below already assume it's landed (single
checkout, no gitlinks). Fixes a real live bug: every `ci/*-deploy.yaml`
fetches 3 repos per build, each pinned to `revision: main` — the
service/infra dependency floats past whatever SHA `sujho` actually
recorded. Merging collapses that to 1 fetch, 1 SHA, no float.
`www`/`design_system`/`docs` stay separate.

- `phase0/repos.json` — the 8 repos and their target subdirectories
- `phase0/merge_repos.py` — clone → `filter-repo` → merge; can't push, structurally
- `phase0/collapse_ci_gitsource.py` — collapses a deploy YAML's gitSource blocks to 1
- `phase0/apply-phase0.sh` — `--output DIR` plans; `--output DIR --apply` runs it, locally only
- `phase0/verify-phase0.sh` — checks a merged tree is correct; `--remote` re-checks GitHub read-only
- `phase0/validate.py` — unit tests for the transform logic
- `phase0/docs-drafts/` — rewritten `monorepo.md`/`deployment.md`/`getting-started.md`
  for `Sujho/docs`, drafted locally against the real current text. Not pushed.

Scripts run and verified against real clones of all 9 repos. Nothing pushed
or applied anywhere — that's a separate, later decision.

## phase1 — who can merge

Only a senior person can let code in, and they can't approve their own work.

- `CODEOWNERS` — only the two Leads can approve
- `apply-phase1.sh` — turns the rule on in GitHub
- `verify-phase1.sh` — checks it actually applied
- `prove-phase1.sh` — proves the rule can't be bypassed (pilot: `sujho` itself)
- `validate.py` — checks the logic locally
- `lib.sh` — shared code the scripts above use

Assumes phase0's merge already landed: the full-treatment list is just
`sujho` + `sujho-ops-mcp`; light-touch is `design-system`/`docs`/`hiring`/`www`.
The 8 backend repos aren't listed separately — they're folders inside
`sujho` now, already covered by its own CODEOWNERS catch-all rule. Like
phase2, this is a design, not yet applied to any real repo (verified —
no repo has a phase1 CODEOWNERS file or ruleset today).

## phase2 — build, deploy, rollback

Building the code, testing it safely, getting sign-off, sending it to
real users, undoing it if something breaks.

- `ci/services.json` — settings per service (memory, CPU, timeout)
- `ci/build-deploy.yaml` — builds + deploys to Pre-Prod, runs the 3 checks first
- `ci/deploy-only.yaml` — promotes the same image to Prod, no rebuild
- `ci/gates/mypy_ratchet.py` — type-error count can't go up
- `ci/gates/resolve_baseline.py` — reads what's currently live, compares against that, not a PR
- `ci/gates/verify_revision.py` — confirms a deploy is healthy before it takes traffic
- `workflows/*.yaml` — the actual "click here to deploy / roll back" buttons
- `scripts/rollback-cloudrun.sh`, `pick_rollback_revision.py` — roll back to the last version that really worked
- `scripts/provision-projects.sh`, `provision-wif.sh`, `developer-connect-setup.sh` — one-time GCP setup
- `IAM-table.md` — exactly who/what gets which access, done by hand
- `jobs/` — same system as above, for background jobs instead of live services

Note: this pipeline is a design, not yet applied to the real `Sujho/sujho`
repo. Assumes phase0's merge — no multi-repo fetch step, one checkout only.

No image/commit retention policy — decided, not an oversight: the old
policy (keep 30, delete after 90 days) protected nothing, since the
`prod-live` tag it anchored to was correctly removed. Simplest fix: nothing
auto-deletes. Enforced by `phase2/validate.py`'s `CleanupPolicyTests`.

## phase3 — weekly health check (off for now)

A weekly report. Doesn't stop or approve anything — just tells us later
if something's quietly wrong.

- `workflows/mutation.yml`, `scripts/mutation_report.py` — checks if our tests would actually catch a bug
- `workflows/eval-replay.yml`, `scripts/eval_replay.py` — checks the AI hasn't quietly gotten worse
- `apply-phase3.sh`, `verify-phase3.sh`, `validate.py`, `lib.sh` — same setup/check pattern as the other phases

## Coding standard

Function length target 20 / hard limit 40. Line length target 80 / hard
limit 100. Every function docstring'd (Args/Returns/Raises), every shell
script header'd (usage/arguments/exit codes).

- Hard limits: fully met, Python and shell, repo-wide.
- Python line length: 3 lines still over 80 (unfixable without renaming
  the test they're named after).
- Python function length: 81 functions still over 20 — mostly generated
  Eval-Suite test-case data and long single-scenario tests with no real
  sub-step to extract.
- Shell: hard limits met, but the 80-char/20-line *targets* were never
  worked — 89 lines over 80, 2 functions over 20.

## Other folders

- `tests` — 160 tests across unit/api/integration/e2e (the guardrail
  baseline in `tests/outcomes/pytest/collected.json`), plus 10 more in
  `knowledge_store` (Docker-only, not in that count). All passing except
  one known Firestore-emulator limitation, not a product bug.
- `Eval-Suite` — checks on how well the AI parts behave. Not decided yet if it's part of this plan.
  **Do not run `Eval-Suite/run.py` from this repo** — it calls live models
  and spends real money (see `Eval-Suite/COPIED_FROM.txt`). Its own unit
  tests (`pytest Eval-Suite/tests`) are safe. Phase 3's weekly job is the
  only intended caller, on `sujho`, with spend limits set at the provider.

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
~30s on a laptop. ~3–7.5 min on the Pre-Prod pipeline (mostly container
setup, not the tests) — an estimate; `sujho-preprod` doesn't exist yet.

## What's still left — Arnav, this is for you

- `sujho-preprod` doesn't exist yet as a project.
- IAM roles aren't granted anywhere — table's written, nobody's applied it.
- Pre-Prod databases, secrets, a test WhatsApp number don't exist.
- The Pre-Prod data pipeline (anonymised copy of Prod, one-way) isn't designed yet.
- Narrowing the Cloud Build identity (`prod-builder`) — designed, not scheduled.
- Phase 3's checks are ready but off — waiting on the test suite being
  committed to the real repo and a runner machine existing.
- `knowledge_store`'s 10 Docker/Neo4j tests pass locally, aren't wired into
  either pipeline (no Docker daemon in Cloud Build's containers yet).
- Phase 2's pipeline design has never been applied to the real repo — it
  now assumes phase0's merge already landed (single checkout, no gitlinks).
- Phase0 is scripted and verified locally; not run for real yet.
- Phase0's GCP-side trigger repointing isn't done — needs write access to
  real Cloud Build triggers, which is separate from anything in this repo.
- `phase2/pointer-bump/` is deleted — phase0 removes the multi-repo split
  it patched around.
- This repo's own `tests/`/`Eval-Suite`/`pyproject.toml` were never landed
  in the real `Sujho/sujho` repo — separate decision, not blocked by phase0.
