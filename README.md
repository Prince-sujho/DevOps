# Sujho DevOps Plan

Scripts here stay dry-run until `--apply`, and none has been applied to `Sujho/platform` yet. The GCP side (projects, accounts, grants, GitHub sign-in) is set up from Arnav's scripts; `phase2/IAM-table.md` records what is granted.

phase0 first, then phase1 and phase2. phase3 stays off.

1. The engineer tries the feature in `sujho-dev`. No CI.
2. Pull request on `Sujho/platform`. A Lead approves. Nothing runs on the pull request. Merge does not deploy.
3. Someone runs Pre-Prod from `main`, then tries it on the Pre-Prod phone.
4. A Lead runs Prod with that full SHA. There is no approval click: Google only accepts a production run that a Lead started. Same image, no rebuild.
5. Rollback moves traffic to the previous revision. No rebuild.

phase0 merges user-service, whatsapp-adapter, text-agent, document-worker, knowledge-store, admin, redirect-service, infra, and docs into one repo, `Sujho/platform` (docs lands as `docs/`). `www` and `design_system` stay out completely. `phase0/apply-phase0.sh --output DIR`.

phase1: Leads own `platform` and `sujho-ops-mcp`. Light touch: `design-system`, `hiring`, `www`. `phase1/apply-phase1.sh`.

phase2: Pre-Prod builds, Prod promotes the same image. Gates: ruff, mypy, semgrep, detect-secrets, the tests, `check_assertions.py`, `check_test_count.py`. Buttons in `phase2/workflows/`. Jobs in `phase2/jobs/`. IAM from `phase2/IAM-table.md`, by hand. Firestore rules/indexes deploy on their own recipe and buttons (`phase2/ci/firestore-deploy.yaml`, `phase2/workflows/firestore-preprod.yaml`, `phase2/workflows/firestore-prod.yaml`) — built, not yet run against real GCP.

phase3: weekly mutation and eval reports. Off until configured. Do not run `Eval-Suite/run.py` here.

Python 3.12+. `phase0/collapse_ci_gitsource.py` and `phase3/validate.py` do not run on 3.9.

In the merged repo:

```bash
pip install -e ./infra -r tests/requirements.txt
pytest tests/unit tests/api
pytest tests/integration   # gcloud + Java
pytest tests/e2e           # gcloud + Java, separate from integration
```

`tests/knowledge_store` needs Docker and is not in the gate.

## What's still left — Arnav

None of this repo's scripts has been applied.

- Pre-Prod runtime accounts have no runtime grants yet (the Part 7 grants in `phase2/IAM-table.md`), and the `analytics-*` accounts are not granted (Session 3b).
- The Firestore deploy needs `roles/datastore.indexAdmin` and `roles/firebaserules.admin` for `prod-builder` in both projects. Neither is in `phase2/IAM-table.md` yet.
- Pre-Prod has no data, secrets, or test WhatsApp number. A deploy proves `/health`.
- `tests/` and `pyproject.toml` are wired into `phase2/lib.sh`'s push list; neither has actually been pushed into `Sujho/platform` yet. `Eval-Suite` stays out — phase 3 stays off.
- Running the gates on the merged tree surfaces ~836 pre-existing ruff/mypy findings in the real app code (confirmed not new — the old repo has nearly the same count under the same settings). `ruff` now ratchets the same way `mypy` already did, so old findings won't block future deploys once there's a baseline — but the very first real deploy still hits them. No owner or timeline set yet for cleaning them up.
- `verify-phase1.sh` and `verify-phase2.sh --remote` are manual. `sujho-ops-mcp` gets the merge gate only.

## Known gaps — Arnav's approval

Left as they are unless you say otherwise.

- Prod trusts the Pre-Prod registry. Images are not signed.
- One service per deploy. Two services means two runs, in an order named in the pull request.
- Rollback does not undo data. The previous revision must still read what the new one writes.
- Nothing alerts after traffic moves.
- The test gate installs every service into one environment.
- `redirect`, `text`, `users`, `whatsapp`, and `document-worker` are public at Cloud Run, including the `lkg` and `prev` tag URLs.
- The gcloud CLI is pinned by version, not checksum. `semgrep --config p/ci` floats. Service dependencies are not hash-pinned.
- Two Leads. Both away blocks a merge and a Prod deploy.
