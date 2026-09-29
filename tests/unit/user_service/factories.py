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
from infra.hubble.types import (
    HubbleAmountRestrictions,
    HubbleInstructionSet,
    HubbleProduct,
)

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
    *, amount_inr: int, status: GiftCardStatus, gift_id: str = "gc-1"
) -> GiftCard:
    """Build one gift card for the fixed Amazon test product.

    Args:
        amount_inr: the card's amount, in INR.
        status: the card's status.
        gift_id: the card's id.
    Returns:
        The GiftCard.
    Raises:
        None.
    """
    return GiftCard(
        id=gift_id,
        productId=AMAZON_PRODUCT_ID,
        brand="Amazon",
        amountInr=amount_inr,
        status=status,
        createdAtMs=1_700_000_000_000,
    )


def _how_to_use(instructions: Optional[list[str]]) -> list:
    """Redemption instructions for a Hubble product.

    Args:
        instructions: redemption instructions, or None for the default.
    Returns:
        A one-item how-to list, or [] when instructions is empty.
    Raises:
        None.
    """
    if instructions is None:
        return [
            HubbleInstructionSet(
                instructions=["Redeem at the brand's checkout"]
            )
        ]
    if instructions:
        return [HubbleInstructionSet(instructions=instructions)]
    return []


def _amount_restrictions(
    omit_restrictions: bool,
    restrictions: Optional[HubbleAmountRestrictions],
    min_voucher: int,
    max_voucher: int,
    denominations: Optional[list[int]],
) -> Optional[HubbleAmountRestrictions]:
    """Amount restrictions for a Hubble product, or None when omitted.

    Args:
        omit_restrictions: True to set amountRestrictions to None entirely.
        restrictions: explicit amountRestrictions to use instead of building
            one.
        min_voucher: the minimum voucher amount, if restrictions apply.
        max_voucher: the maximum voucher amount, if restrictions apply.
        denominations: fixed denominations, or None for the flexible path.
    Returns:
        The amount restrictions, or None.
    Raises:
        None.
    """
    if omit_restrictions:
        return None
    if restrictions is not None:
        return restrictions
    return HubbleAmountRestrictions(
        minVoucherAmount=min_voucher,
        maxVoucherAmount=max_voucher,
        denominations=[] if denominations is None else denominations,
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

    ``denominations=[]`` (the default) is the flexible path; a non-empty list is
    the fixed-denomination path. Pass ``omit_restrictions=True`` for the
    ``amountRestrictions is None`` case.

    Args:
        status: the product's Hubble status.
        min_voucher: the minimum voucher amount, if restrictions apply.
        max_voucher: the maximum voucher amount, if restrictions apply.
        denominations: fixed denominations, or None/[] for the flexible path.
        instructions: redemption instructions, or None for the default.
        restrictions: explicit amountRestrictions to use instead of building
            one.
        omit_restrictions: True to set amountRestrictions to None entirely.
    Returns:
        The HubbleProduct.
    Raises:
        None.
    """
    how = _how_to_use(instructions)
    amount_restrictions = _amount_restrictions(
        omit_restrictions, restrictions, min_voucher, max_voucher, denominations
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
    """Build one flat + per-block payout structure, capped at incentive_cap_inr.

    Args:
        base_inr: the flat base payout.
        per_block_inr: the per-block incremental payout.
        block_size: how many referrals make one block.
        incentive_cap_inr: the maximum total payout.
    Returns:
        The Payout.
    Raises:
        None.
    """
    return Payout(
        baseInr=base_inr,
        perBlockInr=per_block_inr,
        blockSize=block_size,
        incentiveCapInr=incentive_cap_inr,
    )


def campaign(
    campaign_id: str, start_ms: int, end_ms: int, terms: Optional[Payout] = None
) -> Campaign:
    """Build one campaign, defaulting to the standard payout terms.

    Args:
        campaign_id: the campaign's id.
        start_ms: the campaign's start time, epoch ms.
        end_ms: the campaign's end time, epoch ms.
        terms: the payout terms, or None for the default.
    Returns:
        The Campaign.
    Raises:
        None.
    """
    return Campaign(
        id=campaign_id,
        startMs=start_ms,
        endMs=end_ms,
        payout=terms if terms is not None else payout(),
    )


def influencer(
    *, handle: str = "coolkid", created_at_ms: int = 1_000
) -> Influencer:
    """Build one influencer with a fixed platform.

    Args:
        handle: the influencer's handle.
        created_at_ms: the influencer's creation time, epoch ms.
    Returns:
        The Influencer.
    Raises:
        None.
    """
    return Influencer(
        handle=handle, platform="instagram", createdAtMs=created_at_ms
    )


def ambassador(
    *,
    handle: str = "arjun-x4k9",
    user_id: str = "user-arjun",
    created_at_ms: int = 1_000,
) -> Ambassador:
    """Build one ambassador handle/user pair.

    Args:
        handle: the ambassador's handle.
        user_id: the underlying user's id.
        created_at_ms: the ambassador's creation time, epoch ms.
    Returns:
        The Ambassador.
    Raises:
        None.
    """
    return Ambassador(handle=handle, userId=user_id, createdAtMs=created_at_ms)


def _whatsapp_activity(
    session_count: int, last_message_at_ms: Optional[int]
) -> UserActivity:
    """A single-channel whatsapp activity record.

    Args:
        session_count: the whatsapp session count.
        last_message_at_ms: the last whatsapp message time, or None.
    Returns:
        The UserActivity.
    Raises:
        None.
    """
    return UserActivity(
        {
            "whatsapp": ChannelActivity(
                sessionCount=session_count, lastMessageAtMs=last_message_at_ms
            )
        }
    )


def _student_profile(
    user_id: str,
    phone: str,
    name: str,
    grade: Grade,
    subjects: Optional[list[Subject]],
    created_at_ms: int,
    referrer_handle: Optional[str],
    activity: UserActivity,
) -> StudentProfile:
    """Assemble a student profile around the shared test institution.

    Args:
        user_id: the profile's user id.
        phone: the student's phone number.
        name: the student's name.
        grade: the student's grade.
        subjects: enrolled subjects, or None for none.
        created_at_ms: the profile's creation time, epoch ms.
        referrer_handle: the attributed referrer handle, or None.
        activity: the profile's channel activity.
    Returns:
        The StudentProfile.
    Raises:
        None.
    """
    return StudentProfile(
        userId=user_id,
        phone=phone,
        name=name,
        institution=Institution(id="school-1", name="Test School"),
        persona="student",
        createdAtMs=created_at_ms,
        attribution=(
            ReferrerAttribution(handle=referrer_handle)
            if referrer_handle
            else None
        ),
        scope=StudentScope(grade=grade, subjects=subjects or []),
        activity=activity,
    )


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
    """Build one student profile with a single-channel whatsapp activity record.

    Args:
        user_id: the profile's user id.
        phone: the student's phone number.
        name: the student's name.
        grade: the student's grade.
        subjects: enrolled subjects, or None for the default.
        created_at_ms: the profile's creation time, epoch ms.
        referrer_handle: the attributed referrer handle, or None.
        last_message_at_ms: the last whatsapp message time, or None.
        session_count: the whatsapp session count.
    Returns:
        The StudentProfile.
    Raises:
        None.
    """
    activity = _whatsapp_activity(session_count, last_message_at_ms)
    return _student_profile(
        user_id,
        phone,
        name,
        grade,
        subjects,
        created_at_ms,
        referrer_handle,
        activity,
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
    """Build one teacher profile with a single-channel whatsapp activity record.

    Args:
        user_id: the profile's user id.
        phone: the teacher's phone number.
        name: the teacher's name.
        created_at_ms: the profile's creation time, epoch ms.
        referrer_handle: the attributed referrer handle, or None.
        last_message_at_ms: the last whatsapp message time, or None.
        session_count: the whatsapp session count.
    Returns:
        The TeacherProfile.
    Raises:
        None.
    """
    activity = _whatsapp_activity(session_count, last_message_at_ms)
    return TeacherProfile(
        userId=user_id,
        phone=phone,
        name=name,
        institution=Institution(id="school-1", name="Test School"),
        persona="teacher",
        createdAtMs=created_at_ms,
        attribution=(
            ReferrerAttribution(handle=referrer_handle)
            if referrer_handle
            else None
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
    """Build one directory listing row wrapping an existing profile.

    Args:
        profile: the profile this row lists.
        activity_state: the row's activity-state label.
        blocked: whether the profile is blocked.
        last_message_at_ms: the last whatsapp message time, or None.
        session_count: the whatsapp session count.
    Returns:
        The DirectoryEntry.
    Raises:
        None.
    """
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
    """Build one directory search query, defaulting to an unfiltered student
    search.

    Args:
        q: the free-text search string.
        sort: the sort field.
        grade: grade filter, or None.
        subject: subject filter, or None.
        activity: activity-state filter, or None.
        attribution: attribution filter, or None.
        blocked: blocked-state filter, or None.
        persona: the persona to search within.
    Returns:
        The UserDirectoryQuery.
    Raises:
        None.
    """
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
