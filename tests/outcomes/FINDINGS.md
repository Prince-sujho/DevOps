# FINDINGS

The current full pass/fail catalog is [`PYTEST_RESULTS.md`](PYTEST_RESULTS.md)
(470 collected on 2026-09-07: 419 passed, 49 failed, 2 xfailed). This file
keeps the written-up mismatches; some later reds are only in that catalog.

Produced by the WhatsApp pipeline E2E suite (`tests/e2e/`). Each row is a spec-vs-code
mismatch discovered by running a test whose expected value was written from
`whatsapp_adapter/README.md` *before* execution. Per the test rules, failing assertions
were left failing — no assertion or source code was changed to make them pass.

Run: `python -m pytest tests/e2e -v` → **18 passed, 2 failed**.

| # | Test | Spec says | Code did | Likely wrong | Location |
|---|---|---|---|---|---|
| 1 | `test_ambassador_and_gifting.py::test_gift_card_redeem_settles_and_debits_balance` | A pending gift-card mint settles on the **next read** (`UsersClient.redeem_reward` docstring: "lost responses settle on the next read"); journey 17 requires `GET /internal/users/{id}/gift-cards/{id}` to reflect SUCCESS once Hubble settles. | Returned **404**. The route reads Firestore directly and 404s on anything not already `succeeded`; it never calls `_settle`/`get_order_by_reference`. Only `/rewards`, `/ambassador`, `/ambassadors/{id}` actually settle pending orders. | **Code.** This is the same route `whatsapp_adapter`'s outbound `GiftCardMessage` delivery calls (`replies.py::_send`). A freshly minted card is always `pending` at the moment of delivery, so the first delivery attempt 404s and the outbound turn fails. | `user_service/app/src/api/routes/gifting.py:39-45` (contrast the settling paths at `:16-23` and `user_service/app/src/ambassadors.py:109-110`) |
| 2 | `test_onboarding.py::test_forwarded_contact_represents_phone_request` | README: "Forwarded contact (`origin: other`) while phone required → Current `REQUEST_CONTACT_INFO` action is re-presented"; Tradeoffs section: re-presents "**the exact pending interactive**". | Kind and pending-action state matched, but the **body text changed**: the first prompt is `"Hi Priya! 👋 I'm Sujho — your AI for learning.\nShare your number…"`, the re-presentation on the forwarded-contact path is the bare `"Share your number…"` — the greeting is dropped. | **Ambiguous, leaning code/doc mismatch.** Dropping a repeated greeting is defensible copy, but it contradicts the literal "the exact pending interactive" wording. Either re-send the identical body, or amend the README to describe re-presentation as "equivalent," not "exact". | `whatsapp_adapter/app/src/service/coordinator.py:80-89` (`_request_phone`, `if pending is None` branch) |
| 3 | Journey 15 (session gap) — design-time observation while building the test, not a failing assertion | Journey premise: the WhatsApp message's `timestamp` field drives the 2-hour session-gap boundary. | The adapter **ignores the webhook timestamp** on the append path: `_stamp` uses `now_ms()` (wall-clock at processing time), and `ThreadsRepository._resolve` keys the gap off the *previously stored* `createdAtMs`, not the inbound Meta timestamp. `BaseInboundMessage.at_ms` (the property that does derive from the webhook timestamp) is never consulted when appending transcript rows. | **Probably code, possibly intentional** (e.g. deliberately treating "when we processed it" as the session clock rather than "when Meta says it was sent" — but this makes a redelivered-hours-later message land in the *current* session instead of its own). Whichever is intended, the README doesn't say which clock governs, so this is worth a decision either way. Journey 15 could not be exercised through real webhook POSTs as a result — see UNCERTAINTY.md. | `whatsapp_adapter/app/src/transcripts.py:19-25`; `infra/firestore/repos/threads.py:78-83`; unused `infra/conversation/inbound.py:20-23` |

## Notes on scope

- Findings are limited to what the 17 required journeys plus the two signature tests actually exercised. No claim is made about behavior outside that scope (see UNCERTAINTY.md "Not tested" list).
- Finding 1 is the most actionable: it is a live delivery-breaking bug on the WhatsApp gift-card delivery path, not just a test artifact.

---

# API-level route tests (`tests/api/`)

Produced by a second, independent suite that drives each service's real FastAPI app
directly through an ASGI test client (not the full 3-service e2e harness above),
with repositories/external clients faked and request validation, auth, status codes,
and response shapes exercised for real. One subsection per service, added as each
service's test-writing finished.

## whatsapp_adapter

Run: `.venv/bin/python -m pytest tests/api/whatsapp_adapter -v` → **29 passed, 0 failed**.

No confirmed spec-vs-code mismatches — every documented row in the README's Test Matrix
and Routes table behaved as the spec describes. The three robustness gaps below are real
findings, but they are *not* README contradictions (the README never specifies a status
code for these cases), so they're listed as a separate table rather than "spec said X,
code did Y":

| # | Behavior | What happens | Location |
|---|----------|---------------|----------|
| 1 | `GET /webhook` with any of `hub.mode`/`hub.verify_token`/`hub.challenge` missing | Unhandled `KeyError` → 500, instead of a clean 400/403 | `whatsapp_adapter/app/src/api/routes.py:32-37` |
| 2 | `POST /webhook` with `X-Hub-Signature-256` header entirely absent | Unhandled `KeyError` (`request.headers["X-Hub-Signature-256"]`) → 500, instead of the clean 403 a present-but-wrong signature gets | `whatsapp_adapter/app/src/api/routes.py:48` |
| 3 | `POST /flows/onboarding` / `/flows/grade` with garbage/undecryptable (but well-shaped) ciphertext | Unhandled exception (binascii/OAEP/GCM error) → 500, no dedicated Flow-decrypt-failure status (Meta's spec convention is 421) | `whatsapp_adapter/app/src/flows/response.py`, `crypto.py` |

A signature/verification boundary that crashes with 500 on absence rather than rejecting
cleanly is a minor hardening gap, and #3 means Meta won't get the 421 it may expect on
decrypt failure — confirming intended severity is a judgment call for the owning team,
not something the spec adjudicates either way.

## user_service

Run: `.venv/bin/python -m pytest tests/api/user_service -v` → **152 passed, 13 failed** (165 total).

| # | Test | Spec says | Code did | Likely wrong | Location |
|---|------|-----------|----------|---------------|----------|
| 1 | ~~`test_public_access_phone_allowed_for_onboarded_phone`~~ | **Withdrawn:** `public.py` was deleted upstream, so there is no public `/access/phone`. Replaced by `test_public_access_phone_route_is_gone`. | | |
| 2 | `test_enroll_ambassador_refuses_when_institution_id_is_null` | "refuses when the profile school has no directory id" (business-rule refusal on a well-formed request) | Returns `200 {"result":"school_not_recognised"}` — a 2xx success, not a refusal-class status | `user_service/app/src/api/routes/ambassadors.py:26-39` |
| 3 | `test_list_users_limit_zero_returns_zero_items` | Directive: `limit=0` should return an empty page with a populated `totalCount` | `limit` query param has `ge=1`, so `limit=0` → `422` | `user_service/app/src/api/routes/users.py:47` |
| 4 | `test_redeem_gift_card_amount_not_in_live_storefront_is_rejected` | "refuses an amount not currently offered by the live storefront" | Returns `400`, not `422` | `user_service/app/src/api/routes/gifting.py:34-36` |
| 5 | `test_create_influencer_409_on_collision_with_existing_influencer_handle` | "409 if the handle collides in the referrer namespace" | Returns `200` with the existing row (idempotent replay, no conflict) | `infra/firestore/repos/referrers.py:38-46` (`create_influencer`); route has no collision check either |
| 6 | `test_create_influencer_409_on_collision_with_existing_ambassador_handle` | "@-mention namespace shared across kinds ... cannot collide" | Crashes with `500` (parses an ambassador doc as `Influencer`, fails Pydantic validation) instead of `409` | `infra/firestore/repos/referrers.py:38-46` |
| 7 | `test_campaign_overlap_identical_window_is_409` | "409 on overlap" | Returns `200`, creates a duplicate-id campaign silently | `infra/firestore/repos/campaigns.py:24-29`; no overlap check anywhere in the app |
| 8 | `test_campaign_overlap_partial_at_start_is_409` | same | Returns `200` | same |
| 9 | `test_campaign_overlap_partial_at_end_is_409` | same | Returns `200` | same |
| 10 | `test_campaign_overlap_fully_containing_is_409` | same | Returns `200` | same |
| 11 | `test_transactions.py::test_append_for_an_unknown_user_writes_nothing` (moved to integration) | General mandatory-coverage rule + consistency with sibling routes (`get_session_transcripts`/`get_session_transcript` both 404 via `load_user_or_404`) | `POST .../transcript` never calls `load_user_or_404`. Against real Firestore the append fails inside the transaction (`_load_activity` calls `.to_dict()` on a missing user doc) and returns `500`, not `404`. Nothing is written. | `user_service/app/src/api/routes/threads.py` (no `load_user_or_404`); `infra/firestore/repos/threads.py::_load_activity` |
| 12 | `test_set_session_extraction_404_for_unknown_session` | Well-formed lookup-by-id on a missing resource → 404 | No existence check before `.update()`; crashes with `500` | `user_service/app/src/api/routes/threads.py:53-63` |
| 13 | ~~`test_set_session_extraction_then_visible_on_read`~~ | **Withdrawn:** `gradedWith` was removed from the contract, so the test asserted a pre-removal shape. It now asserts the `extraction` round-trip, and passes. | | |

Notably, findings 5-10 mean the README's own documented conflict guarantees
("409 if the handle collides", "409 on overlap") do not hold at all in the current
implementation — no collision or overlap check exists anywhere in the write path for
influencers/ambassadors or campaigns; every one of these silently succeeds or corrupts
state instead of refusing.

## text_agent

Run: `.venv/bin/python -m pytest tests/api/text_agent -v` → **11 passed, 1 failed** (12 total).

| # | Test | Spec says | Code did | Likely wrong | Location |
|---|------|-----------|----------|---------------|----------|
| 1 | `test_plain_text_reply_returns_documented_shape` | README's Response Format example shows exactly `reaction`, `messages`, `evidence` — no `trace` key | Actual JSON response includes an extra `"trace": []` field | README (undocumented response field) | `text_agent/README.md` §Response Format vs `infra/clients/text_agent/types/turns.py::GenerateResponse.trace` |

Two further confirmed mismatches surfaced as *passing* tests (they pass because the
assertion targets the actual, code-derived behavior against the literal README text,
which the README contradicts):

- `test_missing_previous_response_id_is_422`: the README's own example request body
  (§Request Format) omits `previousResponseId`, but `GenerateRequest.previousResponseId:
  Optional[str]` has no default, so it's a required field — sending the README's example
  verbatim 422s. (`text_agent/README.md` §Request Format vs
  `infra/clients/text_agent/types/turns.py::GenerateRequest`)
- `test_audio_message_part_is_422_not_transcribed`: README states `message.parts` "may
  also include `UriMediaContent` for images, **audio**, video, or documents. Audio parts
  are transcribed to text before the model call." But `UriMediaContent.type` is
  `Literal["image", "document"]` (no `"audio"`, no `"video"`), and `RespondService`'s
  constructor has no audio-transcriber dependency at all — an audio part fails validation
  before any turn runs. (`text_agent/README.md` §Request Format/§Architecture vs
  `infra/llm/content.py::UriMediaContent` and `text_agent/app/src/services/respond.py`)

## document_worker

Run: `.venv/bin/python -m pytest tests/api/document_worker -v` → **15 passed, 2 failed** (17 total).

No confirmed spec-vs-code mismatches — every discrepancy traces to a missing local
system binary (`soffice`/LibreOffice) in this sandbox, not to application code diverging
from the README/type contract:

- `test_render_success.py::test_render_docx_success_shape` and `::test_render_pptx_success_shape`
  both assert `response.status_code == 200` per the README's documented `/render` success
  contract; both got `500`. `infra/documents/previews.py` shells out to a local `soffice`
  binary to rasterize preview pages, and that binary is absent in this sandbox even though
  `infra/documents/constants.py` documents it as present in the real deployed image — so
  the real success path cannot be exercised here. Left failing, not weakened, per rule 3.

## redirect_service

Run: `.venv/bin/python -m pytest tests/api/redirect_service -v` → **11 passed, 0 failed**.

No confirmed mismatches — every assertion derived from the README passed against the
real app.

---

# Persistence / cross-service integration tests (`tests/integration/`)

Produced by the Firestore-emulator suite. Expected values were committed from
`user_service/README.md` (Firestore Layout, Stored derivations, transactional
claims) and the task brief *before* execution. Failing assertions were left
failing.

Run: `JAVA_HOME=/opt/homebrew/opt/openjdk PATH="$JAVA_HOME/bin:$PATH" .venv/bin/python -m pytest tests/integration -v`
→ **37 passed, 10 failed** (47 total).

| # | Test | Spec says | Code did | Likely wrong | Location |
|---|------|-----------|----------|--------------|----------|
| 1 | `test_cascade.py::test_delete_user_removes_owned_data_and_cascades_referrer_registry` | `DELETE /internal/users/{userId}` deletes one user **and user-service-owned data**. `blocklist` is listed as owned by this service. | User, threads, enrollments, and the ambassador `referrers/{handle}` row were removed (204, subsequent GET 404). The `blocklist/{userId}` document was **left in place**. | **Code.** A deleted user who was blocked remains blocked by a dangling presence doc; re-creating the same phone would still be blocked with no owned user row. | `user_service/app/src/api/routes/users.py` (`delete_user` — no blocklist remove) |
| 2 | `test_hubble_settlement.py::test_settlement_success_with_empty_vouchers_settles_without_voucher_fields` | README: "a terminal order settles **with or without its voucher**." SUCCESS + `vouchers: []` must become `succeeded` with null voucher fields, not crash. | `GET /internal/users/{id}/rewards` returned **500**. `_apply_order` does `voucher = order.vouchers[0]` → `IndexError`. | **Code.** The task brief flagged this exact indexing. Hubble can return SUCCESS with an empty vouchers array. | `user_service/app/src/gifting.py:52` (`_apply_order`) |
| 3 | `test_hubble_settlement.py::test_redeem_amount_not_offered_is_rejected_without_placing_an_order` | Well-formed redeem of an amount the live storefront does not offer is a business-rule refusal. This suite committed to **422** (README names no status). Hubble must not be called. | Returned **400**. `place_order` was not called (the no-order assertion would have passed). | **Ambiguous status, same as API-suite finding #4.** The important persistence claim (no Hubble mint) holds. | `user_service/app/src/api/routes/gifting.py` |
| 4 | ~~`test_sequences.py::test_caller_supplied_sequence_is_ignored` and the two `test_transactions.py` cursor tests~~ | **Withdrawn:** sequences are 0-based by design (a fresh session starts the counter at 0) and no README line claims 1-origin. These tests failed only on the origin — the ignore-caller-order rule and the rollback both held. Now 0-based, and passing. | | | |
| 5 | `test_session_boundary.py::test_gap_exactly_two_hours_opens_a_new_session` | user_service README: "a gap of **two hours** between user messages opens a new session." This suite committed to exactly `SESSION_GAP_MS` opening a new session. | Exact 2h gap stayed in the original session. Strictly over 2h (tested separately) does open a new session, so the comparison is `>` not `>=`. | **Ambiguous spec.** The adapter/e2e reading was "more than 2 hours." The user_service sentence names the two-hour duration itself. Code implements exclusive-greater-than. Needs an explicit README decision. | `infra/firestore/repos/threads.py` (`_resolve` gap check) |
| 6 | `test_derive_on_read.py::test_influencer_funnel_moves_with_clicks_and_onboards` (retain step) | `startedAtMs` "pins the append to that session (no re-gap)." | Pinning `startedAtMs` to a session document that **does not yet exist** returns **500**: `_resolve` does `SessionRecord.model_validate(doc.to_dict())` on a missing doc (`None`). The retention append hit this by pinning the user's `createdAtMs` rather than a live session id. | **Code.** A pin should create that session or 404; a Pydantic `model_type` crash is not a documented contract. | `infra/firestore/repos/threads.py` (`_resolve`) |
| 7 | `test_idempotency.py::test_concurrent_claims_of_the_same_id_exactly_one_wins` | `claim` succeeds **exactly once** per Meta message id; concurrent claims of the same id: exactly one wins. | `create({})` under 8-way concurrency raised `google.api_core.exceptions.Aborted: 409 Transaction lock timeout` instead of returning `False` via `AlreadyExists`. Sequential duplicate still returns False. | **Code, with an emulator caveat.** `claim` only catches `AlreadyExists`. An `Aborted` lock timeout on the emulator (and possibly under production contention) leaks out of the idempotency boundary, so a retried webhook can 500 instead of no-op. | `infra/firestore/repos/message_claims.py:17` |

## Notes on this layer

- Hubble lazy-settlement matrix that **passed** as specified: 404 → failed + balance restored; FAILED / CANCELLED / REVERSED → failed + balance restored; PROCESSING → pending + debit held; SUCCESS with a voucher → succeeded + voucher fields stored; unknown status `FROBNITZ` → stays pending, no crash; `place_order` timeout after upstream SUCCESS → next `GET /rewards` settles, single gift-card row, no second `POST /orders`.
- Ambassador registry cascade **passed**: leftover `referrers/{handle}` after DELETE would have been caught by `test_delete_cascade_would_catch_a_dangling_ambassador_registry_entry`.
- Derive-on-read inverse **passed**: no stored `points` / `balanceInr` / funnel counters on referrer, campaign, or user documents.
- Failure-append tip **passed**: omitting `previousResponseId` leaves the last good Responses id in place.

---

# Pure derived-logic unit tests (`tests/unit/`)

Produced by the no-I/O suite over `user_service` gifting, influencers, ambassadors,
attribution, directory, and user-id derivation. Expected values were committed from
`user_service/README.md`, the campus-ambassadors skill ladder, frozen constants, and
the task brief *before* execution. Failing assertions were left failing.

Run: `.venv/bin/python -m pytest tests/unit -v` → **110 passed, 5 failed** (115 total).

| # | Test | Spec says | Code did | Likely wrong | Location |
|---|------|-----------|----------|--------------|----------|
| 1 | `test_user_id.py::test_plus_91_is_the_same_identity_as_digits` | README: `userId` is derived from **normalized** phone via keyed HMAC. `+919876543210` and stored `919876543210` are one WhatsApp identity. | Two different 32-hex ids (`c82b144f…` vs `f81d0671…`). HMAC is over the raw string; there is no digit/`+`/whitespace normalization. | **Code**, if any caller can pass a `+` prefix. If every caller already hands over WhatsApp digit form, this is a missing guard rather than a live split-brain — but the README's "normalized" claim is false of the function itself. | `infra/firestore/repos/users.py::_derive_user_id` |
| 2 | `test_user_id.py::test_spaces_in_the_phone_are_the_same_identity` | same normalization claim | `"91 98765 43210"` and `"  919876543210  "` hash to different ids than `"919876543210"` | **Code.** Same helper; spaces are significant. | same |
| 3 | `test_user_id.py::test_leading_zero_is_the_same_identity` | same | `"0919876543210"` hashes differently from `"919876543210"` | **Code.** Same helper. | same |
| 4 | `test_ambassadors.py::test_mint_handle_empty_name_raises` | A name with no Latin letters must raise (documented `ValueError` path for a stem-less name). Empty string has no Latin letters. | `IndexError: list index out of range` on `name.split()[0]` before the stem check. | **Code.** An empty (or whitespace-only) name crashes instead of the documented refusal. `"张伟"` and `"!!!"` do raise `ValueError` as specified. | `user_service/app/src/ambassadors.py:32` (`mint_handle`) |
| 5 | `test_influencers.py::test_campaign_spend_negative_onboards_does_not_pay_below_base` | Docstring: spend is never below `baseInr`. Negative onboards complete zero blocks, so spend is the base fee. | Returned **950** for `baseInr=1000`, `perBlockInr=50`, `blockSize=5`, `onboards=-1` (`-1 // 5 == -1`, then `1000 + min(-50, cap)`). | **Code.** Floor division on a negative onboard count pays *below* the base. Production counts are ≥ 0 so this is not a live money bug, but the "never below base" invariant is not actually enforced. | `user_service/app/src/influencers.py` (`_campaign_spend`) |

## Design finding that the tests *passed* (not a spec-vs-code mismatch)

| # | Test | What the spec arithmetic does | Why it is recorded | Location |
|---|------|------------------------------|--------------------|----------|
| D1 | `test_gifting.py::test_balance_inr_can_go_negative_when_spend_exceeds_earned` | `balance_inr(0, [succeeded ₹100]) == -100`. README: spendable balance is earned ₹ minus non-failed gifting amounts; no floor at 0 is documented. | The task asked to challenge whether balance can go negative. **It can.** The redeem path is supposed to refuse amounts the live storefront does not offer, which should prevent this in production — but the pure function has no floor, so any caller that skips `offered_amounts` (or settles a card after a concurrent earn-drop) can persist a negative wallet. | `user_service/app/src/gifting.py` (`balance_inr`) |

## Notes on this layer

- Money happy-paths matched the frozen ladder and the flexible/fixed storefront fork: cumulative earned ₹ (0 / 100 / 550 / 1450 / 3450), failed cards never spend, pending/succeeded debit, inactive / missing restrictions / empty instructions → `[]`, flexible ladder + exact balance, fixed denominations without injecting exact balance, campaign windows inclusive at both ends, misc click residual, referred-in-gap counts as started **and** onboarded.
- Phone-identity tests that **passed**: the same canonical `91XXXXXXXXXX` string is stable across calls; two distinct canonical mobiles do not collide; a rotated HMAC secret is a different identity space.

---

# Mutation referee (`mutmut` on the five derive-on-read modules)

Oracle remains the README / skill / type docstrings — not captured mutmut output.
Baseline (before killer tests): **448 killed / 103 survived / 13 no-tests / 1 timeout**,
score 81.3%. After KILLABLE tests: **553 killed / 11 survived / 0 no-tests / 1 timeout**,
score 98.0% (553/564). Full table: `tests/outcomes/MUTATION_BASELINE.md`. The 11 remaining
survivors are EQUIVALENT (justified there); they were not marked equivalent
to save effort.

No new spec-vs-code mismatch was introduced by the killer tests themselves;
they target untested I/O wrappers and two-event counts. Pre-existing unit
FINDINGS 1–5 stay red and are `--deselect`ed from the mutmut runner only
(a red test cannot be an oracle).

Coverage gaps the baseline proved (not implementation bugs until a spec
assertion fails):

| gap | what the spec requires | what was untested |
|---|---|---|
| `_settle` | lazy Hubble settlement on next read | 13 mutants with **no tests** |
| `derive_starts` | first registered mention across in-flight onboardings | entire function |
| `derive_influencer_report` | clicks and windows keyed by handle | entire function |
| `+= 1` funnel counters | two starts/onboards/retained in one bucket | single-item fixtures |
| directory `userId in blocked_ids` | blocked filter | page assembler never called |
| SUCCESS + empty `vouchers` | "settles with or without its voucher" | already FINDINGS (integration #2); not re-opened here |

EQUIVALENT mutants (separator join on a one-token stem, `ValueError` message
text, `zip(strict)` on equal-length `gather`, `_matches` join separator,
`or 0`→`or 1` inside the already-last None-timestamp bucket) are justified
in `tests/outcomes/MUTATION_BASELINE.md`. None were marked EQUIVALENT to save effort.

---

# Static analysis / quality gates task

Scope note: this section covers findings from the separate static-analysis/
quality-gates task (mypy/ruff/secrets/the two custom scripts/coverage). It
does not repeat the spec-vs-code findings documented above — those are
referenced by number, not duplicated, except where this task's tools
independently rediscovered the same bug from a different angle (worth
noting as cross-confirmation).

No application source was modified to produce any of these results.

## Baseline (real tool runs — commands and full output below)

Measured 2026-09-04 against commit `bde2e52` (branch `main`) using the
root `.venv` (`/Users/prince/Desktop/Sujho/sujho/.venv`, Python 3.13.15),
after `.venv/bin/pip install mypy ruff pytest-cov detect-secrets diff-cover`
(installed versions: mypy 2.3.1, ruff 0.16.6, pytest-cov 7.1.0,
detect-secrets 1.5.0, diff-cover 10.5.1). Every number below is from an
actual command run, output read in full — reproduce any of them with the
exact command shown.

### mypy --strict

Required scope, `user_service/app/src`:
```
.venv/bin/mypy --strict --follow-imports=silent user_service/app/src
```
→ **14 errors in 5 files** (checked 29 source files). `--follow-imports=silent`
type-checks only files under `user_service/app/src` itself and treats
imports from submodules (`infra.*`) as untyped-but-trusted, so this number
is "errors caused by user_service's own code."

Per-file breakdown:
| file | errors |
|---|---|
| `user_service/app/src/types/config.py` | 9 |
| `user_service/app/src/api/app.py` | 1 |
| `user_service/app/src/api/context.py` | 1 |
| `user_service/app/src/api/routes/users.py` | 1 |
| `user_service/app/src/directory.py` | 1 (`type-arg` on `tuple`) |
| `user_service/app/src/gifting.py`, `influencers.py`, `ambassadors.py`, `attribution.py` | **0** |

The 9 errors in `types/config.py` are one real bug repeated across 9 secret
fields (`Settings.from_env` passing unawaited coroutines where `str` is
expected) — see the finding below.

Same command, but following imports into `infra/` (no `--follow-imports=silent`):
```
.venv/bin/mypy --strict user_service/app/src
```
→ **61 errors in 27 files**. The extra 47 errors are all inside the `infra`
submodule, surfaced only because user_service imports it — recorded for
completeness, not part of the required scope.

Other services, same invocation style (`--strict --follow-imports=silent <pkg>`):
| module | errors | files w/ errors | files checked |
|---|---|---|---|
| `text_agent/app` | 18 | 5 | 20 |
| `whatsapp_adapter/app` | 61 | 16 | 42 |
| `document_worker/src` | 4 | 3 | 8 |
| `redirect_service/app` | 5 | 3 | 9 |

A recurring pattern across every service: `api/context.py` returns `Any`
from a function typed to return `AppState`, and `api/app.py` is missing a
return-type annotation. These look like a shared FastAPI-app-factory
template copied across services with the same two mypy gaps in each copy.

### ruff

Config: `[tool.ruff.lint] select = ["F","E","W","B","C4","SIM","UP","ASYNC","RUF006","RUF029"]`,
`preview = true` (required for RUF029 in ruff 0.16.x — see UNCERTAINTY.md).

```
.venv/bin/ruff check .
```
→ **495 errors** repo-wide (261 auto-fixable with `--fix`, not run — fixing
existing application source is out of scope for this task).

Top rule categories (`ruff check . --statistics`):
| rule | count | meaning |
|---|---|---|
| UP045 | 216 | `Optional[X]` → `X \| None` (pyupgrade) |
| E501 | 179 | line too long |
| UP035 | 14 | deprecated typing import |
| UP007 | 10 | `Union[X, Y]` → `X \| Y` |
| RUF029 | 9 | `async def` that never awaits anything |
| F401 | 9 | unused import |
| B905 | 9 | `zip()` without `strict=` |
| ASYNC109 | 5 | async function with a `timeout` param (should use structured timeout) |
| B008 | 5 | function call in a default argument |
| F821 | 5 | **undefined name** (real bug candidate, see below) |
| (18 more rules, 1-4 hits each) | 43 | — |

Per top-level directory (`ruff check <dir> --statistics`):
| directory | errors |
|---|---|
| `user_service` | 18 |
| `whatsapp_adapter` | 15 |
| `text_agent` | 2 |
| `document_worker` | 0 |
| `redirect_service` | 0 |
| `admin` | 0 (no Python files under it) |
| `knowledge_store` | 71 (includes the 5 F821 hits) |
| `infra` | 160 |
| `tests/` | 215 |
| `evals/` | 13 |
| root-level `run_*.py` scripts | 1 |

Directory counts sum to exactly 495, matching the repo-wide total — both
numbers come from real runs, not estimates.

### Secrets scanning (detect-secrets)

```
.venv/bin/detect-secrets scan --all-files \
  --exclude-files '\.venv/|(^|/)\.git/|(^|/)__pycache__/|(^|/)Data/|(^|/)evals/reports/|(^|/)\.(mypy|ruff|pytest)_cache/|^\.env$' \
  > .secrets.baseline
```
→ 12 files flagged, all manually reviewed and confirmed false positives —
see the "Secrets scan" finding below.

`.env` was excluded from the scan (`^\.env$`) rather than baselined,
because it is not a false positive — see the ".env" finding below.

Note on scope: because this repo is a git-superproject with submodules, a
plain `detect-secrets scan` (git-tracked-files-only, the tool's default)
sees almost nothing — root `git ls-files` lists 47 paths, most of them
directory names for submodule gitlinks or files like `ci/*.yaml`; it does
not descend into submodule content or into `tests/` (untracked in the root
repo as of this baseline). `--all-files` (scanning the real working tree)
was required to get a meaningful scan.

### tests/tooling/check_test_methods.py

```
.venv/bin/python tests/tooling/check_test_methods.py
```
→ **exit 0** — `OK: all critical modules carry their required markers.`
All five critical modules (`gifting.py`, `influencers.py`, `ambassadors.py`,
`attribution.py`, `directory.py`) currently have a matching
`tests/unit/user_service/test_<module>.py` file carrying every required
marker. This is a change from an earlier assumption that these test files
didn't exist yet — see UNCERTAINTY.md "Discrepancy vs. task brief." The
script itself was verified against a synthetic failing fixture during
development to confirm it does correctly detect a missing-marker case
before trusting this green result.

### tests/tooling/check_assertions.py

```
.venv/bin/python tests/tooling/check_assertions.py
```
→ **exit 0** — `OK: no test function relies solely on weak assertions.`
Walked all of `tests/unit/`, `tests/api/`, `tests/integration/`,
`tests/e2e/` (every `test_*.py`). Zero offending functions found. Verified
against a synthetic fixture with 3 deliberately weak-only tests, 1 mixed
test, and 1 strong test — the script flagged exactly the 3 weak-only ones
and spared the other 2, confirming it is not a silent no-op.

### Test suites actually run, and coverage

| suite | command | result |
|---|---|---|
| unit | `pytest tests/unit -c tests/unit/pytest.ini` | 110 passed / 5 failed (all 5 pre-existing, documented above) |
| api | `pytest tests/api -q` | 152 passed / 13 failed under `tests/api/user_service` alone (all pre-existing/documented above); plus 2 failed in `document_worker`, 1 in `text_agent`, 0 in `redirect_service`, 0 in `whatsapp_adapter` |
| integration | `pytest tests/integration -q` | **could not run** — see below |
| e2e | `pytest tests/e2e -q` | **could not run** — see below |

Integration/e2e: both suites bootstrap a Firestore emulator via
`gcloud emulators firestore start`, which requires a real Java 8+ JRE.
`java -version` in this sandbox reports "Unable to locate a Java Runtime"
(the `/usr/bin/java` on PATH is the macOS stub that prompts an install, not
a real JRE), and no `firebase` CLI is present either. This is a real,
reproducible environment gap, not a fabricated excuse — confirmed by
running both suites and reading the actual `pytest.outcomes.Exit` error:
`"Unable to execute the java that was found on your PATH."`

Coverage (the only real, measured number):
```
.venv/bin/python -m pytest tests/unit tests/api -c tests/unit/pytest.ini \
  --cov=user_service/app/src --cov-branch --cov-report=term-missing -q
```
→ **90% total** (687 statements / 58 missed; 76 branches / 6 partial),
328 passed / 21 failed (failures are the same pre-existing, documented
mismatches — coverage is measured regardless of pass/fail).
`[tool.coverage.report] fail_under` is set to **90** in `pyproject.toml` to
match this exact measured number (not rounded up, not aspirational).

Lowest-covered files in that run: `user_service/app/src/corpus.py` (31%),
`user_service/app/src/api/routes/institutions.py` (56%),
`user_service/app/src/api/routes/threads.py` (71%),
`user_service/app/src/attribution.py` (71%) — the 71% on `attribution.py`
is coverage of lines 35-39, the untested exception-path branch noted
informally during this run; not separately investigated further since
fixing/adding tests is out of this task's scope.

## 1. Real bug: `Settings.from_env()` never awaits `SecretReader.get` — every secret field is stored as an unresolved coroutine, not a string

`user_service/app/src/types/config.py:29-47`:

```python
@classmethod
def from_env(cls) -> Settings:
    gcp = GcpIdentity.from_env()
    secrets = SecretReader(gcp)
    return cls(
        gcp=gcp,
        users_service_secret=secrets.get("USERS_SERVICE_SECRET"),
        ...
    )
```

`mypy --strict` flags all 9 keyword arguments here as
`error: Argument "..." has incompatible type "Coroutine[Any, Any, Never]";
expected "str"  [arg-type]`, each with `note: Maybe you forgot to use
"await"?`. Confirmed by reading `infra/platform/secrets/client.py`:
`SecretReader.get` is declared `async def`. `from_env` is a plain
(non-async) classmethod that calls it directly and hands the resulting
coroutine object straight into the `Settings` Pydantic model.

This is not a type-checker false alarm: if `from_env` is ever called as
written, every one of `users_service_secret`, `user_id_hmac_secret`,
`public_origin`, `hubble_api_origin`, `hubble_client_id`,
`hubble_client_secret`, `conversation_media_bucket`, `neo4j_uri`,
`neo4j_user`, `neo4j_password` on the resulting `Settings` object is a
`<coroutine object SecretReader.get at ...>`, not the secret string —
pydantic does not statically type-check field assignment the way
`mypy --strict` does, so this would silently pass model construction and
only blow up (or worse, get formatted into something like
`"<coroutine object ...>"` and used as a literal broken origin/secret)
wherever the field is actually used.

Left red per the task's discipline — no `# type: ignore`, no source edit.
If `from_env` is dead code (never called, superseded by a different async
bootstrap path), that's worth confirming; if it's live, this is a
startup-breaking or silently-wrong-secrets bug.

## 2. Real bug: two undefined names in `knowledge_store/textbooks/extractor.py`

`ruff check` (`F821 undefined-name`) flags:
- `knowledge_store/textbooks/extractor.py:48` — `StageRun` used as a type
  annotation but never imported or defined in this file.
- `knowledge_store/textbooks/extractor.py:52` — `shard_index` called but
  never imported or defined in this file.

```python
async def run(self, stage: StageRun, task_index: int, task_count: int) -> None:
    ...
    assigned = [c for c in raw_chapters if shard_index(c.chapter_key, task_count) == task_index]
```

Both names read as though they belong to a module (a stage-runner protocol
and a sharding helper) that either used to be imported here and the import
was dropped, or was never wired up. Calling `.run(...)` on this class today
raises `NameError` before it gets anywhere near the sharding logic — this
is a hard runtime failure, not a style nit. Left unfixed per scope; flagged
here as the single most actionable ruff finding.

## 3. Secrets scan: 12 flagged locations, all confirmed false positives (manually reviewed, not just pattern-guessed)

| file | what triggered it | why it's not a secret |
|---|---|---|
| `infra/pyproject.toml:94` | Secret Keyword | package-map entry `"infra.platform.secrets" = "platform/secrets"` — the word "secrets" in a module path, no value |
| `knowledge_store/README.md:67` | Secret Keyword | documentation prose listing *names* of Secret-Manager-backed env vars (`NEO4J_PASSWORD`, etc.), not values |
| `user_service/app/src/constants.py:41` | Base64 High-Entropy String | `HANDLE_SUFFIX_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"` — a literal alphabet constant for handle generation, not a key |
| `tests/api/document_worker/conftest.py:25` | Secret Keyword | `SERVICE_SECRET = "test-document-worker-service-secret"` — self-labeled test fixture |
| `tests/api/text_agent/conftest.py:21` | Secret Keyword | same pattern, test fixture |
| `tests/api/user_service/conftest.py:47,612,616` | Secret Keyword (x3) | `USERS_SERVICE_SECRET = "test-users-service-secret"` and siblings — test fixtures |
| `tests/api/whatsapp_adapter/conftest.py:36-37` | Secret Keyword (x2) | test fixture secrets |
| `tests/e2e/servers.py:167,171,253` | Secret Keyword (x3) | test-harness fixture secrets used to spin up fake service processes |
| `tests/e2e/test_webhook_signature.py:54` | Secret Keyword | test fixture |
| `tests/integration/conftest.py:214,218` | Secret Keyword (x2) | test fixtures |
| `tests/unit/user_service/factories.py:52,55` | Base64 High-Entropy String + Secret Keyword | `HMAC_SECRET = "unit-test-users-user-id-hmac-secret"` — test fixture, plus the same `HANDLE_SUFFIX_ALPHABET` constant re-imported |
| `tests/api/redirect_service/test_health_version.py:38` | Hex High-Entropy String | `monkeypatch.setenv("RELEASE_COMMIT_SHA", "abc123deadbeef")` — a fake commit SHA in a test |

No true positive was found among git-tracked / working-tree source.

## 4. MAJOR finding: root `.env` contains what read as live, non-placeholder credentials

`/Users/prince/Desktop/Sujho/sujho/.env` (gitignored — confirmed via
`git check-ignore -v .env`, so it is **not** committed and never reaches
CI or the pre-commit hook) contains, among blank/placeholder entries:

- an `OPENAI_API_KEY` in the `sk-proj-...` format
- a `DEEPSEEK_API_KEY` in the `sk-...` format
- a `NEO4J_PASSWORD` value
- a `GEMINI_API_KEY` value

These are **not reproduced here** (deliberately redacted) — see the file
directly, lines 8-10 and 20, if you need to confirm/rotate them. All four
have the shape of real, live provider credentials rather than obvious
placeholders (`sk-proj-` prefixes, plausible-length hex/base64 payloads),
and the file's own comments ("Paste these. Leave blank to use Secret
Manager") confirm the intended workflow: developers paste real keys here
for local override, and production reads from Secret Manager instead.

Because the file is gitignored, this task's CI/pre-commit secrets gate
(which only ever sees committed content) cannot leak it further — that
part of the design is sound. But the file's *existence on this machine's
disk*, with what read as real values, is itself a real exposure surface
(shell history of whoever pasted them, local backups/sync tools, screen
shares, `cat`/`env` output, etc.) independent of git. This is a judgment
call for the team, not something this task's tooling can or should
silently fix:
- If these are genuinely live keys: rotate them and confirm no other copy
  exists (this task did not search further than the working tree for other
  copies — see UNCERTAINTY.md).
- If they're intentionally-scoped low-privilege dev/sandbox keys, the risk
  is lower but the file should still probably not hold a long-lived
  production-adjacent secret like a Neo4j password in plaintext locally.

## 5. Pre-existing test failures rediscovered by this task's baseline runs (already documented above — not new findings, listed here only because the baseline numbers reference them)

Running `pytest tests/unit` and `pytest tests/api` for the coverage
baseline surfaced 5 unit-test failures and 13 `user_service` API-test
failures. All 5 unit failures match this file's "Pure derived-logic unit
tests" section rows 1-5 exactly (phone-normalization `userId` mismatches,
`mint_handle("")` raising `IndexError` instead of `ValueError`,
negative-onboards `_campaign_spend` paying below the documented base fee).
All 13 API failures match this file's `user_service` API-test section.
These are cross-confirmed, not re-litigated, by this task's tool runs.

Two suites this task ran that the rest of this file doesn't cover:
`tests/api/document_worker` (2 failed / 15 passed) and
`tests/api/text_agent` (1 failed / 11 passed). These were not
independently root-caused here (out of scope: this task builds tooling,
not test analysis) — flagged so whoever looks at this file next knows they
exist. Commands: `pytest tests/api/document_worker -q` and
`pytest tests/api/text_agent -q`.

## 6. Judgment call: integration/e2e suites are "best-effort" in CI, not blocking

`tests/integration` and `tests/e2e` both require a Firestore emulator,
which requires a real JRE. This sandbox has no usable JRE (`/usr/bin/java`
is the macOS "install Java" stub), so neither suite could be run here at
all — confirmed by executing both and reading the actual
`gcloud.emulators.firestore.start` error, not assumed.

`.github/workflows/checks.yml` adds a `setup-java` step and runs both
suites with `continue-on-error: true`, i.e. CI will attempt them on every
run (GitHub-hosted runners have `gcloud` preinstalled and `setup-java` is a
one-line fix for the JRE gap this sandbox has), but a failure there won't
block a PR. This is a deliberate tradeoff, not an oversight: making these
suites hard-blocking before confirming they're reliably green in the actual
CI environment (untested from this sandbox) risks a flaky merge-blocking
gate; leaving them off entirely would silently regress integration coverage
over time with no signal at all. The middle ground picked here is "always
run, always visible, not yet load-bearing." See
`.github/workflows/checks.yml`'s inline comment on that job step and
UNCERTAINTY.md for the confidence level on this choice.

---

# Adapter service-layer unit tests (`tests/unit/whatsapp_adapter/`)

Produced while covering `whatsapp_adapter/app/src/service/` with no-I/O unit
tests (`gate.py`, `turns.py`, `onboarding.py`). Expected values were taken from
`whatsapp_adapter/README.md` before execution. Every test below was then
mutation-checked: a real bug was injected into product code, the test was
confirmed to fail, and the mutation was reverted (submodule verified clean).

## Latent silent-drop in the pending-action state machine

| # | Behavior | What happens | Why it is recorded | Location |
|---|----------|--------------|--------------------|----------|
| S1 | `OnboardingCoordinator._represent` matches on `pending.action` with arms for `select_persona`, `student_flow`, `teacher_flow` only. | Reached with `resolve_phone` (or any future fifth action), no arm matches: the buffered copy is computed and then discarded, nothing is persisted, nothing is sent, nothing raises. The sender's message disappears in silence. | **Not a live bug.** `handle`'s earlier `case PendingAction(action="resolve_phone"), _` always intercepts first, and `_launch_flow` only ever passes `select_persona`. `PendingActionName` is a closed 4-value `Literal`, so all four are covered today. It is recorded because nothing verifies the invariant: the function returns `None`, so mypy cannot flag a missing arm even in principle, and mypy's gate scope (`user_service/app/src`) excludes this service entirely. The protection is arm *ordering* in one function. | `whatsapp_adapter/app/src/service/onboarding.py:104-113` (`_represent`); guarded by `:73-83` (`handle`) |

Closed by `test_onboarding.py::test_no_pending_action_ever_answers_a_stray_message_with_silence`,
which is parametrized off `get_args(PendingActionName)` rather than a hand-written
list, so adding a fifth action fails the suite instead of silently swallowing
conversations. Verified by renaming the `teacher_flow` arm: the test failed with
"a stray message during teacher_flow got silence".

## The hidden-number invariant holds across a file boundary

`mypy --strict --follow-imports=silent whatsapp_adapter/app/src/service/` reports
**7 errors** (run manually; this path is outside the `stage_static` mypy scope).
Three are the same latent shape as S1 — a `str | None` phone flowing into
parameters that require `str`:

| # | Call | Declared | Passed | Why it does not fire today | Location |
|---|------|----------|--------------|---------------------------|----------|
| S2 | `WhatsAppClient.send_buttons(to=...)` | `str` | `inbound.sender_phone` (`str | None`) | `TurnGate.process` returns early on `phone is None` before `handle` is ever called, so `_ask_persona` only runs for senders with a known number. A contact-share inbound has its `sender_phone` rewritten from the card by `_normalize_contact_message`, so that path is covered too. | `onboarding.py:138`, guarded by `gate.py:50-53` |
| S3 | `FlowLauncher.onboarding(sender_phone=...)` | `str` | same | same guard | `onboarding.py:143` |
| S4 | `profile_input_from_flow(phone=...)` | `str` | same | same guard | `onboarding.py:154` |
| S5 | `TurnGate._resume_after_phone` / `_dispatch` (`user`) | `UserProfile` | `access.user` (`Optional`) | Relies on the user service never returning `status="allowed"` with `user=None`. If it did, the failure is **loud** — pydantic raises on `TurnInput` construction — not silent. Confirmed incidentally while mutation-testing the blocked-sender arm. | `gate.py:63,65` |

The remaining two mypy errors are benign: a `list`-vs-`Sequence` variance
complaint in `runner.py:54`, and a `Literal` inference artifact at
`onboarding.py:128` where `persona` is widened to `str` by tuple assignment.

**The pattern worth a decision:** the adapter leans on type-level invariants
(closed `Literal`s and unions, plus non-`None` guarantees established by an
early return in a *different* file), and no tool checks them here. Either widen
the `stage_static` mypy scope past `user_service/app/src`, or accept that these
invariants are test-enforced only. The invariant test above covers S1; S2-S4 are
covered indirectly by
`test_gate.py::test_a_hidden_number_is_asked_for_its_phone_and_yields_no_turn`,
which pins the early return that makes them safe.

Measured scope of the pattern: with the service package at 99% branch coverage,
**every one of the five remaining partial branches is the same construct** -- a
`match` with no fallback arm, unreachable only because its subject type is
closed. None is a test gap; all five are reachable the moment a union or
`Literal` gains a member without a matching arm:

| Partial branch | Match subject | Closed by |
|----------------|---------------|-----------|
| `gate.py` `64->exit` | `access.status` | `AccessStatus` (3 values) |
| `gate.py` `97->99` | the inbound message | `InboundMessage` union (5 kinds) |
| `onboarding.py` `112->exit` | `pending.action` | `PendingActionName` (4 values) |
| `inputs.py` `84->80` | one buffered message | `ConversationalMessage` union (2 kinds) |
| `inputs.py` `101->exit` | the Flow route | `FlowAgentRoute` (2 values) |

Of these, `inputs.py` `84->80` is the one most likely to bite: a third
conversational message kind (a sticker or reaction becoming replayable) would
drop that message from the onboarding replay in silence, with no send, no
persist, and no error -- the same failure shape as S1 but on the user's own
words rather than on a prompt.

---

# Adapter output-layer unit tests (`tests/unit/whatsapp_adapter/`, Wave C)

## The return type is what decides whether a non-exhaustive `match` is a silent bug

The five partial branches above are *not* equivalent to the one in
`replies.py` `_send` (`110->exit`), even though the construct looks identical —
a `match` over a closed union with no fallback arm. The difference is the
declared return type, and it is the whole story:

| Shape | Missing arm behaves as | mypy |
|---|---|---|
| `def f(...) -> str` (`replies.py::_send`) | falls through, returns `None`, violating the annotation | **caught** — `Missing return statement` |
| `def f(...) -> Optional[X]` (the five above) | falls through, returns `None`, satisfying the annotation | **not caught** — nothing is "missing" |

Verified rather than assumed: deleting the `case ContactMessage():` arm from
`_send` makes mypy report `replies.py:67: error: Missing return statement`,
and restoring it returns to `Success: no issues found`. So `_send`'s partial
branch is genuinely unreachable and *statically proven* so — it needs no test
and no fallback arm.

**This turns the earlier "pattern worth a decision" into a concrete, cheap
product fix.** The five service-layer hazards do not need fallback arms, a new
gate, or invariant tests one at a time. Narrowing each function's return type
from `Optional[X]` to `X` — where the code already guarantees non-`None`, which
is exactly what makes those branches unreachable — converts all five from
invisible to compile-time errors. `OnboardingCoordinator._represent` is the
clearest case: it always sends and persists, so it has no reason to be
`Optional`.

Not acted on: this is product code. Recorded for the owner.

## Delivery ordering is enforced by consequence, not by a call count

`ReplyDelivery.send` has two ordering invariants that a per-collaborator
assertion cannot see, because each fake only witnesses its own half:

1. the reaction is sent before any bubble, and
2. each bubble is confirmed before the next is sent, while the last is never
   waited on.

Both are tested through a single `timeline` list shared by `FakeWhatsApp` and
`FakeConfirmations`, so the oracle is one interleaved sequence
(`sent:… → confirmed:… → sent:…`). This was deliberate: rewriting `send` to
fire every bubble first and confirm them all afterwards leaves every
per-fake count and membership assertion true, and is caught only by the
interleaving. It is the same weakness class as the Wave B send-before-record
bug, found by the same lens.

## `FlowLauncher.launch` is the one match where deleting an arm *removes* a mypy error

A sixth instance of the closed-`match` pattern, and the worst-behaved one.
`launch` assigns `flow_id`, `screen`, and `data` inside the match and uses them
after it, so a missing arm leaves all three unbound:

- Removing `case GradeFormMessage():` does **not** produce a mypy error. It
  produces `Success: no issues found` — mypy's error count goes from **2 to 0**,
  because the two pre-existing `None`-into-`str`/`dict` assignment errors live
  on the very line that was deleted.
- So the incentive is backwards: the change that breaks grading at runtime also
  makes the type checker happier than it is today.
- The runtime failure is at least loud — `UnboundLocalError` on `flow_id`, not a
  silent `None` — but it happens per-launch, in production, for one persona's
  one form.

Caught by 8 tests in `test_launcher.py`, including both
`test_each_form_launches_that_personas_published_flow[*-grade]` cases. This is
the clearest example so far of coverage and type-checking each being blind where
the other sees: `launcher.py 58->63` is an unreachable partial branch that no
type is closing.

Root cause of the 2 baseline errors, for whoever fixes them: `screen` and `data`
are inferred from the *first* arm (`str` and `dict[str, Any]`) and then assigned
`None` in the others. Annotating them up front —
`screen: str | None` and `data: dict[str, Any] | None` — clears both errors
without changing behaviour, and is the prerequisite for making this match
exhaustiveness-checkable.

## Wave C tightening (oracle honesty)

A pass against `MIRRORED_AND_WRONG.md` found no WRONG tests and several
mirrored oracles. Tightened in place; product code untouched.

- `test_replies.py` claimed the README said "confirm each bubble before the
  next." That sentence is a comment in `replies.py`, not the README. Module
  docstring now splits README claims from the barrier implementation pin.
- README's italic sources rollup was untested: the factory always sent
  `sources=[]`. `sources_record(..., pages=[SourceMeta(...)])` now exists.
  `test_cited_pages_open_the_sources_block_as_an_italic_rollup` asserts a
  `_…_` text bubble naming the cited book, then the url buttons. Dropping
  the footer from `_bubbles` fails that test only.
- `data == institution_screen_seed()` compared the launcher to its own helper.
  Replaced with `{"query": "", "results": [], "hasResults": False}`. Changing
  the helper to `hasResults=True` now fails both seed tests; the old equality
  would have stayed green.
- Canned CTA/body assertions now check relationships (distinct CTAs, name in
  the body) instead of `== CANNED_RESPONSES…`. Gift-card tests assert brand,
  amount, and omitted nulls, not the exact `*brand gift card — ₹N*` header.
- Skip-last wait, CAPI event names, and frozen Flow tokens are labeled as
  implementation/Meta pins. They stay; they are not README sentences.

---

# Wave D — input layer (`whatsapp_adapter/app/src/input/`)

Unit coverage of the input package went from dark media/uploads/attachments
to **99%** (254 stmts, 4 remaining branch partials, all `match` fall-throughs:
`media.py 80->exit`, `attachments.py 40->exit`, `profiles.py 33->exit` and
`57->exit`). `flows.py` / `webhook.py` / `message.py` were already 100% from
Wave B; those tests were not duplicated.

New files: `test_media.py`, `test_attachments.py`, `test_uploads.py`,
`test_profiles.py`. Adapter unit **320** green (was 288). Collected **788**.

## README vs code

whatsapp_adapter README Key Files says `MediaFetcher` "downloads WhatsApp
media, normalizes MIME, stores in GCS". Audio does **not** store: it
transcribes. The sentence that actually specifies the model-visible contract
is in `text_agent/README.md`: "Voice notes are transcribed in the adapter
before they become rows; rejected or oversized attachments arrive as
synthetic `[attachment unavailable]` text." Wave D follows that sentence,
not the Key Files row. The adapter README's grade-form row ("Fetch uploaded
papers/sheets") and profile-update row (persist institution and scope) are
the other two ANCHORED claims.

## Mutation audit (one bug, run, revert; submodule left clean)

| Mutant | Killed by |
|---|---|
| Download before `_admit` | video and zip refuse-before-download tests |
| Audio `store_inbound` instead of transcribe | voice-note text + no-upload tests |
| `list(usage)` copy into the transcriber | billed-onto-caller's-list test |
| Drop captions | caption-after-attachment tests |
| Skip plaintext SHA-256 | wrong-plaintext-hash test |
| Skip HMAC | wrong-HMAC test |
| HMAC suffix constant `10 → 9` | round-trip (sealer pins Meta's 10, not the product constant) |
| Question papers stored as `image/jpeg` | papers-as-pdfs / slot-order tests |
| Answer sheets gathered before papers | slot-order type sequence |
| Empty `institutionId` kept as `""` | unlisted-school `id is None` |
| `name.strip()` removed | create-input strips typed name |
| Student/teacher match arms swapped | student-one-grade / teacher-grades-list |
| Skip `compress_image_bytes` | photo test, **after** tightening (see below) |

## Tightening found by a surviving mutant

`test_a_photo_is_stored_as_jpeg` originally fed `jpeg_bytes()` labeled as
`image/png`. Skipping compression kept JPEG SOI and the test stayed green.
The input is now `png_bytes()` (`\x89PNG…`); stored bytes must be JPEG SOI
and must differ from the original. The skip-compress mutant then dies.

HMAC suffix is pinned as `META_HMAC_SUFFIX_BYTES = 10` in the test sealer,
not imported from `constants.py`. Changing the product constant no longer
agrees with itself.

## Wave D tightening (oracle honesty)

The first Wave D pass left two mutants that the existing tests did not
uniquely kill:

- **Document cap copied onto images.** `_oversize` using
  `MAX_BYTES_BY_KIND.get(kind, document_limit)` left the tiny-JPEG image
  test green. `test_a_photo_larger_than_the_document_ceiling_is_still_stored`
  pads a real JPEG past the document cap; PIL still opens the trailing
  bytes. That mutant now dies; the tiny-image test still would not catch it.
- **Skip encrypted SHA-256.** Tampering the ciphertext still raised HMAC
  mismatch, so the round-trip and (once loosened) tamper tests stayed
  green. `test_a_wrong_encrypted_hash_is_rejected` is the unique kill.
  The tamper test now asserts `ValueError` without pinning which check
  fired first — each hash/HMAC check has its own metadata test.

Also tightened in place:

- Zip refuse uses the handwritten `[attachment unavailable] …` string, not
  a substring.
- Transcription billing asserts `wiring.usage is marker` (same list object)
  plus the billed item.
- Answer sheets start as PNG, same as inbound photos, so skip-compress
  cannot hide behind bytes that were already JPEG.
- Student/teacher writes use distinct in-test payloads (grade 6 vs
  grades [11, 12]) instead of shared factory numbers. Update writes assert
  `name is None` so they cannot silently become creates.

## Left open (not a product edit)

- The four remaining coverage partials are the same closed-`match` shape as
  Wave C: `kind: str` / `Persona` is not a Literal the type checker can
  exhaust, so deleting an arm is a silent `None` at runtime. Tests cover
  every live arm; nothing static does.

---

# Wave E — Flow data-exchange (`whatsapp_adapter/app/src/flows/`)

`copy.py` was already 100% from Wave A. This wave covered the data endpoint
payloads and the RSA/AES envelope helpers. Package is **133 stmts / 26
branches, 100%**. Adapter unit **340** green (was 320). Collected **808**.

New files: `test_flow_onboarding.py`, `test_flow_grade.py`,
`test_flow_crypto.py`. HTTP 422/421 for the same routes stay in
`tests/api/whatsapp_adapter/test_flows.py` — not duplicated.

## README vs Meta pins

ANCHORED: POST `/flows/onboarding` and `/flows/grade` are the encrypted data
endpoints; a grade completion must carry the uploaded papers/sheets (dropping
`**payload["data"]` empties that). The empty `institutionId` for a typed-in
school is the same Wave D rule.

Ping `{data: {status: active}}`, INIT screen ids (`INSTITUTION_SCREEN`,
`QUESTION_PAPER`), SUCCESS `extension_message_response`, AES-128-GCM tag
length 16, and the response IV XOR `0xFF` are Meta Flow protocol / published
JSON, not README sentences. Handwritten so a product constant cannot agree
with itself.

## Mutation audit (one bug, run, revert)

| Mutant | Killed by |
|---|---|
| `{institution}` match arm before `{institutionChoice, institution}` | listed-school / not-listed stay on INSTITUTION_SCREEN |
| `not_listed` stored as the directory id | empty-id test |
| Student grade seeded as 11–12 | "Grade 8" label + science vs accountancy |
| Query not stripped | blank query / stripped query tests |
| Drop `**payload["data"]` | question_paper missing on SUCCESS |
| `route: "documents"` | grade completion `route == "grade"` |
| Skip response IV flip | opens-under-flipped-IV and does-not-open-under-request-IV |
| GCM tag constant `16 → 15` | request round-trip (sealer pins Meta's 16) |

API `api/` (app, routes, envelopes) remains 0% from the unit suite — those
paths are the existing API tests. `types/config.py` 35-37 is Settings.from_env.

## Wave E tightening

`test_choosing_a_listed_school` asserted `institution` was truthy. Using the
typed string `"ignored typed name"` instead of `school.name` stayed green.
The expected name is now the directory row (`get_school(chosen["id"]).name`),
and must not equal the typed string. That mutant now dies.

---

# Phase 2 — `infra/schools` (directory the user searches)

Eight tests in `tests/unit/infra/test_schools.py`. Collected **816**. No
product edits.

Oracles: user_service README (directory id is a real campus); `School.place`
field meaning (address is not the subtitle); dataset rows pinned by unique
id (Ambah `1000105`, Village `1031219`, P.D. Jain `1130370`); documented
initials merge (`P D` → `P.D.`). Not oracles: rapidfuzz / heapq copies of
`search_schools`.

## Mutation audit

| Mutant | Result |
|---|---|
| `get_school` always `SCHOOLS[0]` | killed — id/name + unknown KeyError |
| `nlargest` → `nsmallest` | killed — unique name is **first**, not merely present |
| `limit + 5` | killed by cap test only; ranking test stayed green |
| Skip `normalize_text` | killed by initials (`P D` vs `P.D.`) and by title-case Ambah |
| `place` includes address | killed |
| Join empty locality | killed by leading-comma test only |

**Weak end caught in this wave.** A SHOUTY / comma Ambah query still ranked
Ambah first *without* `normalize_text` (rapidfuzz already folds case). That
test was deleted. The initials query is the fold only our normalizer does.

**Residual, left unlabeled as a contract.** Dropping either the identity
score or the context score still ranks a unique full name first. There is
no README for the rapidfuzz sum. Freezing “both terms required” would
mirror `catalog.py`. Not added.

---

# Phase 2 — `infra/curriculum` (subjects the Flow offers after a grade)

Eight tests in `tests/unit/infra/test_curriculum.py`. Collected **824**
(unit **521**). No product edits.

Oracles: handwritten NCERT splits a student would recognise (class 8 has
Science, not Accountancy; 11–12 the reverse; class 3 has The World Around
Us, not Science; Knowledge Traditions is 11-only). Checkbox `id`/`title`
pairs are handwritten strings so `subject.value` / `subject.title` cannot
agree with themselves. Not an oracle: reconstructing
`subjects_for_grade` from `Subject.*.grades`.

Skipped in this wave: `include_book` and `resolve_ncert_subject` (overnight
ingest / knowledge_store, not the onboarding picker).

## Mutation audit

| Mutant | Result |
|---|---|
| `subjects_for_grade` returns every `Subject` | killed by the “not in” sides |
| Union without `dict.fromkeys` | killed only by the duplicate-checkbox test |
| Union = first grade only | killed only by the 8+11 union test |
| `subject_options` swaps id/title | killed by the two option tests; grade membership stayed green |
| `subject_options` sorts by slug | killed only by the order test |

**Weak end caught in this wave.** The first order fixture was Accountancy
then Science, which is already alphabetical by slug. Sorting would have
survived. Replaced with Science-then-Accountancy so a sort swaps them.

**Not tested, on purpose.** `include_book` / `resolve_ncert_subject` are
ingest, not the WhatsApp picker. Phase 2 as defined (schools + curriculum
onboarding catalog) is complete.

---

# Phase 3 — rest of `infra` (gaps only)

`infra/api` `/health` `/version` already has five API-suite copies (one per
service). Firestore `threads` / `gifting` / `blocklist` / `claims` already
run against the emulator in `tests/integration`. Those were not duplicated.

Twelve new tests. Collected **836** (unit **533**). No product edits.

## `Lease.blocks` — ingest mutex

`tests/unit/infra/test_leases.py`. knowledge_store holds GRAPH_LEASE through
this rule. Oracle is the type docstring (another token blocks only while
live). Not an oracle: a fake Firestore replay of `_claim`.

| Mutant | Result |
|---|---|
| `now_ms < expires` → `<=` | killed only by the expiry-instant test |

## Client wire paths the running products call

`tests/unit/infra/test_clients.py`. Oracle: user_service / text_agent /
document_worker README route tables, handwritten. Adapter calls covered:
`resolve_phone`, `create_user`, session replay, append, location, profile
overlay, gift-card GET. Plus `POST /respond` and `POST /render`.

| Mutant | Result |
|---|---|
| `/internal/access/phone` → `/phones` | killed only by the resolve-phone test |

**Not in this wave, on purpose.** Admin influencer/campaign client methods
(no WhatsApp caller). `LeasesRepository.hold` I/O (needs the emulator).
Shared ops router (already in `tests/api`).

