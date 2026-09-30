<!--
Nothing automated runs on this pull request (decision 11). Every gate — ruff,
the mypy ratchet, semgrep, detect-secrets, the invariant tests and the suite
guardrails — runs in the Pre-Prod build instead, so it fails when someone
tries to deploy, not when they try to merge. Until then this checklist and
the Lead reading the diff are the only things between this change and `main`.
-->

## How to review — trace it, don't pattern-match

Follow the diff's actual execution path. Don't just check whether a phrase
like "no error handling" applies — work out what happens when this code
runs: what are the inputs, what's the state before and after, does the
diff's behavior actually match what this PR's description claims it does?
A change that *looks* right but isn't, on tracing it through, is the single
most valuable thing to catch here.

## Always worth blocking on

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
- **A changed code path with no corresponding test.** Nothing checks this,
  here or later — it's on you.
- **Tests deleted or weakened.** Removed tests, loosened assertions, tests
  marked skip/xfail. The Pre-Prod build's guardrail gate
  (`check_assertions.py`, `check_test_count.py`) does catch a dropped count
  or a test with no real assertion — but only at deploy time, on whoever
  deploys next, and it cannot see a test that was quietly narrowed.

### Security / compliance
- Hardcoded secrets, API keys, tokens, or credentials in code.
- User-identifying data written to logs or error traces.
- A query not scoped to the calling institution.
- Weakened or bypassed webhook signature validation or Flow decryption.

## Nit only, never a reason to withhold approval
- Style, naming, formatting — lint already covers this.
- Missing docstrings/type hints, minor inefficiencies, suggested refactors.

## Skip entirely
- Generated code, lockfiles, migration files, digest-only `ci/*.yaml` diffs.

## This repo's specifics
<!-- whatsapp-adapter: Flow encryption, sender-queue serialization,
webhook idempotency default to blocking. user-service, knowledge-store:
missing institution/tenant filter defaults to blocking. document-worker:
storage path missing access-control defaults to blocking. admin: any
relaxation of restricted access defaults to blocking. infra: note which
downstream services a finding here could affect. -->

---

**Before requesting review, confirm:**
- [ ] I verified this feature myself, by hand, in `sujho-dev` — it does what I meant it to do.
- [ ] I am not the only reviewer available for this — the other Lead approves, never the author.
