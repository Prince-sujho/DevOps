# Deployment

Cross-cutting documentation for how services in the monorepo are deployed.

## Cloud Run Pattern

Used by `user_service`, `whatsapp_adapter`, `text_agent`, `document_worker`, `admin`, and `redirect_service`.

Pipeline: trigger guard -> Kaniko build -> digest tag -> Cloud Run deploy -> verify release metadata (`/health` + `/version` on public services; Ready revision env on admin).

| Element | Value |
|---------|-------|
| `options.logging` | `CLOUD_LOGGING_ONLY` |
| Substitutions | `_SERVICE_NAME`, `_REGION: asia-south1`, `_RELEASE_COMMIT_SHA`, `_RUNTIME_SERVICE_ACCOUNT`, `_EXPECTED_TRIGGER_NAME`, `_BUILD_CONFIG_PATH` |
| Image destination | `asia-south1-docker.pkg.dev/${PROJECT_ID}/<service>/api:latest` |
| Digest file | `/workspace/<service>.digest` |

Deploy by digest, not by tag. The digest file is written after the Kaniko build and consumed by the deploy step.

Every Cloud Run deploy config must set `_RUNTIME_SERVICE_ACCOUNT` and pass it with
`--service-account="${_RUNTIME_SERVICE_ACCOUNT}"`. Do not rely on the default Compute
service account implicitly.

## Cloud Build Conventions

| Convention | Value |
|------------|-------|
| Trigger naming | `deploy-<service>-gcr` |
| Trigger guard | First step verifies trigger name matches expected and exactly one trigger exists for the build config path |
| Logging | `CLOUD_LOGGING_ONLY` |
| Release traceability | `_RELEASE_COMMIT_SHA` substitution. Falls back to `REVISION_ID` then `SHORT_SHA` for triggered builds. |
| Immutable deploys | Build produces a digest; deploy by digest. Commit SHA is tagged onto the image for traceability. |
| Build service account | `1032258336300-compute@developer.gserviceaccount.com` |
| Runtime service account | Explicit `_RUNTIME_SERVICE_ACCOUNT` per service/job |
| Build region | asia-south1 |

Every Cloud Build trigger for these pipelines is registered in `asia-south1`. Manual `gcloud builds submit` for `ci/*-deploy.yaml` must pass `--region asia-south1`.

## Manual Deploys

Run from the monorepo root:

```bash
gcloud builds submit \
  --config ci/<service>-deploy.yaml \
  --region asia-south1 \
  --project sujho-478914 \
  --substitutions=_RELEASE_COMMIT_SHA=<commit_sha> \
  .
```

The `.` uploads the local workspace — every backend service is already a
plain folder in it, so nothing extra to fetch. `.gcloudignore` controls
what is excluded.

## Push-Triggered Deploys

The working Gen 2 pattern has two pieces:

1. The trigger watches the monorepo repository and resolves the build config from the root-level `ci/` directory.
2. The build config declares one `dependencies` entry — the monorepo itself (`destPath: .`) — since every backend service lives directly in that one checkout. No per-service fetch, no separate repo to materialize.

Use root-level `ci/` when a push-triggered build needs a consistent lookup path across services. Self-contained services can keep service-local build configs.

## Existing Triggers

| Trigger | Service | Platform | Config Path |
|---------|---------|----------|-------------|
| `deploy-users-gcr` | user_service | Cloud Run | `ci/users-deploy.yaml` |
| `deploy-text-gcr` | text_agent | Cloud Run | `ci/text-deploy.yaml` |
| `deploy-whatsapp-gcr` | whatsapp_adapter | Cloud Run | `ci/whatsapp-deploy.yaml` |
| `deploy-document-worker-gcr` | document_worker | Cloud Run | `ci/document-worker-deploy.yaml` |
| `deploy-admin-gcr` | admin | Cloud Run | `ci/admin-deploy.yaml` |
| `deploy-redirect-gcr` | redirect_service | Cloud Run | `ci/redirect-deploy.yaml` |
| `deploy-knowledge-store-jobs-gcr` | knowledge_store | Cloud Run Jobs | `ci/knowledge-store-jobs-deploy.yaml` |
| `deploy-firestore-gcr` | firestore rules + indexes | Firestore | `ci/firestore-deploy.yaml` |

All active push triggers point at the same Developer Connect monorepo link
and rely on `includedFiles` plus a single Cloud Build `dependencies` entry
(the monorepo itself) to fetch what a build needs — there is no longer a
separate repo per service to materialize at build time.

## Global HTTPS Load Balancer

Cloud Run services are fronted by a shared Global HTTPS LB for custom domain support. Cloud Run domain mapping is not available in asia-south1.

| Resource | Name | Purpose |
|----------|------|---------|
| Static IP | `sujho-api-lb-ip` (34.8.131.20) | Global anycast IP for LB |
| URL map | `sujho-api-url-map` | Host-based routing for HTTPS |
| Backend service | `users-backend` | Routes to users NEG |
| Backend service | `text-backend` | Routes to text NEG |
| Backend service | `whatsapp-backend` | Routes to whatsapp NEG |
| Backend service | `document-worker-backend` | Routes to document-worker NEG |
| Backend service | `admin-backend` | Routes to admin NEG; IAP enabled (`group:ops@sujho.com`) |
| Serverless NEG | `users-neg` (asia-south1) | Points to users Cloud Run |
| Serverless NEG | `text-neg` (asia-south1) | Points to text Cloud Run |
| Serverless NEG | `whatsapp-neg` (asia-south1) | Points to whatsapp Cloud Run |
| Serverless NEG | `document-worker-neg` (asia-south1) | Points to document-worker Cloud Run |
| Serverless NEG | `admin-neg` (asia-south1) | Points to admin Cloud Run |
| HTTPS proxy | `sujho-api-https-proxy` | TLS termination |
| URL map | `sujho-api-http-redirect-map` | Port 80 HTTPS redirect (no backends) |
| HTTP proxy | `sujho-api-http-proxy` | Port 80 → `sujho-api-http-redirect-map` |

## Adding A New Service To The LB

1. Deploy the Cloud Run service to asia-south1.
2. Create a Serverless NEG.
3. Create a backend service.
4. Attach the NEG.
5. Add a host rule to the URL map.
6. Create a Google-managed SSL cert.
7. Add the cert to the HTTPS proxy.
8. Add a DNS A record for `<service>.api.sujho.com` -> `34.8.131.20`.
9. Wait for cert provisioning.

## Firebase Hosting

Frontend deployments use GitHub Actions, not Cloud Build.

- Push to `main` -> deploy to live site.
- PR -> deploy preview.

## Domain And DNS Conventions

API services follow `<service>.api.sujho.com`. The admin console uses `admin.sujho.com`.

| Domain | Type | Points to | Purpose |
|--------|------|-----------|---------|
| `users.api.sujho.com` | A record | 34.8.131.20 (LB) | User service |
| `text.api.sujho.com` | A record | 34.8.131.20 (LB) | Text agent |
| `whatsapp.api.sujho.com` | A record | 34.8.131.20 (LB) | WhatsApp adapter |
| `document-worker.api.sujho.com` | A record | 34.8.131.20 (LB) | Document worker |
| `admin.sujho.com` | A record | 34.8.131.20 (LB) | Admin users / influencers / ambassadors UI |
| `sujho.com` | A record | Firebase Hosting IP | Root domain (`/go/**` → redirect) |
| `www.sujho.com` | CNAME | Firebase Hosting | Marketing site |

DNS is managed in GoDaddy. Cloud Run services behind the LB use A records pointing to the LB IP.

## Rollbacks

Redeploy a previous digest:

```bash
gcloud run deploy <service> \
  --image=asia-south1-docker.pkg.dev/sujho-478914/<registry>/<image>@sha256:<known_good_digest> \
  --region=asia-south1 \
  --project=sujho-478914
```

## Verify A Deployment

Every service exposes `/health` and `/version`:

```bash
curl -sS https://<service-url>/health
curl -sS https://<service-url>/version
```

`/version` returns `release_commit_sha` and `release_image_digest` for traceability.
