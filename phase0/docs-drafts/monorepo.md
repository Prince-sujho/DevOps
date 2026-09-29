# Monorepo Structure

How the Sujho codebase is organized.

## Structure

The repo holds 8 backend services as plain folders — no submodules, no
gitlinks. `git clone` alone gets you all of them. Three repos remain
separate submodules: `www` and `design_system` (different toolchain,
different deploy target — Firebase Hosting / npm publish, nothing gained
by folding them in) and `docs` (this repo, unaffected either way).

## Folders (backend services)

| Folder | Purpose |
|--------|---------|
| user_service | Phone-first user profiles, enrollment links, transcripts, session tips, blocklist, and the referrer registry |
| whatsapp_adapter | WhatsApp webhook ingress and outbound message adapter |
| text_agent | Text tutoring API |
| knowledge_store | NCERT/CBSE ingestion into the Neo4j knowledge graph |
| document_worker | Markdown → DOCX/PPTX + page previews |
| infra | Shared Python infrastructure |
| admin | Ops UI (IAP, Workspace group `ops@sujho.com`) |
| redirect_service | Public referral click tracking (`/{ref,ig,yt,tg}/{handle}`) and WhatsApp redirect |

Full history for every one of these is preserved — merged in with
`git filter-repo --to-subdirectory-filter`, not squashed. `git log --follow
<folder>/<file>` still works exactly like it did in the old separate repo.

## Remaining Submodules

| Submodule | GitHub repo | Purpose |
|-----------|-------------|---------|
| design_system | Sujho/design-system | Shared CSS package (`@sujho/design-system`) |
| www | Sujho/www | Marketing site |
| docs | Sujho/docs | Cross-repo documentation |

Clone with `--recurse-submodules` only if you need these three; backend
work needs nothing beyond a plain clone.

## Shared Python Package

`infra` is shared across Python services.

| Context | Install |
|---------|---------|
| Local dev | `pip install -e ./infra` |
| Docker | `pip install /tmp/infra` |

The package uses a flat layout with explicit package listings in `pyproject.toml`. Auto-discovery fails when `pyproject.toml` sits alongside `__init__.py` rather than as a parent. Explicit `[tool.setuptools]` packages and `[tool.setuptools.package-dir]` mappings are required for non-editable builds.

## Shared Frontend Package

`design_system` is published as `@sujho/design-system`. It provides CSS tokens and shared global styles for current frontends. Consumers install from npm; no local build is required.

Contract and publishing docs: [design-system.md](design-system.md).

## Dockerfile Pattern

Deployed Python services use the monorepo root as build context when they need shared packages:

```dockerfile
# Layer 1: shared internal package
COPY infra/ /tmp/infra/
RUN pip install --no-cache-dir /tmp/infra && rm -rf /tmp/infra

# Layer 2: app dependencies
COPY <service>/app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Layer 3: app source
COPY <service>/app/src/ ./src/
```

Build context is the monorepo root. Cloud Build submits from root: `gcloud builds submit --config ci/<service>-deploy.yaml --region asia-south1 .`

Exception: `document_worker` is flat (`document_worker/requirements.txt`, `document_worker/src/`, Dockerfile at `document_worker/Dockerfile`) — no `app/` directory. Copy those paths instead of the `<service>/app/…` pattern above.

## Adding a New Deployed Service

1. Create the service's folder directly in this repo (`<service>/app/...`). No separate GitHub repo, no submodule — it's just a folder here now.
2. Create `<service>/app/Dockerfile` (or a flat Dockerfile when the service has no `app/` directory, as with `document_worker`).
3. Create `ci/<service>-deploy.yaml`. One `dependencies` entry — the monorepo itself (`destPath: .`). Nothing else to declare; every folder is already in that one checkout.
4. Remove the service from `.gcloudignore` exclusions if it is deployed via `gcloud builds submit`.
5. Create Artifact Registry repo in GCP.
6. Create the Cloud Build trigger pointing to `ci/<service>-deploy.yaml`, with an `includedFiles` filter scoped to the new folder.
7. Add to the load balancer if it needs a custom domain.
8. Push. No `.gitmodules` to update.

Root-level `ci/` is intentional: Gen 2 push triggers need to locate the build config before evaluating `includedFiles`, and keeping every service's config at the root keeps that lookup uniform across services.

## pyproject.toml Conventions

Flat-layout repos need:

- Explicit `[tool.setuptools]` packages
- `[tool.setuptools.package-dir]` mappings

Example from `infra`:

```toml
[tool.setuptools]
packages = ["infra", "infra.platform.http", ...]

[tool.setuptools.package-dir]
infra = "."
"infra.platform.http" = "platform/http"
...
```

## .gcloudignore

Controls what gets uploaded during `gcloud builds submit`. Build source is the monorepo root. Repos not deployed via Cloud Build are excluded to keep uploads lean. When adding a new deployed service, remove it from the exclusion list in `.gcloudignore`.
