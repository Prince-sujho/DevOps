# Review rubric for this repo

## How to review — do this, not just pattern-match the list below
Trace the actual execution path of the diff. Don't just check whether a
phrase like "no error handling" applies — simulate what happens when this
code runs: what are the inputs, what's the state before and after, does the
diff's behavior actually match what the PR title/description claims it does?
A change that "looks like" it does the right thing but doesn't, on tracing
it through, is the single most valuable thing to catch here.

## Always escalate to Important (blocks merge)

### Correctness — trace these, don't just scan for keywords
- **Duplicate-delivery safety.** Meta delivers webhooks at-least-once —
  duplicates are guaranteed to happen. Any change to message-processing
  logic must preserve dedup-by-message-ID.
- **Event-ordering safety.** Meta does not guarantee delivery order — a
  "read" status can arrive before "delivered." Flag logic that assumes order.
- **Single-instance state assumptions.** `whatsapp` is pinned to
  `max-instances=1` because the sender queue is serialized in-process per
  phone number. New in-process shared state is coupled to that cap.
- **Timeout budget.** Different Cloud Run timeout per service (`whatsapp`
  600s, `text`/`document-worker` 3600s, `users`/`admin` 240s, `redirect`
  15s). Flag operations whose latency could approach it.
- **Concurrent-write races.** `text`, `users`, `document-worker` scale
  beyond 1 instance — flag non-transactional/non-idempotent writes.
- A changed code path with no corresponding test.

### Security / compliance
- Hardcoded secrets, API keys, tokens, or credentials in code.
- User-identifying data written to logs or error traces.
- A query not scoped to the calling institution.
- Weakened or bypassed webhook signature validation or Flow decryption.

## Nit only, never blocks merge
- Style, naming, formatting — lint already covers this.
- Missing docstrings/type hints, minor inefficiencies, suggested refactors.
- Cap ~5 nits per review; name a repeated pattern once.

## Skip entirely
- Generated code, lockfiles, migration files, digest-only ci/*.yaml diffs.

## This repo's specifics
<!-- whatsapp-adapter: Flow encryption, sender-queue serialization,
webhook idempotency default to Important. user-service, knowledge-store:
missing institution/tenant filter defaults to Important. document-worker:
storage path missing access-control defaults to Important. admin: any
relaxation of restricted access defaults to Important. infra: note which
downstream services an Important finding could affect. -->
