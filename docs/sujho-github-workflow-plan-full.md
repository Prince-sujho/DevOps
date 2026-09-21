# Sujho GitHub workflow

21 Sept 2026. Share this file. **Nothing here is live.** Today: push to `main` → Cloud Build → often `:latest`. Prod GCP is `sujho-478914`. `sujho-preprod` does not exist yet.

Do not run `phase1/`–`phase6/` `--apply` until a Lead asks. Dry-run is the default.

---

## Who

Everyone uses the same GitHub path into **`Sujho/sujho`**. Nobody pushes straight to `main`.

| Role | GitHub | How code lands on `sujho` `main` |
|---|---|---|
| Leads | `@arnavtayal` `@abhishektayal2802` | Feature branch → PR into `main` → the **other** Lead approves → merge |
| Engineer | `@Prince-sujho` | Same. Prince cannot approve (not a Code Owner) |

AI review **comments** on the PR. Lead **Approve** is a separate click. Then merge. Merge does **not** deploy.

Three people can open PRs at once. Each uses **their own branch**. GitHub shows who opened each PR. If two PRs touch the same lines, the second hits a conflict after the first merges.

---

## Places

| Place | What it is |
|---|---|
| Laptop **sandbox** | Playground. Firestore emulator, local Neo4j/Docker, fake APIs. **No GCP bill.** Not a GitHub deploy. |
| Optional GitHub **`Sujho/sujho-dev`** | Own `main`. Feature → PR → AI + Lead → merge. You `git pull` and run **locally**. Does **not** deploy Pre-Prod/Prod. |
| GitHub **`Sujho/sujho` `main`** | Shared code that Pre-Prod/Prod may deploy. Only branch we merge to for ship. No GitHub `dev` / `pre-prod` **branches**. |
| GCP **`sujho-preprod`** | Phone / WhatsApp test. Own Firestore, Neo4j, GCS. Periodically **copy Prod → Pre-Prod** (never write back). |
| GCP **`sujho-478914`** | Prod. Users. Own DBs. |

We do **not** use a billed GCP Dev project as the free playground. If Leads later want paid `sujho-dev` Cloud Run, that is a separate decision.

**Recommended code path:** try on `sujho-dev` + laptop → **second PR** into `Sujho/sujho` `main` → then select Pre-Prod / Prod. Do not point deploy Actions at the Dev repo.

---

## The rule

**No auto-deploy.** Merge is GitHub only.

To update a running env: GitHub Actions **Run workflow**, pick **one** job or service. Opening the file is choosing Pre-Prod vs Prod. Dispatch from `main` only.

- Services Pre-Prod: `.github/workflows/cloud-run-preprod-service.yaml` (build in `sujho-dev`, deploy to `sujho-preprod`)
- Services Prod: `.github/workflows/cloud-run-prod-service.yaml` (same image, **no rebuild**)
- Jobs Pre-Prod: `.github/workflows/cloud-run-preprod-deploy.yaml`
- Jobs Prod: `.github/workflows/cloud-run-prod-deploy.yaml` (same image, **no rebuild**)
- Stamp after a Lead tested Pre-Prod: `.github/workflows/approve-preprod.yaml` (one piece, required commit). Weekly eval does **not** stamp.

Partial: one piece per Run. No `:latest`. Not Cloud Deploy.

---

## Day to day

```
optional: feature → PR into sujho-dev main → AI + Lead → pull locally (sandbox)

then: feature → PR into Sujho/sujho main → AI + tests + Lead Approve → merge
                                                                      ↓
                                                              GitHub only. GCP unchanged.

Then, when a human selects:
  Actions → cloud-run-preprod-service.yaml (or -deploy.yaml for a job) → dropdown → Run
  (test on Pre-Prod)

  Actions → approve-preprod.yaml → the piece you tested + that commit → Run
  (stamp preprod-approved for that image only)

  Actions → cloud-run-prod-service.yaml (or -deploy.yaml for a job) → same name → Run
  (same image, Prod)
```

Setup of those YAML files = a PR that **adds the form**. Seeing the Actions buttons is not going live. **Run** is going live for that one piece.

---

## Repos that follow the sujho `main` ship path

`sujho` `text-agent` `user-service` `whatsapp-adapter` `admin` `document-worker` `redirect-service` `knowledge-store` `sujho-ops-mcp`

Light-touch (PR, Code Owners off): `design-system` `docs` `infra` `hiring` `www`

Build/deploy from **`Sujho/sujho`**. A push to a service repo alone deploys nothing.

Tests: one folder, `sujho/tests/` (pipeline: `python tests/ci/pipeline.py`). A copy lives in DevOps-Plan `tests/`. Eval: `sujho/Eval-Suite/` (copy in DevOps-Plan `Eval-Suite/`). Both source trees are **local untracked** on `Desktop/Sujho/sujho` — they are not on GitHub `main` or in `Sujho-DevOpsCheck`. `sujho/evals/` is a different older tree (not copied). Do not run `Eval-Suite/run.py` from DevOps-Plan.

---

## Rules

- Secrets: GCP Secret Manager. **Never** GitHub Secrets. Same **names** per project, different **values**.
- GitHub **Variables** (not Secrets) for WIF: `GCP_WIF_PROVIDER`, plus one service-account variable per identity (`GCP_WIF_SERVICE_ACCOUNT_PREPROD`, `GCP_WIF_SERVICE_ACCOUNT_PROD`, `GCP_WIF_SERVICE_ACCOUNT_AI_REVIEW`, `GCP_WIF_SERVICE_ACCOUNT_EVAL`). Do not use one SA that can reach both Pre-Prod and Prod. Pin the provider on GitHub's numeric owner id — see `phase4/scripts/provision-wif.sh` (dry-run until a Lead asks).
- CODEOWNERS `*` = Leads only.

```
*                               @arnavtayal @abhishektayal2802
/ci/                            @arnavtayal @abhishektayal2802
.github/                        @arnavtayal @abhishektayal2802
```

- Do not require a GitHub check until it has run once.
- Say “users”, not “students and teachers”, in user-facing text.
- Pre-Prod DBs/buckets/graph = **separate** from Prod; refresh by copy from Prod. Jobs must not use Prod URIs.

---

## Cloud Run jobs (paper in `phase4/jobs/`)

GitHub cannot search other repos when you click Run. Dropdown is generated from `jobs/<id>/job.json`. Python stays in `knowledge_store/`. Live names: `knowledge-store-sessions` (pilot), `ingest`, `remove`, `import-ncert`, `import-educart`. No `session_job` GCP name.

Try the form on a **clone/fork** first. Then PR onto real `sujho`. `apply-phase4.sh --4d` copies job forms + `ci/jobs/` + `jobs/` labels (still dry-run until `--apply`).

---

## What to land (when a Lead asks)

**1 — Protect `sujho` `main`**  
CODEOWNERS + ruleset. PR required, Code Owners ON, merge-only.

**2 — PR checks + AI review**  
`pr-checks` on `sujho`. AI on every full-treatment PR into `main`. Fail-open. Require checks only after they have run once.

**3 — Pre-Prod GCP + manual deploy form**  
Owner creates `sujho-preprod`. WIF, secrets, runtime SAs, Artifact Registry readers. Copy Prod data in. Two workflow files per kind (service vs job). Pre-Prod **builds run in `sujho-dev`** (Kaniko can push); deploy target is `sujho-preprod`. Pilot service: redirect. Pilot job: `knowledge-store-sessions`. No push auto-deploy. No `:latest`.

**4 — Prod**  
Same image as Pre-Prod. Deploy-only workflow. A Lead stamps `preprod-approved` with `approve-preprod` after they tested that commit — not weekly eval.

**5 — Weekly**  
Mutation + Eval on `sujho`. Not a merge gate. Reports only. Does not stamp.

---

## Still open

Lead / owner: create `sujho-preprod`; WIF; secrets; whether Prod snapshots to Pre-Prod must be anonymized; optional `Sujho/sujho-dev` repo; Meta test number; mutation runner.

Not a script: mobile-test sign-off; eval chats / minors; known-red tests (see local unit/api run on `Desktop/Sujho/sujho`: empty-handle mint, influencer campaign overlap/409, gift-card status code, WhatsApp webhook missing params).
