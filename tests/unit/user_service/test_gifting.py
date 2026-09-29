"""Gift-card credit arithmetic, as invariants over all inputs.

Oracle: user_service README (spendable balance = earned ₹ minus non-failed
gifting amounts; pending debits, failed restores) and the campus-ambassadors
skill ("each reward is earned once" on the cumulative ladder). Tier numbers
come from the product's ``AMBASSADOR_TIERS`` via factories, never retyped.
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from infra.clients.users import spent_inr
from user_service.app.src.gifting import (
    balance_inr,
    earned_inr,
    offered_amounts,
)

from .factories import (
    EARNED_AT_TIER_INR,
    TIER_POINTS,
    TIER_REWARDS_INR,
    gift_card,
    hubble_product,
)

AMOUNTS = st.integers(min_value=0, max_value=5000)


@pytest.mark.property
@given(points=st.integers(min_value=0, max_value=10_000))
def test_earned_inr_equals_sum_of_every_crossed_rung(points: int) -> None:
    """Lifetime credit is the sum of every tier reward whose point threshold was
    crossed.

    Args:
        points: hypothesis-generated lifetime ambassador points.
    Returns:
        None.
    Raises:
        None.
    """
    expected = sum(
        reward
        for threshold, reward in zip(TIER_POINTS, TIER_REWARDS_INR)
        if points >= threshold
    )
    assert earned_inr(points) == expected
    assert expected in (0, *EARNED_AT_TIER_INR)


@pytest.mark.property
@given(
    failed_amounts=st.lists(AMOUNTS, max_size=8),
    kept_amounts=st.lists(AMOUNTS, max_size=8),
    kept_status=st.sampled_from(["pending", "succeeded"]),
)
def test_failed_card_never_contributes_to_spend(
    failed_amounts: list[int], kept_amounts: list[int], kept_status: str
) -> None:
    """Failed gift cards never count toward spend, no matter what else is mixed
    in.

    Args:
        failed_amounts: hypothesis-generated amounts for failed gift cards.
        kept_amounts: hypothesis-generated amounts for non-failed gift cards.
        kept_status: the non-failed status shared by every kept card.
    Returns:
        None.
    Raises:
        None.
    """
    failed = [
        gift_card(amount_inr=a, status="failed", gift_id=f"f{i}")
        for i, a in enumerate(failed_amounts)
    ]
    kept = [
        gift_card(
            amount_inr=a,
            status=kept_status,  # type: ignore[arg-type]
            gift_id=f"k{i}",
        )
        for i, a in enumerate(kept_amounts)
    ]
    assert spent_inr(failed) == 0
    assert spent_inr(failed + kept) == spent_inr(kept) == sum(kept_amounts)


@pytest.mark.property
@given(
    points=st.integers(min_value=0, max_value=200),
    cards=st.lists(
        st.tuples(AMOUNTS, st.sampled_from(["pending", "succeeded", "failed"])),
        max_size=6,
    ),
)
def test_balance_equals_earned_minus_non_failed_spend_for_all_inputs(
    points: int, cards: list[tuple[int, str]]
) -> None:
    """Spendable balance is always earned credit minus non-failed spend, for any
    mix of cards.

    Args:
        points: hypothesis-generated lifetime ambassador points.
        cards: hypothesis-generated (amount, status) pairs for gift cards.
    Returns:
        None.
    Raises:
        None.
    """
    gift_cards = [
        gift_card(
            amount_inr=amount,
            status=status,  # type: ignore[arg-type]
            gift_id=f"g{i}",
        )
        for i, (amount, status) in enumerate(cards)
    ]
    assert balance_inr(points, gift_cards) == earned_inr(points) - spent_inr(
        gift_cards
    )


@pytest.mark.property
@given(balance=st.integers(min_value=-1000, max_value=-1))
def test_offered_amounts_negative_balance_is_empty(balance: int) -> None:
    """Negative spendable credit can never mint a voucher, flexible or fixed.

    Args:
        balance: hypothesis-generated negative spendable balance.
    Returns:
        None.
    Raises:
        None.
    """
    flexible = hubble_product(denominations=None)
    fixed = hubble_product(denominations=[100, 250])
    assert offered_amounts(flexible, balance) == []
    assert offered_amounts(fixed, balance) == []
