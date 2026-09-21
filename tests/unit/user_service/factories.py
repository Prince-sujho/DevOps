"""Builders for the pure-function unit tests. No I/O.

Expected values in the tests themselves are spec-derived literals; these
helpers only construct typed inputs the functions under test accept.
"""

from __future__ import annotations

from typing import Optional

from infra.attribution import ReferrerAttribution
from infra.clients.users import (
    Ambassador,
    Campaign,
    ChannelActivity,
    DirectoryEntry,
    GiftCard,
    GiftCardStatus,
    Influencer,
    Institution,
    Payout,
    StudentProfile,
    StudentScope,
    TeacherProfile,
    TeacherScope,
    UserActivity,
    UserDirectoryQuery,
    UserProfile,
    UserSort,
)
from infra.curriculum import Grade, Subject
from infra.hubble.types import HubbleAmountRestrictions, HubbleInstructionSet, HubbleProduct

# The README calls this a "frozen commitment in code" but names no numbers
# itself (user_service/README.md: "The tier ladder lives in
# infra.clients.users.AMBASSADOR_TIERS and is a frozen commitment: earned ₹
# derives retroactively from it"; "Ladder for FLEXIBLE products" for
# REWARD_AMOUNTS). Tests must not re-transcribe those numbers as a second,
# independently-maintained copy -- import the real constants instead, so a
# ladder change in code is visible in these values automatically rather than
# needing this file edited in lockstep.
from user_service.app.src.constants import (
    ACTIVE_USER_WINDOW_MS,
    AMBASSADOR_TIERS,
    HANDLE_SUFFIX_ALPHABET,
    HANDLE_SUFFIX_LENGTH,
    RETENTION_WINDOW_MS,
    REWARD_AMOUNTS,
)

AMAZON_PRODUCT_ID = "01GMAVS2CHXR0XP1BZSTA9A44K"

TIER_POINTS = tuple(tier.points for tier in AMBASSADOR_TIERS)
TIER_REWARDS_INR = tuple(tier.rewardInr for tier in AMBASSADOR_TIERS)
TIER_NAMES = tuple(tier.name for tier in AMBASSADOR_TIERS)
# Cumulative lifetime credit once each rung (in order) has been crossed --
# skill prose: each crossed rung's reward is earned once.
EARNED_AT_TIER_INR = tuple(
    sum(TIER_REWARDS_INR[: i + 1]) for i in range(len(TIER_REWARDS_INR))
)

# Flexible-product preset ladder (constants.py: "Ladder for FLEXIBLE products").
FLEXIBLE_LADDER_INR = REWARD_AMOUNTS

HMAC_SECRET = "unit-test-users-user-id-hmac-secret"


def gift_card(
    *,
    amount_inr: int,
    status: GiftCardStatus,
    gift_id: str = "gc-1",
) -> GiftCard:
    return GiftCard(
        id=gift_id,
        productId=AMAZON_PRODUCT_ID,
        brand="Amazon",
        amountInr=amount_inr,
        status=status,
        createdAtMs=1_700_000_000_000,
    )


def hubble_product(
    *,
    status: str = "ACTIVE",
    min_voucher: int = 10,
    max_voucher: int = 5000,
    denominations: Optional[list[int]] = None,
    instructions: Optional[list[str]] = None,
    restrictions: Optional[HubbleAmountRestrictions] = None,
    omit_restrictions: bool = False,
) -> HubbleProduct:
    """Build one Hubble product.

    ``denominations=[]`` (the default) is the flexible path; a non-empty list
    is the fixed-denomination path. Pass ``omit_restrictions=True`` for the
    ``amountRestrictions is None`` case.
    """
    how = []
    if instructions is None:
        how = [HubbleInstructionSet(instructions=["Redeem at the brand's checkout"])]
    elif instructions:
        how = [HubbleInstructionSet(instructions=instructions)]

    if omit_restrictions:
        amount_restrictions = None
    elif restrictions is not None:
        amount_restrictions = restrictions
    else:
        amount_restrictions = HubbleAmountRestrictions(
            minVoucherAmount=min_voucher,
            maxVoucherAmount=max_voucher,
            denominations=[] if denominations is None else denominations,
        )
    return HubbleProduct(
        id=AMAZON_PRODUCT_ID,
        status=status,
        amountRestrictions=amount_restrictions,
        howToUseInstructions=how,
    )


def payout(
    *,
    base_inr: int = 1000,
    per_block_inr: int = 50,
    block_size: int = 5,
    incentive_cap_inr: int = 200,
) -> Payout:
    return Payout(
        baseInr=base_inr,
        perBlockInr=per_block_inr,
        blockSize=block_size,
        incentiveCapInr=incentive_cap_inr,
    )


def campaign(
    campaign_id: str,
    start_ms: int,
    end_ms: int,
    terms: Optional[Payout] = None,
) -> Campaign:
    return Campaign(
        id=campaign_id,
        startMs=start_ms,
        endMs=end_ms,
        payout=terms if terms is not None else payout(),
    )


def influencer(*, handle: str = "coolkid", created_at_ms: int = 1_000) -> Influencer:
    return Influencer(handle=handle, platform="instagram", createdAtMs=created_at_ms)


def ambassador(
    *,
    handle: str = "arjun-x4k9",
    user_id: str = "user-arjun",
    created_at_ms: int = 1_000,
) -> Ambassador:
    return Ambassador(handle=handle, userId=user_id, createdAtMs=created_at_ms)


def student(
    *,
    user_id: str = "user-ada",
    phone: str = "919811111111",
    name: str = "Ada Lovelace",
    grade: Grade = 8,
    subjects: Optional[list[Subject]] = None,
    created_at_ms: int = 1_700_000_000_000,
    referrer_handle: Optional[str] = None,
    last_message_at_ms: Optional[int] = None,
    session_count: int = 0,
) -> StudentProfile:
    activity = UserActivity(
        {
            "whatsapp": ChannelActivity(
                sessionCount=session_count, lastMessageAtMs=last_message_at_ms
            )
        }
    )
    return StudentProfile(
        userId=user_id,
        phone=phone,
        name=name,
        institution=Institution(id="school-1", name="Test School"),
        persona="student",
        createdAtMs=created_at_ms,
        attribution=(
            ReferrerAttribution(handle=referrer_handle) if referrer_handle else None
        ),
        scope=StudentScope(grade=grade, subjects=subjects or []),
        activity=activity,
    )


def teacher(
    *,
    user_id: str = "user-teacher",
    phone: str = "919822222222",
    name: str = "Alan Turing",
    created_at_ms: int = 1_700_000_000_000,
    referrer_handle: Optional[str] = None,
    last_message_at_ms: Optional[int] = None,
    session_count: int = 0,
) -> TeacherProfile:
    activity = UserActivity(
        {
            "whatsapp": ChannelActivity(
                sessionCount=session_count, lastMessageAtMs=last_message_at_ms
            )
        }
    )
    return TeacherProfile(
        userId=user_id,
        phone=phone,
        name=name,
        institution=Institution(id="school-1", name="Test School"),
        persona="teacher",
        createdAtMs=created_at_ms,
        attribution=(
            ReferrerAttribution(handle=referrer_handle) if referrer_handle else None
        ),
        scope=TeacherScope(grades=[8], subjects=[]),
        activity=activity,
    )


def directory_entry(
    profile: UserProfile,
    *,
    activity_state: str = "never",
    blocked: bool = False,
    last_message_at_ms: Optional[int] = None,
    session_count: int = 0,
) -> DirectoryEntry:
    return DirectoryEntry(
        profile=profile,
        activity=ChannelActivity(
            sessionCount=session_count, lastMessageAtMs=last_message_at_ms
        ),
        activityState=activity_state,  # type: ignore[arg-type]
        blocked=blocked,
    )


def directory_query(
    *,
    q: str = "",
    sort: UserSort = "name",
    grade: Optional[list[Grade]] = None,
    subject: Optional[list[Subject]] = None,
    activity: Optional[list[str]] = None,
    attribution: Optional[list[str]] = None,
    blocked: Optional[list[str]] = None,
    persona: str = "student",
) -> UserDirectoryQuery:
    return UserDirectoryQuery(
        persona=persona,  # type: ignore[arg-type]
        q=q,
        limit=20,
        offset=0,
        sort=sort,
        grade=grade or [],
        subject=subject or [],
        activity=activity or [],  # type: ignore[arg-type]
        attribution=attribution or [],  # type: ignore[arg-type]
        blocked=blocked or [],  # type: ignore[arg-type]
    )
