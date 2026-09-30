# Sujho DevOps Plan

Plan only. Nothing applied. Scripts stay dry-run until `--apply`.

phase0 first, then phase1 and phase2. phase3 stays off.

1. The engineer tries the feature in `sujho-dev`. No CI.
2. Pull request on `Sujho/sujho`. A Lead approves. Nothing runs on the pull request. Merge does not deploy.
3. Someone runs Pre-Prod from `main`, then tries it on the Pre-Prod phone.
4. Someone runs Prod with that full SHA. A Lead approves. Same image, no rebuild.
5. Rollback moves traffic to the previous revision. No rebuild.

phase0 merges user-service, whatsapp-adapter, text-agent, document-worker, knowledge-store, admin, redirect-service, and infra into `sujho`. `www`, `design_system`, and `docs` stay separate. `phase0/apply-phase0.sh --output DIR`.

phase1: Leads own `sujho` and `sujho-ops-mcp`. Light touch: `design-system`, `docs`, `hiring`, `www`. `phase1/apply-phase1.sh`.

phase2: Pre-Prod builds, Prod promotes the same image. Gates: ruff, mypy, semgrep, detect-secrets, the tests, `check_assertions.py`, `check_test_count.py`. Buttons in `phase2/workflows/`. Jobs in `phase2/jobs/`. IAM from `phase2/IAM-table.md`, by hand.

phase3: weekly mutation and eval reports. Off until configured. Do not run `Eval-Suite/run.py` here.

```bash
pip install -e ./infra -r tests/requirements.txt
pytest tests/unit tests/api
pytest tests/integration   # gcloud + Java
pytest tests/e2e           # gcloud + Java, separate from integration
```

`tests/knowledge_store` needs Docker and is not in the gate.

## What's still left — Arnav

Nothing is applied.

- `sujho-preprod` does not exist. IAM is not granted. The `production` and `production-rollback` Environments do not exist.
- Pre-Prod has no data, secrets, or test WhatsApp number. A deploy proves `/health`.
- `tests/`, `Eval-Suite`, and `pyproject.toml` are not in `Sujho/sujho`. Phase 3 stays off.
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
