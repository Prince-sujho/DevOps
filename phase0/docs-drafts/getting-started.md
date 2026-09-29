# Getting Started

How to go from zero to a running local dev environment.

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.13+ |
| Node | 20+ |
| gcloud CLI | For Secret Manager and GCP access |
| git | Only needed for submodule support if you also work in `www`/`design_system`/`docs` |

## Clone

```bash
git clone https://github.com/Sujho/sujho.git
cd sujho
```

Every backend service is a plain folder — this alone gets you everything
needed for backend work. Only clone submodules if you also need `www`,
`design_system`, or `docs`:

```bash
git submodule update --init --recursive
```

## Python Environment

Create a virtual environment and install the shared package:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ./infra
```

Then install app-specific dependencies as needed.

## Auth

For Secret Manager and other GCP access:

```bash
gcloud auth application-default login
```

## Environment Variables

Set before running services:

| Variable | Value |
|----------|-------|
| `GOOGLE_CLOUD_PROJECT` | `sujho-478914` |
| `GOOGLE_CLOUD_LOCATION` | `asia-south1` |

## Running Services

From the monorepo root:

| Service | Command | Port |
|---------|---------|------|
| User service | `python run_users.py` | 8082 |
| WhatsApp adapter | `python run_whatsapp_adapter.py` | 8084 |
| Text agent | `python run_text_agent.py` | 8085 |
| Document worker | `python run_document_worker.py` | 8086 |
| Redirect service | `python run_redirect.py` | 8087 |
| Admin | `cd admin/app && npm ci && npm run build && python3 -m uvicorn src.api:app --host 0.0.0.0 --port 8080` | 8080 |
| Knowledge store | `python run_knowledge_store.py` | — |
| Marketing site | `cd www && npm install && npm run dev` | 4321 |

## Frontend Shared Package

Frontends depend on `@sujho/design-system`, published to npm from the `design_system` submodule. Running `npm install` in a consumer pulls the latest published version; no local build step is required.

## Service-Specific Docs

Each service has its own `docs/` or `README.md` for product-specific setup. Refer to:

- `user_service/`
- `text_agent/`
- `whatsapp_adapter/`
- `knowledge_store/`
- `document_worker/`
- `redirect_service/`
- `admin/`
- `www/` (submodule)
