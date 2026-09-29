"""Lazy Hubble settlement against a real HubbleClient, HTTP mocked at transport.

README: pending gift cards settle lazily against Hubble
(GET /orders/by-reference/{giftCardId}) whenever gift cards are read:
404 means the mint never happened (settle failed), a terminal order settles
with or without its voucher, PROCESSING stays pending. Spendable balance is
earned ₹ minus the sum of non-failed gifting amounts.

Task status matrix (committed before running):
- 404 -> failed, balance restored
- FAILED / CANCELLED / REVERSED -> failed, balance restored
- PROCESSING -> stays pending, balance still debited
- SUCCESS with a voucher -> settles, voucher fields stored
- SUCCESS with empty vouchers -> 500; pending card stays pending
  (Hubble SUCCESS with no voucher is a contract break; silent settle
  could mark a real minted voucher failed and eat credit)
- unknown status string -> stays pending, does not crash
- place_order times out after upstream success -> next read settles,
  user is not double-charged
"""

from __future__ import annotations

import pytest

from . import constants as K
from .helpers import (
    empty_success_order,
    gifting_docs,
    processing_order,
    seed_reward_catalogue,
    student_profile,
    success_order,
    terminal_failure_order,
)

pytestmark = pytest.mark.asyncio


async def _ambassador_with_tier_one(api, phone: str) -> tuple[str, str]:
    """Enroll a student ambassador and refer exactly enough students to reach
    tier one.

    Args:
        api: the UsersApi test client.
        phone: the ambassador's phone number.
    Returns:
        (user_id, handle).
    Raises:
        None.
    """
    holder = await api.create_user(
        student_profile(phone, name="Ishita", institution_id="school-1")
    )
    user_id = holder["userId"]
    enroll = await api.post(f"/internal/users/{user_id}/ambassador")
    handle = enroll.json()["handle"]
    for index in range(K.TIER_ONE_POINTS):
        await api.create_user(
            student_profile(f"{phone}{index:02d}", name=f"Ref{index}"),
            texts=[f"hi @{handle}"],
        )
    status = await api.get(f"/internal/users/{user_id}/ambassador")
    assert status.json()["points"] == K.TIER_ONE_POINTS
    assert status.json()["earnedInr"] == K.TIER_ONE_REWARD_INR
    assert status.json()["balanceInr"] == K.TIER_ONE_REWARD_INR
    return user_id, handle


async def _mint_pending(api, hubble_double, user_id: str) -> str:
    """Mint ₹50; Hubble place_order returns PROCESSING so the card stays
    pending.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
        user_id: the minting ambassador.
    Returns:
        The minted (pending) card's id.
    Raises:
        None.
    """
    hubble_double.seed_catalogue(seed_reward_catalogue())
    hubble_double.place_order_body = processing_order()
    hubble_double.place_order_mode = "respond"
    redeemed = await api.post(
        f"/internal/users/{user_id}/gift-cards",
        json={"productId": K.AMAZON_PRODUCT_ID, "amountInr": 50},
    )
    assert redeemed.status_code == 200
    card = redeemed.json()
    assert card["status"] == "pending"
    assert card["amountInr"] == 50
    return card["id"]


async def test_settlement_404_fails_the_card_and_restores_balance(
    api, hubble_double
):
    """Hubble 404 on the reference id fails the card and gives the credit back.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, "910000060001")
    card_id = await _mint_pending(api, hubble_double, user_id)
    hubble_double.set_order(card_id, None)  # 404

    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    assert rewards.json()["balanceInr"] == K.TIER_ONE_REWARD_INR
    cards = await _gifting(api, user_id)
    assert len(cards) == 1
    assert cards[0]["status"] == "failed"


async def _gifting(api, user_id: str):
    """Gift-card list on the ambassador admin view; that read also settles
    pending cards.

    Args:
        api: the UsersApi test client.
        user_id: the ambassador whose gift cards to list.
    Returns:
        The gift cards list.
    Raises:
        None.
    """
    detail = await api.get(f"/internal/ambassadors/{user_id}")
    assert detail.status_code == 200
    return detail.json()["giftCards"]


@pytest.mark.parametrize(
    "hubble_status,phone",
    [
        ("FAILED", "910000060111"),
        ("CANCELLED", "910000060112"),
        ("REVERSED", "910000060113"),
    ],
)
async def test_settlement_terminal_failure_fails_the_card_and_restores_balance(
    api, hubble_double, hubble_status, phone
):
    """FAILED, CANCELLED and REVERSED all fail the card and restore the balance.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
        hubble_status: the terminal Hubble status under test.
        phone: the ambassador's phone number for this case.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, phone)
    card_id = await _mint_pending(api, hubble_double, user_id)
    hubble_double.set_order(card_id, terminal_failure_order(hubble_status))

    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    assert rewards.json()["balanceInr"] == K.TIER_ONE_REWARD_INR
    cards = await _gifting(api, user_id)
    assert cards[0]["status"] == "failed"
    assert cards[0]["id"] == card_id


async def test_settlement_processing_stays_pending_and_keeps_balance_debited(
    api, hubble_double
):
    """A PROCESSING order stays pending; the debit is not restored while it
    might still land.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, "910000060002")
    card_id = await _mint_pending(api, hubble_double, user_id)
    hubble_double.set_order(card_id, processing_order())

    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    assert rewards.json()["balanceInr"] == K.TIER_ONE_REWARD_INR - 50
    cards = await _gifting(api, user_id)
    assert cards[0]["status"] == "pending"
    assert cards[0]["id"] == card_id


async def test_settlement_success_with_voucher_stores_voucher_fields(
    api, hubble_double
):
    """SUCCESS with a voucher settles the card and stores its delivery fields.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, "910000060003")
    card_id = await _mint_pending(api, hubble_double, user_id)
    hubble_double.set_order(
        card_id,
        success_order(
            card_number="1234-5678", card_pin="4321", valid_till="2027-12-31"
        ),
    )

    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    assert rewards.json()["balanceInr"] == K.TIER_ONE_REWARD_INR - 50
    cards = await _gifting(api, user_id)
    assert cards[0]["status"] == "succeeded"

    delivery = await api.get(f"/internal/users/{user_id}/gift-cards/{card_id}")
    assert delivery.status_code == 200
    body = delivery.json()
    assert body["status"] == "succeeded"
    assert body["cardNumber"] == "1234-5678"
    assert body["cardPin"] == "4321"
    assert body["validTill"] == "2027-12-31"


async def test_settlement_success_with_empty_vouchers_fails_loud(
    api, hubble_double, db
):
    """Hubble breaking its own contract is a loud 500 on purpose; the debit
    stays pending.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, "910000060004")
    card_id = await _mint_pending(api, hubble_double, user_id)
    hubble_double.set_order(card_id, empty_success_order())

    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 500

    docs = await gifting_docs(db, user_id)
    assert len(docs) == 1
    assert docs[0]["_id"] == card_id
    assert docs[0]["status"] == "pending"


async def test_settlement_unknown_status_stays_pending_and_does_not_crash(
    api, hubble_double
):
    """An order status this code has never seen stays pending instead of
    crashing.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, "910000060005")
    card_id = await _mint_pending(api, hubble_double, user_id)
    hubble_double.set_order(card_id, {"status": "FROBNITZ", "vouchers": []})

    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    assert rewards.json()["balanceInr"] == K.TIER_ONE_REWARD_INR - 50
    cards = await _gifting(api, user_id)
    assert cards[0]["status"] == "pending"


async def _assert_settled_without_second_mint(
    api, hubble_double, user_id, reference_id
) -> None:
    """The timed-out mint settles on the next read and is not minted again.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
        user_id: the ambassador who redeemed.
        reference_id: the referenceId of the single upstream place_order.
    Returns:
        None.
    Raises:
        AssertionError: the card did not settle, or a second mint was issued.
    """
    hubble_double.place_order_mode = "respond"
    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    assert rewards.json()["balanceInr"] == K.TIER_ONE_REWARD_INR - 50
    cards = await _gifting(api, user_id)
    assert len(cards) == 1
    assert cards[0]["id"] == reference_id
    assert cards[0]["status"] == "succeeded"
    # A second mint must not have been issued against a new reference.
    assert len(hubble_double.place_order_calls) == 1
    delivery = await api.get(
        f"/internal/users/{user_id}/gift-cards/{reference_id}"
    )
    assert delivery.status_code == 200
    assert delivery.json()["cardNumber"] == "9999-0000"


async def test_place_order_timeout_after_upstream_success_settles_without_double_charge(
    api, hubble_double
):
    """place_order is not retried; lost responses settle by referenceId on the
    next read.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, "910000060006")
    hubble_double.seed_catalogue(seed_reward_catalogue())
    hubble_double.place_order_body = success_order(
        card_number="9999-0000", card_pin="1111", valid_till="2028-01-01"
    )
    hubble_double.place_order_mode = "timeout"

    redeemed = await api.post(
        f"/internal/users/{user_id}/gift-cards",
        json={"productId": K.AMAZON_PRODUCT_ID, "amountInr": 50},
    )
    # Timeout surfaces as an error on the mint call; the pending reservation
    # must still exist so the next read can settle the upstream SUCCESS.
    assert redeemed.status_code == 500

    assert len(hubble_double.place_order_calls) == 1
    reference_id = hubble_double.place_order_calls[0]["referenceId"]

    await _assert_settled_without_second_mint(
        api, hubble_double, user_id, reference_id
    )


async def test_redeem_rejected_for_non_ambassador(api, hubble_double):
    """A user who is not an ambassador can't redeem, and no order is placed.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    hubble_double.seed_catalogue(seed_reward_catalogue())
    profile = await api.create_user(student_profile("910000060007"))
    response = await api.post(
        f"/internal/users/{profile['userId']}/gift-cards",
        json={"productId": K.AMAZON_PRODUCT_ID, "amountInr": 50},
    )
    assert response.status_code == 404
    assert hubble_double.place_order_calls == []


async def test_redeem_amount_not_offered_is_rejected_without_placing_an_order(
    api, hubble_double
):
    """An amount the storefront doesn't currently offer is rejected before
    Hubble is called.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, _ = await _ambassador_with_tier_one(api, "910000060008")
    hubble_double.seed_catalogue(seed_reward_catalogue())
    hubble_double.place_order_body = processing_order()
    response = await api.post(
        f"/internal/users/{user_id}/gift-cards",
        json={"productId": K.AMAZON_PRODUCT_ID, "amountInr": 999},
    )
    # The route maps an unredeemable amount to 400 by design; the rule is that
    # no mint happens.
    assert response.status_code == 400
    assert hubble_double.place_order_calls == []
