# Knowledge-store job split — local implementation source

This directory is the source for the local five-module split. It is not
automatically copied by phase 0 and has not been pushed or deployed. The
merged platform tree must receive these modules together with the catalog and
`infra.catalog.job_args()` changes before a job can use them.

## Why this exists

Item E moves the five verbs out of `knowledge_store/run.py` into real modules
under `knowledge_store/jobs/`. The job catalog names each module explicitly,
then the deploy tooling checks that exact entry file before building.

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

`ingest.py` and `remove.py` take an entry id as their sole argument:
`python -m knowledge_store.jobs.ingest <entry_id>`. `sessions.py`,
`import_ncert.py`, and `import_educart.py` take no arguments.

## What this does NOT cover, on purpose

- **The old `knowledge_store.run` interface remains a compatibility
  dispatcher.** It should not be the catalog entry after the cutover.
- **A real environment run remains required.** Local validation does not
  exercise GCP, Firestore, GCS, Neo4j, or the external importers.

## What was deliberately preserved exactly as-is

- The locking behavior: `ingest` and `remove` still hold `GRAPH_LEASE`,
  `sessions` still holds `SESSIONS_LEASE`, the importers still hold nothing
  — same scope, same holder-name format, just physically relocated.
- Every try/except/finally block, in the same place, doing the same cleanup.
- Every import of real application code (`Extractor`, `Materializer`,
  `Embedder`, `SessionExtractor`, the two importers) — these call into
  exactly the same shared logic as before; none of that logic was rewritten.
