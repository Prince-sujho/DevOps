"""Reward storefront (GET rewards), redemption, and gift-card delivery reads."""

from __future__ import annotations

import pytest

from infra.hubble.types import (
    HubbleAmountRestrictions,
    HubbleInstructionSet,
    HubbleOrder,
    HubbleProduct,
    HubbleVoucher,
)

# The README calls the tier ladder and reward catalogue "a frozen commitment
# in code" but names no numbers itself -- import the real constants instead
# of re-transcribing a second, independently-maintained copy of the ladder
# (see tests/MIRRORED_AND_WRONG.md).
from user_service.app.src.constants import AMBASSADOR_TIERS, REWARD_AMOUNTS, REWARD_PRODUCTS

from .conftest import create_user_body, student_profile_input

pytestmark = pytest.mark.asyncio

AMAZON_PRODUCT_ID = "01GMAVS2CHXR0XP1BZSTA9A44K"

ALL_REWARD_PRODUCT_IDS = list(REWARD_PRODUCTS)
FIRST_TIER_POINTS = AMBASSADOR_TIERS[0].points
FIRST_TIER_REWARD_INR = AMBASSADOR_TIERS[0].rewardInr


def _seed_catalogue(fakes, active_product_id: str = AMAZON_PRODUCT_ID) -> None:
    """Seed every REWARD_PRODUCTS id; only `active_product_id` is offerable."""
    for product_id in ALL_REWARD_PRODUCT_IDS:
        if product_id == active_product_id:
            fakes.hubble.products[product_id] = HubbleProduct(
                id=product_id,
                status="ACTIVE",
                amountRestrictions=HubbleAmountRestrictions(
                    minVoucherAmount=10, maxVoucherAmount=5000, denominations=[]
                ),
                howToUseInstructions=[HubbleInstructionSet(instructions=["Redeem at amazon.in"])],
            )
        else:
            fakes.hubble.products[product_id] = HubbleProduct(
                id=product_id, status="INACTIVE", amountRestrictions=None, howToUseInstructions=[]
            )


async def _enrolled_ambassador_with_points(client, auth_headers, fakes, phone: str, points: int):
    """Create+enroll one ambassador, then seed `points` referred users under its handle."""
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input(phone, name="Holder", institution_id="school-1")),
    )
    user_id = create.json()["userId"]
    enroll = await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    handle = enroll.json()["handle"]
    for i in range(points):
        fakes.users.seed(
            {
                "userId": f"referred-{phone}-{i}",
                "phone": f"91888800{i:04d}",
                "name": f"Referred {i}",
                "institution": {"id": None, "name": "Some School"},
                "persona": "student",
                "createdAtMs": 1_700_000_000_000,
                "location": None,
                "attribution": {"kind": "referrer", "handle": handle},
                "scope": {"grade": 7, "subjects": []},
                "activity": {},
            }
        )
    return user_id, handle


async def test_rewards_balance_and_options_for_ambassador_at_tier_one(client, auth_headers, fakes):
    """Bound to the real named ladder (AMBASSADOR_TIERS / REWARD_AMOUNTS), not
    a second hand-copied ₹ / points pair."""
    _seed_catalogue(fakes)
    user_id, _ = await _enrolled_ambassador_with_points(
        client, auth_headers, fakes, "919999966001", points=FIRST_TIER_POINTS
    )
    response = await client.get(f"/internal/users/{user_id}/rewards", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["balanceInr"] == FIRST_TIER_REWARD_INR
    expected_amounts = sorted(a for a in REWARD_AMOUNTS if a <= FIRST_TIER_REWARD_INR)
    assert body["options"] == [
        {"productId": AMAZON_PRODUCT_ID, "brand": "Amazon", "amountsInr": expected_amounts}
    ]


async def test_rewards_404_for_non_ambassador_user(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999966002"))
    )
    user_id = create.json()["userId"]
    response = await client.get(f"/internal/users/{user_id}/rewards", headers=auth_headers)
    assert response.status_code == 404


async def test_redeem_gift_card_success_shape(client, auth_headers, fakes):
    _seed_catalogue(fakes)
    user_id, _ = await _enrolled_ambassador_with_points(
        client, auth_headers, fakes, "919999966003", points=FIRST_TIER_POINTS
    )
    redeem_amount = min(a for a in REWARD_AMOUNTS if a <= FIRST_TIER_REWARD_INR)
    fakes.hubble.place_order_result = HubbleOrder(
        status="SUCCESS",
        vouchers=[HubbleVoucher(cardNumber="4111-1111", cardPin="9999", validTill="2027-01-01")],
    )
    response = await client.post(
        f"/internal/users/{user_id}/gift-cards",
        headers=auth_headers,
        json={"productId": AMAZON_PRODUCT_ID, "amountInr": redeem_amount},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["productId"] == AMAZON_PRODUCT_ID
    assert body["brand"] == "Amazon"
    assert body["amountInr"] == redeem_amount
    assert body["status"] == "succeeded"

    delivery = await client.get(
        f"/internal/users/{user_id}/gift-cards/{body['id']}", headers=auth_headers
    )
    assert delivery.status_code == 200
    assert delivery.json()["cardNumber"] == "4111-1111"
    assert delivery.json()["instructions"] == "Redeem at amazon.in"


async def test_redeem_gift_card_amount_not_in_live_storefront_is_rejected(client, auth_headers, fakes):
    """README: refuses an amount not currently offered by the live storefront.

    Committing to 422 before running per the task brief's explicit
    recommendation for this ambiguous case (no exact code documented).
    """
    _seed_catalogue(fakes)
    user_id, _ = await _enrolled_ambassador_with_points(
        client, auth_headers, fakes, "919999966004", points=FIRST_TIER_POINTS
    )
    unoffered_amount = FIRST_TIER_REWARD_INR + max(REWARD_AMOUNTS) + 1
    response = await client.post(
        f"/internal/users/{user_id}/gift-cards",
        headers=auth_headers,
        json={"productId": AMAZON_PRODUCT_ID, "amountInr": unoffered_amount},
    )
    assert response.status_code == 422, (
        f"expected 422 for an unredeemable amount; got {response.status_code}: {response.text}"
    )
    assert len(fakes.hubble.place_order_calls) == 0, "an unredeemable amount must never place a Hubble order"


async def test_redeem_gift_card_404_for_non_ambassador_user(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999966005"))
    )
    user_id = create.json()["userId"]
    response = await client.post(
        f"/internal/users/{user_id}/gift-cards",
        headers=auth_headers,
        json={"productId": AMAZON_PRODUCT_ID, "amountInr": 50},
    )
    assert response.status_code == 404


async def test_redeem_gift_card_422_missing_field(client, auth_headers, fakes):
    _seed_catalogue(fakes)
    user_id, _ = await _enrolled_ambassador_with_points(client, auth_headers, fakes, "919999966006", points=5)
    response = await client.post(
        f"/internal/users/{user_id}/gift-cards", headers=auth_headers, json={"productId": AMAZON_PRODUCT_ID}
    )
    assert response.status_code == 422


async def test_get_gift_card_404_for_unknown_gift_card_id(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999966007"))
    )
    user_id = create.json()["userId"]
    response = await client.get(
        f"/internal/users/{user_id}/gift-cards/no-such-card", headers=auth_headers
    )
    assert response.status_code == 404
