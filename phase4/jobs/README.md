# Cloud Run jobs — how we find them and how we deploy them

Nothing here is live. Do not `--apply`. Same rules as the rest of Phase 4: you click, merge does not deploy, one job per click, no `:latest`.

Read this if you are new. Words mean what they say.

## Two kinds of Cloud Run

| Kind | Stays up? | Our names today |
|---|---|---|
| **Service** | Yes. Waits for HTTP. | redirect, text, users, whatsapp, admin, document-worker |
| **Job** | No. Runs, then stops. | `knowledge-store-ingest`, `knowledge-store-remove`, `knowledge-store-sessions`, `knowledge-store-import-ncert`, `knowledge-store-import-educart` |

Jobs use the same two-file rule as services. `apply-phase4.sh` copies the job forms, Cloud Build templates, `lookup_job.py`, catalog, and `job.json` labels onto the sujho PR (still dry-run until a Lead passes `--apply --4d`).

There is **no** Cloud Run job named `session_job` or `user_job`. The live job that grades WhatsApp sessions (transcripts) is **`knowledge-store-sessions`**. Use that as the example.

## How we tell a Cloud Run job from other files

**Do not** look for Python names like `session_job.py`. That would be wrong here.

Why: one Python package (`knowledge_store/`) becomes **one image**. That image is used by **five** Cloud Run jobs. The jobs differ only by the last argument (`ingest`, `sessions`, …). If we made five Python folders, we would build the same code five times.

**Do** look for this folder:

```
jobs/<id>/job.json
```

If `job.json` exists and `"kind": "cloudrun-job"`, it is a Cloud Run job. Anything else (tests, app code, services) is not.

Python stays where it is (`knowledge_store/`, `infra/`). `job.json` is only the **label** the deploy form reads.

In this repo the sample labels are under `phase4/jobs/manifests/`. On `sujho` they would live at `jobs/<id>/job.json`.

## GitHub Actions dropdown

GitHub **cannot** open the Run workflow page and then search every repo for jobs. The dropdown list is fixed in the workflow file.

**Two files = which environment.** You do not pick env on the form.

1. Humans add/edit `job.json` (and `catalog.jobs.json` here while designing).
2. `generate_job_workflow.py` writes the job list into **both**:
   - `workflows/cloud-run-preprod-deploy.yaml` (Pre-Prod; may build)
   - `workflows/cloud-run-prod-deploy.yaml` (Prod; deploy-only, no rebuild)
3. You open **Actions → Deploy Cloud Run job (Pre-Prod)** or **(Prod) → Run workflow**.
4. You pick **one job**. GitHub starts the matching Cloud Build. Still a click. Still not on push.

The forms live on **`sujho`**, because that is where deploy configs live. Job code may sit in the `knowledge-store` gitlink.

## Secrets and env vars

The job already reads secrets at **run time** (`SecretReader`). It asks Secret Manager in **the project it is running in** for a **name** such as `KNOWLEDGE_STORE_GCS_BUCKET`.

| What | Same in every env? | How it changes |
|---|---|---|
| Secret **name** | Yes | Create the same name in `sujho-dev`, `sujho-preprod`, `sujho-478914` |
| Secret **value** | No | Each project has its own value |
| `GOOGLE_CLOUD_PROJECT` | No | Set from the **file you opened** (Pre-Prod file → `sujho-preprod`, Prod file → `sujho-478914`) |
| `GOOGLE_CLOUD_LOCATION` | Yes (`asia-south1`) | Set from the form / Cloud Build |
| API keys in GitHub Secrets | Never | Not used |

Do not put secret values in `job.json` or in YAML. Do not copy Dev values into Prod.

`RELEASE_COMMIT_SHA` and `RELEASE_IMAGE_DIGEST` are set at deploy time from the image you just built or promoted. They are not secrets.

## What you click (same idea as services)

1. **Pre-Prod file** — build image `sha-<7 letters of the commit>`, update **that one** Cloud Run job on `sujho-preprod`.
2. **Prod file** — do not build. Read the digest of `sha-<7>` of this commit, confirm it still matches `preprod-approved`, pass that digest (`_IMAGE_DIGEST`). Cloud Build deploys the digest, not a moving tag.
3. Optional **execute** — run the job once after deploy (`gcloud run jobs execute`). `ingest` / `remove` also need `entry_id`.

The GitHub form passes `_COMMIT_SHA` / `_SHORT_SHA` from `inputs.commit` or `github.sha`. `gcloud builds submit --no-source` does not fill Cloud Build’s trigger substitutions. Pre-Prod Cloud Build runs in `sujho-dev` so Kaniko can push; deploy target is `sujho-preprod`.

Deploying `knowledge-store-sessions` does **not** update ingest/remove/import. Same image **group**, separate Cloud Run job names.

Service rollback is a different pair of files (`cloud-run-preprod-rollback.yaml` / `cloud-run-prod-rollback.yaml`). Jobs have no HTTP traffic, so there is no traffic-shift rollback; deploy an older digest the same way.

## Files in this folder

| File | What it is |
|---|---|
| `catalog.jobs.json` | List of jobs + GCP names |
| `schema.job.json` | Shape of each `job.json` |
| `manifests/*/job.json` | One label per live job |
| `workflows/cloud-run-preprod-deploy.yaml` | Pre-Prod GitHub form (job dropdown) |
| `workflows/cloud-run-prod-deploy.yaml` | Prod GitHub form (job dropdown, no rebuild) |
| `generate_job_workflow.py` | Writes both dropdowns from the catalog |
| `templates/job-build-deploy.yaml` | Cloud Build: build + deploy one job |
| `templates/job-deploy-only.yaml` | Cloud Build: same image, Prod |
| `scripts/lookup_job.py` | Cloud Build reads `job.json` by id |
| `EXAMPLE-knowledge-store-sessions.md` | One real job, step by step |
| `validate.py` | Laptop check. No GitHub. |
| `verify-jobs-local.sh` | Regenerates YAML + runs `validate.py`. No `gh` / `gcloud`. |

There is **no** `deploy-cloudrun-job.yml`. That single env+mode form is gone.

## Setup vs a PR

`apply-phase4.sh --4d` copies these onto the sujho PR (dry-run unless a Lead passes `--apply`).

When a Lead asks: merge that PR, then click the form. Until then this is paper.
