# IAM grants — apply by hand, in the console

No script grants any of this. One person, with console access, works down
this table and checks each box. That's deliberate (design change 8) — these
are one-time, high-consequence changes, and a human following a table can
be checked as they go; a script granting twenty roles in one shot cannot.

Re-run this table once per new project (`sujho-preprod` is created fresh;
`sujho-478914` already exists and only needs the new/changed rows applied).

---

## 1. The narrow GitHub-side accounts

These are what GitHub Actions logs in as via WIF. None of them build,
push, or deploy anything themselves — they only ever ask Cloud Build to
(plus, for rollback, shift Cloud Run traffic).

| Account | Project it lives in | Roles | Used by |
|---|---|---|---|
| `github-deploy-preprod` | `sujho-preprod` | `roles/cloudbuild.builds.editor`, `roles/logging.viewer` (streams the build log), `roles/serviceusage.serviceUsageConsumer`; `roles/storage.objectUser` on `gs://sujho-preprod-build-source` (the source upload); `roles/iam.serviceAccountUser` on `prod-builder@sujho-preprod` (Cloud Build runs as it); `roles/run.jobsExecutorWithOverrides` on each Cloud Run Job (only for "Execute job once") | `cloud-run-preprod-service.yaml`, `cloud-run-preprod-job.yaml` |
| `github-rollback-preprod` | `sujho-preprod` | `roles/run.admin` (traffic + tags only — see note below) | `cloud-run-preprod-rollback.yaml` |
| `github-deploy-prod` | `sujho-478914` | the same roles as `github-deploy-preprod`, in this project: `cloudbuild.builds.editor`, `logging.viewer`, `serviceusage.serviceUsageConsumer`, `storage.objectUser` on `gs://sujho-478914-build-source`, `iam.serviceAccountUser` on `prod-builder@sujho-478914`, `run.jobsExecutorWithOverrides` on each Cloud Run Job | `cloud-run-prod-service.yaml`, `cloud-run-prod-job.yaml` |
| `github-rollback-prod` | `sujho-478914` | `roles/run.admin` (traffic + tags only — see note below) | `cloud-run-prod-rollback.yaml` |
| `github-eval` | `sujho-preprod` | `roles/secretmanager.secretAccessor` on exactly these five secrets: `eval-openai-key`, `eval-gemini-key`, `eval-neo4j-uri`, `eval-neo4j-user`, `eval-neo4j-password` | `phase3/workflows/eval-replay.yml` |

`github-eval` has nothing else: no Cloud Run, no Cloud Build, no registry.

**The pool itself lives in `sujho-478914`, not Pre-Prod.** Whoever can
administer the host project can edit the pool, its provider condition and its
bindings. Hosting it in Pre-Prod would have meant Pre-Prod admin was enough to
mint a token for the Prod deploy account, which undoes the separation these
accounts exist for. Prod is the more closely held project, so it hosts the pool
and Pre-Prod trusts it. `provision-wif.sh` defaults to this.

**Each account trusts one OIDC subject, not "the repo".**
`provision-wif.sh` binds `roles/iam.workloadIdentityUser` on each account to
exactly one subject, so GCP itself refuses a job that isn't the intended one:

| Account | Only this GitHub job can use it |
|---|---|
| `github-deploy-preprod`, `github-rollback-preprod`, `github-eval` | `repo:Sujho/sujho:ref:refs/heads/main` (workflows dispatched on `main`) |
| `github-deploy-prod` | `repo:Sujho/sujho:environment:production` — only exists once a Lead has approved |
| `github-rollback-prod` | `repo:Sujho/sujho:environment:production-rollback` |

A workflow on any other branch, or one that drops the `environment:` line,
gets a different subject and GCP rejects it. The Lead approval is therefore
enforced by Google, not just by the workflow file being well-behaved.

**Note on the rollback accounts.** `roles/run.admin` is broader than
strictly needed (it can do more than shift traffic and move a tag), but Cloud
Run has no narrower built-in role for "may call `update-traffic` and
`revisions list`/`describe`, nothing else." If a custom role is worth the
maintenance later, scope it to exactly those calls. Until then, this is the
accepted gap — the blast radius is still bounded to Cloud Run within one
project, not the whole project.

A rollback needs `update-traffic` for two things, not one: shifting traffic,
and moving the `lkg`/`prev` tags that record which revision is the known-good
one. A revision's labels are fixed when it is created and gcloud has no
command to change them afterwards, so the marker has to live on the service.

A stolen or misused Pre-Prod credential cannot touch Prod, and vice versa —
that's the entire reason these are separate accounts and not one.

## 1b. Build-source buckets

Every deploy uploads the exact checked-out commit to Cloud Build with
`gcloud builds submit . --gcs-source-staging-dir=...`. Nothing is fetched
from GitHub inside Cloud Build.

| Bucket | Created by | Settings |
|---|---|---|
| `gs://sujho-preprod-build-source` | `provision-projects.sh` | uniform access, public access prevention on |
| `gs://sujho-478914-build-source` | by hand, in this table | same settings — `provision-projects.sh` never touches Prod |

Give each bucket a lifecycle rule that deletes objects older than 7 days:
the source tarballs are only needed while a build runs. The `.git` inside
the Pre-Prod tarball is full history and contains no GitHub token (the
workflows check out with `persist-credentials: false`, and upload with an
ignore file that also drops the `gha-creds-*.json` the auth step writes).

## 2. `prod-builder` — the narrow key for the machine that does the real work

**Status: not done.** This is the actual fix from the "narrow the Cloud
Build identity" gap, but nothing below has been applied yet — every real
build still runs as Cloud Build's broad default account. Confirmed by
grepping all four Cloud Build YAMLs for `serviceAccount:`: it isn't there.
The four accounts above only ever *ask* Google to run a build. The account
that actually builds, pushes, and deploys is a separate one — today it's
Google's broad default account. This replaces it, one project at a time.

| Step | Detail |
|---|---|
| Create | `prod-builder@sujho-preprod.iam.gserviceaccount.com` (repeat for `sujho-478914` as `prod-builder@sujho-478914...`) |
| Grant — write to the warehouse | `roles/artifactregistry.writer` on the `services` Artifact Registry repo, **`sujho-preprod` project only**. The `sujho-478914` copy of this account gets `roles/artifactregistry.reader` **on the `sujho-preprod` `services` repo** instead (the repo lives in Pre-Prod; the grant is made there) — it only ever pulls, per design change 1. |
| Grant — deploy to Cloud Run | `roles/run.developer` on the project this account lives in. Deliberately not `run.admin`: the recipes never set a service's IAM policy (see 3d), so `run.developer` is enough, and a stolen builder token cannot open a service to the internet. |
| Grant — tag the verified image (Pre-Prod copy only) | covered by `roles/artifactregistry.writer` above: `publish-verified-tag` runs `gcloud artifacts docker tags add`. |
| Grant — act as the runtime accounts | `roles/iam.serviceAccountUser` on each of the seven runtime accounts (section 3) in that same project. |
| Grant — sync the weekly/hourly schedule | `roles/cloudscheduler.admin` on the project this account lives in — `job-build-deploy.yaml`'s `sync-schedule` step calls `gcloud scheduler jobs describe/update/create`. |
| Grant — attach the scheduler's invoking account | `roles/iam.serviceAccountUser` on `scheduler-invoker@<project>` (section 3b) in that same project — `sync-schedule` passes it via `--oauth-service-account-email`, which needs actAs. |
| Wire it in | Set `serviceAccount:` in `ci/build-deploy.yaml` (Pre-Prod) and `ci/deploy-only.yaml` (Prod) to this account's full resource name. |
| Retire the old account | Nothing to delete — just stop pointing builds at Google's default account. Confirm no other build in the project still relies on it before assuming it's fully out of the path. |

Nobody holds this key personally. It's only ever invoked by Cloud Build
itself, and only after a human clicks Run *and*, for Prod, a Lead clicks
Approve on the `production` Environment.

## 3. Per-service runtime accounts — already correct today, listed for completeness

One per service, per project. This is what each *running container* acts
as — separate from the builder account above.

| Account pattern | Projects | Grants (per project) |
|---|---|---|
| `redirect-run@<project>` | `sujho-preprod`, `sujho-478914` | Whatever `redirect` itself needs (Secret Manager access for its own secrets, Firestore, etc.) — service-specific, audit against what's actually granted in `sujho-478914` today and mirror it into `sujho-preprod`. |
| `text-run@<project>` | same | same approach |
| `users-run@<project>` | same | same approach |
| `whatsapp-run@<project>` | same | same approach |
| `document-worker-run@<project>` | same | same approach |
| `admin-run@<project>` | same | same approach |
| `knowledge-store-run@<project>` | same | same approach |

Every service in `ci/services.json` names its account in `runtime_sa`, and the
deploy **refuses** if that field is missing — without it the container would
run as the project's default compute account. `phase2/validate.py` checks the
two lists match.

Secrets and plain env vars are declared per service in the same file
(`secrets`, `env`, both empty today because Pre-Prod has none yet) and are
applied with `--update-secrets` / `--update-env-vars`. Never `--set-` or
`--clear-`: an incomplete list in a config file must not be able to strip
config a running Prod service depends on. Anything left out is left alone.

`sujho-478914` already has all seven (confirmed live). `sujho-preprod`
needs all seven created fresh, mirroring the same per-service grants —
this is part of "build the Pre-Prod environment," not new scope.

## 3b. `scheduler-invoker` — the account Cloud Scheduler calls jobs as

Cloud Scheduler cannot call a Cloud Run job as nobody: it needs an account
whose OIDC token it presents. `job-build-deploy.yaml`'s `sync-schedule` step
passes this one, but nothing created or granted it until this section — the
gap it closes, alongside `prod-builder`'s Scheduler grants above.

| Step | Detail |
|---|---|
| Create | `scheduler-invoker@<project>.iam.gserviceaccount.com`, in both `sujho-preprod` and `sujho-478914`. |
| Grant — call the job | `roles/run.invoker` on each Cloud Run Job this account is allowed to trigger, in that same project. |

Cloud Scheduler uses this account's OIDC token to call a job's `:run`
endpoint (`job-build-deploy.yaml`/`job-deploy-only.yaml`'s `sync-schedule`
step sets `--oauth-service-account-email` to it) — separate from any
runtime account in section 3, which is what the job's *own container*
acts as once running.

## 3d. Who may call a service — one time, not per deploy

Deciding this needs `run.setIamPolicy`, which comes with `roles/run.admin`.
The builder has `roles/run.developer` (section 2), so the deploy recipes pass
no `allow-unauthenticated` flag at all: they cannot change who may call a
service, and a deploy can never widen access as a side effect.

| Service | Who may invoke | Where it is set |
|---|---|---|
| `redirect`, `text`, `users`, `whatsapp`, `document-worker` | `allUsers` → `roles/run.invoker`. They answer public HTTP: WhatsApp webhooks and short links come from the internet with no Google credential. The apps do their own authentication (webhook signatures, tokens). | Pre-Prod: `provision-projects.sh` does it after the services exist. Prod: by hand, once, in this table. |
| `admin` | nobody public. It keeps `--ingress=internal-and-cloud-load-balancing` and gets no `allUsers` binding. | n/a |

A Cloud Run traffic tag (`lkg`, `prev`) is a URL onto one revision, and it is
covered by the same service-level policy — so on a public service those two
revisions are reachable too. Both are revisions that passed verify and served
traffic, and the deploy recipes delete the per-build tag once traffic has
moved, so no failed or rolled-back revision keeps a URL.

## 3c. Cloud Run pulling the image across projects

Prod's Cloud Run pulls its image from the Pre-Prod warehouse. The account
that does that pull is **not** `prod-builder` — it is the Cloud Run service
agent of the Prod project, so it needs its own grant:

| Account | Grant |
|---|---|
| `service-<sujho-478914 project number>@serverless-robot-prod.iam.gserviceaccount.com` | `roles/artifactregistry.reader` on the `sujho-preprod` `services` repo |

Without it a Prod deploy builds the revision and then fails to start it
("permission denied pulling image"), which `verify` reports as a failed
health check.

## 4. GitHub Environments — the actual deploy-time gate

Not IAM, but belongs in this table because it's also a one-time,
by-hand, console-side setup step — and GCP's trust in
`github-deploy-prod` / `github-rollback-prod` (section 1) is tied to these
exact Environment names.

| Step | Where |
|---|---|
| Create an Environment named `production` | `Sujho/sujho` → Settings → Environments |
| Add required reviewers | List the Leads. Anyone not listed cannot approve a paused run. |
| Turn on "Prevent self-review" | Same screen. Stops the person who started the run from approving it. |
| Deployment branches | "Selected branches" → `main` only. |
| Create an Environment named `production-rollback` | Same place. Used only by `cloud-run-prod-rollback.yaml`. |
| Required reviewers on `production-rollback` | The Leads. |
| "Prevent self-review" on `production-rollback` | **Off, on purpose.** In an incident the Lead who starts a rollback can approve it alone; it is still a named, logged Lead action. Nobody outside the reviewer list can roll Prod back. |
| Deployment branches on `production-rollback` | "Selected branches" → `main` only. |

`phase2/verify-phase2.sh --remote` reads both Environments back and fails
if reviewers are missing or `production` allows self-review.

## 5. What stays exactly as-is

- `sujho-dev` gets no service accounts related to any of this — it's a
  pure sandbox (decision 13), nothing here touches it.
- Nothing in this table grants write access to anyone or anything against
  the warehouse from `sujho-478914` — that project is read-only against
  it, permanently, by construction (design change 1).
