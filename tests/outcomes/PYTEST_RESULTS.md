# Pytest results

Recorded 2026-09-07 with `pytest --junitxml` from the Sujho workspace root. Integration and e2e used `JAVA_HOME=/opt/homebrew/opt/openjdk`. Raw XML and JSON live in [`pytest/`](pytest/). `skipped` includes pytest xfail. Failures are catalogued in [FINDINGS.md](FINDINGS.md); this table is the full collected set.

## Summary

| suite | collected | passed | failed | error | skipped | not-run |
|---|---:|---:|---:|---:|---:|---:|
| `unit` | 162 | 157 | 5 | 0 | 0 | 0 |
| `api` | 240 | 208 | 30 | 0 | 2 | 0 |
| `integration` | 47 | 37 | 10 | 0 | 0 | 0 |
| `e2e` | 21 | 17 | 4 | 0 | 0 | 0 |
| **all** | **470** | **419** | **49** | **0** | **2** | **0** |

## Every test

| suite | result | nodeid | message |
|---|---|---|---|
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_tier_reached_below_first_rung_is_none` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_next_tier_below_first_rung_is_campus_ambassador` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_tier_reached_exactly_at_each_rung` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_next_tier_at_top_rung_is_none` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_next_tier_between_rungs` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_negative_points_have_not_reached_a_tier` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_tier_reached_and_next_tier_are_always_consistent` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_mint_handle_name_with_no_latin_letters_raises` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_mint_handle_punctuation_only_name_raises` |  |
| `unit` | failed | `tests/unit/user_service/test_ambassadors.py::test_mint_handle_empty_name_raises` | IndexError: list index out of range |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_mint_handle_strips_leading_and_trailing_whitespace` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_mint_handle_single_character_first_name` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_mint_handle_matches_documented_arjun_form` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_mint_handle_retries_until_the_registry_reports_a_free_handle` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_minted_handle_always_has_a_four_char_alphabet_suffix` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_enrolled_raises_when_a_registry_entry_has_no_profile` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_row_tier_at_first_rung_is_the_first_named_tier` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_roster_started_is_points_plus_abandoned_starts` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_roster_with_no_starts_and_no_onboards_is_zero` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_status_splits_student_and_teacher_referrals_and_computes_points_to_next` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_status_below_first_rung_has_no_tier_and_points_to_ambassador` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_status_settles_a_pending_mint_before_reporting_balance` |  |
| `unit` | passed | `tests/unit/user_service/test_ambassadors.py::test_detail_started_is_referred_plus_pending_starts` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_first_registered_mention_wins_even_when_an_unregistered_mention_appears_earlier` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_first_of_two_registered_mentions_wins` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_no_mentions_returns_none` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_mentions_none_of_which_are_registered_returns_none` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_empty_string_returns_none` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_empty_registry_returns_none_even_with_mentions` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_uppercase_mention_matches_normalized_lowercase_handle` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_leading_at_in_the_registry_is_not_required` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_a_lone_registered_mention_is_found_regardless_of_surrounding_prose` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_resolve_referrer_first_text_with_a_registered_mention_wins` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_resolve_referrer_skips_earlier_texts_that_only_mention_unregistered_handles` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_resolve_referrer_no_registered_mention_in_any_text` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_resolve_referrer_empty_texts` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_resolve_referrer_uppercase_mention_across_texts` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_derive_starts_records_the_first_registered_mention_timestamp` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_derive_starts_two_in_flight_users_both_count` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_derive_starts_unregistered_mention_is_omitted` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_derive_starts_no_mention_is_omitted` |  |
| `unit` | passed | `tests/unit/user_service/test_attribution.py::test_derive_starts_empty_buffer_is_empty` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_activity_state_none_last_message_is_never` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_activity_state_exactly_on_the_window_boundary_is_active` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_activity_state_one_ms_inside_the_window_is_active` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_activity_state_one_ms_outside_the_window_is_dormant` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_activity_state_message_at_now_is_active` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_any_age_inside_the_closed_window_is_active` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_any_age_past_the_window_is_dormant` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_empty_query_matches_everything` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_multi_token_requires_every_token` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_unicode_name_under_casefold` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_unknown_token_rejects` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_grade_filter_in_isolation` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_subject_filter_in_isolation` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_activity_filter_in_isolation` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_attribution_filter_in_isolation` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_blocked_filter_in_isolation` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_matches_all_filters_combined` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_blank_queries_match_any_name` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_sort_key_name_orders_alphabetically_by_casefold` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_sort_key_identical_names_are_a_stable_tie` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_sort_key_last_active_puts_none_after_every_real_timestamp` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_none_last_message_sorts_after_any_real_timestamp_on_last_active` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_sort_key_newest_puts_later_created_first` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_sort_key_session_count_puts_higher_count_first` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_directory_entry_uses_whatsapp_activity_and_clock_for_state` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_directory_entry_outside_the_window_is_dormant` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_directory_entry_never_messaged_is_never` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_directory_page_blocked_filter_returns_only_blocked_identities` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_directory_page_open_filter_excludes_blocked_identities` |  |
| `unit` | passed | `tests/unit/user_service/test_directory.py::test_directory_page_newest_sort_and_activity_use_the_clock` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_earned_inr_below_first_tier_is_zero` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_earned_inr_exactly_at_each_tier` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_earned_inr_one_below_each_tier` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_earned_inr_one_above_each_tier` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_earned_inr_far_above_top_tier_does_not_invent_a_fifth_rung` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_earned_inr_negative_points_cross_no_rung` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_earned_inr_equals_sum_of_every_crossed_rung` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_spent_inr_empty_list_is_zero` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_spent_inr_only_failed_cards_restore_credit` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_spent_inr_only_pending_cards_debit` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_spent_inr_only_succeeded_cards_debit` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_spent_inr_mix_excludes_failed` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_failed_card_never_contributes_to_spend` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_balance_inr_is_earned_minus_non_failed_spend` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_balance_inr_failed_card_does_not_reduce_balance` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_balance_inr_can_go_negative_when_spend_exceeds_earned` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_balance_equals_earned_minus_non_failed_spend_for_all_inputs` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_inactive_product_is_empty` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_none_amount_restrictions_is_empty` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_empty_how_to_use_instructions_is_empty` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_balance_below_min_is_empty` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_flexible_balance_exactly_min` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_flexible_balance_on_a_ladder_rung` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_flexible_includes_exact_balance_between_rungs` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_flexible_balance_above_max_is_capped_at_max` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_flexible_none_denominations_matches_empty_list` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_fixed_does_not_add_exact_balance` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_fixed_balance_exactly_min_only_if_min_is_a_denomination` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_fixed_balance_above_max_is_capped_at_max` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_fixed_is_sorted_and_deduplicated` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_fixed_filters_denominations_outside_min_max` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_flexible_amounts_are_the_ladder_plus_exact_balance_inside_bounds` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_fixed_amounts_stay_within_bounds_sorted_unique` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_offered_amounts_negative_balance_is_empty` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_apply_order_none_means_404_and_fails_the_card` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_apply_order_hubble_failed_fails_the_card` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_apply_order_hubble_cancelled_fails_the_card` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_apply_order_hubble_reversed_fails_the_card` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_apply_order_success_attaches_voucher_fields` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_apply_order_processing_stays_pending` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_apply_order_unknown_status_stays_pending` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_settle_404_fails_a_pending_card` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_settle_terminal_failed_statuses_fail_the_pending_card` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_settle_success_with_voucher_succeeds` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_settle_processing_and_unknown_leave_pending_and_do_not_call_fail` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_settle_already_succeeded_is_passed_through_without_hubble` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_settle_already_failed_is_passed_through_without_hubble` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_settled_gift_cards_lists_this_user_and_settles_each_pending` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_redeem_places_order_for_the_product_reference_and_amount` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_redeem_unoffered_amount_raises_and_does_not_place_an_order` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_redeem_settles_this_users_cards_before_the_balance_check` |  |
| `unit` | passed | `tests/unit/user_service/test_gifting.py::test_redeem_404_on_an_existing_pending_card_restores_credit` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_for_start_ms_is_inclusive` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_for_end_ms_is_inclusive` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_for_one_ms_before_start_is_none` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_for_one_ms_after_end_is_none` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_for_gap_between_two_campaigns_is_none` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_for_empty_campaign_list_is_none` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_window_contains_exactly_its_closed_interval` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_spend_zero_onboards_is_the_base_fee` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_spend_partial_block_earns_nothing_beyond_base` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_spend_exactly_one_block` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_spend_incentive_is_capped` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_spend_block_size_of_one` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_campaign_spend_block_size_one_still_respects_the_cap` |  |
| `unit` | failed | `tests/unit/user_service/test_influencers.py::test_campaign_spend_negative_onboards_does_not_pay_below_base` | assert 950 == 1000  +  where 950 = _campaign_spend(Payout(baseInr=1000, perBlockInr=50, blockSize=5, incentiveCapInr=200), -1)  +    where Payout(baseInr=1000, perBlockInr=50, blockSize=5, incentiveCapInr=200) = _terms(base=1000, per_block=50, block_size=5, cap=200) |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_spend_never_below_base_and_never_above_base_plus_cap` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_clicks_with_no_matching_campaign_land_in_miscellaneous` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_referred_user_in_no_window_counts_as_started_and_onboarded_in_misc` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_referred_user_inside_a_window_buckets_there_not_misc` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_pending_start_in_a_gap_increments_misc_started_only` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_empty_campaigns_put_every_click_and_referral_in_misc` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_per_campaign_clicks_plus_misc_clicks_equal_total_clicks` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_retained_requires_last_message_at_least_seven_days_after_join` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_two_pending_starts_inside_one_window_both_count` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_two_onboards_inside_one_window_both_count` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_two_retained_users_inside_one_window_both_count` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_pending_start_inside_a_window_increments_that_campaign_not_misc` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_referral_inside_a_window_is_tagged_with_that_campaign_id` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_referral_in_a_gap_has_no_campaign_id` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_derive_influencer_report_fetches_clicks_and_windows_for_this_handle` |  |
| `unit` | passed | `tests/unit/user_service/test_influencers.py::test_derive_influencer_report_unknown_handle_has_zero_clicks_and_no_windows` |  |
| `unit` | passed | `tests/unit/user_service/test_user_id.py::test_same_phone_yields_the_same_user_id_across_calls` |  |
| `unit` | failed | `tests/unit/user_service/test_user_id.py::test_plus_91_is_the_same_identity_as_digits` | AssertionError: assert 'c82b144f6b3c...78f4a05a3e20a' == 'f81d06712d04...274a54fa7f4fd'      - f81d06712d04dc6d5d2274a54fa7f4fd   + c82b144f6b3c0bd18d378f4a05a3e20a |
| `unit` | failed | `tests/unit/user_service/test_user_id.py::test_spaces_in_the_phone_are_the_same_identity` | AssertionError: assert '92de31ab17ac...0a26b9078ca7d' == 'f81d06712d04...274a54fa7f4fd'      - f81d06712d04dc6d5d2274a54fa7f4fd   + 92de31ab17accc2a4270a26b9078ca7d |
| `unit` | failed | `tests/unit/user_service/test_user_id.py::test_leading_zero_is_the_same_identity` | AssertionError: assert '0559c2c54dfc...17a36470ca247' == 'f81d06712d04...274a54fa7f4fd'      - f81d06712d04dc6d5d2274a54fa7f4fd   + 0559c2c54dfcb979c6717a36470ca247 |
| `unit` | passed | `tests/unit/user_service/test_user_id.py::test_two_different_phones_never_share_an_id` |  |
| `unit` | passed | `tests/unit/user_service/test_user_id.py::test_different_hmac_secrets_do_not_alias_the_same_phone` |  |
| `unit` | passed | `tests/unit/user_service/test_user_id.py::test_derivation_is_deterministic_for_any_indian_mobile` |  |
| `unit` | passed | `tests/unit/user_service/test_user_id.py::test_distinct_canonical_phones_do_not_collide` |  |
| `api` | passed | `tests/api/document_worker/test_health_version.py::test_health_ok` |  |
| `api` | passed | `tests/api/document_worker/test_health_version.py::test_version_shape` |  |
| `api` | passed | `tests/api/document_worker/test_render_auth.py::test_render_without_authorization_header_is_401` |  |
| `api` | passed | `tests/api/document_worker/test_render_auth.py::test_render_with_wrong_bearer_token_is_401` |  |
| `api` | passed | `tests/api/document_worker/test_render_auth.py::test_render_with_malformed_authorization_header_is_401` |  |
| `api` | passed | `tests/api/document_worker/test_render_failure.py::test_render_storage_upload_failure_does_not_return_success` |  |
| `api` | passed | `tests/api/document_worker/test_render_failure.py::test_render_nonsensical_but_schema_valid_format_still_reaches_storage_prefix` |  |
| `api` | skipped | `tests/api/document_worker/test_render_success.py::test_render_docx_success_shape` | Environment gap, not a spec-vs-code mismatch: no `soffice` (LibreOffice) binary on PATH in this sandbox, so infra/documents/previews.py fails for every real render regardless of markdown/format validity -- see tests/outcomes/UNCERTAINTY.md document_worker 'Environment limitation' and tests/outcomes/FINDINGS.md document_worker. |
| `api` | skipped | `tests/api/document_worker/test_render_success.py::test_render_pptx_success_shape` | Environment gap, not a spec-vs-code mismatch: no `soffice` (LibreOffice) binary on PATH in this sandbox, so infra/documents/previews.py fails for every real render regardless of markdown/format validity -- see tests/outcomes/UNCERTAINTY.md document_worker 'Environment limitation' and tests/outcomes/FINDINGS.md document_worker. |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_missing_markdown_is_422` |  |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_missing_document_is_422` |  |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_format_outside_documented_enum_is_422` |  |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_missing_scope_is_422` |  |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_missing_scope_user_id_is_422` |  |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_missing_title_is_422` |  |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_missing_filename_is_422` |  |
| `api` | passed | `tests/api/document_worker/test_render_validation.py::test_render_filename_not_matching_slug_pattern_is_422` |  |
| `api` | passed | `tests/api/redirect_service/test_click_best_effort.py::test_click_logging_failure_does_not_break_redirect` |  |
| `api` | passed | `tests/api/redirect_service/test_click_best_effort.py::test_click_logging_failure_302_already_sent_at_asgi_level` |  |
| `api` | passed | `tests/api/redirect_service/test_click_best_effort.py::test_click_logging_success_records_exactly_one_call` |  |
| `api` | passed | `tests/api/redirect_service/test_health_version.py::test_health_returns_exact_documented_shape` |  |
| `api` | passed | `tests/api/redirect_service/test_health_version.py::test_version_returns_exact_documented_shape` |  |
| `api` | passed | `tests/api/redirect_service/test_health_version.py::test_version_fields_are_null_when_env_unset` |  |
| `api` | passed | `tests/api/redirect_service/test_redirect.py::test_go_redirects_302_to_exact_whatsapp_location` |  |
| `api` | passed | `tests/api/redirect_service/test_redirect.py::test_go_unregistered_handle_still_redirects` |  |
| `api` | passed | `tests/api/redirect_service/test_redirect.py::test_go_handle_with_space_is_passed_through_raw` |  |
| `api` | passed | `tests/api/redirect_service/test_redirect.py::test_go_handle_with_at_sign_is_passed_through_raw` |  |
| `api` | passed | `tests/api/redirect_service/test_redirect.py::test_go_empty_handle_segment_is_404_via_routing_not_handler` |  |
| `api` | passed | `tests/api/text_agent/test_ops_routes.py::test_health_is_public_and_returns_documented_shape` |  |
| `api` | passed | `tests/api/text_agent/test_ops_routes.py::test_version_is_public_and_returns_documented_shape` |  |
| `api` | passed | `tests/api/text_agent/test_respond_auth.py::test_respond_without_authorization_header_is_401` |  |
| `api` | passed | `tests/api/text_agent/test_respond_auth.py::test_respond_with_wrong_bearer_token_is_401` |  |
| `api` | passed | `tests/api/text_agent/test_respond_failure.py::test_llm_failure_does_not_return_success` |  |
| `api` | failed | `tests/api/text_agent/test_respond_failure.py::test_audio_message_part_is_transcribed_before_the_model_call` | AssertionError: README promises audio parts are transcribed to text before the model call, not rejected -- a 422 here means the request never reached transcription or the model at all assert 422 == 200  +  where 422 = <Response [422 Unprocessable Entity]>.status_code |
| `api` | failed | `tests/api/text_agent/test_respond_failure.py::test_video_message_part_is_accepted` | AssertionError: README lists video as an accepted UriMediaContent type -- a 422 here means the wire schema still excludes it assert 422 == 200  +  where 422 = <Response [422 Unprocessable Entity]>.status_code |
| `api` | failed | `tests/api/text_agent/test_respond_success.py::test_plain_text_reply_returns_documented_shape` | AssertionError: assert {'reaction': ...ace': [], ...} == {'reaction': ...esp_fake_001'}      Omitting 4 identical items, use -vv to show   Left contains 1 more item:   {'trace': []}   Use -v to get more diff |
| `api` | passed | `tests/api/text_agent/test_respond_validation.py::test_missing_user_field_is_422` |  |
| `api` | passed | `tests/api/text_agent/test_respond_validation.py::test_persona_outside_discriminator_is_422` |  |
| `api` | passed | `tests/api/text_agent/test_respond_validation.py::test_student_missing_scope_grade_is_422` |  |
| `api` | passed | `tests/api/text_agent/test_respond_validation.py::test_teacher_missing_scope_grades_is_422` |  |
| `api` | failed | `tests/api/text_agent/test_respond_validation.py::test_missing_previous_response_id_is_accepted` | AssertionError: README's own request example omits previousResponseId and presents it as valid -- a 422 here means the field is undocumentedly required assert 422 == 200  +  where 422 = <Response [422 Unprocessable Entity]>.status_code |
| `api` | passed | `tests/api/user_service/test_access.py::test_public_access_phone_needs_onboarding_for_unknown_phone` |  |
| `api` | failed | `tests/api/user_service/test_access.py::test_public_access_phone_allowed_for_onboarded_phone` | AssertionError: expected body['user'] populated for an allowed phone, got None assert None is not None |
| `api` | passed | `tests/api/user_service/test_access.py::test_public_access_phone_blocked_takes_precedence` |  |
| `api` | passed | `tests/api/user_service/test_access.py::test_public_access_phone_422_on_missing_field` |  |
| `api` | passed | `tests/api/user_service/test_access.py::test_internal_access_phone_matches_public_result` |  |
| `api` | passed | `tests/api/user_service/test_access.py::test_internal_access_phone_422_on_wrong_type` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_enroll_ambassador_first_call_mints_handle_and_returns_status` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_enroll_ambassador_is_idempotent_same_handle_on_second_call` |  |
| `api` | failed | `tests/api/user_service/test_ambassadors.py::test_enroll_ambassador_refuses_when_institution_id_is_null` | AssertionError: expected 422 for a refused enroll (null institution.id); got 200: {"result":"school_not_recognised"} assert 200 == 422  +  where 200 = <Response [200 OK]>.status_code |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_enroll_ambassador_refusal_does_not_create_a_registry_row` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_enroll_ambassador_404_for_unknown_user` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_get_ambassador_status_null_when_not_enrolled` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_get_ambassador_status_after_enroll` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_list_ambassadors_row_shape` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_ambassador_detail_404_for_unenrolled_user` |  |
| `api` | passed | `tests/api/user_service/test_ambassadors.py::test_ambassador_detail_shape` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_route_enumeration_is_nonempty` |  |
| `api` | failed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /health]` | AssertionError: GET /health returned 200 with no Authorization header; expected 401 (require_internal_secret must short-circuit before validation/lookup) assert 200 == 401  +  where 200 = <Response [200 OK]>.status_code |
| `api` | failed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /version]` | AssertionError: GET /version returned 200 with no Authorization header; expected 401 (require_internal_secret must short-circuit before validation/lookup) assert 200 == 401  +  where 200 = <Response [200 OK]>.status_code |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/access/phone]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/users]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/profiles]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/users:batchGet]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[DELETE /internal/users/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/directory/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/users/x/profile]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/users/x/location]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users/x/enrollments]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/enrollments]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[DELETE /internal/enrollments]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/threads/x/sessions/corpus]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users/x/threads/x/sessions]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users/x/threads/x/sessions/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[PUT /internal/users/x/threads/x/sessions/x/extraction]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/users/x/threads/x/transcript]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/blocklist]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[DELETE /internal/blocklist]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/influencers]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/influencers]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/influencers/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[DELETE /internal/influencers/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/influencers/x/campaigns]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[DELETE /internal/influencers/x/campaigns/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/users/x/ambassador]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users/x/ambassador]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/ambassadors]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/ambassadors/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users/x/rewards]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/users/x/gift-cards]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/users/x/gift-cards/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[POST /internal/referrers/x/click]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_no_auth_header[GET /internal/institutions/x]` |  |
| `api` | failed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /health]` | AssertionError: GET /health returned 200 with a wrong bearer token; expected 401 assert 200 == 401  +  where 200 = <Response [200 OK]>.status_code |
| `api` | failed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /version]` | AssertionError: GET /version returned 200 with a wrong bearer token; expected 401 assert 200 == 401  +  where 200 = <Response [200 OK]>.status_code |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/access/phone]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/users]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/profiles]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/users:batchGet]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[DELETE /internal/users/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/directory/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/users/x/profile]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/users/x/location]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users/x/enrollments]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/enrollments]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[DELETE /internal/enrollments]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/threads/x/sessions/corpus]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users/x/threads/x/sessions]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users/x/threads/x/sessions/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[PUT /internal/users/x/threads/x/sessions/x/extraction]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/users/x/threads/x/transcript]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/blocklist]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[DELETE /internal/blocklist]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/influencers]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/influencers]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/influencers/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[DELETE /internal/influencers/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/influencers/x/campaigns]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[DELETE /internal/influencers/x/campaigns/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/users/x/ambassador]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users/x/ambassador]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/ambassadors]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/ambassadors/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users/x/rewards]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/users/x/gift-cards]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/users/x/gift-cards/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[POST /internal/referrers/x/click]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_every_guarded_route_401s_with_wrong_bearer_token[GET /internal/institutions/x]` |  |
| `api` | passed | `tests/api/user_service/test_auth_boundary.py::test_public_route_exemption_set_matches_readme` |  |
| `api` | passed | `tests/api/user_service/test_blocklist.py::test_block_phone_then_access_reports_blocked` |  |
| `api` | passed | `tests/api/user_service/test_blocklist.py::test_unblock_phone_removes_block` |  |
| `api` | passed | `tests/api/user_service/test_blocklist.py::test_block_phone_422_missing_field` |  |
| `api` | passed | `tests/api/user_service/test_blocklist.py::test_unblock_unknown_phone_does_not_crash` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_users_offset_beyond_total_returns_empty_but_true_total` |  |
| `api` | failed | `tests/api/user_service/test_directory.py::test_list_users_limit_zero_returns_zero_items` | AssertionError: expected 200 with an empty page for limit=0, got 422: {"detail":[{"type":"greater_than_equal","loc":["query","limit"],"msg":"Input should be greater than or equal to 1","input":"0","ctx":{"ge":1}}]} assert 422 == 200  +  where 422 = <Response [422 Unprocessable Entity]>.status_code |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_users_sort_by_name_is_case_insensitive_alphabetical` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_users_search_matching_nothing_returns_empty` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_users_search_multi_token_requires_all_tokens_to_match` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_users_combined_grade_and_subject_filters` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_users_401_and_shape_smoke` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_users_422_missing_required_persona` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_profiles_returns_every_stored_profile_of_one_persona` |  |
| `api` | passed | `tests/api/user_service/test_directory.py::test_list_profiles_422_missing_required_persona` |  |
| `api` | passed | `tests/api/user_service/test_enrollments.py::test_get_enrollments_empty_for_unrelated_user` |  |
| `api` | passed | `tests/api/user_service/test_enrollments.py::test_create_enrollment_then_visible_from_both_sides` |  |
| `api` | passed | `tests/api/user_service/test_enrollments.py::test_create_enrollment_422_missing_field` |  |
| `api` | passed | `tests/api/user_service/test_enrollments.py::test_delete_enrollment_removes_it` |  |
| `api` | passed | `tests/api/user_service/test_enrollments.py::test_delete_enrollment_422_missing_field` |  |
| `api` | passed | `tests/api/user_service/test_gifting.py::test_rewards_balance_and_options_for_ambassador_at_tier_one` |  |
| `api` | passed | `tests/api/user_service/test_gifting.py::test_rewards_404_for_non_ambassador_user` |  |
| `api` | passed | `tests/api/user_service/test_gifting.py::test_redeem_gift_card_success_shape` |  |
| `api` | failed | `tests/api/user_service/test_gifting.py::test_redeem_gift_card_amount_not_in_live_storefront_is_rejected` | AssertionError: expected 422 for an unredeemable amount; got 400: {"detail":"₹2101 is not redeemable on Amazon right now"} assert 400 == 422  +  where 400 = <Response [400 Bad Request]>.status_code |
| `api` | passed | `tests/api/user_service/test_gifting.py::test_redeem_gift_card_404_for_non_ambassador_user` |  |
| `api` | passed | `tests/api/user_service/test_gifting.py::test_redeem_gift_card_422_missing_field` |  |
| `api` | passed | `tests/api/user_service/test_gifting.py::test_get_gift_card_404_for_unknown_gift_card_id` |  |
| `api` | passed | `tests/api/user_service/test_health_version.py::test_health_returns_200` |  |
| `api` | passed | `tests/api/user_service/test_health_version.py::test_version_returns_200` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_create_influencer_shape` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_create_influencer_422_missing_field` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_create_influencer_422_empty_handle` |  |
| `api` | failed | `tests/api/user_service/test_influencers.py::test_create_influencer_409_on_collision_with_existing_influencer_handle` | AssertionError: README documents 409 on handle collision; got 200: {"kind":"influencer","handle":"dupe","platform":"instagram","createdAtMs":1788767614855} assert 200 == 409  +  where 200 = <Response [200 OK]>.status_code |
| `api` | failed | `tests/api/user_service/test_influencers.py::test_create_influencer_409_on_collision_with_existing_ambassador_handle` | AssertionError: README documents the @-mention namespace as shared across kinds; got 500: Internal Server Error assert 500 == 409  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_get_influencer_report_404_for_unknown_handle` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_get_influencer_report_shape_empty` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_list_influencers_includes_every_registered_handle` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_create_campaign_shape` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_create_campaign_404_for_unknown_handle` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_create_campaign_422_start_not_before_end` |  |
| `api` | failed | `tests/api/user_service/test_influencers.py::test_campaign_overlap_identical_window_is_409` | AssertionError: identical window must be rejected as an overlap; got 200: {"id":"10000_20000","startMs":10000,"endMs":20000,"payout":{"baseInr":100,"perBlockInr":10,"blockSize":5,"incentiveCapInr":200}} assert 200 == 409  +  where 200 = <Response [200 OK]>.status_code |
| `api` | failed | `tests/api/user_service/test_influencers.py::test_campaign_overlap_partial_at_start_is_409` | AssertionError: window overlapping the start must be rejected; got 200: {"id":"5000_15000","startMs":5000,"endMs":15000,"payout":{"baseInr":100,"perBlockInr":10,"blockSize":5,"incentiveCapInr":200}} assert 200 == 409  +  where 200 = <Response [200 OK]>.status_code |
| `api` | failed | `tests/api/user_service/test_influencers.py::test_campaign_overlap_partial_at_end_is_409` | AssertionError: window overlapping the end must be rejected; got 200: {"id":"15000_25000","startMs":15000,"endMs":25000,"payout":{"baseInr":100,"perBlockInr":10,"blockSize":5,"incentiveCapInr":200}} assert 200 == 409  +  where 200 = <Response [200 OK]>.status_code |
| `api` | failed | `tests/api/user_service/test_influencers.py::test_campaign_overlap_fully_containing_is_409` | AssertionError: a window fully containing the existing one must be rejected; got 200: {"id":"5000_25000","startMs":5000,"endMs":25000,"payout":{"baseInr":100,"perBlockInr":10,"blockSize":5,"incentiveCapInr":200}} assert 200 == 409  +  where 200 = <Response [200 OK]>.status_code |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_campaign_adjacent_non_overlapping_window_succeeds` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_delete_campaign_204` |  |
| `api` | passed | `tests/api/user_service/test_influencers.py::test_delete_influencer_204_and_report_then_404s` |  |
| `api` | passed | `tests/api/user_service/test_referrers.py::test_click_on_registered_influencer_handle_records_one_row` |  |
| `api` | passed | `tests/api/user_service/test_referrers.py::test_click_on_registered_ambassador_handle_records_one_row` |  |
| `api` | passed | `tests/api/user_service/test_referrers.py::test_click_on_unknown_handle_is_a_no_op_but_still_succeeds` |  |
| `api` | passed | `tests/api/user_service/test_referrers.py::test_click_normalizes_handle_case_and_at_sign` |  |
| `api` | passed | `tests/api/user_service/test_threads.py::test_append_transcript_returns_tip_and_started_at_ms` |  |
| `api` | failed | `tests/api/user_service/test_threads.py::test_append_transcript_404_for_unknown_user` | assert 200 == 404  +  where 200 = <Response [200 OK]>.status_code |
| `api` | passed | `tests/api/user_service/test_threads.py::test_append_transcript_422_empty_messages` |  |
| `api` | passed | `tests/api/user_service/test_threads.py::test_append_transcript_422_missing_read_ids` |  |
| `api` | passed | `tests/api/user_service/test_threads.py::test_get_session_transcripts_returns_appended_session` |  |
| `api` | passed | `tests/api/user_service/test_threads.py::test_get_session_transcripts_404_for_unknown_user` |  |
| `api` | passed | `tests/api/user_service/test_threads.py::test_get_session_transcripts_empty_for_thread_never_used` |  |
| `api` | failed | `tests/api/user_service/test_threads.py::test_set_session_extraction_404_for_unknown_session` | AssertionError: expected 404 for grading a nonexistent session; got 500: Internal Server Error assert 500 == 404  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | failed | `tests/api/user_service/test_threads.py::test_set_session_extraction_then_visible_on_read` | AssertionError: README's Firestore layout documents `gradedWith` as a stored session field; it is absent from the session-read response body, keys=['extraction', 'lastMessageAtMs', 'messages', 'readNodeIds', 'startedAtMs'] assert 'gradedWith' in {'startedAtMs': 1700000000000, 'lastMessageAtMs': 1700000000000, 'readNodeIds': [], 'extraction': {'intent': 'wanted help with algebra', 'grounding': 3, 'boundaries': 3, 'craft': 2, ...}, ...} |
| `api` | passed | `tests/api/user_service/test_threads.py::test_set_session_extraction_422_missing_field` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_create_user_returns_201_or_200_with_profile_shape` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_create_user_is_create_only_original_profile_survives_second_create` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_create_user_422_missing_required_field` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_get_user_404_for_unknown_user_id` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_get_user_200_returns_created_profile` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_batch_get_users_returns_only_existing_ids_in_request_order` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_batch_get_users_422_wrong_type` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_get_directory_entry_404_for_unknown_user` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_get_directory_entry_shape` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_delete_user_returns_204_and_user_then_404s` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_delete_unknown_user_does_not_crash` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_update_profile_overlays_only_provided_fields` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_update_profile_404_for_unknown_user` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_update_profile_422_wrong_type` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_set_location_200_returns_profile_with_location` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_set_location_404_for_unknown_user` |  |
| `api` | passed | `tests/api/user_service/test_users.py::test_set_location_422_missing_required_field` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_missing_encrypted_aes_key_returns_422[/flows/onboarding]` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_missing_encrypted_aes_key_returns_422[/flows/grade]` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_missing_encrypted_flow_data_returns_422[/flows/onboarding]` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_missing_encrypted_flow_data_returns_422[/flows/grade]` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_missing_initial_vector_returns_422[/flows/onboarding]` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_missing_initial_vector_returns_422[/flows/grade]` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_empty_body_returns_422[/flows/onboarding]` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_flows.py::test_empty_body_returns_422[/flows/grade]` |  |
| `api` | failed | `tests/api/whatsapp_adapter/test_flows.py::test_plausible_shaped_garbage_ciphertext_fails_with_421[/flows/onboarding]` | assert 500 == 421  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | failed | `tests/api/whatsapp_adapter/test_flows.py::test_plausible_shaped_garbage_ciphertext_fails_with_421[/flows/grade]` | assert 500 == 421  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | failed | `tests/api/whatsapp_adapter/test_flows.py::test_non_base64_ciphertext_fails_with_421[/flows/onboarding]` | assert 500 == 421  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | failed | `tests/api/whatsapp_adapter/test_flows.py::test_non_base64_ciphertext_fails_with_421[/flows/grade]` | assert 500 == 421  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | failed | `tests/api/whatsapp_adapter/test_flows.py::test_empty_string_fields_fail_with_421[/flows/onboarding]` | assert 500 == 421  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | failed | `tests/api/whatsapp_adapter/test_flows.py::test_empty_string_fields_fail_with_421[/flows/grade]` | assert 500 == 421  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | passed | `tests/api/whatsapp_adapter/test_ops_endpoints.py::test_health_returns_ok_status_and_started_at` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_ops_endpoints.py::test_version_returns_release_metadata_shape` |  |
| `api` | failed | `tests/api/whatsapp_adapter/test_webhook_signature.py::test_missing_signature_header_is_rejected_with_403` | assert 500 == 403  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_signature.py::test_wrong_secret_signature_is_rejected_with_403` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_signature.py::test_syntactically_present_but_invalid_signature_is_rejected_with_403` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_signature.py::test_correct_signature_is_accepted` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_success.py::test_well_formed_inbound_message_is_claimed_then_enqueued_then_200` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_success.py::test_duplicate_delivery_is_claimed_and_processed_only_once` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_success.py::test_sent_status_confirms_delivery` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_validation.py::test_malformed_supported_payload_fails_loudly` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_validation.py::test_reaction_message_is_dropped_and_returns_200` |  |
| `api` | failed | `tests/api/whatsapp_adapter/test_webhook_validation.py::test_unrecognized_message_type_is_ignored_and_returns_200` | AssertionError: an ignored message must not be claimed assert ['wamid.UNRECOGNIZED1'] == []      Left contains one more item: 'wamid.UNRECOGNIZED1'   Use -v to get more diff |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_verification.py::test_matching_token_echoes_challenge` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_verification.py::test_wrong_verify_token_is_rejected` |  |
| `api` | passed | `tests/api/whatsapp_adapter/test_webhook_verification.py::test_wrong_hub_mode_is_rejected` |  |
| `api` | failed | `tests/api/whatsapp_adapter/test_webhook_verification.py::test_missing_query_params_is_rejected_with_403` | assert 500 == 403  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `integration` | failed | `tests/integration/test_cascade.py::test_delete_user_removes_owned_data_and_cascades_referrer_registry` | assert True is False |
| `integration` | passed | `tests/integration/test_cascade.py::test_delete_cascade_would_catch_a_dangling_ambassador_registry_entry` |  |
| `integration` | passed | `tests/integration/test_cascade.py::test_delete_does_not_remove_adapter_owned_onboarding` |  |
| `integration` | passed | `tests/integration/test_cascade.py::test_delete_unknown_user_does_not_crash` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_adapter_create_user_payload_validates_and_round_trips` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_adapter_append_transcript_payload_validates_and_round_trips` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_adapter_append_result_is_a_valid_text_agent_previous_response_id` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_text_agent_profile_update_payload_validates_and_round_trips` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_text_agent_ambassador_and_rewards_responses_validate` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_malformed_create_user_payload_is_422` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_malformed_append_payload_is_422` |  |
| `integration` | passed | `tests/integration/test_cross_service_contract.py::test_users_client_parses_live_responses` |  |
| `integration` | passed | `tests/integration/test_derive_on_read.py::test_directory_activity_moves_with_session_and_transcript_rows` |  |
| `integration` | passed | `tests/integration/test_derive_on_read.py::test_directory_unknown_user_is_404` |  |
| `integration` | passed | `tests/integration/test_derive_on_read.py::test_ambassador_points_move_with_attributed_user_rows` |  |
| `integration` | passed | `tests/integration/test_derive_on_read.py::test_ambassador_status_null_when_not_enrolled` |  |
| `integration` | failed | `tests/integration/test_derive_on_read.py::test_influencer_funnel_moves_with_clicks_and_onboards` | assert 500 == 200  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `integration` | passed | `tests/integration/test_derive_on_read.py::test_influencer_started_moves_with_buffered_onboarding_rows` |  |
| `integration` | passed | `tests/integration/test_derive_on_read.py::test_influencer_unknown_handle_is_404` |  |
| `integration` | passed | `tests/integration/test_derive_on_read.py::test_nothing_writes_stored_counters_for_points_or_balances` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_settlement_404_fails_the_card_and_restores_balance` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_settlement_terminal_failure_fails_the_card_and_restores_balance[FAILED-910000060111]` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_settlement_terminal_failure_fails_the_card_and_restores_balance[CANCELLED-910000060112]` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_settlement_terminal_failure_fails_the_card_and_restores_balance[REVERSED-910000060113]` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_settlement_processing_stays_pending_and_keeps_balance_debited` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_settlement_success_with_voucher_stores_voucher_fields` |  |
| `integration` | failed | `tests/integration/test_hubble_settlement.py::test_settlement_success_with_empty_vouchers_settles_without_voucher_fields` | AssertionError: SUCCESS with empty vouchers must settle, not crash; got 500: Internal Server Error assert 500 == 200  +  where 500 = <Response [500 Internal Server Error]>.status_code |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_settlement_unknown_status_stays_pending_and_does_not_crash` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_place_order_timeout_after_upstream_success_settles_without_double_charge` |  |
| `integration` | passed | `tests/integration/test_hubble_settlement.py::test_redeem_rejected_for_non_ambassador` |  |
| `integration` | failed | `tests/integration/test_hubble_settlement.py::test_redeem_amount_not_offered_is_rejected_without_placing_an_order` | assert 400 == 422  +  where 400 = <Response [400 Bad Request]>.status_code |
| `integration` | failed | `tests/integration/test_idempotency.py::test_concurrent_claims_of_the_same_id_exactly_one_wins` | google.api_core.exceptions.Aborted: 409 Transaction lock timeout. |
| `integration` | passed | `tests/integration/test_idempotency.py::test_sequential_claim_of_the_same_id_succeeds_once` |  |
| `integration` | passed | `tests/integration/test_idempotency.py::test_distinct_message_ids_each_succeed_once` |  |
| `integration` | failed | `tests/integration/test_sequences.py::test_concurrent_appends_to_one_session_assign_sequences_1_through_n` | assert [500, 500, 50...500, 500, ...] == [200, 200, 20...200, 200, ...]      At index 0 diff: 500 != 200   Use -v to get more diff |
| `integration` | failed | `tests/integration/test_sequences.py::test_caller_supplied_sequence_is_ignored` | assert [0] == [1]      At index 0 diff: 0 != 1   Use -v to get more diff |
| `integration` | passed | `tests/integration/test_sequences.py::test_append_empty_messages_is_422` |  |
| `integration` | passed | `tests/integration/test_session_boundary.py::test_gap_strictly_under_two_hours_stays_in_the_same_session` |  |
| `integration` | passed | `tests/integration/test_session_boundary.py::test_gap_strictly_over_two_hours_opens_a_new_session` |  |
| `integration` | failed | `tests/integration/test_session_boundary.py::test_gap_exactly_two_hours_opens_a_new_session` | assert 1770000000000 == 1770007200000 |
| `integration` | passed | `tests/integration/test_session_boundary.py::test_pinned_started_at_ms_does_not_re_gap` |  |
| `integration` | passed | `tests/integration/test_session_boundary.py::test_started_at_ms_of_wrong_type_is_422` |  |
| `integration` | failed | `tests/integration/test_transactions.py::test_successful_append_moves_cursors_with_the_rows` | assert [0, 1] == [1, 2]      At index 0 diff: 0 != 1   Use -v to get more diff |
| `integration` | failed | `tests/integration/test_transactions.py::test_failed_append_leaves_all_cursors_and_rows_unchanged` | assert [0] == [1]      At index 0 diff: 0 != 1   Use -v to get more diff |
| `integration` | passed | `tests/integration/test_transactions.py::test_failure_append_does_not_advance_previous_response_id` |  |
| `integration` | passed | `tests/integration/test_transactions.py::test_read_node_ids_are_a_deduplicated_union_across_appends` |  |
| `integration` | passed | `tests/integration/test_transactions.py::test_append_with_non_list_read_ids_is_422` |  |
| `e2e` | passed | `tests/e2e/test_ambassador_and_gifting.py::test_ambassador_enrollment_counts_a_referred_student` |  |
| `e2e` | failed | `tests/e2e/test_ambassador_and_gifting.py::test_gift_card_redeem_settles_and_debits_balance` | assert 404 == 200  +  where 404 = <Response [404 Not Found]>.status_code |
| `e2e` | passed | `tests/e2e/test_blocking_and_failures.py::test_blocked_phone_gets_only_the_canned_error` |  |
| `e2e` | passed | `tests/e2e/test_blocking_and_failures.py::test_reaction_message_is_dropped` |  |
| `e2e` | failed | `tests/e2e/test_blocking_and_failures.py::test_unrecognized_message_type_is_ignored` | AssertionError: an ignored message must not produce any outbound reply assert [WhatsAppCall...wamid.out.1')] == []      Left contains one more item: WhatsAppCall(kind='text', to='919300000112', data={'body': 'Sorry, something went wrong while preparing that. Please try again in a bit.'}, wamid='wamid.out.1')   Use -v to get more diff |
| `e2e` | passed | `tests/e2e/test_blocking_and_failures.py::test_malformed_supported_payload_fails_loudly` |  |
| `e2e` | passed | `tests/e2e/test_blocking_and_failures.py::test_generation_failure_sends_canned_error_and_closes_the_turn` |  |
| `e2e` | passed | `tests/e2e/test_conversation.py::test_known_phone_generates_and_delivers_in_model_order` |  |
| `e2e` | passed | `tests/e2e/test_conversation.py::test_form_message_resolves_persona_specific_flow_id` |  |
| `e2e` | passed | `tests/e2e/test_conversation.py::test_location_share_saves_profile_and_runs_one_turn` |  |
| `e2e` | passed | `tests/e2e/test_conversation.py::test_button_tap_runs_one_stateless_turn` |  |
| `e2e` | passed | `tests/e2e/test_idempotency.py::test_duplicate_delivery_is_processed_once` |  |
| `e2e` | passed | `tests/e2e/test_onboarding.py::test_unknown_phone_sends_text_then_picks_student` |  |
| `e2e` | passed | `tests/e2e/test_onboarding.py::test_onboarding_flow_completion_attributes_first_mention` |  |
| `e2e` | passed | `tests/e2e/test_onboarding.py::test_hidden_number_requests_contact_then_resumes` |  |
| `e2e` | failed | `tests/e2e/test_onboarding.py::test_forwarded_contact_represents_phone_request` | AssertionError: assert 'Share your n...ays with you.' == 'Hi Priya! 👋 ...ays with you.'      - Hi Priya! 👋 I'm Sujho — your AI for learning.     Share your number so everything you learn and create stays with you. |
| `e2e` | passed | `tests/e2e/test_onboarding.py::test_stray_message_during_onboarding_buffers_and_represents` |  |
| `e2e` | failed | `tests/e2e/test_session_gap.py::test_session_gap_boundary` | assert 1750000000000 == 1750014340000 |
| `e2e` | passed | `tests/e2e/test_webhook_signature.py::test_valid_signature_is_accepted_and_processed` |  |
| `e2e` | passed | `tests/e2e/test_webhook_signature.py::test_wrong_secret_signature_is_rejected` |  |
| `e2e` | passed | `tests/e2e/test_webhook_signature.py::test_tampered_body_signature_is_rejected` |  |
