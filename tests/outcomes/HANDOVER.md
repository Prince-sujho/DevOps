# Handover — what the suite found, and what needs a person

State of the local suite: **468 tests, 448 pass, 18 fail, 2 xfail.** All tooling
gates green. Every remaining failure has been checked against the current
product code (all service submodules at their own `origin/main`), so none of
them are the tests being out of date. They split into three piles:

| Pile | Rows | Who acts |
|---|---|---|
| Real defects | 6 | product — code change |
| Open questions | 7 | product — a decision, then code *or* README |
| Parked / environment | 5 | nobody right now |

To reproduce anything below:

```sh
cd /Users/prince/Desktop/Sujho/sujho
export PYTHONPATH=.
# integration and e2e also need the emulator's JVM:
export JAVA_HOME=/opt/homebrew/opt/openjdk
export PATH="$JAVA_HOME/bin:$PATH"
```

---

## Part 1 — Six real defects

Ordered by user-visible harm, not by effort.

### 1. A paid gift card can never be delivered

**What happens.** The user redeems, Hubble mints the voucher, and the delivery
read still returns `404`. The money is gone and the card is undeliverable.

**Why.** `list_rewards` settles pending orders before answering — it calls
`settled_gift_cards(...)`. `get_gift_card` does not: it reads the stored row
straight from Firestore and 404s anything that is not already `succeeded`.
Since the stored row is still `pending` until something settles it, the one
route the delivery path actually uses is the one route that never settles.
`whatsapp_adapter`'s `ReplyDelivery` GETs the card id directly and never reads
`/rewards` first, so nothing settles it on the user's behalf.

**Where.** `user_service/app/src/api/routes/gifting.py:40-47` (`get_gift_card`),
versus `:16-23` (`list_rewards`) for the correct pattern.

**Fix.** Settle before the status check, the same way `list_rewards` does.

```sh
.venv/bin/pytest "tests/e2e/test_ambassador_and_gifting.py::test_gift_card_redeem_settles_and_debits_balance"
# assert 404 == 200
```

### 2. Deleting a user leaves them blocked forever

**What happens.** `DELETE /internal/users/{userId}` returns `204` and removes
the user, their threads, enrollments, gift cards, clicks and referrer row — but
not their blocklist document. The blocklist is keyed on `userId`, and `userId`
is a deterministic HMAC of the phone, so the same person re-onboarding lands on
the same id and is still blocked, with no user row to explain why.

**Where.** `user_service/app/src/api/routes/users.py:97-110` (`delete_user`) —
eight cascade steps, no `ctx.blocklist.remove(user_id)`. The method already
exists and is idempotent: `infra/firestore/repos/blocklist.py:22-24`.

**Fix.** One line in the cascade. The README lists `blocklist` as owned by this
service, so this is unambiguous.

```sh
.venv/bin/pytest "tests/integration/test_cascade.py::test_delete_user_removes_owned_data_and_cascades_referrer_registry"
# assert True is False   (blocklist doc still present after delete)
```

### 3. An influencer handle that collides with an ambassador handle crashes

**What happens.** `POST /internal/influencers` with a handle already held by an
*ambassador* returns `500`.

**Why.** `create_influencer` sees the document exists and parses it as an
`Influencer` regardless of its `kind`. An ambassador row has `userId` and
`kind: "ambassador"`, so Pydantic raises and it escapes as a 500. Note the
registry's whole design intent, per README:187, is that the two kinds share one
collection so the `@`-mention namespace *cannot* collide — this is the door that
was supposed to enforce that.

**Where.** `infra/firestore/repos/referrers.py:38-46` (`create_influencer`).

**Fix.** Coupled to decision A below — the same function decides both the
cross-kind case and the same-kind case, so fix them in one change.

```sh
.venv/bin/pytest "tests/api/user_service/test_influencers.py::test_create_influencer_409_on_collision_with_existing_ambassador_handle"
# assert 500 == 409
```

### 4. Grading a session that does not exist crashes

**What happens.** `PUT .../sessions/{startedAtMs}/extraction` for a
`startedAtMs` with no session returns `500`.

**Why.** The repository calls `.update()` on the session document with no
existence check, and Firestore's `NOT_FOUND` escapes. The route is also the
only thread route with no user gate: its GET siblings all call
`load_user_or_404`, this one does not, so a bad `userId` fails the same way.

**Where.** `infra/firestore/repos/threads.py:233-234` (`set_session_extraction`);
route at `user_service/app/src/api/routes/threads.py:76-86`.

**Fix.** `load_user_or_404`, then a read before the update, 404 if absent —
mirroring `_load_session_or_404` at `threads.py:61-73`, which already does
exactly this for the read path.

```sh
.venv/bin/pytest "tests/api/user_service/test_threads.py::test_set_session_extraction_404_for_unknown_session"
# expected 404 for grading a nonexistent session; got 500
```

### 5. `GET /webhook` with missing query params crashes

**What happens.** Meta's verification challenge without `hub.mode` returns
`500` instead of `403`.

**Why.** `params["hub.mode"]` — raw dict indexing on `QueryParams`, so an
absent key is a `KeyError`. This is the same class of mistake as the missing
signature header that was just fixed by moving envelope-opening into a
dependency; the GET verification challenge was not part of that change and
still indexes directly.

**Where.** `whatsapp_adapter/app/src/api/routes.py:33-35`.

**Fix.** `params.get(...)` — a missing param then compares unequal and falls
through to the existing `403`.

```sh
.venv/bin/pytest "tests/api/whatsapp_adapter/test_webhook_verification.py::test_missing_query_params_is_rejected_with_403"
# assert 500 == 403
```

### 6. An ambassador with an empty name crashes on an index

**What happens.** `mint_handle("")` raises `IndexError: list index out of range`
rather than the intended `ValueError`.

**Why.** `name.split()[0]` runs before the guard that was written for exactly
this case. The next two lines already raise a clean `ValueError` when the stem
is empty — the check is simply on the wrong side of the indexing.

**Where.** `user_service/app/src/ambassadors.py:34`.

**Fix.** Guard the split, or take `name.split()[:1]` and let the existing
empty-stem check fire.

```sh
.venv/bin/pytest "tests/unit/user_service/test_ambassadors.py::test_mint_handle_empty_name_raises"
# IndexError: list index out of range
```

### Also worth fixing, no red test

`POST .../threads/{thread_key}/transcript` has no `load_user_or_404` gate, so an
append for a nonexistent user fails inside the Firestore transaction
(`_load_activity` calls `.to_dict()` on a missing document) and returns `500`
where its siblings return `404`. Nothing is written, so there is no corruption,
which is why the covering test
(`tests/integration/test_transactions.py::test_append_for_an_unknown_user_writes_nothing`)
passes — it asserts the append does not succeed and leaves nothing behind, which
holds under both the current 500 and a future 404. Adding the gate is still
right for consistency and for a usable error.

---

## Part 2 — Three decisions

Each of these is a place where the README states a rule the code does not
implement. Either the code is wrong or the sentence is wrong; the suite can't
tell which, and picked the README.

### A. Registering an influencer handle that is already taken

README:44 — *"Register one influencer (409 if the handle collides in the
referrer namespace)."*

Code returns `200` with the existing row for a same-kind collision — a silent
idempotent replay — and `500` for a cross-kind one (defect 3 above).

- **Option 1: implement the 409.** Matches the README and the shared-namespace
  design at README:187. Costs the idempotent replay, so a retried registration
  becomes an error.
- **Option 2: keep the replay, fix the README.** Still needs the cross-kind case
  to stop crashing — returning someone else's ambassador row as an influencer is
  not an acceptable replay, so this option is `200` same-kind and `409`
  cross-kind.

**Recommendation: option 1.** Handle registration is an interactive admin
action, not a retried machine call, so idempotency buys little, and one rule is
easier to reason about than a split one. Affects 1 red row.

### B. Overlapping campaign windows

README:47 — *"Create one campaign window (409 on overlap)."* README:188 also
describes campaigns as *"non-overlapping time windows"*, and the derivation
logic buckets each event into *a* campaign, which only makes sense if windows
don't overlap.

Code has no overlap check anywhere in the write path. An identical window
returns `200` and creates a second campaign with the same derived id, silently
corrupting the funnel maths that assumes one bucket per event.

- **Option 1: implement the 409.** Needs a range query against existing windows
  for that handle on create.
- **Option 2: allow overlap.** Then the per-campaign derivation needs a defined
  tie-break, and README:188 needs rewriting.

**Recommendation: option 1.** Option 2 isn't really a documentation fix, it's a
redesign of the attribution maths. Affects 4 red rows.

### C. Is the session boundary two hours, or more than two hours?

README:192 — *"a gap of two hours between user messages opens a new session."*

Code implements `>`, so a gap of exactly `SESSION_GAP_MS` stays in the old
session and only `+1ms` opens a new one. Read plainly, a gap that *has reached*
two hours has opened a new session, which is `>=`.

- **Option 1: change the code to `>=`.** Matches the sentence as written.
- **Option 2: change the README** to "more than two hours" and keep `>`.

**Recommendation: either is fine — this one is genuinely cosmetic**, since real
traffic never lands on the exact millisecond. Pick option 2 if you'd rather not
touch the resolver. It needs *a* decision only because two tests at different
layers were silently disagreeing with each other about it before. Affects 2 red
rows (`tests/integration/test_session_boundary.py::test_gap_exactly_two_hours_opens_a_new_session`
and `tests/e2e/test_session_gap.py::test_session_gap_boundary`), which are
deliberately aligned so they move together.

---

## Part 3 — Not asking you for anything

Listed so nobody re-investigates them.

**Four rows where the suite committed to a status code the README never named.**
Refusing a redeem of an amount the storefront doesn't offer returns `400`, the
tests want `422` (2 rows). `limit=0` on the directory returns `422` because the
query param is `ge=1`, the test wants an empty page (1 row). Negative onboards
in campaign spend (1 row). The behaviour underneath is correct in every case —
only the number is in dispute — and these are parked by prior decision.

**One row is the Firestore emulator under contention.** Eight concurrent claims
of one message id (`test_concurrent_claims_of_the_same_id_exactly_one_wins`)
exhaust the transaction's five commit attempts, and the failure escapes as a
`500`. Real Firestore handles contention better and nothing in production fans
out eight simultaneous writes to one document, but two things are still worth
knowing: retry exhaustion reaches the client as a 500 rather than as something
retryable, and `MessageClaims.claim` only catches `AlreadyExists`, so an
`Aborted` lock timeout leaks out of the idempotency boundary and a retried
webhook can 500 instead of no-op.

**The transcript-sequence concurrency test is `xfail(strict=False)` for the same
reason.** The emulator's ceiling is low: three concurrent writers on one document
exhaust the budget outright and wedge the locks for every integration test that
follows, and even two writers only pass intermittently — measured at 3 passed /
2 failed over 5 runs. So `test_concurrent_appends_to_one_session_assign_contiguous_sequences`
contends with two writers and is marked non-strict xfail: it reports `xpassed`
when the emulator cooperates and `xfailed` when it does not, and either way the
suite stays honest instead of carrying a flake. The property it asserts —
contiguous 0-based sequences under contention — is worth keeping and should be
re-run against real Firestore before anyone trusts it.

**Separately: pinning `startedAtMs` to a session that doesn't exist returns
500.** `_resolve` validates `SessionRecord` against a missing document.
No red test covers it any more — the concurrent-appends test used to hit it by
accident and now opens the session first — but it is a real rough edge for any
caller that pins a stale or invented `startedAtMs`.
