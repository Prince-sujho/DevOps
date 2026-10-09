# Knowledge-store job split — draft, not a merge

This is a **suggestion**, built by reading the real, current
`Sujho/knowledge-store` repo (`run.py` as of commit `9e7f438`, main branch)
read-only. Nothing here has been merged, tested against the real
environment, or reviewed by whoever owns `knowledge_store`. Treat it as a
concrete starting point for that review, not a finished change.

## Why this exists

Arnav's item E asks for `knowledge_store/run.py` (one file, one
`python -m knowledge_store.run <verb>` entry point) split into five real
per-verb modules under `knowledge_store/jobs/`, because the deploy tooling
checks that a job's entry file exists before deploying it, and expects
`<group>/jobs/<verb>.py`.

## What's in `knowledge_store/jobs/` here

- `setup.py` — the shared part of `run.py`'s old `main()`: building the GCP
  identity, secrets reader, bucket/storage, database repositories, and the
  Neo4j graph client. Every verb file below builds on this instead of
  repeating it.
- `ingest.py`, `remove.py`, `sessions.py`, `import_ncert.py`,
  `import_educart.py` — one file per verb. Each one's actual logic (what it
  does with the graph, the storage, the usage ledger) is copied verbatim
  from the matching branch of `run.py`'s `_run_verb()` — nothing about *how*
  each verb works was changed, only *where* the code for each one lives.

`ingest.py` and `remove.py` read the entry id as `sys.argv[1]`, matching
what the deploy tooling already passes (`python -m knowledge_store.jobs.ingest
<entry_id>`). `sessions.py`, `import_ncert.py`, and `import_educart.py` take
no arguments.

## What this does NOT cover, on purpose

- **`infra.catalog.job_args()` / `job_name()`** still assume the old
  `python -m knowledge_store.run <verb>` shape. Those would need updating
  too, in `infra`, once/if this split is adopted — not touched here, since
  that's a different package with its own owner.
- **No tests were added or changed.** Whoever adopts this should decide how
  `tests/unit/knowledge_store` and any job-specific tests should cover the
  new layout.
- **Not verified against a real environment.** This was built from reading
  the source, not from running it. The actual owner should run it for real
  before trusting it.

## What was deliberately preserved exactly as-is

- The locking behavior: `ingest` and `remove` still hold `GRAPH_LEASE`,
  `sessions` still holds `SESSIONS_LEASE`, the importers still hold nothing
  — same scope, same holder-name format, just physically relocated.
- Every try/except/finally block, in the same place, doing the same cleanup.
- Every import of real application code (`Extractor`, `Materializer`,
  `Embedder`, `SessionExtractor`, the two importers) — these call into
  exactly the same shared logic as before; none of that logic was rewritten.
