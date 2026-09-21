# Assertion Correctness Audit

Scope: every test function under `tests/` and `infra/tests/` (34 files, 340 test
functions), audited against the ONLY three valid spec sources:
`user_service/README.md`, `whatsapp_adapter/README.md`, `text_agent/README.md`.

This audit is about whether each expected value is the *right* one, not
whether tests run, whether coverage is adequate, or code style. A test can be
green, well-covered, and still wrong — because its expected value was copied
from what the implementation does rather than derived from spec. That is the
defect this document hunts.

Verdict legend: **ANCHORED** (spec quote required) / **MIRRORED** (expected
value could only have come from reading the implementation) / **UNDEFINED**
(spec is genuinely silent) / **WRONG** (expected value contradicts spec).

---

## Section 1 — CANDIDATE BUGS

Ordered: money paths first, then data integrity, then auth, then the rest.
For each: what the assertion should be per spec, and whether that change
would fail against the current implementation (= live bug).

### Money paths

1. **`gifting.py:52` `IndexError` on a terminal Hubble order with empty
   `vouchers`.** README: *"a terminal order settles with or without its
   voucher"* (user_service/README.md:189). `tests/integration/
   test_hubble_settlement.py:156`
   (`test_settlement_success_with_empty_vouchers_settles_without_voucher_fields`)
   is correctly ANCHORED to this sentence and asserts a clean 200 with null
   voucher fields — but the assertion **fails today**: `_apply_order` indexes
   `order.vouchers[0]` unconditionally and raises `IndexError` before reaching
   `gifting.succeed(...)`. Fix: guard the index (`order.vouchers[0] if
   order.vouchers else None`). **Live bug**, test already correct.

2. **`influencers.py:31` `_campaign_spend` pays *below* the base fee for
   negative onboard counts.** `blocks = onboards // payout.blockSize` uses
   Python floor division, so `-1 // 5 == -1`, driving total spend to 950
   instead of the base-fee floor of 1000.
   `tests/unit/user_service/test_influencers.py:146`
   (`test_campaign_spend_negative_onboards_does_not_pay_below_base`) asserts
   the correct floor (1000) and **fails today** (`assert 950 == 1000`). Spec
   is silent on negative onboards (verdict UNDEFINED), but the test's own
   expectation is the only defensible one and it does not hold. **Live bug.**

3. **Campaign-window overlap 409 is unimplemented.** README:
   *"POST /internal/influencers/{handle}/campaigns | Create one campaign
   window (409 on overlap)"* (user_service/README.md:49).
   `CampaignsRepository.create` (`infra/firestore/repos/campaigns.py:24-29`)
   performs no overlap check at all — any window is accepted with 200. Four
   correctly ANCHORED tests in `tests/api/user_service/test_influencers.py`
   (`test_campaign_overlap_identical_window_is_409` :150,
   `test_campaign_overlap_partial_at_start_is_409` :162,
   `test_campaign_overlap_partial_at_end_is_409` :173,
   `test_campaign_overlap_fully_containing_is_409` :184) **fail today** (get
   200, not 409). **Live bug**, tests already correct. (One additional test,
   `test_campaign_overlap_adjacent_non_overlapping_window_succeeds` :196,
   passes today for the wrong reason — no overlap logic exists at all — so it
   isn't actually exercising adjacency semantics; flagged as a weak test, not
   a bug.)

4. **Influencer-registration handle-collision 409 is unimplemented, and the
   ambassador/influencer cross-kind collision crashes with a 500.** README:
   *"Register one influencer (409 if the handle collides in the referrer
   namespace)"* (user_service/README.md:46). `ReferrersRepository.
   create_influencer` (`infra/firestore/repos/referrers.py:38-46`) silently
   returns the existing doc on collision (no 409) and, when the existing doc
   is an ambassador (no `platform` field), raises an unhandled Pydantic
   validation error that surfaces as a 500.
   `tests/api/user_service/test_influencers.py:34`
   (`test_create_influencer_409_on_collision_with_existing_influencer_handle`,
   gets 200) and `:47`
   (`test_create_influencer_409_on_collision_with_existing_ambassador_handle`,
   gets 500) are both correctly ANCHORED and **fail today**. **Live bug**,
   tests already correct.

5. **`gifting.py:52` `IndexError` reachability was independently confirmed**
   via `test_place_order_timeout_after_upstream_success_settles_without_
   double_charge` (`tests/integration/test_hubble_settlement.py:200`) and the
   settlement-mechanics tests generally — see item 1.

6. **Ambassador tier ladder (`AMBASSADOR_TIERS`: 5/20/45/95 points →
   100/450/900/2000 ₹) and the entire reward/storefront ladder
   (`REWARD_AMOUNTS`: 50/100/250/500/1000/2000) are asserted as exact numeric
   literals across ~50 test functions in `tests/unit/user_service/
   test_gifting.py`, `tests/api/user_service/test_gifting.py`,
   `tests/unit/user_service/test_ambassadors.py`, `tests/api/user_service/
   test_ambassadors.py`, `tests/e2e/test_ambassador_and_gifting.py`, and
   `tests/integration/test_hubble_settlement.py` — yet none of these numbers,
   or the `offered_amounts` ladder-generation algorithm itself, appear
   anywhere in any of the three READMEs.** The spec states only that the
   ladder is *"a frozen commitment"* living in code
   (user_service/README.md:188), never what the commitment's values are. This
   is not a "wrong" test — the numbers do match `constants.py` — but it means
   ~50 assertions have zero independent spec check: if the ladder changes in
   code without a README amendment, every one of these tests re-freezes the
   new numbers as "correct" silently. Recommend the README enumerate the tier
   and reward ladders explicitly (see Section 3).

7. **`gifting.py:48` terminal-failure status enumeration
   (`"FAILED"`/`"CANCELLED"`/`"REVERSED"`) and the catch-all handling of any
   other unrecognized status string are both undocumented.**
   `test_hubble_settlement.py:101` (parametrized on the three names) and
   `:186` (`test_settlement_unknown_status_stays_pending_and_does_not_crash`)
   encode this catch-all as "any unrecognized status stays pending," which is
   only a reading of the code's `if status != "SUCCESS": return gift_card`
   fallthrough — the README documents only `404`, `PROCESSING`, and "terminal
   order," never a specific status list nor what should happen to a genuinely
   unrecognized status. Not contradicted, but not derivable either — flag for
   spec clarification (Section 3).

8. **`balance_inr` can go negative, and the test suite asserts this as
   correct.** `tests/unit/user_service/test_gifting.py:179`
   (`test_balance_inr_can_go_negative_when_spend_exceeds_earned`) asserts
   `balance_inr(0, [succeeded ₹100]) == -100`. This literally follows the
   spec's stated formula — *"the spendable balance is earned ₹ minus the sum
   of non-failed `gifting` amounts"* (user_service/README.md:189) — with no
   stated floor, so it is technically ANCHORED, not a mismatched-oracle bug.
   But it freezes a real product gap (a "spendable balance" that can go
   negative) as intended behavior. Flag for product sign-off, not a test fix.

### Data integrity

9. **Blocklist is not cascaded on user delete.** README states
   *"Delete one user and user-service-owned data"*
   (user_service/README.md:38), and `blocklist/{userId}` is explicitly
   user-service-owned (README:162-163, 185).
   `app/src/api/routes/users.py:102-116` (`delete_user`) deletes media,
   enrollments, threads, referrer/click/gifting data, but never calls
   `ctx.blocklist.remove(...)`. `tests/integration/test_cascade.py:45`
   (`test_delete_user_removes_owned_data_and_cascades_referrer_registry`)
   is correctly ANCHORED and asserts the blocklist entry is gone after
   delete — **it fails today**. **Live bug**, test already correct.

10. **Two tests directly contradict each other, and only one matches the
    shipped implementation, on the exact-2-hour session-gap boundary.**
    `tests/integration/test_session_boundary.py:53`
    (`test_gap_exactly_two_hours_opens_a_new_session`) asserts a gap of
    exactly 2h opens a **new** session. `tests/e2e/test_session_gap.py:45`
    asserts the opposite: exactly 2h stays in the **same** session ("not yet
    'more than 2 hours'"). The implementation
    (`infra/firestore/repos/threads.py:79`, `if ... at_ms - previous.
    lastMessageAtMs <= SESSION_GAP_MS: # same session`) matches the e2e test,
    not the integration test. The README's wording — *"a gap of two hours
    between user messages opens a new session"* (user_service/README.md:191)
    — does not itself fix `<=` vs `<`, so the boundary choice is genuinely
    UNDEFINED by spec; but one of these two committed tests is *currently
    red* against the real implementation while both claim to encode the same
    rule. This needs either a README amendment naming the operator, or
    deleting/fixing the integration test to match shipped behavior.

11. **Two tests labeled "unsupported message type" actually test something
    else, and hide a real spec/implementation contradiction.**
    `tests/api/whatsapp_adapter/test_webhook_validation.py:57`
    (`test_unsupported_message_type_is_ignored_and_returns_200`) and
    `tests/e2e/test_blocking_and_failures.py:64`
    (`test_unsupported_message_type_is_ignored`) both send a `type:
    "reaction"` payload, which `webhook.py`'s parser drops via a distinct
    `case "reaction": return None` branch — never reaching the actual
    `UnsupportedMessage` path. The real "genuinely unrecognized type" branch
    (`case _: return UnsupportedMessage(...)`) is **not ignored** by
    `coordinator.py:105-106` — it is claimed, queued, and run through a full
    agent turn, contradicting the README's Test Matrix row: *"Unsupported
    message type | Ignore and return `200`"*. No test in the suite exercises
    the actual `UnsupportedMessage` path; if one did, honestly, it would show
    the README row is currently false for that path. **Live spec/impl
    contradiction, currently untested and mislabeled** — not simply a
    MIRRORED test, but a WRONG scenario mapping.

12. **Auth-boundary exemption test misquotes the very README sentence it
    cites.** `tests/api/user_service/test_auth_boundary.py:89`
    (`test_public_route_exemption_set_matches_readme`) claims the exemption
    set `{POST /access/phone, GET /health, GET /version}` is "exactly the
    three routes README documents as public." The actual README sentence is
    singular: *"Internal routes require `Authorization: Bearer
    <USERS_SERVICE_SECRET>`, enforced once as a router-level dependency
    (`require_internal_secret`); the only public route is `POST
    /access/phone`"* (user_service/README.md:66). `/health` and `/version`
    are not documented as auth-exempt anywhere — they are simply separate API
    rows. The test's exemption set was copied from what the implementation's
    route wiring actually does (`ops_router` mounted outside `/internal`,
    with no auth dependency), then mischaracterized as spec. Changing the
    assertion to match the literal README (single public route) would
    **fail today**, since `/health` and `/version` genuinely return 200
    unauthenticated. This also silently narrows what the neighboring
    `test_every_guarded_route_401s_with_no_auth_header` (:61) and
    `..._with_wrong_bearer_token` (:81) check — they never verify
    `/health`/`/version` reject unauthenticated traffic, despite the README
    implying they should. **WRONG verdict, live bug.**

13. **Webhook auth-boundary crashes (500) instead of a controlled rejection
    on missing/malformed input.**
    `tests/api/whatsapp_adapter/test_webhook_signature.py:39`
    (`test_missing_signature_header_crashes_instead_of_rejecting_cleanly`)
    and `tests/api/whatsapp_adapter/test_webhook_verification.py:81`
    (`test_missing_query_params_crashes_instead_of_rejecting_cleanly`) both
    commit a real crash-on-missing-auth-input bug as expected behavior — the
    routes directly index `request.headers[...]` / query params with no
    guard. The README only says signature verification "checks Meta's HMAC"
    (Architecture item 1) and never specifies status codes for malformed
    requests, so these tests are MIRRORED (not WRONG), but both test names
    admit the crash is a defect, not a feature. Recommend fixing the route to
    return a clean 4xx.

14. **`text_agent` `/respond` response leaks an undocumented `trace` field.**
    `tests/api/text_agent/test_respond_success.py:39`
    (`test_plain_text_reply_returns_documented_shape`) is correctly ANCHORED
    to the README's Response Format example (`reaction`/`messages`/
    `evidence` only — no `trace`, text_agent/README.md:43-94) and asserts the
    full body has exactly those keys — **it fails today**, because
    `GenerateResponse.trace: list[TraceContent] = Field(default_factory=list)`
    is not excluded from the route's serialization
    (`app/src/api/internal.py:15`), so the real body also carries `"trace":
    []`. **Live implementation/README shape drift**, test already correct.

15. **`text_agent` audio-input test asserts rejection, contradicting the
    README's explicit statement that audio is accepted and transcribed.**
    README: *"Audio parts are transcribed to text before the model call"*
    (text_agent/README.md:41). `tests/api/text_agent/
    test_respond_failure.py:42` (`test_audio_message_part_is_422_not_
    transcribed`) asserts a 422 instead. Confirmed: the wire schema's
    `UriMediaContent.type` has no `"audio"` literal and `RespondService`
    takes no transcriber dependency, so audio can never reach the promised
    transcription step as implemented. Changing the assertion to the
    spec-correct expectation (200, transcribed, answered) would **fail**
    against the current implementation. **WRONG verdict — audio
    transcription is documented but unimplemented, and the test freezes the
    gap as correct.**

16. **`text_agent` validation test contradicts the README's own canonical
    request example.** The Request Format JSON example
    (text_agent/README.md:13-39) omits `previousResponseId` entirely,
    presenting that exact payload as valid. `GenerateRequest.
    previousResponseId` is `Optional[str]` with no default, so the key must
    still be present (even as `null`) or pydantic 422s.
    `tests/api/text_agent/test_respond_validation.py:64`
    (`test_missing_previous_response_id_is_422`) asserts 422 for the README's
    own literal example — a genuine schema/README mismatch. Changing to the
    spec-implied 200 would **fail** against current code. **WRONG verdict.**

### Auth / identity

17. **Phone-normalization tests assert behavior the implementation does not
    have.** `_derive_user_id` (`infra/firestore/repos/users.py:27-34`)
    performs zero normalization — it HMACs the raw string verbatim. Verified
    directly: `derive("+919876543210") != derive("919876543210")`,
    `derive("91 98765 43210") != derive("919876543210")`,
    `derive("0919876543210") != derive("919876543210")`. Yet
    `tests/unit/user_service/test_user_id.py:32`
    (`test_plus_91_is_the_same_identity_as_digits`), `:42`
    (`test_spaces_in_the_phone_are_the_same_identity`), and `:52`
    (`test_leading_zero_is_the_same_identity`) all assert these ARE equal.
    The README only says `userId` is *"deterministically derived from
    normalized phone via keyed HMAC"* (user_service/README.md:179) without
    ever defining the normalization rule, and no phone-normalization function
    exists anywhere in the repo. These three tests **cannot pass against the
    current implementation as a pure-function unit test** — either the tests
    invented a spec that doesn't exist, or normalization is genuinely missing
    upstream of this call and needs to be added (relevant since WhatsApp may
    send `+91...` while the stored canonical form is `91XXXXXXXXXX`,
    README:106). This is the highest-priority identity-correctness question
    in the whole suite.

### Everything else

18. **`gifting.py` `offered_amounts`/storefront ladder-generation algorithm
    (flexible vs. fixed denomination paths, min/max bound handling, exact-
    balance synthesis) is entirely undocumented** — every assertion in
    `tests/unit/user_service/test_gifting.py` covering this function (~15
    tests, lines 212-396) is MIRRORED from `gifting.py:30-38`, including the
    property-based oracle tests that literally reimplement the algorithm.
    Not contradicted, just unverifiable against spec. See Section 3.

---

## Section 2 — Full per-test-function table

### `tests/unit/user_service/test_gifting.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_earned_inr_below_first_tier_is_zero` :35 | `earned_inr(0)==0`, `earned_inr(4)==0` | NONE FOUND | MIRRORED (`constants.py:11`) |
| `test_earned_inr_exactly_at_each_tier` :42 | 100/550/1450/3450 at 5/20/45/95 | NONE FOUND | MIRRORED (`constants.py:11-14`) |
| `test_earned_inr_one_below_each_tier` :51 | off-by-one below ladder | NONE FOUND | MIRRORED |
| `test_earned_inr_one_above_each_tier` :59 | off-by-one above ladder | NONE FOUND | MIRRORED |
| `test_earned_inr_far_above_top_tier_...` :67 | `earned_inr(10_000)==3450` | NONE FOUND | MIRRORED |
| `test_earned_inr_negative_points_cross_no_rung` :72 | `earned_inr(-1)==0` etc. | NONE FOUND | MIRRORED |
| `test_earned_inr_equals_sum_of_every_crossed_rung` :82 (property) | sum of crossed rungs | NONE FOUND | MIRRORED |
| `test_spent_inr_empty_list_is_zero` :97 | `spent_inr([])==0` | "...minus the sum of non-failed `gifting` amounts..." (README:189) | ANCHORED |
| `test_spent_inr_only_failed_cards_restore_credit` :102 | all-failed → 0 | same quote | ANCHORED |
| `test_spent_inr_only_pending_cards_debit` :111 | pending 50+100=150 | same quote | ANCHORED |
| `test_spent_inr_only_succeeded_cards_debit` :120 | succeeded 100+500=600 | same quote | ANCHORED |
| `test_spent_inr_mix_excludes_failed` :129 | 50+100=150, failed excluded | same quote | ANCHORED |
| `test_failed_card_never_contributes_to_spend` :144 (property) | failed contributes 0 | same quote | ANCHORED |
| `test_balance_inr_is_earned_minus_non_failed_spend` :166 | `balance_inr(5,[pending 50])==50` | balance formula (README:189); ₹100-input mirrored | MIRRORED (input `constants.py:11`) |
| `test_balance_inr_failed_card_does_not_reduce_balance` :173 | `balance_inr(5,[failed 100])==100` | same formula, mirrored input | MIRRORED |
| `test_balance_inr_can_go_negative_...` :179 | `balance_inr(0,[succeeded 100])==-100` | formula literal, no floor stated (README:189) | ANCHORED (see Candidate Bug 8) |
| `test_balance_equals_earned_minus_non_failed_spend_for_all_inputs` :195 (property) | `balance==earned-spent` | balance formula (README:189) | ANCHORED |
| `test_offered_amounts_inactive_product_is_empty` :212 | inactive→`[]` | NONE FOUND | MIRRORED |
| `test_offered_amounts_none_amount_restrictions_is_empty` :218 | `None`→`[]` | NONE FOUND | MIRRORED |
| `test_offered_amounts_empty_how_to_use_instructions_is_empty` :224 | no instructions→`[]` | NONE FOUND | MIRRORED |
| `test_offered_amounts_balance_below_min_is_empty` :230 | below min→`[]` | NONE FOUND | MIRRORED |
| `test_offered_amounts_flexible_balance_exactly_min` :243 | `[10]` | NONE FOUND | MIRRORED |
| `test_offered_amounts_flexible_balance_on_a_ladder_rung` :252 | ladder to 2000 | NONE FOUND | MIRRORED (`constants.py:32`) |
| `test_offered_amounts_flexible_includes_exact_balance_between_rungs` :260 | e.g. `[50,75]` | NONE FOUND | MIRRORED |
| `test_offered_amounts_flexible_balance_above_max_is_capped_at_max` :267 | capped ladder | NONE FOUND | MIRRORED |
| `test_offered_amounts_flexible_none_denominations_matches_empty_list` :277 | `None`≡`[]` | NONE FOUND | MIRRORED |
| `test_offered_amounts_fixed_does_not_add_exact_balance` :295 | no exact-balance synth | NONE FOUND | MIRRORED |
| `test_offered_amounts_fixed_balance_exactly_min_only_if_min_is_a_denomination` :304 | fixed-path min behavior | NONE FOUND | MIRRORED |
| `test_offered_amounts_fixed_balance_above_max_is_capped_at_max` :312 | filter to ≤max | NONE FOUND | MIRRORED |
| `test_offered_amounts_fixed_is_sorted_and_deduplicated` :318 | sorted/deduped | NONE FOUND | MIRRORED |
| `test_offered_amounts_fixed_filters_denominations_outside_min_max` :324 | bound filter | NONE FOUND | MIRRORED |
| `test_flexible_amounts_are_the_ladder_plus_exact_balance_inside_bounds` :360 (property) | reimplements algorithm as oracle | NONE FOUND | MIRRORED |
| `test_fixed_amounts_stay_within_bounds_sorted_unique` :380 (property) | same, fixed fork | NONE FOUND | MIRRORED |
| `test_offered_amounts_negative_balance_is_empty` :396 (property) | negative balance→`[]` | NONE FOUND | MIRRORED |

### `tests/api/user_service/test_gifting.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_rewards_balance_and_options_for_ambassador_at_tier_one` :81 | `balanceInr==100`, `amountsInr==[50,100]` | NONE FOUND (numerics) | MIRRORED |
| `test_rewards_404_for_non_ambassador_user` :93 | 404 | NONE FOUND | UNDEFINED |
| `test_redeem_gift_card_success_shape` :102 | 200, `status=="succeeded"`, brand/amount echoed | status enum is spec (README:126); rest isn't | MIRRORED (dominant) |
| `test_redeem_gift_card_amount_not_in_live_storefront_is_rejected` :129 | 422 | author-admitted "no exact code documented" | UNDEFINED |
| `test_redeem_gift_card_404_for_non_ambassador_user` :148 | 404 | NONE FOUND | UNDEFINED |
| `test_redeem_gift_card_422_missing_field` :161 | 422 | NONE FOUND (generic validation) | UNDEFINED |
| `test_get_gift_card_404_for_unknown_gift_card_id` :170 | 404 | NONE FOUND | UNDEFINED |

### `tests/unit/user_service/test_ambassadors.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_tier_reached_below_first_rung_is_none` :45 | `_tier_reached(0/4) is None` | NONE FOUND | MIRRORED |
| `test_next_tier_below_first_rung_is_campus_ambassador` :51 | tier-1 name/points/reward | NONE FOUND | MIRRORED |
| `test_tier_reached_exactly_at_each_rung` :60 | 4 tier names at thresholds | NONE FOUND | MIRRORED |
| `test_next_tier_at_top_rung_is_none` :68 | `_next_tier(95/10000) is None` | NONE FOUND | MIRRORED |
| `test_next_tier_between_rungs` :74 | tier-3 name/points/reward | NONE FOUND | MIRRORED |
| `test_negative_points_have_not_reached_a_tier` :83 | negative points → no tier | NONE FOUND | MIRRORED |
| `test_tier_reached_and_next_tier_are_always_consistent` :92 (property) | ladder-consistency oracle | NONE FOUND | MIRRORED |
| `test_mint_handle_name_with_no_latin_letters_raises` :133 | `ValueError` on Han name | NONE FOUND | MIRRORED (`ambassadors.py:31-34`) |
| `test_mint_handle_punctuation_only_name_raises` :141 | `ValueError` | NONE FOUND | MIRRORED |
| `test_mint_handle_empty_name_raises` :148 | `ValueError` | NONE FOUND | MIRRORED |
| `test_mint_handle_strips_leading_and_trailing_whitespace` :155 | stem `"arjun"` | NONE FOUND | MIRRORED |
| `test_mint_handle_single_character_first_name` :165 | stem `"a"` | NONE FOUND | MIRRORED |
| `test_mint_handle_matches_documented_arjun_form` :175 | `arjun-x4k9` form | NONE FOUND (code docstring, not README) | MIRRORED |
| `test_mint_handle_retries_until_the_registry_reports_a_free_handle` :185 | collision-retry semantics | NONE FOUND | MIRRORED |
| `test_minted_handle_always_has_a_four_char_alphabet_suffix` :199 (property) | suffix length 4 | NONE FOUND | MIRRORED |

### `tests/api/user_service/test_ambassadors.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_enroll_ambassador_first_call_mints_handle_and_returns_status` :12 | handle prefix, zero counts, `tier is None`, `balanceInr=0` | zero-counts trivial; handle/tier mirrored | MIRRORED (dominant) |
| `test_enroll_ambassador_is_idempotent_same_handle_on_second_call` :30 | reused handle, 200 | "Enroll ... (idempotent)" (README:53) | ANCHORED |
| `test_enroll_ambassador_refuses_when_institution_id_is_null` :48 | refusal happens; specific 422 | "refuses when the profile school has no directory id" (README:53); code itself unstated | MIXED — refusal ANCHORED, code UNDEFINED |
| `test_enroll_ambassador_refusal_does_not_create_a_registry_row` :70 | no registry row on refusal | same quote (README:53) | ANCHORED |
| `test_enroll_ambassador_404_for_unknown_user` :85 | 404 | NONE FOUND | UNDEFINED |
| `test_get_ambassador_status_null_when_not_enrolled` :90 | `null` | "or null when not enrolled" (README:54) | ANCHORED |
| `test_get_ambassador_status_after_enroll` :100 | handle prefix `"esha-"` | NONE FOUND | MIRRORED |
| `test_list_ambassadors_row_shape` :113 | `points=0,started=0,tier=None` | zero counts trivial; tier=None mirrors threshold | MIRRORED |
| `test_ambassador_detail_404_for_unenrolled_user` :134 | 404 | NONE FOUND | UNDEFINED |
| `test_ambassador_detail_shape` :143 | `earnedInr=0,balanceInr=0` at zero referrals | trivially 0 | ANCHORED |

### `tests/e2e/test_ambassador_and_gifting.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_ambassador_enrollment_counts_a_referred_student` :51 | link path formula; referral counts after 1 referral; tier-1 numerics | link-path formula and count-increment logic ANCHORED; tier-1 numerics MIRRORED | MIXED |
| `test_gift_card_redeem_settles_and_debits_balance` :148 | settlement mechanics + tier-1 numerics | settlement mechanics ANCHORED (README:189); numerics MIRRORED | MIXED |

### `tests/integration/test_hubble_settlement.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_settlement_404_fails_the_card_and_restores_balance` :73 | 404→failed, balance restored | "404 means the mint never happened (settle failed)" (README:189) | ANCHORED |
| `test_settlement_terminal_failure_fails_the_card_and_restores_balance` :101 (FAILED/CANCELLED/REVERSED) | those 3 statuses → failed | NONE FOUND (statuses not enumerated) | MIRRORED |
| `test_settlement_processing_stays_pending_and_keeps_balance_debited` :116 | `PROCESSING`→pending | "`PROCESSING` stays pending" (README:189) | ANCHORED |
| `test_settlement_success_with_voucher_stores_voucher_fields` :131 | `SUCCESS`+voucher→succeeded | "settles with or without its voucher" (README:189) | ANCHORED |
| `test_settlement_success_with_empty_vouchers_settles_without_voucher_fields` :156 | `SUCCESS`+empty vouchers→succeeded, no crash | same quote | ANCHORED — live bug, see Candidate Bug 1 |
| `test_settlement_unknown_status_stays_pending_and_does_not_crash` :186 | unrecognized status→pending | NONE FOUND | MIRRORED |
| `test_place_order_timeout_after_upstream_success_settles_without_double_charge` :200 | timeout→500; later read settles by referenceId | mechanism not in README | MIRRORED |
| `test_redeem_rejected_for_non_ambassador` :238 | 404, no order placed | NONE FOUND | UNDEFINED |
| `test_redeem_amount_not_offered_is_rejected_without_placing_an_order` :249 | 422, no order placed | NONE FOUND | UNDEFINED |

### `tests/api/user_service/test_threads.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_append_transcript_returns_tip_and_started_at_ms` :29 | returns `{previousResponseId, startedAtMs}` | "Append returns `{ previousResponseId, startedAtMs }`" (README:198) | ANCHORED |
| `test_append_transcript_404_for_unknown_user` :45 | 404 | NONE FOUND | MIRRORED |
| `test_append_transcript_422_empty_messages` :57 | 422 | NONE FOUND | MIRRORED |
| `test_append_transcript_422_missing_read_ids` :66 | 422 | NONE FOUND | MIRRORED |
| `test_get_session_transcripts_returns_appended_session` :75 | `readNodeIds`, content shape present | "readNodeIds: string[] every graph node id..." (README:138) | ANCHORED |
| `test_get_session_transcripts_404_for_unknown_user` :95 | 404 | NONE FOUND | MIRRORED |
| `test_get_session_transcripts_empty_for_thread_never_used` :102 | `[]` for unused thread | NONE FOUND | UNDEFINED |
| `test_set_session_extraction_404_for_unknown_session` :109 | 404 | NONE FOUND (author-admitted invented convention) | UNDEFINED |
| `test_set_session_extraction_then_visible_on_read` :140 | `gradedWith`, `extraction.intent/concept_ids` echoed | "gradedWith / extraction: object \| null (intent, outcome, worked, failed, concept_ids)" (README:139-140) | ANCHORED |
| `test_set_session_extraction_422_missing_field` :186 | 422 | NONE FOUND | MIRRORED |

### `tests/api/user_service/test_directory.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_list_users_offset_beyond_total_returns_empty_but_true_total` :32 | empty entries, true totalCount | NONE FOUND | MIRRORED |
| `test_list_users_limit_zero_returns_zero_items` :43 | limit=0 → empty | NONE FOUND | MIRRORED |
| `test_list_users_sort_by_name_is_case_insensitive_alphabetical` :57 | case-insensitive sort | NONE FOUND | MIRRORED |
| `test_list_users_search_matching_nothing_returns_empty` :67 | no-match → empty | NONE FOUND | UNDEFINED |
| `test_list_users_search_multi_token_requires_all_tokens_to_match` :78 | AND semantics | NONE FOUND | MIRRORED |
| `test_list_users_combined_grade_and_subject_filters` :94 | combined filters | NONE FOUND | MIRRORED |
| `test_list_users_401_and_shape_smoke` :110 | empty bucket shape (mislabeled, no 401 asserted) | NONE FOUND | UNDEFINED |
| `test_list_users_422_missing_required_persona` :116 | 422 | NONE FOUND | MIRRORED |
| `test_list_profiles_returns_every_stored_profile_of_one_persona` :121 | all stored profiles of persona | "List every stored profile of one persona..." (README:34) | ANCHORED |
| `test_list_profiles_422_missing_required_persona` :133 | 422 | NONE FOUND | MIRRORED |

### `tests/unit/user_service/test_directory.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_activity_state_none_last_message_is_never` :43 | `None`→"never" | NONE FOUND (states not in README) | UNDEFINED |
| `test_activity_state_exactly_on_the_window_boundary_is_active` :49 | age==window→active (closed) | NONE FOUND (window itself absent) | UNDEFINED |
| `..._one_ms_inside_the_window_is_active` :58 | age=window-1→active | NONE FOUND | UNDEFINED |
| `..._one_ms_outside_the_window_is_dormant` :66 | age=window+1→dormant | NONE FOUND | UNDEFINED |
| `..._message_at_now_is_active` :74 | age 0→active | NONE FOUND | UNDEFINED |
| `test_any_age_inside_the_closed_window_is_active` :81 (property) | ∀age∈[0,window] active | NONE FOUND | UNDEFINED |
| `test_any_age_past_the_window_is_dormant` :87 (property) | ∀age>window dormant | NONE FOUND | UNDEFINED |
| `test_matches_empty_query_matches_everything` :101 | blank q matches all | NONE FOUND | MIRRORED |
| `test_matches_multi_token_requires_every_token` :108 | AND semantics | NONE FOUND | MIRRORED |
| `test_matches_unicode_name_under_casefold` :120 | unicode casefold | NONE FOUND | MIRRORED |
| `test_matches_unknown_token_rejects` :128 | no match | NONE FOUND | UNDEFINED |
| `test_matches_grade_filter_in_isolation` :139 | empty list unconstrained; membership | NONE FOUND | MIRRORED |
| `test_matches_subject_filter_in_isolation` :151 | same for subject | NONE FOUND | MIRRORED |
| `test_matches_activity_filter_in_isolation` :169 | same for activity | NONE FOUND | MIRRORED |
| `test_matches_attribution_filter_in_isolation` :182 | organic = `referrerHandle is None` | `referrerHandle` null-ability is spec (README:111); "organic" vocabulary isn't | MIRRORED |
| `test_matches_blocked_filter_in_isolation` :196 | blocked/open filter | NONE FOUND | MIRRORED |
| `test_matches_all_filters_combined` :208 | all filters AND | NONE FOUND | MIRRORED |
| `test_blank_queries_match_any_name` :246 (property) | blank/whitespace q matches all | NONE FOUND | MIRRORED |
| `test_sort_key_name_orders_alphabetically_by_casefold` :259 | casefolded sort | NONE FOUND | MIRRORED |
| `test_sort_key_identical_names_are_a_stable_tie` :267 | stable tie order | NONE FOUND | MIRRORED |
| `test_sort_key_last_active_puts_none_after_every_real_timestamp` :283 | `None` sorts last | NONE FOUND | MIRRORED |
| `test_none_last_message_sorts_after_any_real_timestamp_on_last_active` :305 (property) | same, generalized | NONE FOUND | MIRRORED |

### `tests/integration/test_session_boundary.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_gap_strictly_under_two_hours_stays_in_the_same_session` :26 | gap<2h→same | "a gap of two hours...opens a new session" (README:191) | ANCHORED |
| `test_gap_strictly_over_two_hours_opens_a_new_session` :40 | gap>2h→new | same quote | ANCHORED |
| `test_gap_exactly_two_hours_opens_a_new_session` :53 | gap==2h→**new** | operator not fixed by spec wording | UNDEFINED — and contradicts implementation + the e2e test below; see Candidate Bug 10 |
| `test_pinned_started_at_ms_does_not_re_gap` :74 | pinned `startedAtMs` ignores 3h gap | "Optional `startedAtMs` pins the append to that session (no re-gap)" (README:198) | ANCHORED |
| `test_started_at_ms_of_wrong_type_is_422` :93 | 422 | NONE FOUND | MIRRORED |

### `tests/integration/test_sequences.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_concurrent_appends_to_one_session_assign_sequences_1_through_n` :23 | sequences exactly 1..N | "nextTranscriptSequence...callers cannot assign transcript order" (README:194) | ANCHORED |
| `test_caller_supplied_sequence_is_ignored` :46 | caller's `sequence=99` ignored | same quote | ANCHORED |
| `test_append_empty_messages_is_422` :59 | 422 | NONE FOUND | MIRRORED |

### `tests/integration/test_transactions.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_successful_append_moves_cursors_with_the_rows` :32 | cursors + activity tip move together | "session cursors...and the user-level channel activity tip" written "in the same commit" (README:196, 183) | ANCHORED |
| `test_failed_append_leaves_all_cursors_and_rows_unchanged` :62 | injected mid-transaction failure rolls back everything | same "same commit" quote; structural test | ANCHORED |
| `test_failure_append_does_not_advance_previous_response_id` :114 | failure append leaves tip at last good value | "Incomplete turns never advance the tip..." (README:202-203) | ANCHORED |
| `test_read_node_ids_are_a_deduplicated_union_across_appends` :157 | dedup union | "readNodeIds...deduplicated" (README:138) | ANCHORED |
| `test_append_with_non_list_read_ids_is_422` :181 | 422 | NONE FOUND | MIRRORED |

### `tests/integration/test_derive_on_read.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_directory_activity_moves_with_session_and_transcript_rows` :36 | directory activity mirrors live rows | "no count can disagree with the conversation it summarizes" (README:197) | ANCHORED |
| `test_directory_unknown_user_is_404` :65 | 404 | NONE FOUND | MIRRORED |
| `test_ambassador_points_move_with_attributed_user_rows` :70 | points derived live, no stored counters | "derived on read from users keyed by referrerHandle" + "stays derived on read" (README:188, 196) | ANCHORED |
| `test_ambassador_status_null_when_not_enrolled` :108 | `null` | "or null when not enrolled" (README:54) | ANCHORED |
| `test_influencer_funnel_moves_with_clicks_and_onboards` :115 | clicks/onboards/retained live | "count() aggregations" + ">= 7 days" (README:187) | ANCHORED |
| `test_influencer_started_moves_with_buffered_onboarding_rows` :188 | abandoned mention → started=1, onboards=0 | "started additionally counts people...who never finished" (README:187) | ANCHORED |
| `test_influencer_unknown_handle_is_404` :226 | 404 | NONE FOUND | MIRRORED |
| `test_nothing_writes_stored_counters_for_points_or_balances` :231 | no forbidden stored counter fields | "stays derived on read" (README:196) | ANCHORED |

### `tests/integration/test_cascade.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_delete_user_removes_owned_data_and_cascades_referrer_registry` :45 | delete removes user/session/transcript/gifting/enrollment/referrer **and blocklist** | "Delete one user and user-service-owned data" (README:38); blocklist is owned (README:162-163) | ANCHORED for spec claim — **fails today** on blocklist clause, see Candidate Bug 9 |
| `test_delete_cascade_would_catch_a_dangling_ambassador_registry_entry` :78 | no orphaned registry row without a live profile | "school is read live off the profile" (README:188) | ANCHORED |
| `test_delete_does_not_remove_adapter_owned_onboarding` :118 | onboarding untouched | "onboarding/{senderId}: whatsapp_adapter-owned" (README:102,165) | ANCHORED |
| `test_delete_unknown_user_returns_204` :145 | unknown user delete → 204 | no lookup-first semantics implied, but code not quoted | UNDEFINED |

### `tests/e2e/test_session_gap.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_session_gap_boundary` :24 (under 2h) | same session | "a gap of two hours...opens a new session" (README:191) | ANCHORED |
| same test (exactly 2h) | same session ("not yet 'more than 2 hours'") | operator not fixed by spec | UNDEFINED — matches implementation, contradicts the integration test above |
| same test (2h+1ms) | new session | same quote | ANCHORED |

### `tests/unit/user_service/test_user_id.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_same_phone_yields_the_same_user_id_across_calls` :24 | determinism | "deterministically derived from normalized phone via keyed HMAC" (README:179) | ANCHORED |
| `test_plus_91_is_the_same_identity_as_digits` :32 | `+91...` == digits-only | NONE FOUND (no normalization rule stated or implemented) | UNDEFINED — live bug, see Candidate Bug 17 |
| `test_spaces_in_the_phone_are_the_same_identity` :42 | spaced == canonical | NONE FOUND | UNDEFINED — same live bug |
| `test_leading_zero_is_the_same_identity` :52 | leading-zero == canonical | NONE FOUND | UNDEFINED — same live bug |
| `test_two_different_phones_never_share_an_id` :59 | distinct phones → distinct ids | keyed HMAC collision-resistance (README:179) | ANCHORED |
| `test_different_hmac_secrets_do_not_alias_the_same_phone` :66 | different secret → different id | "Keyed secret used to derive..." (README:211) | ANCHORED |
| `test_derivation_is_deterministic_for_any_indian_mobile` :75 (property) | determinism | README:179 | ANCHORED |
| `test_distinct_canonical_phones_do_not_collide` :84 (property) | no collision | README:179 | ANCHORED |

### `tests/api/user_service/test_access.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_public_access_phone_needs_onboarding_for_unknown_phone` :12 | `status=="needs_onboarding"`, no `user` | "Public precheck: blocked/needs_onboarding/allowed" (README:30) | ANCHORED (status); `user` absence MIRRORED |
| `test_public_access_phone_allowed_for_onboarded_phone` :20 | `status=="allowed"`, `userId`, `user` populated | status/userId ANCHORED; `user` field shape not in README | MIRRORED (dominant) |
| `test_public_access_phone_blocked_takes_precedence` :43 | `status=="blocked"` | "Blocked users receive only the canned error..." (README:185) | ANCHORED |
| `test_public_access_phone_422_on_missing_field` :54 | 422 | NONE FOUND | UNDEFINED |
| `test_internal_access_phone_matches_public_result` :59 | same result via internal route | "Internal: resolve...into blocked/needs_onboarding/allowed" (README:31) | ANCHORED |
| `test_internal_access_phone_422_on_wrong_type` :67 | 422 | NONE FOUND | UNDEFINED |

### `tests/api/user_service/test_blocklist.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_block_phone_then_access_reports_blocked` :10 | block → blocked | "Block one phone identity" (README:41) + "presence only" (README:162-163) | ANCHORED (behavior); `204` code UNDEFINED |
| `test_unblock_phone_removes_block` :21 | unblock → removed | "Unblock one phone identity" (README:42) | ANCHORED (behavior); `204` UNDEFINED |
| `test_block_phone_422_missing_field` :32 | 422 | NONE FOUND | UNDEFINED |
| `test_unblock_unknown_phone_is_idempotent_204` :37 | idempotent 204 | NONE FOUND | MIRRORED |

### `tests/api/user_service/test_auth_boundary.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_route_enumeration_is_nonempty` :51 | harness sanity check | N/A | ANCHORED (trivial) |
| `test_every_guarded_route_401s_with_no_auth_header` :61 | guarded routes 401 without header | "enforced once as a router-level dependency" (README:66) | ANCHORED, but undermined by wrong exemption set — see Candidate Bug 12 |
| `test_every_guarded_route_401s_with_wrong_bearer_token` :81 | same, wrong token | same quote | same caveat |
| `test_public_route_exemption_set_matches_readme` :89 | exemption set includes `/health`,`/version` | contradicts "the only public route is `POST /access/phone`" (README:66) | **WRONG** — see Candidate Bug 12 |

### `tests/api/user_service/test_enrollments.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_get_enrollments_empty_for_unrelated_user` :22 | empty lists, specific key names | key names MIRRORED; empty-for-unknown UNDEFINED | MIRRORED (dominant) |
| `test_create_enrollment_then_visible_from_both_sides` :28 | bidirectional visibility | "Many-to-many teacher-student relationships" (README:184, 148) | ANCHORED (behavior); code/keys MIRRORED |
| `test_create_enrollment_422_missing_field` :44 | 422 | NONE FOUND | UNDEFINED |
| `test_delete_enrollment_removes_it` :51 | removal effect | "Delete one teacher-student enrollment" (README:45) | ANCHORED (behavior); code MIRRORED |
| `test_delete_enrollment_422_missing_field` :69 | 422 | NONE FOUND | UNDEFINED |

*(Double-create / delete-nonexistent enrollment edge cases are not covered by any test — coverage gap, not an assertion to audit.)*

### `tests/api/user_service/test_users.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_create_user_returns_201_or_200_with_profile_shape` :12 | 200; fields echoed | field-echo ANCHORED (README:105-116); `200` vs `201` MIRRORED | MIRRORED (dominant) |
| `test_create_user_is_create_only_original_profile_survives_second_create` :25 | second create doesn't overwrite | "Creation is create-only...neither overwritten nor re-attributed" (README:181) | ANCHORED |
| `test_create_user_422_missing_required_field` :69 | 422 | NONE FOUND | UNDEFINED |
| `test_get_user_404_for_unknown_user_id` :75 | 404 | NONE FOUND | MIRRORED |
| `test_get_user_200_returns_created_profile` :80 | 200, name matches | "Fetch one user profile" (README:36) | ANCHORED |
| `test_batch_get_users_returns_only_existing_ids_in_request_order` :92 | order preserved, unknown ids dropped | NONE FOUND | MIRRORED |
| `test_batch_get_users_422_wrong_type` :110 | 422 | NONE FOUND | UNDEFINED |
| `test_get_directory_entry_404_for_unknown_user` :117 | 404 | NONE FOUND | MIRRORED |
| `test_get_directory_entry_shape` :122 | `activity` shape; `activityState=="never"`; `blocked` present | activity/blocked shape ANCHORED (README:37,183); `"never"` literal MIRRORED | MIRRORED (dominant) |
| `test_delete_user_returns_204_and_user_then_404s` :138 | delete effect + 404 after | "Delete one user..." (README:38) | ANCHORED (behavior); `204` MIRRORED |
| `test_delete_unknown_user_returns_204_delete_has_no_documented_404` :149 | unknown user delete → 204 | author-admitted "no documented 404" | MIRRORED |
| `test_update_profile_overlays_only_provided_fields` :155 | partial overlay | "Overlay authored profile fields (name, institution, scope)" (README:39) | ANCHORED |
| `test_update_profile_404_for_unknown_user` :172 | 404 | NONE FOUND | MIRRORED |
| `test_update_profile_422_wrong_type` :179 | 422 | NONE FOUND | UNDEFINED |
| `test_set_location_200_returns_profile_with_location` :190 | location echoed | "Save one user-shared location" + "carries required coordinates and an optional address" (README:40,180) | ANCHORED |
| `test_set_location_404_for_unknown_user` :205 | 404 | NONE FOUND | MIRRORED |
| `test_set_location_422_missing_required_field` :214 | 422 | NONE FOUND | UNDEFINED |

### `tests/unit/user_service/test_influencers.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_campaign_for_start_ms_is_inclusive` :52 | at `startMs` → in window | "startMs: int # inclusive window start" (README:169) | ANCHORED |
| `test_campaign_for_end_ms_is_inclusive` :58 | at `endMs` → in window | "endMs: int # inclusive window end" (README:170) | ANCHORED |
| `test_campaign_for_one_ms_before_start_is_none` :64 | one before start → None | derivable from inclusive-bound definition | ANCHORED |
| `test_campaign_for_one_ms_after_end_is_none` :70 | one after end → None | same | ANCHORED |
| `test_campaign_for_gap_between_two_campaigns_is_none` :76 | gap → None | "land in a derived 'miscellaneous' bucket" (README:187) | ANCHORED |
| `test_campaign_for_empty_campaign_list_is_none` :86 | empty list → None | trivial corollary | ANCHORED |
| `test_campaign_window_contains_exactly_its_closed_interval` :90 (property) | closed-interval membership | inclusive-bound quotes, generalized | ANCHORED |
| `test_campaign_spend_zero_onboards_is_the_base_fee` :110 | spend(0)==1000 | NONE FOUND | MIRRORED |
| `test_campaign_spend_partial_block_earns_nothing_beyond_base` :115 | 4/blockSize5 → 1000 | NONE FOUND | MIRRORED |
| `test_campaign_spend_exactly_one_block` :121 | 5 onboards → 1050 | NONE FOUND | MIRRORED |
| `test_campaign_spend_incentive_is_capped` :127 | 40 onboards → 1200 capped | NONE FOUND | MIRRORED |
| `test_campaign_spend_block_size_of_one` :135 | blockSize=1, 3 onboards → 130 | NONE FOUND | MIRRORED |
| `test_campaign_spend_block_size_one_still_respects_the_cap` :141 | 20 onboards → 55 capped | NONE FOUND | MIRRORED |
| `test_campaign_spend_negative_onboards_does_not_pay_below_base` :146 | -1 onboards → 1000 | NONE FOUND | UNDEFINED — live bug, see Candidate Bug 2 |
| `test_spend_never_below_base_and_never_above_base_plus_cap` :154 (property, onboards≥0) | `spend==base+min(blocks*per_block,cap)` | NONE FOUND (reimplements formula) | MIRRORED |
| `test_clicks_with_no_matching_campaign_land_in_miscellaneous` :179 | 3/10 clicks in misc | "land in a derived 'miscellaneous' bucket" (README:187) | ANCHORED |
| `test_referred_user_in_no_window_counts_as_started_and_onboarded_in_misc` :197 | misc.started=1, onboards=1 | "Onboards are referred users...bucketed by join time" (README:187) | ANCHORED |
| `test_referred_user_inside_a_window_buckets_there_not_misc` :222 | in-window bucketing | same | ANCHORED |
| `test_pending_start_in_a_gap_increments_misc_started_only` :242 | misc.started=1, onboards=0 | "started additionally counts people...who never finished" (README:187) | ANCHORED |
| `test_empty_campaigns_put_every_click_and_referral_in_misc` :258 | everything → misc | combination of above quotes | ANCHORED |
| `test_per_campaign_clicks_plus_misc_clicks_equal_total_clicks` :275 (property) | conservation | implied by bucketing quotes | ANCHORED |
| `test_retained_requires_last_message_at_least_seven_days_after_join` :301 | `>=7d` boundary | "retained are referred users still messaging >= 7 days after joining" (README:187) | ANCHORED |

### `tests/api/user_service/test_influencers.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_create_influencer_shape` :11 | handle normalized, `kind:"influencer"` | "doc id is the normalized handle (lowercase, no @)" (README:153); `kind` enum (README:154) | ANCHORED |
| `test_create_influencer_422_missing_field` :22 | 422 | NONE FOUND | UNDEFINED |
| `test_create_influencer_422_empty_handle` :27 | 422 | NONE FOUND | UNDEFINED |
| `test_create_influencer_409_on_collision_with_existing_influencer_handle` :34 | 409 | "409 if the handle collides..." (README:46) | ANCHORED — live bug, see Candidate Bug 4 |
| `test_create_influencer_409_on_collision_with_existing_ambassador_handle` :47 | 409 | "the `@`-mention namespace cannot collide" (README:186) | ANCHORED — live bug, see Candidate Bug 4 |
| `test_get_influencer_report_404_for_unknown_handle` :63 | 404 | NONE FOUND | UNDEFINED |
| `test_get_influencer_report_shape_empty` :68 | all-zero shape | derivable trivially from bucketing rules | ANCHORED |
| `test_list_influencers_includes_every_registered_handle` :82 | all handles listed | "List influencer reports..." (README:47) | ANCHORED |
| `test_create_campaign_shape` :99 | echoes startMs/endMs/payout | Firestore layout block (README:168-175) | ANCHORED |
| `test_create_campaign_404_for_unknown_handle` :115 | 404 | NONE FOUND | UNDEFINED |
| `test_create_campaign_422_start_not_before_end` :124 | 422 | NONE FOUND | UNDEFINED |
| `test_campaign_overlap_identical_window_is_409` :150 | 409 | "409 on overlap" (README:49) | ANCHORED — live bug, see Candidate Bug 3 |
| `test_campaign_overlap_partial_at_start_is_409` :162 | 409 | same | ANCHORED — live bug |
| `test_campaign_overlap_partial_at_end_is_409` :173 | 409 | same | ANCHORED — live bug |
| `test_campaign_overlap_fully_containing_is_409` :184 | 409 | same | ANCHORED — live bug |
| `test_campaign_overlap_adjacent_non_overlapping_window_succeeds` :196 | 200, no overlap | "non-overlapping time windows" + inclusive bounds (README:187,169-170) | ANCHORED, but degenerate (passes for the wrong reason today) |
| `test_delete_campaign_204` :210 | 204 | NONE FOUND | UNDEFINED |
| `test_delete_influencer_204_and_report_then_404s` :217 | 204, then 404 | "Delete one influencer, its campaigns, and click events" (README:51); 404 code UNDEFINED | MIXED — dominant UNDEFINED |

### `tests/api/user_service/test_referrers.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_click_on_registered_influencer_handle_records_one_row` :10 | 1 row recorded | "Record one link click for a referrer of either kind" (README:52) | ANCHORED |
| `test_click_on_registered_ambassador_handle_records_one_row` :19 | 1 row recorded | same | ANCHORED |
| `test_click_on_unknown_handle_is_a_no_op_but_still_succeeds` :26 | succeeds, 0 rows | "no-op for unknown handle" (README:52) | ANCHORED |
| `test_click_normalizes_handle_case_and_at_sign` :38 | normalized to lowercase | "doc id is the normalized handle (lowercase, no @)" (README:153) | ANCHORED |

### `tests/unit/user_service/test_attribution.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_first_registered_mention_wins_even_when_an_unregistered_mention_appears_earlier` :30 | first *registered* mention wins | "the first `referrers` handle @-mentioned across everything the person sent" (README:181) | ANCHORED |
| `test_first_of_two_registered_mentions_wins` :38 | earlier of two wins | same | ANCHORED |
| `test_no_mentions_returns_none` :45 | no mentions → None | same + `referrerHandle` nullable (README:111) | ANCHORED |
| `test_mentions_none_of_which_are_registered_returns_none` :50 | unregistered-only → None | same | ANCHORED |
| `test_empty_string_returns_none` :55 | empty text → None | trivial corollary | ANCHORED |
| `test_empty_registry_returns_none_even_with_mentions` :60 | empty registry → None | "first `referrers` handle" implies must be registered | ANCHORED |
| `test_uppercase_mention_matches_normalized_lowercase_handle` :65 | `@ALICE` matches `alice` | normalization (README:153) | ANCHORED |
| `test_leading_at_in_the_registry_is_not_required` :71 | registry stored without `@` | same | ANCHORED |
| `test_a_lone_registered_mention_is_found_regardless_of_surrounding_prose` :77 (property) | found amid arbitrary prose | "across everything the person sent" (README:181) | ANCHORED |
| `test_resolve_referrer_first_text_with_a_registered_mention_wins` :94 | first text's mention wins | same | ANCHORED |
| `test_resolve_referrer_skips_earlier_texts_that_only_mention_unregistered_handles` :104 | unregistered-only skipped | same | ANCHORED |
| `test_resolve_referrer_no_registered_mention_in_any_text` :111 | no registered mention → None | `referrerHandle` nullable (README:111) | ANCHORED |
| `test_resolve_referrer_empty_texts` :118 | empty list → None | trivial | ANCHORED |
| `test_resolve_referrer_uppercase_mention_across_texts` :125 | uppercase normalizes | normalization (README:153) | ANCHORED |

### `tests/api/whatsapp_adapter/test_flows.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_missing_encrypted_aes_key_returns_422` :49 | 422 | NONE FOUND | MIRRORED |
| `test_missing_encrypted_flow_data_returns_422` :60 | 422 | NONE FOUND | MIRRORED |
| `test_missing_initial_vector_returns_422` :71 | 422 | NONE FOUND | MIRRORED |
| `test_empty_body_returns_422` :82 | 422 | NONE FOUND | MIRRORED |
| `test_plausible_shaped_garbage_ciphertext_fails_with_500` :91 | 500 | NONE FOUND | MIRRORED |
| `test_non_base64_ciphertext_fails_with_500` :103 | 500 | NONE FOUND | MIRRORED |
| `test_empty_string_fields_fail_with_500` :119 | 500 | NONE FOUND | MIRRORED |

### `tests/api/whatsapp_adapter/test_ops_endpoints.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_health_returns_ok_status_and_started_at` :15 | shape | NONE FOUND | MIRRORED |
| `test_version_returns_release_metadata_shape` :27 | shape | NONE FOUND | MIRRORED |

### `tests/api/whatsapp_adapter/test_webhook_signature.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_missing_signature_header_crashes_instead_of_rejecting_cleanly` :39 | 500 | NONE FOUND | MIRRORED — flagged, see Candidate Bug 13 |
| `test_wrong_secret_signature_is_rejected_with_403` :57 | 403 | NONE FOUND | MIRRORED |
| `test_syntactically_present_but_invalid_signature_is_rejected_with_403` :79 | 403 | NONE FOUND | MIRRORED |
| `test_correct_signature_is_accepted` :101 | 200 | "webhook route returns 200 immediately" (Architecture item 4) | ANCHORED |

### `tests/api/whatsapp_adapter/test_webhook_success.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_well_formed_inbound_message_is_claimed_then_enqueued_then_200` :39 | claim→enqueue→200 | Architecture items 3-4 | ANCHORED |
| `test_duplicate_delivery_is_claimed_and_processed_only_once` :63 | claimed twice, processed once | "creates one Firestore marker per Meta message ID and skips duplicates" (item 3) | ANCHORED |
| `test_sent_status_confirms_delivery` :90 | confirm_sent called | NONE FOUND (status webhooks not in README) | MIRRORED |

### `tests/api/whatsapp_adapter/test_webhook_validation.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_malformed_supported_payload_fails_loudly` :35 | 500, nothing processed | "Fail loudly during parsing" (Test Matrix); status code itself not specified | ANCHORED (qualitative) / MIRRORED (500 specific) |
| `test_unsupported_message_type_is_ignored_and_returns_200` :57 | 200, ignored, using `type:"reaction"` | "Ignore and return `200`" (Test Matrix) | **WRONG** — mislabeled scenario, see Candidate Bug 11 |

### `tests/api/whatsapp_adapter/test_webhook_verification.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_matching_token_echoes_challenge` :33 | 200, echoes challenge | "Meta verification challenge" (Routes table) | ANCHORED |
| `test_wrong_verify_token_is_rejected` :49 | 403 | NONE FOUND | MIRRORED |
| `test_wrong_hub_mode_is_rejected` :65 | 403 | NONE FOUND | MIRRORED |
| `test_missing_query_params_crashes_instead_of_rejecting_cleanly` :81 | 500 | NONE FOUND | MIRRORED — flagged, see Candidate Bug 13 |

### `tests/e2e/test_blocking_and_failures.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_blocked_phone_gets_only_the_canned_error` :28 | 1 canned-error send, 0 transcript rows, 0 openai calls | "blocked phones receive only the canned error message; no transcript or agent work runs" (item 7) | ANCHORED (behavior); literal copy text MIRRORED |
| `test_unsupported_message_type_is_ignored` :64 | 200, ignored, using `reaction_webhook` | "Ignore and return `200`" (Test Matrix) | **WRONG** — mislabeled scenario, see Candidate Bug 11 |
| `test_malformed_supported_payload_fails_loudly` :96 | `KeyError`→500, nothing processed | "Fail loudly during parsing" | ANCHORED (qualitative) / MIRRORED (KeyError/500 specific) |
| `test_generation_failure_sends_canned_error_and_closes_the_turn` :123 | canned error sent + recorded in transcript | "Generation failures send the canned error message and record it in the transcript." | ANCHORED (behavior); row-count/ordering/literal text MIRRORED |

### `tests/e2e/test_conversation.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_known_phone_generates_and_delivers_in_model_order` :34 | ordered list: reaction, then messages in model order, then footer | "reaction first, then `messages` in model order, then a sources footer when `citations` is non-empty" (Current Delivery Semantics) | ANCHORED — correctly asserts sequence, not just membership |
| `test_form_message_resolves_persona_specific_flow_id` :126 | persona-specific Flow launch | "Form launches...`FlowLauncher`" (item 11) | ANCHORED (launch-by-persona); literal test-fixture flow ids are test-owned, not mirrored |
| `test_location_share_saves_profile_and_runs_one_turn` :208 | location saved, 1 agent turn | "Location...saves it on the profile and runs one agent turn to acknowledge it" (item 13) | ANCHORED |
| `test_button_tap_runs_one_stateless_turn` :250 | `"[tapped] {id} — {title}"` format, 1 turn | literal format string quoted in README (item 14) | ANCHORED |

### `tests/e2e/test_idempotency.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_duplicate_delivery_is_processed_once` :17 | 0 extra sends/calls on replay | "creates one Firestore marker per Meta message ID and skips duplicates" (item 3) | ANCHORED |

### `tests/e2e/test_onboarding.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_unknown_phone_sends_text_then_picks_student` :38 | fork→Flow sequence, pending action state | "Webhook claim, sender queue sends the persona fork, then the onboarding Flow" (Test Matrix) + items 5/8 | ANCHORED (shape); literal copy/ids MIRRORED |
| `test_onboarding_flow_completion_attributes_first_mention` :121 | first-mention attribution, one-turn replay | "Create user, replay the buffered pre-onboarding conversation as one agent turn, attribute from the first buffered text" (Flow Completion Routing) + first-touch quote (user_service README:181) | ANCHORED |
| `test_hidden_number_requests_contact_then_resumes` :212 | `resolve_phone` action + resume on contact share | "Senders whose number is absent receive a `REQUEST_CONTACT_INFO` prompt and a `resolve_phone` pending action..." (item 5) | ANCHORED (shape); literal copy MIRRORED |
| `test_forwarded_contact_represents_phone_request` :281 | re-presents same `contact_request` | "Forwarded contact (origin: other) while phone required | Current REQUEST_CONTACT_INFO action is re-presented" (Test Matrix) | ANCHORED |
| `test_stray_message_during_onboarding_buffers_and_represents` :331 | buffered + re-presented | "Stray message during onboarding | Conversational messages buffered; current persona buttons...re-presented" (Test Matrix) + item 8 | ANCHORED |

### `tests/e2e/test_webhook_signature.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_valid_signature_is_accepted_and_processed` :31 | 200, processed | "checks Meta's HMAC" (item 1) + "returns 200 immediately" (item 4) | ANCHORED (qualitative pass-through) |
| `test_wrong_secret_signature_is_rejected` :51 | 403 | NONE FOUND | MIRRORED |
| `test_tampered_body_signature_is_rejected` :64 | 403 | NONE FOUND | MIRRORED |

### `tests/integration/test_idempotency.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_concurrent_claims_of_the_same_id_exactly_one_wins` :26 | 1 True, 7 False under concurrency | "creates one Firestore marker per Meta message ID and skips duplicates" (item 3) | ANCHORED |
| `test_sequential_claim_of_the_same_id_succeeds_once` :33 | first True, second False | same | ANCHORED |
| `test_distinct_message_ids_each_succeed_once` :41 | distinct ids each succeed once | same | ANCHORED |

### `tests/api/text_agent/test_ops_routes.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_health_returns_ok_status_and_started_at` :15 | shape | NONE FOUND (only `/respond` in text_agent Routes table) | MIRRORED |
| `test_version_returns_release_metadata_shape` :25 | shape | NONE FOUND | MIRRORED |

### `tests/api/text_agent/test_respond_auth.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_no_auth_header_is_401` :17 | 401 | "requires bearer service secret" (README:9) — that auth is required is ANCHORED; the code is not | MIRRORED |
| `test_wrong_bearer_token_is_401` :23 | 401 | same | MIRRORED |

### `tests/api/text_agent/test_respond_failure.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_llm_exception_is_500` :33 | 500 | NONE FOUND | MIRRORED |
| `test_audio_message_part_is_422_not_transcribed` :42 | 422 | contradicts "Audio parts are transcribed to text before the model call" (README:41) | **WRONG** — see Candidate Bug 15 |

### `tests/api/text_agent/test_respond_success.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_plain_text_reply_returns_documented_shape` :39 | body == `{reaction,messages,evidence,previousResponseId}`, no `trace` | Response Format example (README:43-94) + "Returns GenerateResponse with optional reaction, ordered outbound messages, evidence, and the new tip" (README:179) | ANCHORED — currently FAILS, see Candidate Bug 14 |

### `tests/api/text_agent/test_respond_validation.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_missing_user_is_422` :29 | 422 | NONE FOUND | MIRRORED |
| `test_wrong_persona_is_422` :37 | 422 for `persona="parent"` | "`user` is the full discriminated `UserProfile` (student or teacher)" (README:41) | ANCHORED |
| `test_student_missing_scope_grade_is_422` :44 | 422 | "Students carry `scope.grade`" (README:41) | ANCHORED |
| `test_teacher_missing_scope_grades_is_422` :53 | 422 | "teachers carry `scope.grades`" (README:41) | ANCHORED |
| `test_missing_previous_response_id_is_422` :64 | 422 | contradicts README's own request example, which omits this field (README:13-39) | **WRONG** — see Candidate Bug 16 |

### `tests/api/document_worker/*` (5 files, 15 test functions)

document_worker has no in-scope README (only user_service, whatsapp_adapter,
text_agent READMEs are valid spec sources for this audit). All rows below are
UNDEFINED by explicit scope — flagged, not silently substituted with another
file as spec.

| File | Tests | Verdict |
|---|---|---|
| `test_health_version.py` :13, :23 | health/version shape | UNDEFINED |
| `test_render_auth.py` :17, :23, :31 | 401 for missing/wrong/malformed auth (partial anchor: text_agent README:111 names `DOCUMENT_WORKER_SERVICE_SECRET` as existing, not its behavior) | UNDEFINED |
| `test_render_failure.py` :43, :54 | 500 on storage failure; object-name prefix | UNDEFINED |
| `test_render_success.py` :46, :68 | 200 shape, url suffix, base64 previews | UNDEFINED |
| `test_render_validation.py` :18,26,34,42,50,59,67,75 | 422 for missing/invalid fields (8 tests) | UNDEFINED |

### `tests/api/redirect_service/*` (3 files, 8 test functions)

redirect_service likewise has no in-scope README.

| File | Tests | Verdict |
|---|---|---|
| `test_click_best_effort.py` :67,83,134 | best-effort click logging, call cardinality | UNDEFINED |
| `test_health_version.py` :18,34,50 | health/version shape, env-driven values | UNDEFINED |
| `test_redirect.py` :40,50,67,81,90 | 302 to `wa.me` URL, handle pass-through, 404 on empty segment | UNDEFINED |

### `tests/api/user_service/test_health_version.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_health` :10 | 200 | "GET /health | Health check" (README:63) | ANCHORED (status only, no body shape claimed) |
| `test_version` :15 | 200 | "GET /version | Release metadata" (README:64) | ANCHORED (status only) |

### `tests/integration/test_cross_service_contract.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_adapter_create_user_payload_round_trips_through_firestore_layout` :50 | phone/name/persona/scope round-trip | Firestore Layout fields (README:106-116) | ANCHORED |
| `test_adapter_append_transcript_payload_advances_the_tip_correctly` :75 | tip absent on first append, advances on reply | "Append returns {previousResponseId, startedAtMs}" + "Absent on a new session" (README:198,192) | ANCHORED |
| `test_adapter_append_result_is_a_valid_text_agent_previous_response_id` :122 | tip is None; userId equality | tip-absence quote ANCHORED; userId equality tautological by construction | ANCHORED (tip fact) / UNDEFINED (trivial userId check) |
| `test_text_agent_profile_update_payload_overlays_correctly` :148 | profile overlay updates | "Overlay authored profile fields (name, institution, scope)" (README:39) | ANCHORED |
| `test_text_agent_ambassador_and_rewards_responses_validate` :168 | zero-referral → `points==0`, `balanceInr==0` | derivable chain from README:188-189 | ANCHORED |
| `test_malformed_create_user_payload_is_422` :193 | 422 for missing persona/scope | same Firestore Layout quote (README:106-116) | ANCHORED |
| `test_malformed_append_payload_is_422` :206 | 422 for missing `text` field | NONE FOUND (README doesn't specify `TextMessage` field shape) | MIRRORED |
| `test_users_client_parses_live_responses` :215 | round-tripped name/userId/phone | Firestore Layout fields (README:106-107) | ANCHORED (thin) |

### `infra/tests/test_reader.py`

| Test | Assertion | Spec rule | Verdict |
|---|---|---|---|
| `test_session_read_renders_judgment_when_text_is_intent` :6 | exact literal render strings (`"grounding 2"`, `"# Transcript"` header) | NONE FOUND — README describes only that sessions are read via `sessions(scope=...)`, never a literal render format | UNDEFINED |

---

## Section 3 — SPEC GAPS

Grouped by topic, so the READMEs can be amended to close each gap.

**Gift-card / ambassador economics (user_service/README.md)**
- The `AMBASSADOR_TIERS` ladder (points thresholds and ₹ rewards per tier)
  is never enumerated — only "a frozen commitment" is asserted (README:188).
  ~30 test assertions across 5 files depend on these exact numbers with zero
  spec backing.
- The `REWARD_AMOUNTS` / storefront denomination ladder is never enumerated.
- The `offered_amounts` algorithm itself (flexible vs. fixed-denomination
  paths, min/max bound handling, exact-balance synthesis between rungs) has
  no specification at all — ~15 tests, including several property-based
  "oracle" tests that literally reimplement the algorithm as their own
  expected value.
- Ambassador handle-minting format (Latin-letters requirement, punctuation
  handling, alphabet suffix length/charset) is undocumented.
- Whether `balance_inr` should be allowed to go negative is unaddressed — the
  stated formula permits it but no design intent is recorded.
- Hubble's terminal-failure status enumeration (`FAILED`/`CANCELLED`/
  `REVERSED`) and the correct behavior for a genuinely unrecognized status
  string are not documented (only 404, `PROCESSING`, and "terminal order"
  are).
- `_campaign_spend`'s base-fee + capped block-incentive formula is not
  described anywhere, nor is behavior for negative onboard counts.

**Session/activity semantics (user_service/README.md)**
- The exact-2-hour session-gap boundary operator (`<=` vs `<`) is not fixed
  by the current wording ("a gap of two hours...opens a new session"), and
  the test suite currently contains two tests that assert opposite answers
  for this exact boundary.
- The directory "active / dormant / never" activity-state vocabulary and its
  7-day window constant do not appear anywhere in the README, despite ~10
  tests depending on the exact window value and its closed-interval
  boundary.
- Directory search/sort semantics (multi-token AND matching, casefold
  comparison, `None` sort-order placement, stable-tie behavior) are only
  described as "searched and sorted in the service," with no rules.

**Auth / identity (user_service/README.md, whatsapp_adapter/README.md)**
- Phone normalization for `userId` derivation (`+91` prefix, whitespace,
  leading zeros) is not defined — "derived from normalized phone" is the
  only wording, and no normalization function exists in the codebase at all.
  This is the most operationally important gap, since WhatsApp inbound
  phones and stored canonical phones could plausibly differ in format.
  See Candidate Bug 17.
- `/health` and `/version` auth-exemption status is not addressed by the
  README's auth sentence, which names only one public route
  (`POST /access/phone`). A test in the suite currently misquotes this
  sentence to justify two additional unauthenticated routes. See Candidate
  Bug 12.
- HTTP status codes for not-found/validation-error paths (404 vs. no
  documented code, 422 vs. unspecified) are never stated anywhere in any of
  the three READMEs — this affects ~35 test assertions across the whole
  suite.
- Webhook/verification behavior for missing signature headers or missing
  verification query parameters is unaddressed (currently crashes with 500).

**WhatsApp adapter (whatsapp_adapter/README.md)**
- The Test Matrix's "Unsupported message type | Ignore and return 200" row
  is untested for its actual scenario (a genuinely unrecognized WhatsApp
  `type` string) and contradicted by the real dispatch code for that
  scenario. The two tests claiming to cover this row instead test a
  `"reaction"` payload, which is handled by an entirely different, unrelated
  code path.
- WhatsApp Flow endpoint (`/flows/onboarding`, `/flows/grade`) error/validation
  status codes are unaddressed.
- Delivery-status webhook handling (`test_sent_status_confirms_delivery`) is
  not mentioned in the README at all.

**text_agent (text_agent/README.md)**
- Audio-input handling is contradictory: the README states audio is
  "transcribed to text before the model call," but the implementation has no
  audio wire type or transcriber, and a test commits the 422-rejection as
  correct. See Candidate Bug 15.
- The Request Format's own JSON example omits `previousResponseId`, but the
  schema requires the key be present; a test asserts 422 for the README's own
  example payload. See Candidate Bug 16.
- The Response Format's documented shape (`reaction`/`messages`/`evidence`)
  does not match the real wire response, which also includes an undocumented
  `trace` field. See Candidate Bug 14.

**Out of audit scope entirely**
- `document_worker` and `redirect_service` have no README among the three
  valid spec sources for this audit. All 23 test functions across their 8
  test files are UNDEFINED by design — not a defect in those tests, simply
  outside what this audit's designated spec set can verify. If these
  services are meant to be covered by a future audit, they need their own
  README specs first.

---

## Section 4 — COUNTS

| Verdict | Count |
|---|---|
| ANCHORED | 150 |
| MIRRORED | 114 |
| UNDEFINED | 70 |
| WRONG | 6 |
| **Total test functions audited** | **340** |

WRONG verdicts (6): `test_auth_boundary.py::test_public_route_exemption_set_matches_readme`;
`test_webhook_validation.py::test_unsupported_message_type_is_ignored_and_returns_200`;
`test_blocking_and_failures.py::test_unsupported_message_type_is_ignored`;
`test_respond_failure.py::test_audio_message_part_is_422_not_transcribed`;
`test_respond_validation.py::test_missing_previous_response_id_is_422`;
and the blocklist-cascade clause within `test_cascade.py::test_delete_user_removes_owned_data_and_cascades_referrer_registry`
(ANCHORED to spec, contradicted by implementation).
