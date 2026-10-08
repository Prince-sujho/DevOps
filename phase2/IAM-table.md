# Permissions as actually granted

These are the machine accounts that deploy or run the app, and the access they hold now. This is a record of what is in Google, not a list of grants still to apply.

"Project" means a grant on the whole project. Anything else is on one resource only. From here, the apply scripts in `tasks/gcp/` and `devops-architecture.md` are the source of truth. The production runtime rows also match the 6 Oct access snapshot.

GitHub sign-in is already set on `Sujho/platform`: pool `github-pool`, provider `github-provider`. The `production` and `production-rollback` Environments exist, limited to `main`, with no required reviewers. This GitHub plan cannot require reviewers on a private repo. Google only accepts a `production` or `production-rollback` run that a Lead started.

## Pipeline accounts

Created in Session 2. GitHub sign-in was added in Session 3a.

| Account | Grant | On | Why |
|---|---|---|---|
| `github-deploy-preprod@sujho-preprod` | GitHub sign-in (`workloadIdentityUser`) | Runs of `Sujho/platform` on `main` | What GitHub signs in as for Pre-Prod deploys |
| | Cloud Build Editor | Project `sujho-preprod` | Start a build |
| | Logs Viewer (`roles/logging.viewer`) | Project | Show the build log in GitHub |
| | Service Usage Consumer | Project | Call Google APIs |
| | Cloud Run Jobs Executor With Overrides (`roles/run.jobsExecutorWithOverrides`) | Project | "Run this job now" from the job workflow |
| | Storage Object User (`roles/storage.objectUser`) + Legacy Bucket Reader | Bucket `sujho-preprod-build-source` | Upload the code |
| | Act as (`roles/iam.serviceAccountUser` on `prod-builder@sujho-preprod`) | `prod-builder@sujho-preprod` | Run the build as the builder |
| `github-rollback-preprod@sujho-preprod` | GitHub sign-in | Runs on `main` (`repo:Sujho/platform:ref:refs/heads/main`) | Pre-Prod rollbacks |
| | Cloud Run Developer | Project `sujho-preprod` | Switch traffic between versions |
| `github-eval@sujho-preprod` | GitHub sign-in | Runs on `main` | Phase 3 eval (off). No other grants until then. |
| `prod-builder@sujho-preprod` | Artifact Registry Writer | Repo `services` | Store the images it builds; add the verified tag |
| | Cloud Run Developer | Project | Deploy services and jobs |
| | Cloud Scheduler Admin | Project | Set a job's timer |
| | Logs Writer | Project | Write the build log |
| | Storage Object Viewer | Bucket `sujho-preprod-build-source` | Read the uploaded code |
| | Act as | The 7 runtime accounts, `jobs-run`, `scheduler-invoker` (Pre-Prod) | Deploy code that runs as them; hand the timer its identity |
| `scheduler-invoker@sujho-preprod` | Cloud Run Jobs Executor | Project | The timer can start any job |
| `github-deploy-prod@sujho-478914` | GitHub sign-in | Runs of `Sujho/platform` in Environment `production`, started by a Lead (`repo:Sujho/platform:environment:production`) | What GitHub signs in as for production deploys |
| | Cloud Build Editor, Logs Viewer, Service Usage Consumer, Cloud Run Jobs Executor With Overrides | Project `sujho-478914` | Same as Pre-Prod |
| | Storage Object User + Legacy Bucket Reader | Bucket `sujho-478914-build-source` | Upload the deploy files |
| | Act as | `prod-builder@sujho-478914` | Run the deploy as the builder |
| `github-rollback-prod@sujho-478914` | GitHub sign-in | Runs in Environment `production-rollback`, started by a Lead | Production rollbacks |
| | Cloud Run Developer | Project `sujho-478914` | Switch traffic between versions |
| `prod-builder@sujho-478914` | Artifact Registry Reader | Repo `services` (in `sujho-preprod`) | Take the verified image; can never write one |
| | Cloud Run Developer, Cloud Scheduler Admin, Logs Writer | Project `sujho-478914` | Deploy, set timers, write logs |
| | Storage Object Viewer | Bucket `sujho-478914-build-source` | Read the deploy files |
| | Act as | The 7 runtime accounts, `jobs-run`, `scheduler-invoker` (production) | Same as Pre-Prod |
| `scheduler-invoker@sujho-478914` | Cloud Run Jobs Executor | Project | The timer can start any job. Also an older grant on `knowledge-store-sessions`, now redundant. |
| Cloud Run robot `service-1032258336300@serverless-robot-prod` | Artifact Registry Reader | Repo `services` (in `sujho-preprod`) | Google fetches the image when production starts a service |

## Runtime accounts in production

These are what the running code is.

| Account | Grants | Notes |
|---|---|---|
| `whatsapp-run` | Cloud Datastore User; Secret Accessor (project); Storage Object Admin on `sujho-conversation-media` | |
| `text-run` | Vertex AI User; Discovery Engine Viewer; Secret Accessor (project); Storage Object Admin on `sujho-conversation-media` | |
| `users-run` | Cloud Datastore User; Secret Accessor (project); Storage Object Admin on `sujho-conversation-media` | |
| `document-worker-run` | Secret Accessor (project); Storage Object Admin on `sujho-conversation-media` | |
| `redirect-run` | Secret Accessor (project) | |
| `admin-run` | Cloud Datastore User; Secret Accessor (project); Storage Object Admin on `sujho-knowledge-store-staging`; Cloud Run Invoker + Viewer on the 5 knowledge-store jobs | Starts the jobs from the admin panel |
| `knowledge-store-run` | Cloud Datastore User; Logs Writer; Secret Accessor (project); Storage Object Admin on `sujho-knowledge-store-staging`; Invoker on `knowledge-store-sessions` | The invoker grant is the old self-start (cleanup P8). Moves to `jobs-run` later (P13). |
| `jobs-run` | Cloud Datastore User; Secret Accessor (project); Logs Writer; Storage Object Admin on `sujho-knowledge-store-staging` | Shared by all new jobs. Mirrors `knowledge-store-run`. |

Secret access is project-wide for every runtime account (decided 7 Oct; narrowing services is later cleanup P1).

## Runtime accounts in Pre-Prod

The same 7 names plus `jobs-run` exist, with no runtime grants yet. In Part 7 they get exactly the production grants above, against Pre-Prod's own buckets.

## Not yet granted

`analytics-export-run` and `analytics-notebook` (production), in Session 3b.

## Outside this system

Not used by the pipeline. See the tracker's cleanup list. Google's default compute and legacy Cloud Build accounts are the old deploy path and are stripped after cutover. The Firebase accounts serve the website. The ops server's accounts are separate too.
