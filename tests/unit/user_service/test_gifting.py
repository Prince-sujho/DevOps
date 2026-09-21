"""Pure gift-card arithmetic and storefront amounts.

Oracle: user_service README (spendable balance = earned ₹ minus non-failed
gifting amounts; pending debits, failed restores), campus-ambassadors skill
("each reward is earned once" on the cumulative ladder), gifting function
docstrings, and the frozen ``AMBASSADOR_TIERS`` / ``REWARD_AMOUNTS`` tables.

Expected rupee literals were written from those sources *before* execution.
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from infra.clients.users import RedeemRequest
from infra.hubble.types import HubbleAmountRestrictions
from user_service.app.src.gifting import (
    _apply_order,
    _settle,
    balance_inr,
    earned_inr,
    offered_amounts,
    redeem,
    settled_gift_cards,
    spent_inr,
)

from .factories import (
    AMAZON_PRODUCT_ID,
    EARNED_AT_TIER_INR,
    FLEXIBLE_LADDER_INR,
    TIER_POINTS,
    TIER_REWARDS_INR,
    gift_card,
    hubble_product,
    student,
)
from .fakes import FakeGifting, FakeHubble, hubble_order, success_order


# ---------------------------------------------------------------------------
# earned_inr
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_earned_inr_below_first_tier_is_zero() -> None:
    """Below the ladder's first named rung, nothing has been crossed yet."""
    assert earned_inr(0) == 0
    assert earned_inr(TIER_POINTS[0] - 1) == 0


@pytest.mark.boundary
def test_earned_inr_exactly_at_each_tier() -> None:
    """Each crossed rung adds its reward once, cumulatively -- bound to the
    real named ladder (AMBASSADOR_TIERS via factories.TIER_POINTS /
    EARNED_AT_TIER_INR), not a second hand-copied set of numbers."""
    for points, expected in zip(TIER_POINTS, EARNED_AT_TIER_INR):
        assert earned_inr(points) == expected


@pytest.mark.boundary
def test_earned_inr_one_below_each_tier() -> None:
    """One point short of a rung must not credit that rung's reward."""
    previous = 0
    for points, expected in zip(TIER_POINTS, EARNED_AT_TIER_INR):
        assert earned_inr(points - 1) == previous
        previous = expected


@pytest.mark.boundary
def test_earned_inr_one_above_each_tier() -> None:
    """One point past a rung still only credits that rung, not the next."""
    for points, expected in zip(TIER_POINTS, EARNED_AT_TIER_INR):
        assert earned_inr(points + 1) == expected


@pytest.mark.boundary
def test_earned_inr_far_above_top_tier_does_not_invent_a_fifth_rung() -> None:
    assert earned_inr(TIER_POINTS[-1] + 1) == EARNED_AT_TIER_INR[-1]
    assert earned_inr(10_000) == EARNED_AT_TIER_INR[-1]


@pytest.mark.boundary
def test_earned_inr_negative_points_cross_no_rung() -> None:
    """Spec does not allow negative points (API types are `ge=0`); the pure
    function itself is unguarded. Reviewed per tests/outcomes/UNCERTAINTY.md's
    "guesses that stayed green" list: kept intentionally, not just because it
    passed -- every rung threshold is non-negative, so "no rung crossed -> ₹0"
    is the only value consistent with `earned_inr`'s own definition (sum of
    crossed-rung rewards) for any input below the lowest threshold, not a
    separate policy choice layered on top.
    """
    assert earned_inr(-1) == 0
    assert earned_inr(-10_000) == 0


@pytest.mark.property
@given(points=st.integers(min_value=0, max_value=10_000))
def test_earned_inr_equals_sum_of_every_crossed_rung(points: int) -> None:
    expected = 0
    for threshold, reward in zip(TIER_POINTS, TIER_REWARDS_INR):
        if points >= threshold:
            expected += reward
    assert earned_inr(points) == expected
    assert expected in (0, *EARNED_AT_TIER_INR)


# ---------------------------------------------------------------------------
# spent_inr
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_spent_inr_empty_list_is_zero() -> None:
    assert spent_inr([]) == 0


@pytest.mark.boundary
def test_spent_inr_only_failed_cards_restore_credit() -> None:
    cards = [
        gift_card(amount_inr=100, status="failed", gift_id="f1"),
        gift_card(amount_inr=250, status="failed", gift_id="f2"),
    ]
    assert spent_inr(cards) == 0


@pytest.mark.boundary
def test_spent_inr_only_pending_cards_debit() -> None:
    cards = [
        gift_card(amount_inr=50, status="pending", gift_id="p1"),
        gift_card(amount_inr=100, status="pending", gift_id="p2"),
    ]
    assert spent_inr(cards) == 150


@pytest.mark.boundary
def test_spent_inr_only_succeeded_cards_debit() -> None:
    cards = [
        gift_card(amount_inr=100, status="succeeded", gift_id="s1"),
        gift_card(amount_inr=500, status="succeeded", gift_id="s2"),
    ]
    assert spent_inr(cards) == 600


@pytest.mark.boundary
def test_spent_inr_mix_excludes_failed() -> None:
    cards = [
        gift_card(amount_inr=50, status="pending", gift_id="p"),
        gift_card(amount_inr=100, status="succeeded", gift_id="s"),
        gift_card(amount_inr=200, status="failed", gift_id="f"),
    ]
    assert spent_inr(cards) == 150


@pytest.mark.property
@given(
    failed_amounts=st.lists(st.integers(min_value=0, max_value=5000), max_size=8),
    kept_amounts=st.lists(st.integers(min_value=0, max_value=5000), max_size=8),
    kept_status=st.sampled_from(["pending", "succeeded"]),
)
def test_failed_card_never_contributes_to_spend(
    failed_amounts: list[int], kept_amounts: list[int], kept_status: str
) -> None:
    failed = [
        gift_card(amount_inr=amt, status="failed", gift_id=f"f{i}")
        for i, amt in enumerate(failed_amounts)
    ]
    kept = [
        gift_card(amount_inr=amt, status=kept_status, gift_id=f"k{i}")  # type: ignore[arg-type]
        for i, amt in enumerate(kept_amounts)
    ]
    assert spent_inr(failed) == 0
    assert spent_inr(failed + kept) == spent_inr(kept)
    assert spent_inr(kept) == sum(kept_amounts)


# ---------------------------------------------------------------------------
# balance_inr
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_balance_inr_is_earned_minus_non_failed_spend() -> None:
    """Five points earn ₹100; a pending ₹50 card holds half of it."""
    cards = [gift_card(amount_inr=50, status="pending")]
    assert balance_inr(5, cards) == 50


@pytest.mark.boundary
def test_balance_inr_failed_card_does_not_reduce_balance() -> None:
    cards = [gift_card(amount_inr=100, status="failed")]
    assert balance_inr(5, cards) == 100


@pytest.mark.boundary
def test_balance_inr_can_go_negative_when_spend_exceeds_earned() -> None:
    """Design challenge. Spec arithmetic is earned − non-failed spend, with
    no documented floor at ₹0. Zero points and a succeeded ₹100 card produce
    a negative spendable balance of −100. If this assertion holds, the design
    allows a negative wallet; that is recorded in FINDINGS.md, not softened.
    """
    cards = [gift_card(amount_inr=100, status="succeeded")]
    assert balance_inr(0, cards) == -100


@pytest.mark.property
@given(
    points=st.integers(min_value=0, max_value=200),
    amounts=st.lists(st.integers(min_value=0, max_value=2000), max_size=6),
    statuses=st.lists(st.sampled_from(["pending", "succeeded", "failed"]), max_size=6),
)
def test_balance_equals_earned_minus_non_failed_spend_for_all_inputs(
    points: int, amounts: list[int], statuses: list[str]
) -> None:
    n = min(len(amounts), len(statuses))
    cards = [
        gift_card(amount_inr=amounts[i], status=statuses[i], gift_id=f"g{i}")  # type: ignore[arg-type]
        for i in range(n)
    ]
    assert balance_inr(points, cards) == earned_inr(points) - spent_inr(cards)


# ---------------------------------------------------------------------------
# offered_amounts — rejection / empty cases
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_offered_amounts_inactive_product_is_empty() -> None:
    product = hubble_product(status="INACTIVE", denominations=[100, 250])
    assert offered_amounts(product, 500) == []


@pytest.mark.boundary
def test_offered_amounts_none_amount_restrictions_is_empty() -> None:
    product = hubble_product(omit_restrictions=True)
    assert offered_amounts(product, 500) == []


@pytest.mark.boundary
def test_offered_amounts_empty_how_to_use_instructions_is_empty() -> None:
    product = hubble_product(instructions=[], denominations=[100])
    assert offered_amounts(product, 500) == []


@pytest.mark.boundary
def test_offered_amounts_balance_below_min_is_empty() -> None:
    product = hubble_product(min_voucher=50, max_voucher=5000, denominations=None)
    assert offered_amounts(product, 49) == []
    product_fixed = hubble_product(min_voucher=50, max_voucher=5000, denominations=[100])
    assert offered_amounts(product_fixed, 49) == []


# ---------------------------------------------------------------------------
# offered_amounts — flexible (empty/None denominations): ladder + exact balance
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_offered_amounts_flexible_balance_exactly_min() -> None:
    """min=10 is not on the (50, 100, ...) ladder, so the exact balance is the
    only redeemable amount.
    """
    product = hubble_product(min_voucher=10, max_voucher=5000, denominations=None)
    assert offered_amounts(product, 10) == [10]


@pytest.mark.boundary
def test_offered_amounts_flexible_balance_on_a_ladder_rung() -> None:
    """A balance exactly on a rung offers every rung up to and including it --
    bound to the real named ladder (REWARD_AMOUNTS via
    factories.FLEXIBLE_LADDER_INR), not a second hand-copied list."""
    product = hubble_product(min_voucher=10, max_voucher=5000, denominations=None)
    assert offered_amounts(product, FLEXIBLE_LADDER_INR[0]) == [FLEXIBLE_LADDER_INR[0]]
    assert offered_amounts(product, FLEXIBLE_LADDER_INR[1]) == list(FLEXIBLE_LADDER_INR[:2])
    assert offered_amounts(product, FLEXIBLE_LADDER_INR[-1]) == list(FLEXIBLE_LADDER_INR)


@pytest.mark.boundary
def test_offered_amounts_flexible_includes_exact_balance_between_rungs() -> None:
    product = hubble_product(min_voucher=10, max_voucher=5000, denominations=None)
    below_second_rung = FLEXIBLE_LADDER_INR[1] - 1
    assert offered_amounts(product, below_second_rung) == sorted(
        {*[a for a in FLEXIBLE_LADDER_INR if a <= below_second_rung], below_second_rung}
    )
    just_above_third_rung = FLEXIBLE_LADDER_INR[2] + 1
    assert offered_amounts(product, just_above_third_rung) == sorted(
        {*[a for a in FLEXIBLE_LADDER_INR if a <= just_above_third_rung], just_above_third_rung}
    )


@pytest.mark.boundary
def test_offered_amounts_flexible_balance_above_max_is_capped_at_max() -> None:
    """A balance past max is not itself offerable, and max is not synthesized
    as a rung unless it already is one -- only ladder rungs at or below max
    remain.
    """
    max_voucher = FLEXIBLE_LADDER_INR[-1] + 3000
    product = hubble_product(min_voucher=10, max_voucher=max_voucher, denominations=None)
    assert offered_amounts(product, max_voucher + 1000) == list(FLEXIBLE_LADDER_INR)


@pytest.mark.boundary
def test_offered_amounts_flexible_none_denominations_matches_empty_list() -> None:
    """Hubble null-denominations become []. Both are the flexible path."""
    empty = hubble_product(min_voucher=10, max_voucher=5000, denominations=[])
    via_none = hubble_product(
        restrictions=HubbleAmountRestrictions(
            minVoucherAmount=10, maxVoucherAmount=5000, denominations=[]
        )
    )
    assert offered_amounts(empty, 75) == [50, 75]
    assert offered_amounts(via_none, 75) == [50, 75]


# ---------------------------------------------------------------------------
# offered_amounts — fixed (denominations present): NOT + exact balance
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_offered_amounts_fixed_does_not_add_exact_balance() -> None:
    """This is the documented fork from flexible: a ₹150 balance against
    denominations [100, 250] offers 100 only — not 150.
    """
    product = hubble_product(min_voucher=10, max_voucher=5000, denominations=[100, 250])
    assert offered_amounts(product, 150) == [100]


@pytest.mark.boundary
def test_offered_amounts_fixed_balance_exactly_min_only_if_min_is_a_denomination() -> None:
    product = hubble_product(min_voucher=100, max_voucher=5000, denominations=[100, 250])
    assert offered_amounts(product, 100) == [100]
    no_min_denom = hubble_product(min_voucher=100, max_voucher=5000, denominations=[250, 500])
    assert offered_amounts(no_min_denom, 100) == []


@pytest.mark.boundary
def test_offered_amounts_fixed_balance_above_max_is_capped_at_max() -> None:
    product = hubble_product(min_voucher=10, max_voucher=400, denominations=[100, 250, 500])
    assert offered_amounts(product, 10_000) == [100, 250]


@pytest.mark.boundary
def test_offered_amounts_fixed_is_sorted_and_deduplicated() -> None:
    product = hubble_product(min_voucher=10, max_voucher=5000, denominations=[500, 100, 100, 250])
    assert offered_amounts(product, 1000) == [100, 250, 500]


@pytest.mark.boundary
def test_offered_amounts_fixed_filters_denominations_outside_min_max() -> None:
    product = hubble_product(min_voucher=100, max_voucher=300, denominations=[50, 100, 250, 500])
    assert offered_amounts(product, 300) == [100, 250]


# ---------------------------------------------------------------------------
# offered_amounts — properties
# ---------------------------------------------------------------------------


@pytest.mark.property
@given(
    balance=st.integers(min_value=0, max_value=8000),
    min_v=st.integers(min_value=1, max_value=200),
    max_v=st.integers(min_value=200, max_value=5000),
)
def test_flexible_amounts_are_the_ladder_plus_exact_balance_inside_bounds(
    balance: int, min_v: int, max_v: int
) -> None:
    """Invariants only -- deliberately NOT a second reimplementation of
    `offered_amounts` compared for exact equality (that failure mode turns a
    property test into "the function equals a copy of itself"). Instead this
    pins the independently-statable rules: below min is empty; every result
    is sorted, unique, and bounded; every ladder rung inside bounds is
    offered; the exact balance is offered when it is itself inside bounds;
    and nothing outside the ladder-or-exact-balance set is ever invented.
    """
    product = hubble_product(min_voucher=min_v, max_voucher=max_v, denominations=None)
    result = offered_amounts(product, balance)

    if balance < min_v:
        assert result == []
        return

    cap = min(max_v, balance)
    assert result == sorted(result)
    assert len(result) == len(set(result))
    assert all(min_v <= amount <= cap for amount in result)
    for rung in FLEXIBLE_LADDER_INR:
        if min_v <= rung <= cap:
            assert rung in result
    if min_v <= balance <= cap:
        assert balance in result
    allowed = {*FLEXIBLE_LADDER_INR, balance}
    assert all(amount in allowed for amount in result)


@pytest.mark.property
@given(
    balance=st.integers(min_value=0, max_value=8000),
    min_v=st.integers(min_value=1, max_value=200),
    max_v=st.integers(min_value=200, max_value=5000),
    denoms=st.lists(st.integers(min_value=1, max_value=6000), min_size=1, max_size=8),
)
def test_fixed_amounts_stay_within_bounds_sorted_unique(
    balance: int, min_v: int, max_v: int, denoms: list[int]
) -> None:
    """Empty denominations is the flexible path (covered separately). This
    property is only the fixed fork: at least one denomination. Invariants
    only, per the same reimplementation concern as the flexible property
    above: no exact-balance synthesis (the documented flexible/fixed fork),
    every in-bounds denomination present, nothing outside the given
    denominations ever invented.
    """
    product = hubble_product(min_voucher=min_v, max_voucher=max_v, denominations=denoms)
    result = offered_amounts(product, balance)

    if balance < min_v:
        assert result == []
        return

    cap = min(max_v, balance)
    assert result == sorted(result)
    assert len(result) == len(set(result))
    assert all(min_v <= amount <= cap for amount in result)
    for denom in denoms:
        if min_v <= denom <= cap:
            assert denom in result
    assert all(amount in set(denoms) for amount in result)
    assert all(min_v <= amount <= cap for amount in result)


@pytest.mark.property
@given(balance=st.integers(min_value=-1000, max_value=-1))
def test_offered_amounts_negative_balance_is_empty(balance: int) -> None:
    """Negative spendable credit cannot mint a voucher."""
    flexible = hubble_product(min_voucher=10, max_voucher=5000, denominations=None)
    fixed = hubble_product(min_voucher=10, max_voucher=5000, denominations=[100, 250])
    assert offered_amounts(flexible, balance) == []
    assert offered_amounts(fixed, balance) == []


# ---------------------------------------------------------------------------
# Lazy Hubble settlement (_apply_order / _settle / settled_gift_cards / redeem)
# Oracle: user_service README + HubbleOrder docstring (only SUCCESS settles;
# 404/None means the mint never happened → fail; FAILED/CANCELLED/REVERSED
# fail; PROCESSING and unknown stay pending; pending debits, failed restores).
# ---------------------------------------------------------------------------

USER_ID = "user-arjun"
PROFILE = student(user_id=USER_ID, name="Arjun")
CARD_ID = "gc-1"


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_apply_order_none_means_404_and_fails_the_card() -> None:
    """README: Hubble 404 on the reference id means the mint never happened;
    the pending card must settle as failed so credit is restored.
    """
    gifting = FakeGifting()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _apply_order(USER_ID, card, None, gifting)
    assert settled.status == "failed"
    assert gifting.fail_calls == [(USER_ID, CARD_ID)]
    assert gifting.succeed_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_apply_order_hubble_failed_fails_the_card() -> None:
    gifting = FakeGifting()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _apply_order(USER_ID, card, hubble_order("FAILED"), gifting)
    assert settled.status == "failed"
    assert gifting.fail_calls == [(USER_ID, CARD_ID)]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_apply_order_hubble_cancelled_fails_the_card() -> None:
    gifting = FakeGifting()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _apply_order(USER_ID, card, hubble_order("CANCELLED"), gifting)
    assert settled.status == "failed"
    assert gifting.fail_calls == [(USER_ID, CARD_ID)]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_apply_order_hubble_reversed_fails_the_card() -> None:
    gifting = FakeGifting()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _apply_order(USER_ID, card, hubble_order("REVERSED"), gifting)
    assert settled.status == "failed"
    assert gifting.fail_calls == [(USER_ID, CARD_ID)]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_apply_order_success_attaches_voucher_fields() -> None:
    """SUCCESS with a voucher stores cardNumber / cardPin / validTill (YYYY-MM-DD)."""
    gifting = FakeGifting()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _apply_order(
        USER_ID,
        card,
        success_order(
            card_number="4111111111111111",
            card_pin="9999",
            valid_till="2027-12-31",
        ),
        gifting,
    )
    assert settled.status == "succeeded"
    assert gifting.succeed_calls == [
        (USER_ID, CARD_ID, "4111111111111111", "9999", "2027-12-31")
    ]
    assert gifting.fail_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_apply_order_processing_stays_pending() -> None:
    """HubbleOrder: unknown / in-flight statuses stay pending; PROCESSING is not SUCCESS."""
    gifting = FakeGifting()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _apply_order(USER_ID, card, hubble_order("PROCESSING"), gifting)
    assert settled.status == "pending"
    assert gifting.fail_calls == []
    assert gifting.succeed_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_apply_order_unknown_status_stays_pending() -> None:
    """HubbleOrder docstring: unknown values stay pending. Not a crash, not a fail."""
    gifting = FakeGifting()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _apply_order(USER_ID, card, hubble_order("FROBNITZ"), gifting)
    assert settled.status == "pending"
    assert gifting.fail_calls == []
    assert gifting.succeed_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_settle_404_fails_a_pending_card() -> None:
    gifting = FakeGifting()
    hubble = FakeHubble()
    card = gift_card(amount_inr=50, status="pending")
    settled = await _settle(USER_ID, card, gifting, hubble)
    assert settled.status == "failed"
    assert hubble.get_order_calls == [CARD_ID]
    assert gifting.fail_calls == [(USER_ID, CARD_ID)]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_settle_terminal_failed_statuses_fail_the_pending_card() -> None:
    for status in ("FAILED", "CANCELLED", "REVERSED"):
        gifting = FakeGifting()
        hubble = FakeHubble()
        hubble.orders[CARD_ID] = hubble_order(status)
        card = gift_card(amount_inr=50, status="pending")
        settled = await _settle(USER_ID, card, gifting, hubble)
        assert settled.status == "failed", status
        assert gifting.fail_calls == [(USER_ID, CARD_ID)]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_settle_success_with_voucher_succeeds() -> None:
    gifting = FakeGifting()
    hubble = FakeHubble()
    hubble.orders[CARD_ID] = success_order(
        card_number="5555", card_pin="1234", valid_till="2028-01-15"
    )
    card = gift_card(amount_inr=50, status="pending")
    settled = await _settle(USER_ID, card, gifting, hubble)
    assert settled.status == "succeeded"
    assert gifting.succeed_calls == [(USER_ID, CARD_ID, "5555", "1234", "2028-01-15")]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_settle_processing_and_unknown_leave_pending_and_do_not_call_fail() -> None:
    for status in ("PROCESSING", "FROBNITZ"):
        gifting = FakeGifting()
        hubble = FakeHubble()
        hubble.orders[CARD_ID] = hubble_order(status)
        card = gift_card(amount_inr=50, status="pending")
        settled = await _settle(USER_ID, card, gifting, hubble)
        assert settled.status == "pending", status
        assert gifting.fail_calls == []
        assert gifting.succeed_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_settle_already_succeeded_is_passed_through_without_hubble() -> None:
    """Docstring: pass terminal ones through. A succeeded card is not re-queried."""
    gifting = FakeGifting()
    hubble = FakeHubble()
    card = gift_card(amount_inr=50, status="succeeded")
    settled = await _settle(USER_ID, card, gifting, hubble)
    assert settled.status == "succeeded"
    assert hubble.get_order_calls == []
    assert gifting.fail_calls == []
    assert gifting.succeed_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_settle_already_failed_is_passed_through_without_hubble() -> None:
    gifting = FakeGifting()
    hubble = FakeHubble()
    card = gift_card(amount_inr=50, status="failed")
    settled = await _settle(USER_ID, card, gifting, hubble)
    assert settled.status == "failed"
    assert hubble.get_order_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_settled_gift_cards_lists_this_user_and_settles_each_pending() -> None:
    """List one user's gift cards, lazily settling any still pending."""
    gifting = FakeGifting()
    hubble = FakeHubble()
    pending = gift_card(amount_inr=50, status="pending", gift_id="gc-pending")
    done = gift_card(amount_inr=100, status="succeeded", gift_id="gc-done")
    other = gift_card(amount_inr=250, status="pending", gift_id="gc-other")
    gifting.seed(USER_ID, pending)
    gifting.seed(USER_ID, done)
    gifting.seed("someone-else", other)
    hubble.orders["gc-pending"] = hubble_order("FAILED")

    cards = await settled_gift_cards(USER_ID, gifting, hubble)

    assert gifting.list_calls == [USER_ID]
    statuses = {card.id: card.status for card in cards}
    assert statuses == {"gc-pending": "failed", "gc-done": "succeeded"}
    assert hubble.get_order_calls == ["gc-pending"]
    assert "gc-other" not in hubble.get_order_calls
    assert gifting.fail_calls == [(USER_ID, "gc-pending")]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_redeem_places_order_for_the_product_reference_and_amount() -> None:
    """Redeem snapshots instructions, uses the gift-card id as Hubble referenceId,
    and mints the requested amount on the live storefront SKU.
    """
    gifting = FakeGifting()
    hubble = FakeHubble()
    hubble.products[AMAZON_PRODUCT_ID] = hubble_product(
        instructions=["Show at checkout", "Keep the SMS"]
    )
    hubble.place_order_result = success_order(
        card_number="4111", card_pin="0000", valid_till="2027-06-01"
    )

    card = await redeem(
        PROFILE,
        5,
        RedeemRequest(productId=AMAZON_PRODUCT_ID, amountInr=50),
        gifting,
        hubble,
    )

    assert card.status == "succeeded"
    assert card.amountInr == 50
    assert card.productId == AMAZON_PRODUCT_ID
    assert gifting.create_pending_calls == [
        {
            "user_id": USER_ID,
            "product_id": AMAZON_PRODUCT_ID,
            "brand": "Amazon",
            "amount_inr": 50,
            "instructions": "Show at checkout\nKeep the SMS",
        }
    ]
    assert hubble.place_order_calls == [
        {
            "product_id": AMAZON_PRODUCT_ID,
            "reference_id": "gc-mint-1",
            "amount_inr": 50,
        }
    ]
    assert gifting.succeed_calls == [
        (USER_ID, "gc-mint-1", "4111", "0000", "2027-06-01")
    ]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_redeem_unoffered_amount_raises_and_does_not_place_an_order() -> None:
    """README: refuses an amount not currently offered by the live storefront.
    Hubble must not be asked to mint. Five points earn ₹100; ₹250 is off the
    flexible ladder below that ceiling.
    """
    gifting = FakeGifting()
    hubble = FakeHubble()
    hubble.products[AMAZON_PRODUCT_ID] = hubble_product()

    with pytest.raises(ValueError):
        await redeem(
            PROFILE,
            5,
            RedeemRequest(productId=AMAZON_PRODUCT_ID, amountInr=250),
            gifting,
            hubble,
        )

    assert hubble.place_order_calls == []
    assert gifting.create_pending_calls == []


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_redeem_settles_this_users_cards_before_the_balance_check() -> None:
    """Settle first so existing spends cap the storefront. Five points earn ₹100;
    a succeeded ₹50 card leaves ₹50 spendable, so ₹100 is not offered.
    Listing some other user's (or no one's) cards would restore a fake ₹100 wallet.
    """
    gifting = FakeGifting()
    gifting.seed(USER_ID, gift_card(amount_inr=50, status="succeeded", gift_id="gc-old"))
    hubble = FakeHubble()
    hubble.products[AMAZON_PRODUCT_ID] = hubble_product()

    with pytest.raises(ValueError):
        await redeem(
            PROFILE,
            5,
            RedeemRequest(productId=AMAZON_PRODUCT_ID, amountInr=100),
            gifting,
            hubble,
        )

    assert hubble.place_order_calls == []
    assert gifting.list_calls == [USER_ID]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_redeem_404_on_an_existing_pending_card_restores_credit() -> None:
    """A leftover pending mint that Hubble never created must fail on the
    next redeem so the debit does not block a real ₹50 offer.
    """
    gifting = FakeGifting()
    gifting.seed(USER_ID, gift_card(amount_inr=50, status="pending", gift_id="gc-stale"))
    hubble = FakeHubble()
    hubble.products[AMAZON_PRODUCT_ID] = hubble_product()
    hubble.place_order_result = success_order()

    card = await redeem(
        PROFILE,
        5,
        RedeemRequest(productId=AMAZON_PRODUCT_ID, amountInr=50),
        gifting,
        hubble,
    )

    assert card.status == "succeeded"
    assert gifting.fail_calls == [(USER_ID, "gc-stale")]
    assert hubble.get_order_calls == ["gc-stale"]
