# Tests that rubber-stamp the code

Sources: `tests/outcomes/ASSERTION_AUDIT.md`, plus cross-checks from `tests/outcomes/FINDINGS.md`,
`tests/outcomes/EXECUTION_AUDIT.md`, and `tests/outcomes/UNCERTAINTY.md`.

These tests do **not** check the README independently. They copy the current
implementation's numbers, status codes, or shapes. If the code changes, the
test is usually updated to match — so it stays green and never catches a
regression against spec.

Two kinds from the assertion audit:

- **WRONG** — the test contradicts the README, or tests the wrong scenario, and
  treats that as correct.
- **MIRRORED** — the expected value could only have come from reading the
  code. There is no README sentence that independently requires it.

Not listed in the main tables: **ANCHORED** tests (they follow the README) and
most **UNDEFINED** tests (the README is silent). Extra sections at the bottom
add cases the other three docs found that belong with this list even though
the assertion audit did not tag them MIRRORED/WRONG.

Counts from the original assertion audit (before this pass's remediation):
**6 WRONG**, **114 MIRRORED**, of **340** test functions. Not every MIRRORED
row was green at audit time — see
[Mirrored rows that already fail](#mirrored-rows-that-already-fail).

**Current status, after this pass's remediation:** 6/6 WRONG rows rewritten
from spec (0 remain lying). Of the 114 MIRRORED rows, every money/ladder
group (~50 tests), every "500 as contract" group (10 tests), every
canned-copy group (~15 tests), the property-test reimplementation cases,
and the explicitly-named "kept green as a guess" cases are fixed or
reviewed-and-annotated; see the "Remediation changelog (this pass)" section
near the bottom for the full inventory. The remaining MIRRORED rows
(directory/search/sort pure-logic behavior, plain Pydantic-422 shape tests,
resource-lookup 404s consistent with the shared `load_user_or_404`
convention) were reviewed and left as-is because there is no
better-than-current oracle without inventing undocumented product policy —
see "Reviewed and intentionally left unchanged" in the changelog.

---

## WRONG — freeze a spec contradiction as “correct”

If you change the code to match the README, these tests fail. If you leave the
code as-is, they keep the bug (or the wrong scenario) looking intentional.

**All five rows below have been rewritten from spec** (see commit history /
diff for exact before→after). Each now fails against current code, which is
the correct outcome — they are the oracle for a real spec-vs-code gap, not
freezing one as correct anymore.

| File | Test | What the test asserted (before) | What the README actually says | Status |
|---|---|---|---|---|
| `tests/api/user_service/test_auth_boundary.py:89` | `test_public_route_exemption_set_matches_readme` | Public set was `{POST /access/phone, GET /health, GET /version}` | “the only public route is `POST /access/phone`” | **Rewritten.** `PUBLIC_EXEMPT` now `{("POST", "/access/phone")}` only. This pulls `GET /health` and `GET /version` into the parametrized 401-with-no-auth / 401-with-wrong-token checks — both now **fail** (health/version do not actually require the internal bearer secret today), which is the correct oracle: the README never calls them public. |
| `tests/api/whatsapp_adapter/test_webhook_validation.py:57` | `test_unsupported_message_type_is_ignored_and_returns_200` | `type: "reaction"` is ignored with 200 | Test Matrix: unsupported type → ignore and 200. `reaction` is a different, already-dropped branch — not what this row means. | **Split into two tests.** `test_reaction_message_is_dropped_and_returns_200` keeps the `"reaction"` scenario (genuinely ignored, still passes — but relabeled as the reaction-drop branch, not the README's unsupported-type claim). New `test_unrecognized_message_type_is_ignored_and_returns_200` uses a genuinely unrecognized type (`"order"`, added to `payloads.py`) and asserts the README's literal claim — **fails today** (it runs a full agent turn via `AgentInputBuilder.unsupported()`, confirming UNCERTAINTY Journey 12). |
| `tests/e2e/test_blocking_and_failures.py:64` | `test_unsupported_message_type_is_ignored` | Same as above, using `reaction_webhook` | Same mislabeled scenario. | **Split the same way** into `test_reaction_message_is_dropped` (kept) and `test_unrecognized_message_type_is_ignored` (new, uses `payloads.unrecognized_type_webhook`, type `"order"`) — expected to fail once the e2e suite can run (JRE gap, see EXECUTION_AUDIT). |
| `tests/api/text_agent/test_respond_failure.py:42` | `test_audio_message_part_is_422_not_transcribed` | Audio part → 422 | “Audio parts are transcribed to text before the model call.” Transcription is unimplemented. | **Rewritten** to `test_audio_message_part_is_transcribed_before_the_model_call`: asserts `200` and that the fake LLM was actually called. **Fails today** (`422`) — confirmed by running. |
| `tests/api/text_agent/test_respond_validation.py:64` | `test_missing_previous_response_id_is_422` | Omitting `previousResponseId` → 422 | The README’s own request JSON example omits that field and presents it as valid. | **Rewritten** to `test_missing_previous_response_id_is_accepted`: asserts `200`. **Fails today** (`422`) — confirmed by running. |

The assertion audit’s sixth WRONG tag was the **blocklist clause** of
`test_delete_user_removes_owned_data_and_cascades_referrer_registry`. That
test is **not** a rubber-stamp: it is spec-correct and **fails today**
(FINDINGS integration #1). Same for `test_plain_text_reply_returns_documented_shape`
(extra `trace` field) — ANCHORED, currently red. Those belong in FINDINGS,
not here.

---

## MIRRORED — copied from code, so a code change will not fail them

Grouped by file. “Assertion” is what the test hard-codes. “Copied from” is
where that value actually lives.

### Money / gifting / ambassador ladders

None of the ₹ amounts, tier thresholds, or storefront-ladder rules appear in
any README. The spec only says the ladder is “a frozen commitment” in code.

**Status: rewritten.** `tests/unit/user_service/factories.py` now imports
`AMBASSADOR_TIERS`, `REWARD_AMOUNTS`, `ACTIVE_USER_WINDOW_MS`,
`RETENTION_WINDOW_MS`, `HANDLE_SUFFIX_ALPHABET`, `HANDLE_SUFFIX_LENGTH`
directly from `user_service.app.src.constants` instead of re-transcribing a
second hand-copied set of numbers; `TIER_POINTS` / `TIER_REWARDS_INR` /
`TIER_NAMES` / `EARNED_AT_TIER_INR` / `FLEXIBLE_LADDER_INR` are now derived
from that import. `tests/e2e/constants.py`'s reward-catalogue block
(`AMAZON_BRAND`, `ALL_REWARD_PRODUCT_IDS`, `TIER_ONE_*`) does the same. Every
test below that used to hard-code a ladder number (`5`, `100`, `550`,
`"Campus Ambassador"`, …) now reads it off these imports, so a ladder change
in `constants.py` is automatically visible instead of silently going stale.
The two `offered_amounts` property tests that used to reimplement the
algorithm and compare the function to a second copy of itself
(`test_flexible_amounts_are_the_ladder_plus_exact_balance_inside_bounds`,
`test_fixed_amounts_stay_within_bounds_sorted_unique`) were rewritten to
assert only independently-statable invariants (sorted, unique, bounded,
every in-bounds ladder rung/denomination present, nothing outside the
ladder-or-exact-balance set invented) — same fix applied to
`tests/unit/user_service/test_influencers.py::
test_spend_never_below_base_and_never_above_base_plus_cap`, which now
asserts only the two documented bounds (`spend >= base`, `spend <= base +
cap`) instead of re-deriving `_campaign_spend`'s block-counting formula
inline. All of the above still pass against current code (the ladder
numbers were never wrong, only the tests' independence from them was) —
verified by running `tests/unit/user_service/test_gifting.py`,
`test_ambassadors.py`, and the touched parts of `test_influencers.py`;
`tests/api/user_service/test_gifting.py` was also updated the same way and
still passes except the two rows already tracked in FINDINGS (API #2, #4),
which are untouched pre-existing failures, not regressions from this pass.

The rows below are the original per-test inventory this rewrite addressed;
kept for traceability of what each test used to hard-code.

#### `tests/unit/user_service/test_gifting.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_earned_inr_below_first_tier_is_zero` :35 | `earned_inr(0)==0`, `earned_inr(4)==0` | `constants.py:11` |
| `test_earned_inr_exactly_at_each_tier` :42 | 100/550/1450/3450 at 5/20/45/95 | `constants.py:11-14` |
| `test_earned_inr_one_below_each_tier` :51 | off-by-one below ladder | same |
| `test_earned_inr_one_above_each_tier` :59 | off-by-one above ladder | same |
| `test_earned_inr_far_above_top_tier_...` :67 | `earned_inr(10_000)==3450` | same |
| `test_earned_inr_negative_points_cross_no_rung` :72 | `earned_inr(-1)==0` | same |
| `test_earned_inr_equals_sum_of_every_crossed_rung` :82 (property) | sum of crossed rungs | same |
| `test_balance_inr_is_earned_minus_non_failed_spend` :166 | `balance_inr(5,[pending 50])==50` | formula is spec; ₹100 input is `constants.py:11` |
| `test_balance_inr_failed_card_does_not_reduce_balance` :173 | `balance_inr(5,[failed 100])==100` | same |
| `test_offered_amounts_inactive_product_is_empty` :212 | inactive → `[]` | `gifting.py` |
| `test_offered_amounts_none_amount_restrictions_is_empty` :218 | `None` → `[]` | `gifting.py` |
| `test_offered_amounts_empty_how_to_use_instructions_is_empty` :224 | no instructions → `[]` | `gifting.py` |
| `test_offered_amounts_balance_below_min_is_empty` :230 | below min → `[]` | `gifting.py` |
| `test_offered_amounts_flexible_balance_exactly_min` :243 | `[10]` | `gifting.py` |
| `test_offered_amounts_flexible_balance_on_a_ladder_rung` :252 | ladder to 2000 | `constants.py:32` |
| `test_offered_amounts_flexible_includes_exact_balance_between_rungs` :260 | e.g. `[50,75]` | `gifting.py` |
| `test_offered_amounts_flexible_balance_above_max_is_capped_at_max` :267 | capped ladder | `gifting.py` |
| `test_offered_amounts_flexible_none_denominations_matches_empty_list` :277 | `None` ≡ `[]` | `gifting.py` |
| `test_offered_amounts_fixed_does_not_add_exact_balance` :295 | no exact-balance synth | `gifting.py` |
| `test_offered_amounts_fixed_balance_exactly_min_only_if_min_is_a_denomination` :304 | fixed-path min behavior | `gifting.py` |
| `test_offered_amounts_fixed_balance_above_max_is_capped_at_max` :312 | filter to ≤max | `gifting.py` |
| `test_offered_amounts_fixed_is_sorted_and_deduplicated` :318 | sorted/deduped | `gifting.py` |
| `test_offered_amounts_fixed_filters_denominations_outside_min_max` :324 | bound filter | `gifting.py` |
| `test_flexible_amounts_are_the_ladder_plus_exact_balance_inside_bounds` :360 (property) | reimplements the algorithm as the oracle | `gifting.py:30-38` |
| `test_fixed_amounts_stay_within_bounds_sorted_unique` :380 (property) | same, fixed fork | `gifting.py` |
| `test_offered_amounts_negative_balance_is_empty` :396 (property) | negative balance → `[]` | `gifting.py` |

#### `tests/api/user_service/test_gifting.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_rewards_balance_and_options_for_ambassador_at_tier_one` :81 | `balanceInr==100`, `amountsInr==[50,100]` | ladder numerics in `constants.py` |
| `test_redeem_gift_card_success_shape` :102 | 200, `status=="succeeded"`, brand/amount echoed | status enum is spec; the rest is code shape |

#### `tests/unit/user_service/test_ambassadors.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_tier_reached_below_first_rung_is_none` :45 | `_tier_reached(0/4) is None` | `AMBASSADOR_TIERS` |
| `test_next_tier_below_first_rung_is_campus_ambassador` :51 | tier-1 name/points/reward | same |
| `test_tier_reached_exactly_at_each_rung` :60 | 4 tier names at thresholds | same |
| `test_next_tier_at_top_rung_is_none` :68 | `_next_tier(95/10000) is None` | same |
| `test_next_tier_between_rungs` :74 | tier-3 name/points/reward | same |
| `test_negative_points_have_not_reached_a_tier` :83 | negative points → no tier | same |
| `test_tier_reached_and_next_tier_are_always_consistent` :92 (property) | ladder-consistency oracle | same |
| `test_mint_handle_name_with_no_latin_letters_raises` :133 | `ValueError` on Han name | `ambassadors.py:31-34` |
| `test_mint_handle_punctuation_only_name_raises` :141 | `ValueError` | same |
| `test_mint_handle_empty_name_raises` :148 | `ValueError` | same |
| `test_mint_handle_strips_leading_and_trailing_whitespace` :155 | stem `"arjun"` | same |
| `test_mint_handle_single_character_first_name` :165 | stem `"a"` | same |
| `test_mint_handle_matches_documented_arjun_form` :175 | `arjun-x4k9` form | code docstring, not README |
| `test_mint_handle_retries_until_the_registry_reports_a_free_handle` :185 | collision-retry semantics | `ambassadors.py` |
| `test_minted_handle_always_has_a_four_char_alphabet_suffix` :199 (property) | suffix length 4 | same |

#### `tests/api/user_service/test_ambassadors.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_enroll_ambassador_first_call_mints_handle_and_returns_status` :12 | handle prefix, zero counts, `tier is None`, `balanceInr=0` | handle/tier thresholds in code |
| `test_get_ambassador_status_after_enroll` :100 | handle prefix `"esha-"` | handle-minting code |
| `test_list_ambassadors_row_shape` :113 | `points=0,started=0,tier=None` | `tier=None` mirrors the first threshold |

#### `tests/e2e/test_ambassador_and_gifting.py` (numerics only)

Behavior against README settlement/referral rules is ANCHORED. **Fixed:**
the ₹ / tier literals below no longer copy `constants.py` by hand — both
tests now read `K.TIER_ONE_POINTS` / `K.TIER_ONE_REWARD_INR` (bound to
`AMBASSADOR_TIERS[0]` via `tests/e2e/constants.py`), and the redeem test's
fixed-denomination Hubble catalogue is parameterized by that same value
instead of a coincidentally-matching `100` literal.

| Test | Assertion | Copied from |
|---|---|---|
| `test_ambassador_enrollment_counts_a_referred_student` :51 | tier-1 numerics | `constants.py` |
| `test_gift_card_redeem_settles_and_debits_balance` :148 | tier-1 numerics | `constants.py` |

#### `tests/integration/test_hubble_settlement.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_settlement_terminal_failure_fails_the_card_and_restores_balance` :101 | `FAILED` / `CANCELLED` / `REVERSED` → failed | `gifting.py` status list (README never enumerates these) |
| `test_settlement_unknown_status_stays_pending_and_does_not_crash` :186 | unrecognized status → pending | `if status != "SUCCESS": return gift_card` fallthrough |
| `test_place_order_timeout_after_upstream_success_settles_without_double_charge` :200 | timeout → 500; later read settles by referenceId | settlement-on-timeout mechanism, not in README |

#### `tests/unit/user_service/test_influencers.py`

Spend formula (base fee + capped block incentive) is not in the README, and
`Payout` terms (`baseInr`, `perBlockInr`, `blockSize`, `incentiveCapInr`) are
per-campaign runtime input, not a named frozen table like `AMBASSADOR_TIERS`
— there is no constant to import here, so the boundary rows below are still
test-author-chosen numbers (left unchanged; not a mirrored ladder in the
same sense as the money tables above).

| Test | Assertion | Copied from |
|---|---|---|
| `test_campaign_spend_zero_onboards_is_the_base_fee` :110 | spend(0)==1000 | `_campaign_spend` |
| `test_campaign_spend_partial_block_earns_nothing_beyond_base` :115 | 4 / blockSize 5 → 1000 | same |
| `test_campaign_spend_exactly_one_block` :121 | 5 onboards → 1050 | same |
| `test_campaign_spend_incentive_is_capped` :127 | 40 onboards → 1200 capped | same |
| `test_campaign_spend_block_size_of_one` :135 | blockSize=1, 3 onboards → 130 | same |
| `test_campaign_spend_block_size_one_still_respects_the_cap` :141 | 20 onboards → 55 capped | same |

**Fixed:** `test_spend_never_below_base_and_never_above_base_plus_cap` :154
(property) previously reimplemented `_campaign_spend`'s block-counting
formula inline and compared the function to a second copy of itself — now
asserts only the two independently-statable bounds (`spend >= base`,
`spend <= base + cap`).

---

### Directory / search / sort (no README rules)

#### `tests/api/user_service/test_directory.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_list_users_offset_beyond_total_returns_empty_but_true_total` :32 | empty entries, true totalCount | directory implementation |
| `test_list_users_limit_zero_returns_zero_items` :43 | limit=0 → empty | same |
| `test_list_users_sort_by_name_is_case_insensitive_alphabetical` :57 | case-insensitive sort | same |
| `test_list_users_search_multi_token_requires_all_tokens_to_match` :78 | AND semantics | same |
| `test_list_users_combined_grade_and_subject_filters` :94 | combined filters | same |
| `test_list_users_422_missing_required_persona` :116 | 422 | generic validation |
| `test_list_profiles_422_missing_required_persona` :133 | 422 | same |

#### `tests/unit/user_service/test_directory.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_matches_empty_query_matches_everything` :101 | blank q matches all | directory match code |
| `test_matches_multi_token_requires_every_token` :108 | AND semantics | same |
| `test_matches_unicode_name_under_casefold` :120 | unicode casefold | same |
| `test_matches_grade_filter_in_isolation` :139 | empty list unconstrained; membership | same |
| `test_matches_subject_filter_in_isolation` :151 | same for subject | same |
| `test_matches_activity_filter_in_isolation` :169 | same for activity | same |
| `test_matches_attribution_filter_in_isolation` :182 | organic = `referrerHandle is None` | “organic” vocabulary is not spec |
| `test_matches_blocked_filter_in_isolation` :196 | blocked/open filter | same |
| `test_matches_all_filters_combined` :208 | all filters AND | same |
| `test_blank_queries_match_any_name` :246 (property) | blank/whitespace q matches all | same |
| `test_sort_key_name_orders_alphabetically_by_casefold` :259 | casefolded sort | same |
| `test_sort_key_identical_names_are_a_stable_tie` :267 | stable tie order | same |
| `test_sort_key_last_active_puts_none_after_every_real_timestamp` :283 | `None` sorts last | same |
| `test_none_last_message_sorts_after_any_real_timestamp_on_last_active` :305 (property) | same, generalized | same |

---

### Status codes and shapes the README never states

HTTP 404/422/204/200-vs-201 are almost never named in the three READMEs.
These tests freeze whatever the current FastAPI/Pydantic wiring returns.

#### `tests/api/user_service/test_threads.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_append_transcript_404_for_unknown_user` :45 | 404 | route wiring |
| `test_append_transcript_422_empty_messages` :57 | 422 | pydantic |
| `test_append_transcript_422_missing_read_ids` :66 | 422 | pydantic |
| `test_get_session_transcripts_404_for_unknown_user` :95 | 404 | route wiring |
| `test_set_session_extraction_422_missing_field` :186 | 422 | pydantic |

#### `tests/integration/test_session_boundary.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_started_at_ms_of_wrong_type_is_422` :93 | 422 | pydantic |

#### `tests/integration/test_sequences.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_append_empty_messages_is_422` :59 | 422 | pydantic |

#### `tests/integration/test_transactions.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_append_with_non_list_read_ids_is_422` :181 | 422 | pydantic |

#### `tests/integration/test_derive_on_read.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_directory_unknown_user_is_404` :65 | 404 | route wiring |
| `test_influencer_unknown_handle_is_404` :226 | 404 | route wiring |

#### `tests/api/user_service/test_access.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_public_access_phone_needs_onboarding_for_unknown_phone` :12 | no `user` field | response shape (status itself is spec) |
| `test_public_access_phone_allowed_for_onboarded_phone` :20 | `user` populated | `user` field shape is not in README |

#### `tests/api/user_service/test_blocklist.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_unblock_unknown_phone_is_idempotent_204` :37 | idempotent 204 | route wiring |

#### `tests/api/user_service/test_enrollments.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_get_enrollments_empty_for_unrelated_user` :22 | empty lists, specific key names | response keys |
| `test_create_enrollment_then_visible_from_both_sides` :28 | key names | key names (bidirectional visibility is spec) |
| `test_delete_enrollment_removes_it` :51 | 204 / keys | status code (removal effect is spec) |

#### `tests/api/user_service/test_users.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_create_user_returns_201_or_200_with_profile_shape` :12 | 200 (not 201) | current create status |
| `test_get_user_404_for_unknown_user_id` :75 | 404 | route wiring |
| `test_batch_get_users_returns_only_existing_ids_in_request_order` :92 | order preserved, unknown ids dropped | batch-get implementation |
| `test_get_directory_entry_404_for_unknown_user` :117 | 404 | route wiring |
| `test_get_directory_entry_shape` :122 | `activityState=="never"` | `"never"` literal not in README |
| `test_delete_user_returns_204_and_user_then_404s` :138 | 204 | status code (delete effect is spec) |
| `test_delete_unknown_user_returns_204_delete_has_no_documented_404` :149 | unknown user delete → 204 | author-admitted “no documented 404” |
| `test_update_profile_404_for_unknown_user` :172 | 404 | route wiring |
| `test_set_location_404_for_unknown_user` :205 | 404 | route wiring |

#### `tests/integration/test_cross_service_contract.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_malformed_append_payload_is_422` :206 | 422 for missing `text` | `TextMessage` field shape is not in README |

---

### WhatsApp adapter — codes and crash behavior copied from routes

**This whole section is the original, pre-fix inventory** (kept for
traceability of what each test used to hard-code). The three "500 crashes
instead of rejecting cleanly" rows and the "500 specifically" fail-loudly
row were all rewritten in this pass — see "Crash / 500 frozen as the
contract (FINDINGS robustness) — REWRITTEN" above and the changelog at the
bottom for current names/assertions. The 422 rows (real Pydantic validation
on the two `/flows/*` routes) and the ops-route/webhook-success rows were
not changed — they are structural request-validation facts and documented
architecture wiring, not guessed business-rule status codes.

#### `tests/api/whatsapp_adapter/test_flows.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_missing_encrypted_aes_key_returns_422` :49 | 422 | flow endpoint validation |
| `test_missing_encrypted_flow_data_returns_422` :60 | 422 | same |
| `test_missing_initial_vector_returns_422` :71 | 422 | same |
| `test_empty_body_returns_422` :82 | 422 | same |
| ~~`test_plausible_shaped_garbage_ciphertext_fails_with_500`~~ :91 | ~~500~~ **now `test_..._fails_with_421`, asserts 421** | decrypt crash → Meta's Flow Data Exchange convention |
| ~~`test_non_base64_ciphertext_fails_with_500`~~ :103 | ~~500~~ **now asserts 421** | same |
| ~~`test_empty_string_fields_fail_with_500`~~ :119 | ~~500~~ **now asserts 421** | same |

#### `tests/api/whatsapp_adapter/test_ops_endpoints.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_health_returns_ok_status_and_started_at` :15 | body shape | ops route |
| `test_version_returns_release_metadata_shape` :27 | body shape | ops route |

#### `tests/api/whatsapp_adapter/test_webhook_signature.py`

| Test | Assertion | Copied from |
|---|---|---|
| ~~`test_missing_signature_header_crashes_instead_of_rejecting_cleanly`~~ :39 | ~~500~~ **now `test_missing_signature_header_is_rejected_with_403`, asserts 403** | unguarded `request.headers[...]` → this route's own established rejection code |
| `test_wrong_secret_signature_is_rejected_with_403` :57 | 403 | signature middleware |
| `test_syntactically_present_but_invalid_signature_is_rejected_with_403` :79 | 403 | same |

#### `tests/api/whatsapp_adapter/test_webhook_success.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_sent_status_confirms_delivery` :90 | `confirm_sent` called | status webhooks are not in the README |

#### `tests/api/whatsapp_adapter/test_webhook_validation.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_malformed_supported_payload_fails_loudly` :35 | ~~500 specifically~~ **now `not (200 <= status < 300)`** | “Fail loudly” is spec; the 500 is code |

#### `tests/api/whatsapp_adapter/test_webhook_verification.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_wrong_verify_token_is_rejected` :49 | 403 | verification route |
| `test_wrong_hub_mode_is_rejected` :65 | 403 | same |
| ~~`test_missing_query_params_crashes_instead_of_rejecting_cleanly`~~ :81 | ~~500~~ **now `test_missing_query_params_is_rejected_with_403`, asserts 403** | unguarded query-param index → this route's own established rejection code |

#### `tests/e2e/test_blocking_and_failures.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_blocked_phone_gets_only_the_canned_error` :28 | **fixed:** `K.CANNED_ERROR` now imports from `infra.canned.CANNED_RESPONSES`, no longer a hand-copied literal (see tests/e2e/constants.py) | copy text (behavior is spec) |
| `test_malformed_supported_payload_fails_loudly` :96 | ~~`KeyError` → 500~~ **now `not (200 <= status < 300)`, no exception-type pin** | exception type and 500 (qualitative fail-loudly is spec) |
| `test_generation_failure_sends_canned_error_and_closes_the_turn` :123 | row-count / ordering; body text is `K.CANNED_ERROR` (**fixed**, now import-bound) | same |

#### `tests/e2e/test_onboarding.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_unknown_phone_sends_text_then_picks_student` :38 | **fixed:** body text is now built from `K.INTRO_TEMPLATE.format(name=name)` + `K.PERSONA_QUESTION` (both import-bound), not a hand-typed duplicate; flow ids are test-harness-owned config | fixture copy (shape is spec) |
| `test_hidden_number_requests_contact_then_resumes` :212 | **fixed:** body text now built from `K.INTRO_TEMPLATE` / `K.PHONE_REQUEST` / `K.PHONE_ACK` (import-bound) at both assertion sites in this test | same |

#### `tests/e2e/test_webhook_signature.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_wrong_secret_signature_is_rejected` :51 | 403 | signature middleware |
| `test_tampered_body_signature_is_rejected` :64 | 403 | same |

---

### text_agent — auth codes and ops shapes not in the Routes table

#### `tests/api/text_agent/test_ops_routes.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_health_returns_ok_status_and_started_at` :15 | body shape | ops route (README Routes table only lists `/respond`) |
| `test_version_returns_release_metadata_shape` :25 | body shape | same |

#### `tests/api/text_agent/test_respond_auth.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_no_auth_header_is_401` :17 | 401 | FastAPI bearer wiring (that auth is required is spec; the code is not) |
| `test_wrong_bearer_token_is_401` :23 | 401 | same |

#### `tests/api/text_agent/test_respond_failure.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_llm_exception_is_500` :33 | 500 | exception handler |

#### `tests/api/text_agent/test_respond_validation.py`

| Test | Assertion | Copied from |
|---|---|---|
| `test_missing_user_is_422` :29 | 422 | pydantic |

---

---

## Added from FINDINGS / EXECUTION / UNCERTAINTY

These did not show up as MIRRORED/WRONG rows, but they are the same class of
problem: a green (or weakly green) test that will not catch the product rule
if the code moves.

### Passes for the wrong reason

Overlap logic does not exist at all (`CampaignsRepository.create` never
checks). This test still gets 200, so it never actually proves “adjacent
windows are allowed.” If overlap checks are added later, it might keep
passing; if they never are, it also keeps passing.

| File | Test | Why it is weak |
|---|---|---|
| `tests/api/user_service/test_influencers.py:196` | `test_campaign_overlap_adjacent_non_overlapping_window_succeeds` | ANCHORED to “non-overlapping time windows,” but today it passes only because **every** window is accepted. |

### Guessed the operator, stayed green

The README does not name `<=` vs `<`. The test author guessed; the guess
matched the code, so the test is now a silent freeze of that operator.

| File | Test | Guess that matched code | Confirmed by |
|---|---|---|---|
| `tests/e2e/test_session_gap.py:45` | `test_session_gap_boundary` (exactly 2h) | **Rewritten.** Was: exact 2h stays in the same session (matched code's exclusive `>`). Now: exact 2h opens a new session, matching the README's plain-English reading and the integration suite's sibling test. **Fails today** (confirmed: code implements `<=`), consistently with `tests/integration/test_session_boundary.py::test_gap_exactly_two_hours_opens_a_new_session` instead of contradicting it. | UNCERTAINTY Journey 15; FINDINGS integration #5 |
| `tests/unit/user_service/test_directory.py:49` | `test_activity_state_exactly_on_the_window_boundary_is_active` | `age == ACTIVE_USER_WINDOW_MS` → `"active"` (closed interval) | UNCERTAINTY unit “Active-window inclusivity.” Window length itself is not in the README. **Not changed** -- unlike the session-gap wording ("a gap of two hours... opens"), the README's "within this window" phrasing plausibly reads as inclusive, and no sibling test disagrees; kept as a documented, not silently-frozen, guess. |
| same file :58, :81 | one-ms-inside / property “any age inside the closed window” | same closed-interval guess | same |

### Product gap frozen as intended (ANCHORED, but still a freeze)

| File | Test | What it freezes | Confirmed by |
|---|---|---|---|
| `tests/unit/user_service/test_gifting.py:179` | `test_balance_inr_can_go_negative_when_spend_exceeds_earned` | `balance_inr(0, [succeeded ₹100]) == -100`. Formula is in the README; **no floor** is. A green test now makes a negative wallet look designed. | FINDINGS unit D1 |

### Crash / 500 frozen as the contract (FINDINGS robustness) — REWRITTEN

All three rows below have been rewritten to no longer assert 500 as the
contract, per the "never assert 500 because there is no try/except" rule.
Each now asserts the boundary's own established/documented rejection code
instead, and fails against current code (the correct oracle for the gap):

| File | Test (new name) | Old frozen behavior | New assertion | FINDINGS note |
|---|---|---|---|---|
| `tests/api/whatsapp_adapter/test_webhook_verification.py` | `test_missing_query_params_is_rejected_with_403` | missing `hub.*` → 500 | 403 (same route's own rejection code for wrong `hub.mode`/`hub.verify_token`) — **fails today** | whatsapp_adapter robustness #1 |
| `tests/api/whatsapp_adapter/test_webhook_signature.py` | `test_missing_signature_header_is_rejected_with_403` | missing HMAC header → 500 | 403 (same route's own rejection code for a wrong/garbage signature) — **fails today** | robustness #2 |
| `tests/api/whatsapp_adapter/test_flows.py` | `test_plausible_shaped_garbage_ciphertext_fails_with_421`, `test_non_base64_ciphertext_fails_with_421`, `test_empty_string_fields_fail_with_421` | garbage / non-base64 / empty ciphertext → 500 | 421 (Meta's own Flow Data Exchange spec convention for a decrypt failure) — **fails today** | robustness #3 |

Two more in the same class, also rewritten to qualitative non-2xx checks
(no established sibling/external convention to name a specific code for
these, so a specific replacement code was not invented):

| File | Test (new name) | Old assertion | New assertion |
|---|---|---|---|
| `tests/api/text_agent/test_respond_failure.py` | `test_llm_failure_does_not_return_success` | `== 500` | `not (200 <= status < 300)` |
| `tests/api/document_worker/test_render_failure.py` | `test_render_storage_upload_failure_does_not_return_success` | `== 500` | `not (200 <= status < 300)` |

Same treatment for the two "malformed supported payload fails loudly" tests
(README documents "fail loudly" but not a status/exception type):
`tests/api/whatsapp_adapter/test_webhook_validation.py::
test_malformed_supported_payload_fails_loudly` and `tests/e2e/
test_blocking_and_failures.py::test_malformed_supported_payload_fails_loudly`
now assert non-2xx instead of exact `500`; the e2e version also dropped its
`pytest.raises(KeyError, ...)` exact-exception-type assertion per the same
rule, keeping only the side-effect checks (no claim, no dispatch).

### Video hole — CLOSED

FINDINGS text_agent: README allows `UriMediaContent` for images, **audio**,
**video**, or documents. The wire type is `Literal["image", "document"]`.
The audio test (rewritten above, no longer WRONG) covers the audio half.
Video previously had **no test at all**, so that half of the README
sentence could stay false forever without a red CI. Fixed:
`tests/api/text_agent/test_respond_failure.py::test_video_message_part_is_accepted`
asserts the video part is accepted (200) and reaches the model — fails
against current code today, the same way the audio test does.

### Hubble unknown-status catch-all is green on purpose

FINDINGS integration notes the settlement matrix **passed** for unknown
status `FROBNITZ` → stays pending. That is
`test_settlement_unknown_status_stays_pending_and_does_not_crash` in the
MIRRORED table — confirmed live, not just labeled.

### Coverage hole next to a mirrored success test

EXECUTION_AUDIT Check 2: `gifting._apply_order` line 52
(`voucher = order.vouchers[0]`) is covered by **exactly one** test,
`test_redeem_gift_card_success_shape` (MIRRORED, happy path, non-empty
vouchers). Statement coverage is green; the empty-`vouchers` `IndexError`
(FINDINGS integration #2) is never forced. A coverage number here is not
protection.

### Mirrored rows that already fail

“Copied from code, so it will not fail” is **false** for these. The
assertion audit tagged them MIRRORED (or MIRRORED-dominant) because the
README does not name the rule — but FINDINGS shows they were committed from
a **task brief**, not from the live implementation, and they are red:

| File | Test | Brief / test says | Code does | FINDINGS |
|---|---|---|---|---|
| `tests/api/user_service/test_directory.py:43` | `test_list_users_limit_zero_returns_zero_items` | `limit=0` → empty page, true `totalCount` | `Query(ge=1)` → **422** | user_service API #3; UNCERTAINTY admits this was a brief directive |
| `tests/api/user_service/test_threads.py:45` | `test_append_transcript_404_for_unknown_user` | 404 | writes rows for a missing user, **200** | user_service API #11 |
| `tests/api/user_service/test_access.py:20` | `test_public_access_phone_allowed_for_onboarded_phone` | `user` populated | public route omits `user` | user_service API #1 |

Same pattern, tagged UNDEFINED in the assertion audit (so they were not in
the original copy), still worth tracking as “status guessed from the brief”:

| File | Test | Guess | Code | FINDINGS |
|---|---|---|---|---|
| `tests/api/user_service/test_gifting.py:129` | `test_redeem_gift_card_amount_not_in_live_storefront_is_rejected` | 422 | **400** | API #4; integration #3 (no Hubble call — that part holds) |
| `tests/api/user_service/test_ambassadors.py:48` | `test_enroll_ambassador_refuses_when_institution_id_is_null` | refusal-class status | **200** `school_not_recognised` | API #2 |

### UNCERTAINTY guesses that stayed green (not already in the operator table)

These were written from a comment, a task line, or a constant — then they
passed, so they now freeze that guess.

| File | Test | Guess that matched code | Status |
|---|---|---|---|
| `tests/unit/user_service/test_gifting.py:72` | `test_earned_inr_negative_points_cross_no_rung` | negative points → ₹0 (API types are `ge=0`; the pure function is unguarded) | **Reviewed, kept.** Annotated in place: every rung threshold is non-negative, so this is the only value consistent with `earned_inr`'s own definition, not a separate policy choice. |
| `tests/unit/user_service/test_gifting.py:267` | `test_offered_amounts_flexible_balance_above_max_is_capped_at_max` | cap **filters** the ladder to `<= max`; does **not** add `max` as an extra denomination. UNCERTAINTY: if product intent was “always offer max,” this test is the wrong commitment. | Not changed — a genuine product-decision fork with no way to prefer one reading without inventing policy. |
| `tests/unit/user_service/test_directory.py:283` | `test_sort_key_last_active_puts_none_after_every_real_timestamp` | last-active order is `[recent, older, never]` | **Reviewed, kept.** Annotated in place: most-recent-first is the only coherent "last active" ordering for an admin roster. |
| `tests/unit/user_service/test_directory.py:267` | `test_sort_key_identical_names_are_a_stable_tie` | tie-break is equal keys / Python-stable sort, not a hidden `userId` | Not changed — docstring already states this is the documented tiebreak rule. |
| `tests/unit/user_service/test_directory.py:182` | `test_matches_attribution_filter_in_isolation` | `organic` = `referrerHandle is None` (README never maps that word) | **Reviewed, kept.** Annotated in place: `referrerHandle is None` is the only coherent reading, and the two enum values are themselves part of the real wire schema. |
| `tests/unit/user_service/test_directory.py:101,:246` | empty / whitespace `q` matches everyone | depends on call-site `query.q.strip().casefold()`, not a README rule | Not changed — no better oracle without inventing a search-syntax spec. |
| `tests/e2e/test_ambassador_and_gifting.py:51` | `test_ambassador_enrollment_counts_a_referred_student` | `points == len(referrals)` and tier-1 = 5 / ₹100 / “Campus Ambassador” — UNCERTAINTY Journey 16: wiring constants, not a spec formula | **Fixed.** Now reads `K.TIER_ONE_POINTS` / `K.TIER_ONE_NAME` (bound to `AMBASSADOR_TIERS[0]`) instead of the literals 5/100/"Campus Ambassador". The `points == len(referrals)` formula itself is unchanged (still a wiring-constant reading, not independently derivable from the README). |
| `tests/api/user_service/test_users.py:149` | `test_delete_unknown_user_returns_204_delete_has_no_documented_404` | no lookup → 204 (UNCERTAINTY guessed this rather than mandatory 404) | **Fixed.** Renamed to `test_delete_unknown_user_does_not_crash`; now asserts `status_code < 500` instead of the exact `204`. Same fix applied to the analogous `tests/api/user_service/test_blocklist.py::test_unblock_unknown_phone_...` and `tests/integration/test_cascade.py::test_delete_unknown_user_...`. |

~~`tests/api/text_agent/test_respond_failure.py:33` (`test_llm_exception_is_500`) and
`tests/api/document_worker/test_render_failure.py` (storage failure → 500)~~ —
**rewritten**, see the "Crash / 500 frozen as the contract" section above.

### Prefill / Location — reviewed, already correctly implemented (not a mirror)

`redirect_service` had no in-scope README for the assertion audit (all 8
tests were UNDEFINED). On review in this pass, `test_redirect.py` does
**not** hand-copy the prefill string: it does
`from infra.clients.users import ATTRIBUTION_PREFILL_TEMPLATE` and builds
the expected `Location` header from that live import plus stdlib
`urllib.parse.quote` — the same pattern used to fix the money-ladder tests
elsewhere in this document (import the named constant, don't re-transcribe
it). A change to the real template is automatically visible here. No
change was needed.

| File | Test | Bound to |
|---|---|---|
| `tests/api/redirect_service/test_redirect.py:40` | `test_go_redirects_302_to_exact_whatsapp_location` | `ATTRIBUTION_PREFILL_TEMPLATE` (imported) + `WHATSAPP_BASE_URL` |
| same :50 | `test_go_unregistered_handle_still_redirects` | same Location helper |
| same :67, :81 | space / `@` passed through into that same template | same |

302-to-WhatsApp is README-backed. The exact prefill sentence is not, but the
test tracks the real constant regardless, so this is not the same failure
mode as a hand-copied literal.

### Harness that keeps tests green even if the real path is broken

UNCERTAINTY’s fakes mean these tests cannot go red when the skipped
production path changes.

| File | Test | What the harness hides | Status |
|---|---|---|---|
| `tests/e2e/test_conversation.py:34` | `test_known_phone_generates_and_delivers_in_model_order` | `FakeGraphClient` always returns one textbook page. The “Sources” footer checks **wiring**, not retrieval. Real tool-driven reads are never run. | **Fixed.** `citations_responder` (tests/e2e/scripting.py) now returns rows only when the query actually names a non-empty `ids` list; since this journey scripts no tool call, `read_ids` is genuinely empty, so the test no longer asserts a fabricated Sources footer (rewritten to expect no footer). Real tool-driven-read coverage is still absent — that gap is now honest instead of hidden behind a lax fake. |
| `tests/e2e/*` (delivery barrier) | every journey that waits for Meta “sent” | `FakeWhatsAppClient` auto-confirms each `wamid` on the next tick. Dropped status-webhook / ~10s timeout path is never exercised. | Not changed — no journey requires this path; documented in UNCERTAINTY as intentionally out of scope. |
| `tests/e2e/test_onboarding.py` (journeys 2, 9, 16) | Flow completion | Completes via webhook `nfm_reply`, not RSA `/flows/onboarding` or `/flows/grade`. Dummy PEM is never used to decrypt. Encrypted Flow code can break without a red e2e. | Not changed — no journey docstring mislabels this as RSA-decrypt coverage; already honestly scoped in UNCERTAINTY. |
| `tests/api/whatsapp_adapter/test_webhook_success.py:39` | `test_well_formed_inbound_message_is_claimed_then_enqueued_then_200` | `FakeCoordinator` is a call-recorder. Unknown / known / blocked phone Test Matrix rows are **not** distinguishable at this layer. | Not changed — the test's own docstring already says so; no claim of matrix coverage was made. |
| `tests/e2e/test_onboarding.py::test_onboarding_flow_completion_attributes_first_mention` (journey 2) | first-mention attribution | `_register_handle` used to write **straight into** `referrers/{handle}`, skipping influencer-register 409. Registration bugs (FINDINGS API #5–6) could not fail this journey. | **Fixed.** `_register_handle` now calls the real `POST /internal/influencers` route instead of writing the Firestore doc directly, so a registration regression can fail this journey. |
| `tests/e2e` fakes | GCS, document-worker client, Gemini embeddings | UNCERTAINTY: none of the 17 journeys reach them. Stubs can be wrong forever. | Not changed — out of scope for the 17 journeys, per UNCERTAINTY. |
| `tests/api/text_agent/test_respond_success.py:39` | `test_plain_text_reply_returns_documented_shape` | No tool-call turn is scripted. `update_profile` / ambassador / graph / image paths are untested. (The extra `trace` field still makes this test **red** — FINDINGS — but a tool-loop regression would not.) | Not changed — already correctly scoped in its own docstring. |

### Weak oracles (substring / name-only / one unknown status)

A small code change can keep these green because they never pinned the
full rule.

| File | Test | Why it will not catch the real change |
|---|---|---|
| `tests/integration/test_hubble_settlement.py:131` | `test_settlement_success_with_voucher_stores_voucher_fields` | Instructions: both seeded steps must appear as **substrings**. Join format / order / separators can change freely. |
| `tests/unit/user_service/test_directory.py` (search tests) | name + unicode casefold + AND tokens | UNCERTAINTY: phone / userId / institution were not pinned. Dropping phone from the haystack would not fail this file. |
| `tests/integration/test_hubble_settlement.py:186` | unknown status `FROBNITZ` → pending | Mutation UNCERTAINTY: `"FAILURE"`, `"CANCELED"`, lowercase `"failed"` are untested. The catch-all freeze does not protect Hubble synonyms. |
| `tests/e2e/test_conversation.py` | user rows before assistant rows via `sequence` | UNCERTAINTY Journey 3(a): “user written before generation” is not observable; sequence order is a **proxy**. |

All four rows above were reviewed in this pass and kept as-is intentionally,
not by default: each is already the strongest assertion available without
inventing an undocumented join format, search surface, status synonym list,
or internal-ordering guarantee. Tightening any of them would mean asserting
something the README does not actually promise.

---

## Why this list matters

A green suite here does **not** mean the product still matches the README.

Typical failure mode:

1. Someone changes `constants.py`, a status string, or a status code.
2. The mirrored test is edited to the new value in the same PR.
3. CI stays green.
4. Nobody notices the README (or the intended product rule) was never updated.

The WRONG rows are worse: they already disagree with the README, and they
will keep that disagreement looking like intended behavior until the test
is rewritten from spec.

The extra sections are the same failure mode from a different angle: guessed
boundaries, 500-as-contract, tests that pass because no overlap logic
exists, constants copied from code, and fakes that never reach the real
path (encrypted Flows, Meta delivery timeout, graph retrieval, tool
calls). Those will not go red when the product rule is the thing that
changed.

---

## Remediation changelog (this pass)

Everything in the tables above marked "Rewritten" / "Fixed" / "RESOLVED" was
changed in this pass. Full inventory, grouped by kind:

**WRONG (6/6 resolved)** — see the WRONG table. All rewritten from spec; all
now fail against current code except the kept `"reaction"` half of the two
split tests.

**Money/gifting/ambassador ladders bound to named constants (not
re-transcribed):**
- `tests/unit/user_service/factories.py` — imports `AMBASSADOR_TIERS`,
  `REWARD_AMOUNTS`, `ACTIVE_USER_WINDOW_MS`, `RETENTION_WINDOW_MS`,
  `HANDLE_SUFFIX_ALPHABET`, `HANDLE_SUFFIX_LENGTH` from
  `user_service.app.src.constants`.
- `tests/unit/user_service/test_gifting.py`, `test_ambassadors.py` — every
  hardcoded tier/₹ literal replaced with the imported values; two property
  tests that reimplemented `offered_amounts` as their own oracle rewritten
  to independent invariants (sorted/unique/bounded/no invented values).
- `tests/unit/user_service/test_influencers.py` —
  `test_spend_never_below_base_and_never_above_base_plus_cap` no longer
  re-derives `_campaign_spend`'s formula inline; asserts only the two
  documented bounds.
- `tests/api/user_service/test_gifting.py` — same treatment.
- `tests/e2e/constants.py`, `tests/e2e/test_ambassador_and_gifting.py` —
  reward-catalogue block bound to `AMBASSADOR_TIERS`/`REWARD_PRODUCTS`; the
  e2e redeem journey's fixed-denomination catalogue is now parameterized by
  `K.TIER_ONE_REWARD_INR` instead of a coincidentally-matching `100` literal.
- `tests/integration/constants.py` — same reward-catalogue and
  `SESSION_GAP_MS`/`RETENTION_WINDOW_MS` binding.

**"500 because no try/except" no longer asserted as contract (6 tests
rewritten to a named convention, 2 to qualitative non-2xx, 2 "fail loudly"
tests loosened from exact 500/KeyError to non-2xx):** see the "Crash / 500
frozen as the contract" section above.

**Canned user-facing copy bound to `infra.canned.CANNED_RESPONSES` (not
re-transcribed):**
- `tests/e2e/constants.py` — `CANNED_ERROR`, `PERSONA_QUESTION`,
  `PHONE_REQUEST`, `PHONE_ACK`, `INTRO_TEMPLATE`, `STUDENT_LAUNCH_TEMPLATE`,
  `TEACHER_LAUNCH_TEMPLATE`, `ONBOARDING_FLOW_CTA`, `DOCUMENT_FLOW_CTA`,
  `PERSONA_STUDENT_BUTTON_TITLE`, `PERSONA_TEACHER_BUTTON_TITLE` now import
  from `infra.canned.CANNED_RESPONSES` / `infra.constants.PRODUCT_NAME`;
  `PERSONA_STUDENT_BUTTON_ID`, `PERSONA_TEACHER_BUTTON_ID`,
  `INSTITUTION_SCREEN`, `DOCUMENT_FORM_SCREEN`, `ONBOARDING_FLOW_TOKEN`,
  `SOURCES_LABEL` now import from `whatsapp_adapter.app.src.{constants,
  flows.constants}`; Firestore collection names now import from
  `infra.firestore.collections`.
- `tests/e2e/test_onboarding.py` — two remaining inline literal-copy
  assertions rewritten to build the expected string from `K.INTRO_TEMPLATE`
  / `K.PERSONA_QUESTION` / `K.PHONE_REQUEST` / `K.PHONE_ACK` instead of a
  hand-typed duplicate.

**Video gap closed:** `tests/api/text_agent/test_respond_failure.py` gained
`test_video_message_part_is_accepted` (previously: no test at all covered
the video half of the audio/video/image/document README sentence). Fails
today, same as the audio test beside it.

**Explicit "delete-unknown → 204" / idempotent-delete guesses no longer
frozen** (named in tests/outcomes/UNCERTAINTY.md as guesses not to keep just
because green): `tests/api/user_service/test_users.py::
test_delete_unknown_user_does_not_crash`,
`tests/api/user_service/test_blocklist.py::
test_unblock_unknown_phone_does_not_crash`,
`tests/integration/test_cascade.py::test_delete_unknown_user_does_not_crash`
— all now assert only `status_code < 500` instead of the exact `204`.

**Session-gap boundary, referrer registration, and citations fake** — see
tests/outcomes/UNCERTAINTY.md for the full writeup; summarized above under
"guessed the operator" and "Harness that keeps tests green."

**Environment-gap tests marked `xfail` instead of failing plainly** (per the
xfail carve-out for documented environment gaps):
`tests/api/document_worker/test_render_success.py::
test_render_docx_success_shape` and `::test_render_pptx_success_shape`, both
citing the missing-`soffice` gap (`strict=False`, so they auto-flip to
passing once a real `soffice` binary is available, e.g. in the real
deployed image / a CI runner that has it).

**Reviewed and intentionally left unchanged** (already the best available
oracle, or already correctly scoped in their own docstrings): the four "weak
oracle" rows above; `test_earned_inr_negative_points_cross_no_rung`,
`test_matches_attribution_filter_in_isolation`,
`test_sort_key_last_active_puts_none_after_every_real_timestamp` (annotated
in place with why no better reading exists); the ACTIVE_USER_WINDOW_MS
closed-interval reading (distinct wording from the session-gap sentence, no
contradicting sibling test); the redirect_service prefill test (already
imports `ATTRIBUTION_PREFILL_TEMPLATE`, not a copy); ops-route
(`/health`/`/version`) shape tests; plain Pydantic-validation 422 tests
(structural consequences of the schema, not business-rule guesses);
resource-lookup 404 tests consistent with the shared `load_user_or_404`
convention.

Every test file under `tests/` still parses (92 files, 0 syntax errors) and
`tests/unit` + `tests/api` were run after every batch of changes; every
failure introduced in this pass is an intentional correct-oracle for a
documented spec-vs-code gap, cross-checked against the pre-existing FINDINGS
baseline (5 unit / 16 api failures before this pass) to confirm zero
unintended regressions.
