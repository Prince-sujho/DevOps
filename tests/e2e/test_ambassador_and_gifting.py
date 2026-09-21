"""Journeys 16 and 17 — ambassador attribution and gift-card redemption."""

from __future__ import annotations

import pytest

from infra.hubble.types import (
    HubbleAmountRestrictions,
    HubbleInstructionSet,
    HubbleOrder,
    HubbleProduct,
    HubbleVoucher,
)

from . import constants as K
from . import payloads
from .conftest import derive_user_id, pending_action
from .scripting import create_user, student_profile_input, turn
from .servers import settle, wait_until

pytestmark = pytest.mark.asyncio


def _catalogue(active_product_id: str, *, denomination: int) -> dict[str, HubbleProduct]:
    """One offerable product with exactly one fixed denomination; every other
    reward SKU is inactive. `denomination` is bound by the caller to the real
    ladder (K.TIER_ONE_REWARD_INR), not a magic number picked to happen to
    match it."""
    catalogue: dict[str, HubbleProduct] = {}
    for product_id in K.ALL_REWARD_PRODUCT_IDS:
        if product_id == active_product_id:
            catalogue[product_id] = HubbleProduct(
                id=product_id,
                status="ACTIVE",
                amountRestrictions=HubbleAmountRestrictions(
                    minVoucherAmount=min(50, denomination),
                    maxVoucherAmount=max(1000, denomination),
                    denominations=[denomination],
                ),
                howToUseInstructions=[
                    HubbleInstructionSet(instructions=["Open the app", "Enter the code"])
                ],
            )
        else:
            catalogue[product_id] = HubbleProduct(id=product_id, status="INACTIVE")
    return catalogue


# --------------------------------------------------------------------------
# Journey 16
# --------------------------------------------------------------------------


async def test_ambassador_enrollment_counts_a_referred_student(
    adapter, whatsapp, openai, db, users_api
):
    """A new user onboarding with @handle increments that ambassador's student count."""
    ambassador_phone = "919600000016"
    ambassador_id = derive_user_id(ambassador_phone)
    await create_user(
        users_api, student_profile_input(phone=ambassador_phone, name="Arjun")
    )

    enrolled = await users_api.post(f"/internal/users/{ambassador_id}/ambassador")
    assert enrolled.status_code == 200
    status = enrolled.json()
    handle = status["handle"]
    assert handle.startswith("arjun-")
    assert len(handle) == len("arjun-") + 4
    assert status["link"] == f"{K.PUBLIC_ORIGIN}/go/{handle}"
    assert status["points"] == 0
    assert status["studentsReferred"] == 0
    assert status["teachersReferred"] == 0
    assert status["tier"] is None
    assert status["nextTier"] == {
        "name": K.TIER_ONE_NAME,
        "points": K.TIER_ONE_POINTS,
        "rewardInr": K.TIER_ONE_REWARD_INR,
    }
    assert status["pointsToNextTier"] == K.TIER_ONE_POINTS
    assert status["earnedInr"] == 0
    assert status["balanceInr"] == 0

    # --- a brand new sender onboards, mentioning the ambassador ---
    referred_phone = "919600000116"
    sender_id = "bsuid-j16"
    name = "Neha"
    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j16.a",
            sender_id=sender_id,
            sender_phone=referred_phone,
            body=f"hi, @{handle} told me about you",
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)

    response = await adapter.post_webhook(
        payloads.button_reply_webhook(
            message_id="wamid.j16.b",
            sender_id=sender_id,
            sender_phone=referred_phone,
            reply_id=K.PERSONA_STUDENT_BUTTON_ID,
            title=K.PERSONA_STUDENT_BUTTON_TITLE,
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 2)

    openai.push(turn(response_id="resp-j16"))
    response = await adapter.post_webhook(
        payloads.flow_completion_webhook(
            message_id="wamid.j16.done",
            sender_id=sender_id,
            sender_phone=referred_phone,
            response_json=payloads.student_onboarding_completion(),
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(openai.calls) >= 1)
    await settle()

    assert await pending_action(db, sender_id) is None
    referred_id = derive_user_id(referred_phone)
    referred_doc = await db.collection(K.USERS_COLLECTION).document(referred_id).get()
    assert referred_doc.exists is True
    assert referred_doc.to_dict()["attribution"] == {"kind": "referrer", "handle": handle}

    after = await users_api.get(f"/internal/users/{ambassador_id}/ambassador")
    assert after.status_code == 200
    updated = after.json()
    # points are one per attributed referral (user_service/app/src/ambassadors.py)
    assert updated["studentsReferred"] == 1
    assert updated["teachersReferred"] == 0
    assert updated["points"] == 1
    assert updated["pointsToNextTier"] == K.TIER_ONE_POINTS - 1
    assert updated["tier"] is None
    assert updated["earnedInr"] == 0
    assert updated["balanceInr"] == 0


# --------------------------------------------------------------------------
# Journey 17
# --------------------------------------------------------------------------


async def test_gift_card_redeem_settles_and_debits_balance(db, users_api, hubble):
    """A pending mint settles to succeeded and debits exactly the redeemed amount."""
    ambassador_phone = "919600000017"
    ambassador_id = derive_user_id(ambassador_phone)
    await create_user(
        users_api, student_profile_input(phone=ambassador_phone, name="Ishita")
    )
    enrolled = await users_api.post(f"/internal/users/{ambassador_id}/ambassador")
    assert enrolled.status_code == 200
    handle = enrolled.json()["handle"]

    # Five attributed referrals cross tier one: ₹100 lifetime credit.
    for index in range(K.TIER_ONE_POINTS):
        await create_user(
            users_api,
            student_profile_input(
                phone=f"9196001700{index:02d}", name=f"Referred {index}"
            ),
            texts=[f"hello @{handle}"],
        )

    status = (await users_api.get(f"/internal/users/{ambassador_id}/ambassador")).json()
    assert status["points"] == K.TIER_ONE_POINTS
    assert status["tier"] == K.TIER_ONE_NAME
    assert status["earnedInr"] == K.TIER_ONE_REWARD_INR
    assert status["balanceInr"] == K.TIER_ONE_REWARD_INR

    redeem_amount = K.TIER_ONE_REWARD_INR
    hubble.products = _catalogue(K.AMAZON_PRODUCT_ID, denomination=redeem_amount)
    hubble.place_order_result = HubbleOrder(status="PROCESSING", vouchers=[])

    rewards = (await users_api.get(f"/internal/users/{ambassador_id}/rewards")).json()
    assert rewards["balanceInr"] == K.TIER_ONE_REWARD_INR
    assert rewards["options"] == [
        {
            "productId": K.AMAZON_PRODUCT_ID,
            "brand": K.AMAZON_BRAND,
            "amountsInr": [redeem_amount],
        }
    ]

    redeemed = await users_api.post(
        f"/internal/users/{ambassador_id}/gift-cards",
        json={"productId": K.AMAZON_PRODUCT_ID, "amountInr": redeem_amount},
    )
    assert redeemed.status_code == 200
    card = redeemed.json()
    assert card["status"] == "pending"
    assert card["productId"] == K.AMAZON_PRODUCT_ID
    assert card["brand"] == K.AMAZON_BRAND
    assert card["amountInr"] == redeem_amount

    gifting_ids = [
        doc.id
        async for doc in db.collection(K.USERS_COLLECTION)
        .document(ambassador_id)
        .collection(K.GIFTING_SUBCOLLECTION)
        .stream()
    ]
    assert gifting_ids == [card["id"]]
    assert hubble.method_calls("place_order")[0].args == {
        "product_id": K.AMAZON_PRODUCT_ID,
        "reference_id": card["id"],
        "amount_inr": redeem_amount,
    }

    # From this point Hubble reports the order settled.
    hubble.order_reads[card["id"]] = [
        HubbleOrder(
            status="SUCCESS",
            vouchers=[
                HubbleVoucher(
                    cardNumber="1234-5678", cardPin="9999", validTill="2027-12-31"
                )
            ],
        )
    ]

    # From this point Hubble reports the order settled. The delivery path
    # (whatsapp_adapter ReplyDelivery) GETs this card id directly — it does
    # not read /rewards first — so settlement must happen on this read.
    delivered = await users_api.get(
        f"/internal/users/{ambassador_id}/gift-cards/{card['id']}"
    )
    assert delivered.status_code == 200
    body = delivered.json()
    assert body["status"] == "succeeded"
    assert body["cardNumber"] == "1234-5678"
    assert body["cardPin"] == "9999"
    assert body["validTill"] == "2027-12-31"
    assert body["instructions"] == "Open the app\nEnter the code"

    after = (await users_api.get(f"/internal/users/{ambassador_id}/rewards")).json()
    assert after["balanceInr"] == 0
