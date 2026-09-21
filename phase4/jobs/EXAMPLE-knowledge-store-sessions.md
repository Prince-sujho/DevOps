# knowledge-store-sessions — one real job in the new form

Today this job already runs in prod GCP (`sujho-478914`). Code: `python -m knowledge_store.run sessions`. Image today is tagged `:latest`. That last part we stop doing.

There is no job named `session_job`. This is that job.

## What it looks like on the GitHub form

Actions → **Deploy Cloud Run job (Pre-Prod)** → Run workflow:

| Field | You pick |
|---|---|
| job | `knowledge-store-sessions` |
| entry_id | leave empty |
| execute | false until you want it to run now |

Opening the Pre-Prod file **is** choosing Pre-Prod. There is no env/mode dropdown.

GitHub then starts Cloud Build with `_JOB_ID=knowledge-store-sessions` and `_TARGET_PROJECT=sujho-preprod`, plus `_COMMIT_SHA` / `_SHORT_SHA` from the commit you ran against.

Prod is a **second** Action: **Deploy Cloud Run job (Prod)** → same job name → Run. No rebuild.

## What the label file looks like

`jobs/knowledge-store-sessions/job.json` (sample in `manifests/knowledge-store-sessions/job.json`):

- `kind`: `cloudrun-job` — this is how we know it is a job
- `args`: `-m, knowledge_store.run, sessions`
- `needs_entry_id`: false
- `secrets_via`: `runtime-secret-reader` — reads `KNOWLEDGE_STORE_GCS_BUCKET` from Secret Manager in **that** GCP project

Python does not move. It stays in `knowledge_store/`.

## Folder on `sujho` (target, not done yet)

```
sujho/
  jobs/
    knowledge-store-sessions/job.json
    knowledge-store-ingest/job.json
    ...
  knowledge_store/          # python, Dockerfile (gitlink)
  infra/                    # gitlink
  .github/workflows/cloud-run-preprod-deploy.yaml
  .github/workflows/cloud-run-prod-deploy.yaml
  ci/jobs/job-build-deploy.yaml
  ci/jobs/job-deploy-only.yaml
```

## Deploy steps (after a Lead has installed the files)

1. PR your code into `sujho` `main`. AI comments. Lead clicks Approve. Merge. Users see nothing.
2. Actions → Pre-Prod file → Run workflow with the table above.
3. Cloud Build: pin gitlinks → build `knowledge-store-jobs:sha-<7>` → `gcloud run jobs deploy knowledge-store-sessions` in Pre-Prod.
4. Check logs in Cloud Run Jobs. If you ticked **execute**, it also runs once.
5. Stamp `preprod-approved` for `knowledge-store-jobs` only: Actions → Approve Pre-Prod image → piece `knowledge-store-jobs` + the commit you tested → Run. Weekly eval does not stamp. `--all` is refused unless `SUJHO_APPROVE_ALL=1`.
6. Actions → Prod file → same job name. Do not build again.

Other jobs (`ingest`, …) keep their old image until you run the form for **that** job.

## What must exist in each GCP project

- Artifact Registry reader (image is in `sujho-dev`)
- Service account `knowledge-store-run@<project>.iam.gserviceaccount.com`
- Secret Manager secret **named** `KNOWLEDGE_STORE_GCS_BUCKET` (value is the bucket for that env)
- Cloud Run Job API
- WIF so GitHub can start Cloud Build (same as Phase 2/3)

## What changes vs today (`ci/knowledge-store-jobs-deploy.yaml`)

| Today | New |
|---|---|
| One Cloud Build updates **all five** jobs | Form updates **one** job |
| Image `:latest` | `sha-<7>` then `preprod-approved` |
| `revision: main` on gitSource | gitlink SHAs (`checkout-gitlinks.py`); `_COMMIT_SHA` from GitHub |
| Verbs listed in bash | `job.json` |
| Push trigger name guard | No push. Two GitHub forms (or Cloud Build Run) |
| SA hardcoded to prod project | `knowledge-store-run@${_TARGET_PROJECT}` |

## `user_job`

Does not exist. If you add one later: new `jobs/<id>/job.json`, re-run `generate_job_workflow.py`, PR. Do not invent a Python folder unless it is a **new** image.
