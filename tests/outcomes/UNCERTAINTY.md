# UNCERTAINTY REPORT

Honest accounting of guesses, assumptions, and untested territory in `tests/e2e/`.
If this list were empty it would be a red flag, per the test-writing rules — it isn't.

## Where the spec didn't define behavior, and I guessed

- **Journey 15 boundary mechanism — exactly-2h reading RESOLVED.** The README doesn't say
  whether the WhatsApp webhook `timestamp` or server processing time governs the 2-hour
  session-gap boundary. Building the test surfaced that the code uses processing time /
  previously-stored `createdAtMs`, not the webhook timestamp (see FINDINGS.md #3) — and Meta
  webhook timestamps are unix **seconds**, so millisecond-precision boundary testing
  (exactly 2h vs 2h+1ms) isn't reachable through a real webhook POST regardless. The
  boundary test instead drives user_service's real transcript-append route directly with
  explicit `createdAtMs` values (the exact field `ThreadsRepository._resolve` reads),
  bypassing the webhook layer for this one journey — that harness limitation stands, it is
  still not testing the webhook clock. The exactly-2-hours expectation itself, though, was
  flipped: the old version asserted "same session" (matching the code's exclusive `>`,
  which is what let it pass silently) while the sibling `tests/integration/
  test_session_boundary.py::test_gap_exactly_two_hours_opens_a_new_session` asserted the
  opposite and was red — two tests silently disagreeing about the same README sentence.
  `tests/e2e/test_session_gap.py::test_session_gap_boundary` now asserts "new session" at
  exactly 2h, matching the README's plain reading ("a gap of two hours... opens a new
  session") and the integration suite instead of contradicting it. It now fails against
  current code, same as its sibling — see MIRRORED_AND_WRONG.md.

- **Journey 12 (unsupported type) — RESOLVED, split into two tests.** The README says
  "Unsupported message type → Ignore and return 200." `_normalize_message` fully drops
  `"reaction"` (returns `None`, never claimed/dispatched), but converts genuinely-unrecognized
  types (e.g. `"order"`) into an `UnsupportedMessage`, which *does* run one agent turn via
  `AgentInputBuilder.unsupported()` — not silently ignored. The old test used `type:
  "reaction"` to match the README's literal claim, which was the WRONG case (see
  MIRRORED_AND_WRONG.md): "reaction" is a different, already-dropped branch, not what the
  Test Matrix row is describing. Both `tests/api/whatsapp_adapter/test_webhook_validation.py`
  and `tests/e2e/test_blocking_and_failures.py` now carry two tests each:
  `test_reaction_message_is_dropped[...]` (kept, still passes, relabeled) and
  `test_un{recognized,supported}_message_type_is_ignored[...]` (new, uses a genuine
  unrecognized type via `payloads.unrecognized_type_webhook` / `payloads.
  unrecognized_message_type_webhook`, asserting the README's literal "ignore" claim — fails
  against current code, confirming the agent-turn behavior described above is real, not a
  guess).

- **Journey 16 points/tier formula.** The README doesn't specify a points-per-referral
  formula. Two constants in the ambassador code turned out to be frozen, named values
  (`points == len(referrals)`, and the first tier threshold `AMBASSADOR_TIERS[0]` =
  5 points / ₹100 / "Campus Ambassador") rather than inferred behavior, so those were
  asserted as exact literals. If those constants are ever renamed or the tier table
  reordered, this test's literals should be revisited — they're wiring constants, not a
  spec-derived formula.

## Assumptions about external services / harness design

- **Delivery confirmation barrier.** The real `ReplyDelivery` waits (up to a real timeout)
  for a WhatsApp "message sent" status webhook after each non-final outbound message.
  `FakeWhatsAppClient` plays Meta's role and auto-confirms each `wamid` on the next event
  loop tick, so tests don't eat the real ~10s-per-message timeout. This assumes Meta
  always eventually confirms delivery; the real dropped-status-webhook timeout path is
  **not** exercised by any journey here.
- **Flow endpoints (`/flows/onboarding`, `/flows/grade`) are not exercised directly.**
  These are RSA-encrypted Flow data endpoints; `WHATSAPP_FLOWS_PRIVATE_KEY_PEM` in the test
  harness is a throwaway dummy key never actually used to decrypt a real Flow payload.
  All flow-completion journeys (2, 9, 16) go through the plain webhook's `nfm_reply`
  interactive path instead, which is genuinely the production completion route Meta uses
  after a Flow submits — but the encrypted-endpoint code itself is untested.
- **Referrer/handle registration (journey 2) — RESOLVED.** Used to write handle documents
  directly into the `referrers` Firestore collection (doc id = handle) to satisfy
  `resolve_referrer`'s lookup, rather than going through the public influencer-registration
  route -- which meant a registration regression (FINDINGS API #5-6: collision returns 200
  or crashes 500 instead of the documented 409) could not fail this attribution journey.
  `tests/e2e/test_onboarding.py::_register_handle` now calls the real
  `POST /internal/influencers` route instead. Journey 16 (ambassador enrollment) already
  went through the real `POST /internal/users/{id}/ambassador` route and needed no change.
- **Journey 3(a), "user row written before generation."** This ordering isn't
  independently observable from outside the system without instrumenting user_service
  internals. It's asserted via the canonical `sequence` field instead: the max sequence
  among user-role rows is less than the min sequence among assistant-role rows, combined
  with content matching — the strongest assertion actually observable at the HTTP/Firestore
  boundary.
- **Journey 3 citations — RESOLVED (fake fixed, coverage gap now honest).** When no tool
  call reads any graph nodes, `state.read_ids` is empty, and the citation-rendering path
  still queries the graph client with an empty id list. `citations_responder` (tests/e2e/
  scripting.py) used to return one `textbook_page`-shaped row regardless of whether the
  query actually named any ids, so `test_known_phone_generates_and_delivers_in_model_order`
  asserted a Sources footer that was pure wiring, not realistic retrieval. The responder now
  returns rows only for a non-empty `ids` list; since this journey scripts no tool call, the
  test was rewritten to expect no Sources footer at all. Real citation content still depends
  on tool-driven reads, which no journey in this suite exercises -- that gap remains, but is
  no longer hidden behind a fake that answered a query the turn never made.
- **Journey 17 balance seeding** runs 5 real onboarded referrals through
  `POST /internal/users` (each with an `@handle` mention) to accumulate a redeemable
  balance, rather than writing a balance value directly into Firestore, so that
  attribution and tier-crossing logic are exercised as a side effect rather than assumed
  correct.
- **Fakes stand in for `ConversationMediaStore`'s GCS bucket, the document-worker client,
  and the Gemini embeddings client.** None of the 17 journeys reach these (no inbound
  media, no tool execution that embeds/searches). Their fakes are unexercised stubs —
  their correctness is unverified, not proven safe.

## Things I chose not to test, and why

- **Inbound media** (image/audio/video/document messages) and `MediaFetcher` — no
  required journey exercises media, and building a realistic GCS-backed media fetch fake
  was out of scope for the 17 listed journeys.
- **Grade-flow uploads** (`/flows/grade` completion fetching uploaded papers/sheets) —
  same reasoning; not one of the 17 required journeys, and depends on the untested
  encrypted Flow endpoint.
- **Profile-update Flow completions** (onboarding-shaped, sender already allowed) — the
  README documents this as a distinct Flow Completion Routing row, but it isn't one of
  the 17 numbered journeys the task enumerated, so it's out of scope here.
- **`GET /webhook` verification challenge** — not one of the 17 journeys; would be a
  cheap addition but wasn't required.
- **Delivery-status / `failed` status webhooks** (`extract_sent_status_ids`,
  `extract_failed_statuses`) — not exercised; only the "sent" confirmation used to unblock
  the delivery barrier (see above) is faked.
- **Cross-instance queue ordering** — the README's own Tradeoffs section says strict
  ordering across separate Cloud Run instances isn't guaranteed and would need a durable
  external queue; this is explicitly out of scope for a single-process E2E suite.
- **Retry/backoff amplification on transient failures** — no journey scripts a fake to
  fail once-then-succeed; only journey 14's hard failure (agent generation error) is
  covered.
- **The `assert 500` path's server-side logging** for journey 13 (malformed payload) —
  the test asserts the HTTP status and the specific exception `extract_inbound_messages`
  raises directly, but doesn't inspect server logs for what gets logged around the
  unhandled exception.

## Environment / concurrency caveats

- All three services (whatsapp_adapter, text_agent, user_service) and every fake run in
  one Python process, each service's `uvicorn.Server` on its own daemon thread with its
  own event loop, talking over real loopback TCP to each other and to the Firestore
  emulator. This is genuinely real HTTP between the three services, not in-process ASGI
  transport — but it is not a multi-process deployment topology.
- Fake call-log lists are appended to from multiple threads/event loops. CPython's GIL
  makes individual `list.append` calls atomic enough for these tests' purposes, but there
  is no explicit synchronization — a stress/fuzz test hammering the fakes concurrently
  could still observe reordering artifacts that these journeys don't.
- Test ports are allocated by a bind-then-release probe before handing them to `uvicorn`;
  there's a theoretical (very small) race window if something else on the machine grabs
  the same port in between.
- Running the suite requires a JRE for the Firestore emulator (`gcloud emulators firestore
  start`); it was not present by default and was installed via `brew install openjdk` to
  execute the suite once. `tests/e2e/requirements-test.txt` lists the Python-side test-only
  dependencies (kept separate from the repo's existing dependency manifests per the "don't
  modify files outside the test directory" rule).

---

# API-level route tests (`tests/api/`)

Second, independent suite: each service's real FastAPI app driven directly through an
ASGI test client, with external clients/repositories faked. One subsection per service.

## whatsapp_adapter

**Where the spec didn't define behavior, and I guessed**
- Auth-mandate adaptation: the task's generic "missing/wrong bearer auth → 401/403"
  mandate doesn't literally apply since this route uses HMAC, not bearer tokens. The
  analogous boundary was tested instead (missing signature header, wrong-secret
  signature, garbage-but-present signature). **RESOLVED:** the missing-header (and
  missing-query-param, for `GET /webhook`) case's actual 500 is no longer asserted as
  the contract -- both were rewritten to assert 403, the same rejection code this
  route's own sibling cases (wrong secret, garbage signature, wrong verify token/mode)
  already establish. Both now fail against current code, documenting the gap instead of
  freezing the crash.
- Flow-decrypt-failure status: no README or code text names a status for a Flow decrypt
  failure. **RESOLVED:** rather than committing to 500 ("no try/except anywhere in the
  path"), the three garbage-ciphertext tests in `test_flows.py` now assert 421 -- Meta's
  own WhatsApp Flows Data Exchange spec convention for a decrypt failure -- and fail
  against current code.
- 404 category: intentionally skipped — none of this service's routes take a
  resource-id path param naming an entity to look up (same reasoning as text_agent's
  `/respond`).

**Assumptions about external services / harness design**
- `ConversationCoordinator` is faked as a bare synchronous call-recorder
  (`FakeCoordinator.process_inbound` just appends to a list), not the real coordinator
  plus a fake `UsersClient`/`OnboardingRepository`. This means "Unknown phone inbound"
  vs. "Known phone inbound" vs. "Blocked phone inbound" Test Matrix rows are **not**
  distinguishable at this route layer — that branching lives entirely inside the real
  coordinator, out of bounds for route-level success assertions per the task's own
  scoping note (only claim-then-enqueue ordering is guaranteed synchronously).
  Blocked-phone was not tested for the same reason.
- Verified empirically (on a throwaway FastAPI app, not the app under test) that
  `httpx.ASGITransport(raise_app_exceptions=False)` turns an unhandled app exception
  into a real 500 response rather than propagating a Python exception to the test —
  tooling/harness plumbing, documented in `conftest.py`.
- `POST /webhook`'s "422 for malformed bodies" mandatory category doesn't literally
  apply — the route has no pydantic body model at all (manual `json.loads`/dict
  access), so malformed input there is 500 ("fail loudly"), not 422. The 422 mandate
  was satisfied via the two `/flows/*` routes instead, which do have
  `EncryptedFlowRequest`.

**Things I chose not to test, and why**
- Full RSA/AES Flow-crypto round-trip (a genuinely decryptable request/response) — no
  real `WHATSAPP_FLOWS_PRIVATE_KEY_PEM` counterpart exists to construct one; coverage is
  limited to request-shape 422s and predictable-decrypt-failure 500s.
- Downstream side effects of `POST /webhook` racing the unawaited background task
  (outbound sends, transcript writes) — not observable/deterministic at this layer
  since the coordinator is faked as an opaque recorder; no bounded poll was needed
  because claim-then-enqueue is already synchronous in the real route.
- Multi-message webhook batches, media/location/interactive/flow-completion inbound
  message shapes — out of scope since `ConversationCoordinator` (where their handling
  actually diverges) is faked as a single opaque call recorder; the route treats every
  valid `InboundMessage` subtype identically (claim, then hand off).

## user_service

**Where the spec didn't define behavior, and I guessed:**
- For "refuses when the profile school has no directory id" (ambassador enroll) and
  "refuses an amount not currently offered" (gift-card redeem), the README names no
  exact status code. 422 was committed to before running for both, per the task brief's
  explicit recommendation; the actual codes (200 and 400 respectively) are recorded as
  findings rather than adjusting the commitment after the fact.
- `GET /internal/users` `limit=0`: committed to "200 with empty items, populated
  totalCount" per the task brief's directive; the route's own `Query(ge=1)` constraint
  disagrees (422). This is flagged with lower confidence than the other findings — it may
  be the task's assumed boundary conflicting with a deliberate request-validation floor
  rather than a genuine bug.
- `DELETE /internal/users/{user_id}` for an unknown id: the route performs no existence
  check and deletes unconditionally across every owned collection, so 204 was asserted
  rather than a mandatory-404, since the route never "looks up" the user — there is no
  promise to test against.

**Assumptions about external services / harness design:**
- Firestore, Hubble, Neo4j (`GraphClient`), and the conversation-media GCS bucket are all
  replaced with pure in-memory fakes (`tests/api/user_service/conftest.py`). Fakes for
  `UsersRepository`, `ReferrersRepository`, `CampaignsRepository`, `GiftingRepository`,
  etc. mirror the *plumbing* behavior of the real Firestore-backed repos (idempotent
  creates, no server-side uniqueness enforcement) rather than inventing the business
  rules the README promises — this is what let the collision/overlap findings above
  surface honestly instead of being masked by an over-helpful fake.
- `FakeThreadsRepository` is a simplified reimplementation of the 2-hour session-gap /
  tip-advance contract from the Firestore-layout section, not a byte-for-byte port of the
  real transactional Firestore repo — faithful enough to drive the real route handlers for
  shape/behavior assertions, but Firestore's transaction semantics were not reproduced.
- `httpx.ASGITransport(raise_app_exceptions=False)` was required so unhandled exceptions
  in routes/repositories (findings #6, #12) surface as real 500 responses instead of
  propagating as raw Python exceptions out of the test.
- `AppState.db` is passed as `None` (untyped dataclass field, never touched since
  Firestore access always goes through the fake repos, not `ctx.db` directly).

**Things I chose not to test, and why:**
- **Undocumented routes found by enumeration** (not in the README table, but exercised by
  the generic auth-boundary test since it derives from `app.openapi()`, not the README):
  `GET /internal/institutions/{institution_id}`,
  `GET /internal/threads/{thread_key}/sessions/corpus`, and
  `GET /internal/users/{user_id}/threads/{thread_key}/sessions/{started_at_ms}` (single-session
  fetch — README only documents the list variant). All three passed the
  401-with-no-auth / 401-with-wrong-token checks; they were not given full CRUD/shape
  coverage since they're undocumented, per the task brief.
- The `knowledge_store` sessions-job side effect of `readNodeIds` ("membership in the
  corpus is closedness alone") — a different service's concern, out of scope for
  user_service's API surface.
- Hubble transport-level failures (5xx, timeouts) for gift-card settlement — the README
  doesn't document a specific contract for that failure mode at the API layer.
- Deep testing of `PendingAction`/onboarding-derived "started" counts in
  influencer/ambassador reports beyond the zero-case, since building realistic buffered
  pre-onboarding message fixtures added complexity disproportionate to the marginal spec
  coverage gained given the effort budget for this task.

## text_agent

**Where the spec didn't define behavior, and I guessed:**
- LLM-failure status code: README gives no `/respond`-level error contract.
  `text_agent/app/src/api/internal.py`'s handler has no try/except around
  `ctx.respond.respond(...)`, so 500 falls out per Starlette's documented
  unhandled-exception default. **RESOLVED:** no established convention exists for an LLM
  provider failure's client-visible status, so 500 is no longer asserted as the desired
  contract -- `test_llm_failure_does_not_return_success` (renamed from
  `test_llm_failure_propagates_as_500`) now checks only the qualitative claim (not 2xx).
- The "second failure axis" (rule 8) was represented as the audio-schema 422 (see
  FINDINGS.md) rather than a graph/image-tool failure, since triggering a tool call
  deterministically through the fake LLM's scripted structured-output turn would need
  deep knowledge of the tool-calling loop (`OpenAIToolExecutor`) that reading only for
  signatures wouldn't responsibly cover. **Since resolved as WRONG, not just axis
  coverage:** `test_audio_message_part_is_422_not_transcribed` treated the current 422
  as the intended failure axis, but the README states audio parts *are* transcribed
  before the model call — the 422 is the bug, not a documented failure mode. Rewritten
  to `test_audio_message_part_is_transcribed_before_the_model_call` (asserts 200 and
  that the model was actually called); fails today. Same class of issue for
  `test_missing_previous_response_id_is_422` -> `test_missing_previous_response_id_is_accepted`
  (the README's own request example omits that field). See MIRRORED_AND_WRONG.md.

**Assumptions about external services / harness design:**
- Fully self-contained fakes in `tests/api/text_agent/fakes.py` (not importing
  `tests/e2e/fakes.py`/`servers.py`), modeled on the same duck-typed method signatures
  (`chat`, `count_input_tokens`, `query`, `close`, `embed_documents`, `embed_queries`,
  `generate`, `edit`).
- `FakeUsersClient` is a bare stand-in, not the real `infra.clients.users.client.UsersClient`
  — `RespondService`'s constructor is typed against the concrete class but never calls it
  during construction; only `update_profile`/`enroll_ambassador`/`get_ambassador_status`
  tool invocations would reach it, and no scripted turn in this suite triggers a tool
  call, so no live or faked user_service backend is exercised.
- `httpx.ASGITransport(raise_app_exceptions=False)` set globally so an unhandled route
  exception surfaces as a real 500 response (matching uvicorn) instead of propagating as
  a raised Python exception inside the test client.

**Things I chose not to test, and why:**
- 404 on `POST /respond`: intentionally skipped — no path parameter, no named resource to
  404 against.
- Image/document/grading/form/buttons/list/cta_url/location_request response shapes,
  `update_profile`, `enroll_ambassador`, `get_ambassador_status` tool paths, and a
  graph-client-raises/image-client-raises failure axis: all depend on scripting a
  specific tool-call sequence through the fake LLM and the real `OpenAIToolExecutor`
  loop — judged out of scope for this pass to avoid guessing at tool-loop internals;
  only the plain-text, no-tool-call path is exercised as the success case.
- No exact error-message-string assertions inside `{"detail": [...]}` for any 422 case —
  only the standard FastAPI shape, per the brief's own instruction not to guess message
  text.

## document_worker

**Where the spec didn't define behavior, and I guessed:**
- The README gives no explicit error-status contract for a storage failure.
  `document_worker/src/api/internal.py` and `document_worker/src/service.py` have no
  try/except around `render_document`, `render_previews`, or
  `media.upload_generated_document`; `app.py` registers no custom exception handlers and
  doesn't set `debug=True` — so an unhandled exception falls through to Starlette's
  default `ServerErrorMiddleware` → 500. **RESOLVED:** no established convention exists
  for this failure's client-visible status, so 500 is no longer asserted as the desired
  contract -- `test_render_storage_upload_failure_does_not_return_success` (renamed from
  `test_render_storage_upload_failure_is_500`) now checks only the qualitative claim (not
  2xx).
- `/health`/`/version` shape asserted from the shared `infra/api/routes.py` ops router,
  since document_worker's own README only lists `/render`.

**Assumptions about external services / harness design:**
- `httpx.ASGITransport(raise_app_exceptions=False)` needed to get the real 500 response
  instead of a re-raised Python exception in-process.
- Lifespan triggered manually (`async with test_lifespan(app):`) rather than via ASGI
  lifespan protocol events, since `ASGITransport` doesn't send them — standard harness
  pattern, not a spec claim.
- `FakeGcsBucket.public_url` returns a URL under a made-up `fake-conversation-media-bucket`
  root; only the README-documented fact (`url` ends in `/{filename}.{format}`) is
  asserted, never the fake root itself.

**Things I chose not to test, and why:**
- 404: `/render` takes no path parameter and looks up no named resource by ID —
  intentionally skipped, same reasoning as text_agent's `/respond`.
- **Environment limitation — LibreOffice (`soffice`) missing.** `infra/documents/previews.py`
  shells out to a local `soffice` binary to convert rendered docx/pptx to PDF before
  rasterizing preview pages. Neither `soffice` nor `libreoffice` is on PATH in this
  sandbox, even though `infra/documents/constants.py`'s own comment states it is
  "Installed on PATH in the document-worker image" in the real deployment — confirmed by
  first trying the genuine success path for real, not by assumption. This means every
  real `/render` call in this sandbox fails at the previews step regardless of
  markdown/format validity (see FINDINGS.md). LibreOffice/previews was NOT faked to force
  the success tests green — only the GCS/storage boundary was authorized as a fake, and
  Pandoc/preview rendering were meant to run for real — so the two success tests are left
  failing as a direct, documented consequence of the sandbox's missing binary.
  **Updated in this pass:** per the rule allowing `xfail` for documented environment gaps
  (missing soffice, no JRE/emulator), both tests
  (`test_render_docx_success_shape`, `test_render_pptx_success_shape`) are now marked
  `@pytest.mark.xfail(reason=..., strict=False)` citing this section, instead of failing
  plainly — `strict=False` so they flip to passing automatically once a real `soffice`
  binary is available (e.g. the real deployed image, or a CI runner that installs it).
- Real Pandoc turned out to be very permissive under direct probing (empty markdown,
  unbalanced `$...` math, unclosed fenced div all exit 0, no stderr) — none of these make
  Pandoc itself fail, so the "Pandoc-hostile input" negative test was pivoted to a
  directory-traversal-shaped `filename` instead (rejected by Pydantic's `Slug` pattern at
  the 422 layer before any object name is composed), plus a schema-valid-but-adversarial
  path test asserting the composed storage object name stays under the expected prefix
  with no `../` in it.
- For the storage-upload-failure test, since `render_previews` runs before the storage
  upload call and is itself broken by the missing-`soffice` gap (which would mask the
  storage failure entirely), `document_worker.src.service.render_previews` was
  monkeypatched to a canned-success stub **only in that one test**, to actually reach and
  exercise the storage-exception branch rule 8 calls for. Flagged in that test's own
  docstring as an environment-gap workaround, not a weakened assertion — the 500
  expectation itself was derived from reading real control flow, not guessed.

## redirect_service

**Where the spec didn't define behavior, and I guessed:**
- The README doesn't give the exact prefill text/format string. Per the task's explicit
  carve-out for wiring/constant facts, `ATTRIBUTION_PREFILL_TEMPLATE` was read from
  `infra/clients/users/constants.py` (`f"Hi {PRODUCT_NAME}! @{{handle}} mentioned you —
  what can you do?"`) as a signature/constant fact, then expected `Location` literals
  were built with stdlib `urllib.parse.quote` (generic encoding, not source logic) — the
  same function `redirect_service/app/src/api/routes.py::_whatsapp_url` uses.
- For the "unregistered handle still redirects" test, the fake user_service click client
  was modeled as a no-op (returns normally) per the README's "no-op for unregistered
  ones" line — redirect_service itself has no way to distinguish registered vs.
  unregistered handles, and user_service's actual no-op behavior is a different
  workstream's concern, not independently verified here.

**Assumptions about external services / harness design:**
- `AppState` (`redirect_service/app/src/api/context.py`) is a plain, unvalidated
  dataclass; `Settings` was duck-typed as a `SimpleNamespace` exposing only
  `public_whatsapp_number` (the only attribute the route reads) rather than constructing
  a real `Settings`/`GcpIdentity` (which needs live ADC credentials).
- **Background-task draining, confirmed empirically:** on the success path,
  `httpx.ASGITransport` fully awaits Starlette's `Response.__call__`, including its
  attached `BackgroundTasks`, before returning control to the test — the click was
  already recorded by the time `client.get()` returned; a bounded poll is kept as a
  safety net rather than asserted on directly.
- **Background-task failure limitation, confirmed empirically:** on the failure path,
  `httpx.ASGITransport` does NOT hand back the already-built 302 response when the
  background task raises — it propagates the exception out of `client.get()` instead,
  because `ASGITransport` only constructs an `httpx.Response` after the whole ASGI
  app-call coroutine returns without error. Verified via a raw ASGI
  scope/receive/send call (bypassing httpx) that Starlette had already sent
  `http.response.start` (302, correct `Location`) and an empty body to `send` *before*
  the background task's exception surfaced — i.e. a real deployed uvicorn server would
  have already flushed the 302 to the client socket, with the exception only logged
  server-side. Documented as two tests: one records the httpx-level limitation
  (`pytest.raises`), the other drives the ASGI app directly to assert the actual "even if
  click logging fails" contract at the level where it's really guaranteed.

**Things I chose not to test, and why:**
- No 401/missing-header/bearer-token tests: redirect_service is intentionally public per
  its own README (no internal-secret auth on any of its three routes) — the auth-boundary
  mandate is inapplicable here, not skipped out of laziness.
- No generic 422-malformed-body tests: `GET /go/{handle}` has no request body — adapted to
  boundary/malformed *path* input instead (a handle with a URL-encoded space, one
  containing `@`, and the empty-segment case `/go/`, which FastAPI's own routing 404s on
  before the handler runs, confirmed empirically).
- No retry/backoff testing of the real `UsersClient.record_referrer_click` (wrapped in
  `infra.platform.retry.retry()`) — that's `infra/clients/users` behavior, out of scope
  for a redirect_service-owned test; the fake client bypasses it entirely by design.

---

# Persistence / cross-service integration tests (`tests/integration/`)

Honest accounting for the Firestore-emulator suite. An empty list here would be
a red flag; this one is not.

## Where the spec didn't define behavior, and I guessed

- **Sequence origin (0 vs 1).** The README says `nextTranscriptSequence` is a
  transactional counter callers cannot assign; it never says the first row is
  `1`. The task brief required sequences `1..N`. I committed to `1` before
  running. The code stores `0` first. Recorded as FINDINGS #4 rather than
  silently switching the literal — but confidence that `0` is *wrong* (vs
  undocumented) is low.
- **Gap of exactly two hours.** user_service README: "a gap of two hours
  between user messages opens a new session." I read that as `>= 2h` opens a
  new session. The whatsapp_adapter/e2e suite read the same window as
  exclusive (`>`). Code matches the exclusive reading. FINDINGS #5; this is a
  documentation decision, not a silent guess I want to pretend was certain.
- **Pin to a session that does not exist.** README: optional `startedAtMs`
  "pins the append to that session (no re-gap)." I guessed a pin would
  *create* that session if missing (concurrent first-appends all pinned to
  the same `startedAtMs`; retention append pinned to `user.createdAtMs`).
  Code 500s on `SessionRecord.model_validate(None)`. FINDINGS #6. A 404 would
  also have been a defensible contract; I did not guess 404.
- **Unredeemable gift-card amount status.** README names no code. I committed
  to 422; code returns 400. Same silence as the API suite.
- **Gift-card `instructions` join.** README says instructions are snapshotted
  brand redemption steps, not how multiple Hubble `howToUseInstructions`
  arrays are joined. I asserted only that both seeded steps appear as
  substrings, not a full joined string.
- **Failed-append injection.** The README requires atomic commit of rows and
  cursors but does not name a public failure switch. I raised from
  `ThreadsRepository._save_activity` inside the real emulator transaction
  (Firestore itself was not mocked). That is a failing-dependency axis, not a
  documented error type. Rollback of the activity tip and rows did hold.

## Assumptions about external services / harness design

- **Firestore emulator, not production Firestore.** Concurrent `claim()` of
  one document id raised `Aborted: Transaction lock timeout` on this
  emulator. Production Cloud Firestore `create()` more typically returns
  `ALREADY_EXISTS`. FINDINGS #7 is still a missing-handler bug if `Aborted`
  can happen in prod; it may be emulator-amplified.
- **Hubble is the real `HubbleClient`** with `httpx.MockTransport` answering
  `/v1/partners/auth/login`, `/v1/partners/products/{id}`,
  `/v1/partners/orders`, `/v1/partners/orders/by-reference/{id}`. No
  HubbleClient method is stubbed. `place_order` timeout is `TimeoutException`
  raised at that transport after the order body has already been recorded
  upstream — the client has `timeout=None`, so a real hang could not be used.
- **Neo4j and GCS are in-process fakes** (`FakeGraphClient.query`,
  `FakeGcsBucket.delete_prefix`). DELETE's graph/media side effects are
  "did not crash", not "wrote the right Cypher / deleted the right objects."
- **Settling read used is `GET /rewards` and `GET /ambassadors/{id}`**, which
  the README groups under "whenever gift cards are read." This suite did **not**
  independently re-assert that `GET /gift-cards/{id}` itself settles a pending
  card (the e2e suite already found it does not). After a successful settling
  read, `GET /gift-cards/{id}` did return voucher fields.
- **user_service only.** whatsapp_adapter and text_agent are not booted; their
  payloads are built with the same constructors those services use
  (`profile_input_from_flow`, `user_rows` / `assistant_row`, `ProfileUpdate`)
  and then POSTed at user_service.
- **JRE.** `java` is not on the default macOS PATH; Homebrew OpenJDK at
  `/opt/homebrew/opt/openjdk` was required to start the emulator.

## Things I chose not to test, and why

- **Pinning an append onto an already-created session under 8-way
  concurrency** after a successful first write — the concurrent-sequence test
  as written all pinned to a not-yet-created session and 500'd (FINDINGS #6),
  so the 1..N race was not actually observed. I did not rewrite it after
  seeing the 500s.
- **`GET /internal/users/{id}/gift-cards/{id}` as the settling read** for a
  still-pending card — already a confirmed e2e finding; repeating it here
  would not add a new persistence fact.
- **Influencer spend formula** (`baseInr + per-block incentive` capped) —
  README describes the inputs but not a numeric example I could commit to
  without inventing arithmetic. Funnel tests assert clicks / onboards /
  started / retained against row counts, with payout terms zeroed so spend
  cannot silently disagree.
- **Campaign overlap / handle-collision 409s** — already failing in the API
  suite against the same README lines; this layer is persistence and
  derive-on-read, not that write-path.
- **whatsapp_adapter `onboarding` writes through the adapter process** —
  started-count was seeded via the real `OnboardingRepository` against the
  emulator, which is the document user_service actually reads.
- **Multi-instance Firestore contention beyond one uvicorn process** — one
  user_service, one emulator, real HTTP. Not a Cloud Run replica set.

---

# Pure derived-logic unit tests (`tests/unit/`)

Honest accounting for the no-I/O Hypothesis + boundary suite. An empty list
here would be a red flag; this one is not.

## Where the spec didn't define behavior, and I guessed

- **Negative points / negative onboards.** The ladder and payout types are
  `ge=0` at the API boundary, but the pure functions take bare `int`. I
  committed to "no rung crossed → ₹0" for `earned_inr(-1)` (passed) and
  "no completed block → spend == baseInr" for `_campaign_spend(..., -1)`
  (failed: 950). The second is FINDINGS #5; both are guesses about
  undocumented invalid inputs, not named README cases.
- **Empty ambassador name.** The task requires a raise for a name with no
  Latin letters. I committed to `ValueError` (the stem-less path `"张伟"`
  and `"!!!"` use). `""` instead does `name.split()[0]` → `IndexError`.
  FINDINGS #4. Whitespace-only `"   "` was not separately asserted after
  seeing the empty-string crash; it would hit the same `split()[0]`.
- **Phone normalization algorithm.** README says "normalized phone" and
  stores `91XXXXXXXXXX`, but never lists the rewrite rules (`+`, spaces,
  leading zeros, national `0`). I treated those three surface forms as the
  same identity. All three failed (FINDINGS #1–3). I did **not** guess a
  full E.164 parser (no test that `9876543210` without the 91 country code
  is the same user).
- **Active-window inclusivity.** Constants comment: active when last
  message is "within this window." I committed to a closed interval
  (`age == ACTIVE_USER_WINDOW_MS` → `"active"`). It passed. The 2-hour
  session-gap README had the opposite exclusive reading in the integration
  suite; I did not reuse that reading here.
- **Flexible storefront when `balance > maxVoucherAmount`.** Task: "capped
  at max." I committed to *filtering* the ladder to `<= max`, without
  synthesizing `max` as an extra denomination when it is not on the ladder
  and is not the exact balance. `offered_amounts(..., 6000)` with max 5000
  is `[50, 100, 250, 500, 1000, 2000]`, not `[..., 5000]`. Passed. If the
  product intent was "always offer max as a redeemable amount," that test
  would have been the wrong commitment — it wasn't contradicted.
- **`_sort_key(..., "last_active")` direction.** "None sorts AFTER all real
  timestamps" plus typical directory "last active" meaning most-recent
  first. I asserted order `[recent, older, never]`. Passed. I did not
  independently specify `"newest"` / `"session_count"` key shapes.
- **Identical-name tiebreak.** Docstring: "always tiebroken by cased name."
  I committed to *equal* keys (Python-stable sort) rather than a hidden
  `userId` component. Passed.
- **Attribution filter.** `UserDirectoryQuery.attribution` is
  `organic | attributed` with no README sentence mapping it. I guessed
  `referrerHandle is None` → organic, set → attributed. Passed.
- **Needle construction.** `_matches` takes a precomputed `needle`. I used
  the directory page's call-site `query.q.strip().casefold()`, which is
  wiring, not an independent spec. Empty / whitespace queries matching
  everything depends on that strip.

## Assumptions about external services / harness design

- **No Hubble, no Firestore, no emulator.** Gift cards, campaigns, and
  profiles are constructed as Pydantic models. `mint_handle` / `resolve_referrer`
  take in-memory fakes that only implement `exists` / `list_handles`.
- **`_derive_user_id(phone, secret)`** is the pure helper behind
  `UsersRepository.derive_user_id`. The repository constructor needs a
  Firestore client, so the helper is what this layer actually calls. Same
  HMAC, same secret-as-bytes, no extra wrapping.
- **Hypothesis** `max_examples=80`, in-memory example DB (the default
  `.hypothesis/` path was unusable in this sandbox). Collisions between
  two random 12-digit Indian mobiles are treated as impossible at 128 bits;
  the property would fail the suite if one ever appeared.
- **Frozen tables** (`AMBASSADOR_TIERS`, `REWARD_AMOUNTS`,
  `HANDLE_SUFFIX_ALPHABET`, `ACTIVE_USER_WINDOW_MS`) were read as named
  constants the README calls out as the source of those values — the same
  carve-out previous suites used — not by reverse-engineering function
  bodies for expected rupees.

## Things I chose not to test, and why

- **I/O functions** in the same modules (`redeem`, `settled_gift_cards`,
  `derive_directory_page`, `derive_influencer_report`, `derive_status`,
  `derive_starts`): the task is the pure derived-logic layer. Settlement,
  paging, and roster assembly are covered at `tests/api` / `tests/integration`.
- **`offered_amounts` for `status="active"` (wrong case)** and Hubble
  statuses other than `ACTIVE`/`INACTIVE`. Only the documented `ACTIVE`
  gate was pinned.
- **`howToUseInstructions` containing an instruction set whose
  `instructions` list is empty** (as opposed to the field itself being
  `[]`). The task named the empty-field case.
- **Teacher `scope.grades` against the directory grade filter.** Isolation
  tests use `StudentProfile.scope.grade` only; teacher multi-grade matching
  is not specified beyond "empty filter lists mean unconstrained."
- **Search over phone / userId / institution name.** Spec says "identity
  search"; I pinned name (and unicode casefold) plus AND-across-tokens.
  Phone-as-needle was not asserted, so a regression that dropped phone from
  the haystack would not be caught here.
- **`mint_handle` on a multi-token name (`"Arjun Singh"`).** The documented
  example is first-name-flavoured `arjun-x4k9`. I did not commit to whether
  the stem is the first token or the full normalized name.
- **HMAC output length / hex alphabet.** README says "opaque." I asserted
  equality and inequality, not `len == 32`.
- **Concurrent `mint_handle` uniqueness** — would need a real registry and
  is not pure.
- **`_assemble_report` when `sum(campaign_clicks) > total_clicks`.** That
  would make miscellaneous clicks negative; the inputs are supposed to be
  consistent (windowed `count()` plus a total). I `assume`d `c0 + c1 <= total`
  rather than inventing a residual-floor.

---

# Static analysis / quality gates task

Honest accounting of guesses, unverified choices, things not attempted, and
install/version decisions made blind, for the separate static-analysis/
quality-gates task (mypy/ruff/secrets/the two custom scripts/coverage/CI).

## Discrepancy vs. task brief

The task brief stated `tests/unit/user_service/` "currently only has
`__init__.py` and `factories.py`" and that `tests/tooling/check_test_methods.py`
should therefore fail honestly against a missing baseline. When this task
actually started, `tests/unit/user_service/` already contained
`test_gifting.py`, `test_influencers.py`, `test_ambassadors.py`,
`test_attribution.py`, `test_directory.py`, and `test_user_id.py`, all with
`@pytest.mark.property`/`@pytest.mark.boundary` markers already in place
(most files are 100-400 lines, clearly not stubs). `check_test_methods.py`
therefore passes cleanly right now.

I trusted what was actually found in the working tree over the brief's
description of it, on the assumption the brief was written before or
during whatever session produced `tests/unit/user_service/*.py` and this
file's earlier sections (git status shows `tests/` as wholly
untracked/new, consistent with very recent prior work). I did not modify
or delete any of those test files to force the "expected" failing baseline
— that would have been dishonest in the other direction. If the intent was
specifically to see the script fail today, that intent is now stale; the
script was still verified against a synthetic missing-marker fixture during
development to confirm it *would* fail correctly if the situation the brief
described were true.

## Tool and rule-code choices made without a fully authoritative source

- **ASYNC rule group + RUF006/RUF029, not guessed from memory**: I ran
  `ruff linter` and `ruff rule <code>` locally against the installed ruff
  0.16.6 before adding anything to `pyproject.toml`, per the brief's own
  instruction not to guess codes from memory. `RUF029` (unused-async) turned
  out to be preview-only in this ruff version — confirmed by an actual
  "Selection `RUF029` has no effect because preview is not enabled" warning
  on the first run. I enabled `preview = true` under `[tool.ruff.lint]`
  rather than dropping the rule, since it's exactly the "un-awaited
  coroutine"-adjacent check the brief asked for. Risk: preview rules can
  change or be removed between ruff versions without the same stability
  guarantee as stable rules; if this becomes a problem, the fallback is to
  drop `RUF029` and keep `RUF006` (asyncio-dangling-task), which is stable.
  I did not pin ruff's exact patch version anywhere beyond what
  `pip install ruff` resolved to (0.16.6) — no `rev:`-style pin exists for
  the CI `pip install ruff` step, only the pre-commit hook pins
  `rev: v0.16.6`. A version drift between CI's ruff and the pre-commit
  hook's ruff is possible; not addressed.

- **mypy vs. pyright**: picked mypy because the brief named it first and
  because I could get `--strict` working against the submodule import
  layout (via `--follow-imports=silent` plus `namespace_packages`/
  `explicit_package_bases` in `pyproject.toml`) without installing anything
  beyond what's already in `.venv`. I did not actually try pyright, so this
  is not a real A/B comparison — pyright might handle the
  submodule/no-`__init__`-based-package-root situation more gracefully out
  of the box (it has better monorepo/multi-root support in some setups),
  or might not; I have no measured basis for the claim either way. If mypy's
  namespace-package resolution turns out to be fragile in CI (different
  Python version, different install layout), pyright is the documented
  fallback to try, not a verified one.

- **`--follow-imports=silent` as "the required scope"**: the brief said to
  "investigate ... whether pointing mypy directly at that path ... works."
  Pointing mypy at `user_service/app/src` without `--follow-imports=silent`
  works, but follows every import into `infra/` and reports those errors
  too (61 total vs. 14). Both numbers are recorded above; the 14-error
  `--follow-imports=silent` run was treated as "user_service/app/src's own
  errors" since that's what most naturally matches "type checking scoped to
  user_service/app/src." Whether CI *should* also gate on the 47 `infra/`
  errors surfaced through that import chain is a real open question this
  task doesn't resolve — `infra` is a separate submodule with its own
  ownership boundary, and gating user_service's CI on infra's type errors
  seems like the wrong coupling, so the CI workflow uses
  `--follow-imports=silent`. Not a confident call, just the more
  conservative one.

## Coverage / diff-coverage thresholds

- **`fail_under = 90`**: this is the actual measured number from
  `pytest tests/unit tests/api --cov=user_service/app/src --cov-branch`
  (90% exactly, per the tool's own rounded-to-int-percent output; a more
  precise decimal was not computed). It is NOT a number chosen for any
  reason other than "this is what the tool reported" — per the brief's own
  instruction. It excludes integration/e2e coverage entirely, since those
  suites cannot run here (see below); if/when they can run in real CI, the
  true coverage number is almost certainly higher (integration tests likely
  exercise Firestore-repo code paths the in-memory API fakes don't), and
  `fail_under` should be re-measured and probably raised at that point. No
  attempt was made to estimate what that higher number would be.

- **diff-cover bar of 95%**: the brief suggested "e.g. 80%, since the global
  baseline is lower" as an example, but the actual global baseline (90%) is
  already higher than that example. 95% was picked — "materially higher
  than the 90% floor, but not 100%" — as a reasonable middle ground, not a
  number derived from any data (there's no historical diff-coverage trend
  to calibrate against, since this is the first time this gate would exist).
  This is a guess flagged explicitly as a guess; the team should adjust it
  after watching a few real PRs go through it.

## detect-secrets mechanics worked out by testing, not by reading docs first

- **Submodule + untracked-`tests/` scanning gap**: `detect-secrets scan`
  with no `--all-files` flag scans only `git ls-files` output, which for
  this root superproject is ~47 paths (mostly submodule gitlinks and a
  handful of root-level files) — it does **not** descend into submodule
  content or into currently-untracked `tests/`. This was discovered by
  running the tracked-only scan first (got 0 findings, which looked wrong
  given `.env` obviously has secrets), then diffing against an
  `--all-files` run (12 findings in real content). Both the pre-commit hook
  and the CI step in this task use `--all-files`, which is the correct
  choice for a submodule repo, but this is worth double-checking after any
  future change to how submodules are structured or after `tests/` gets
  `git add`ed to the root repo (at which point the tracked-only scan
  behavior would change too).

- **No non-interactive "fail on unaudited" flag in detect-secrets 1.5.0**:
  the `detect-secrets audit` command's `--help` in this installed version
  has no `--fail-on-unaudited`-style flag (initially the CI step was
  written assuming one existed, then verified against `--help` output and
  found it doesn't). The CI workaround (a small inline Python check for any
  baseline result missing an `is_secret` key after a fresh `scan --baseline`
  merge) is a custom construction, not a documented detect-secrets pattern —
  it should behave correctly (verified locally: a fresh scan against the
  existing audited baseline produces zero unaudited entries and only
  `generated_at`/filter-metadata churn), but it hasn't been exercised
  against a real "someone adds a real secret" scenario in CI.

## check_test_methods.py: the file-naming convention

The brief allowed either "a reasonable filename convention" or an
import-scanning approach and said to document whichever was picked. The
filename convention (`tests/**/test_<module_stem>*.py`) was picked over
import-scanning because:
- it's what the existing test suite already does (one file per module,
  named to match), so it needed no invented convention to already work;
- import-scanning has a real failure mode this repo would hit immediately:
  `tests/unit/user_service/factories.py` and various conftest files import
  from several of the critical modules' sibling modules for fixture-building
  purposes without those imports indicating "this file is the test for
  that module" — an import scan would have needed extra heuristics
  (e.g. only counting imports from files whose name starts with `test_`)
  that end up reconstructing the filename convention anyway, just with
  more code and more surface for false matches.

This convention will silently under-report coverage if a future module's
tests get split across multiple oddly-named files, or over-report if a
file named `test_gifting_something_unrelated.py` happens to exist without
actually testing `gifting.py`. Neither situation exists in the repo today
(verified by listing `tests/unit/user_service/`), so this is a theoretical
gap, not a current false result.

## Not attempted at all

- **Extending mypy/ruff CI gating to every submodule** (`admin`,
  `design_system`, `www`, `docs`, `firestore`, `ci`): `admin` has no Python
  files (ruff confirmed: "No Python files found"); `design_system`/`www`/
  `docs`/`firestore` were not investigated for language/content at all —
  they may be non-Python (design tooling, static site, Firebase config) and
  pointing Python linters at them was assumed out of scope rather than
  confirmed empirically.
- **Searching outside the working tree for other copies of the `.env`
  secrets** (shell history, other clones, cloud sync folders, CI secret
  stores). Flagged as a finding, not chased down — that's a rotation/IR
  decision for whoever owns those credentials, not something to
  investigate further from inside an agentic coding session.
- **Running the full `ruff --fix` / `--unsafe-fixes` pass** to see what the
  495 errors would look like post-fix. Explicitly out of scope (would touch
  existing application source), so the 261/23 "fixable" counts in the
  baseline are ruff's own estimate from a dry run, not verified by actually
  applying and re-measuring.
- **Root-causing the 2 `document_worker` and 1 `text_agent` API test
  failures** discovered incidentally while measuring coverage. Flagged
  above (finding #5) but not analyzed (out of scope for a static-analysis
  infra task; belongs with whoever owns the spec-vs-code findings sections
  of this file).
- **Pinning exact submodule requirements versions in CI.** The CI workflow
  installs from each submodule's own `requirements.txt` as-is; no audit was
  done of those files for pin consistency, conflicting transitive
  dependencies across submodules installed into one shared CI Python env,
  or whether installing all of them together (rather than isolated per
  service) could produce version conflicts that don't show up when each
  service is installed alone (which is closer to how they'd actually run in
  production, one container per service). This is a real risk for the CI
  workflow as written and would only surface by actually running it on
  GitHub Actions, which this task could not do from the sandbox.

---

# Mutation referee task

Honest accounting for `mutmut` config, baseline, killer tests, and CI ratchet.
An empty list here would be a red flag.

## Where the spec didn't define behavior, and I guessed

- **`ValueError` message text** on `mint_handle` (no Latin stem) and `redeem`
  (unoffered amount). Spec names the exception type, not the string. Mutating
  the message to `ValueError(None)` is EQUIVALENT. I did not invent a required
  message.
- **`mint_handle` stem for a multi-word / hyphenated first token.** Spec example
  is `arjun-x4k9` (first name). `"-".join(...)` on a one-token list ignores the
  separator — EQUIVALENT for every documented name. I did not invent a
  multi-token stem rule to kill that mutant.
- **Hubble status synonyms** (`"FAILURE"`, `"CANCELED"`, lowercase `"failed"`).
  Documented fail set is uppercase `FAILED` / `CANCELLED` / `REVERSED`; unknown
  stays pending. Lowercase staying pending is specified. Synonyms are an
  accepted residual risk (adversarial pass).
- **`zip(..., strict=True)` on `derive_rewards` and `derive_roster` counts.**
  Lengths match by construction (`gather` of one call per input). Spec never
  mentions zip. Marked EQUIVALENT, not a contract I invented. Contrast
  `_enrolled`, whose docstring *does* say a missing profile is a bug.
- **Directory haystack join character.** Search is AND across `needle.split()`
  tokens using `in haystack`. The separator is not a documented search surface.

## Assumptions about external services

- **Fake Hubble / Fake Gifting / Fake users** are in-memory recording stand-ins,
  not Firestore or the real Hubble partners API. Settlement tests assume
  `get_order_by_reference` returns `None` for 404 (HubbleClient docstring:
  "None means it was never created") and that `fail`/`succeed` persist status
  under the `user_id` they were given.
- **Duck-typed buffered onboarding** (`TextMessage.text` + `.at_ms`) rather than
  constructing a full `PendingAction`/`ContentMessage`. Spec surface for
  `derive_starts` is those two fields.
- **mutmut 3.7.0 has no `--ci` flag and no `mutmut html`.** CI uses `mutmut run`
  + `export-cicd-stats` + `tests/mutation/render_report.py`, and fails via
  `check_threshold.py`. Documented in `pyproject.toml` and the workflow.
- **18 known-red spec-mismatch tests are `--deselect`ed from the mutmut runner
  only.** Mutmut requires a green unmutated oracle. Those tests stay red in
  `pytest tests/unit` / `tests/api/user_service`. Deselecting them means a
  mutant that *only* those tests would kill can survive — accepted, because a
  test that already fails on unmutated code cannot distinguish a mutant.
- **Hypothesis `max_examples=80`** (unit conftest profile). Property tests are
  not an exhaustive proof; they are a sample.
- **I/O fakes are not the API-layer fakes** in `tests/api/user_service/conftest.py`.
  A mutant that only breaks FastAPI wiring would not be killed by these unit
  tests. API tests remain in the mutmut runner for that reason.

## Places the intended behaviour is unclear

- **`mint_handle` invert-`exists` timeout.** Mutmut hits empty-registry tests
  first; those hang under the inverted predicate (SIGXCPU). The existing retry
  test would kill it if reached. I did not skip or rewrite the hanging tests.
- **CI ratchet vs post-kill score.** Honest baseline was 81.3%. After killer
  tests the measured score is 553/564 = 98.05%; CI now ratchets at **98.0%**.
  Never lower it. The 11 remaining survivors are EQUIVALENT (see
  `tests/outcomes/MUTATION_BASELINE.md`).
- **`GiftCard` (secret-free) vs `GiftCardDelivery`.** `succeed` writes voucher
  fields to storage but the returned `GiftCard` type has no pin. Killer tests
  pin voucher fields via recorded `succeed` arguments, which is the documented
  attach-voucher behaviour, not an invented return-shape.

## Chose not to test, and why

- **Integration and e2e per mutant** — task said they are too slow.
- **Other services** (whatsapp_adapter, text_agent, document_worker,
  redirect_service) — surviving mutant in those trees is out of this referee
  scope.
- **`derive_rewards` first-offerable-SKU-per-brand** — not a surviving mutant
  cluster; `offered_amounts` already pins the storefront. Two Zomato SKUs in
  `REWARD_PRODUCTS` would need a live/inactive pair to kill a "second SKU
  overwrites first" bug; mutmut did not report that as a survivor.
- **Re-testing SUCCESS + empty vouchers at unit layer** — already a failing
  integration FINDING (`vouchers[0]` IndexError). Duplicating a known-red test
  does not kill a new mutant and would need another mutmut `--deselect`.
- **Tuning mutmut before recording the baseline** — forbidden by the task.
  Baseline numbers are the first honest `mutmut run`.


