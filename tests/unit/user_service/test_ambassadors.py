"""Pure ambassador tier lookup and handle minting.

Oracle: campus-ambassadors skill (cumulative ladder; each reward earned once),
``_tier_reached`` / ``_next_tier`` docstrings (None before the first rung;
None next-tier once the ladder is complete), ``mint_handle`` docstring
(``arjun-x4k9`` name-flavoured form), and frozen handle-suffix constants.
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from user_service.app.src.ambassadors import (
    _enrolled,
    _next_tier,
    _row,
    _tier_reached,
    derive_detail,
    derive_roster,
    derive_status,
    mint_handle,
)

from .factories import (
    EARNED_AT_TIER_INR,
    HANDLE_SUFFIX_ALPHABET,
    HANDLE_SUFFIX_LENGTH,
    TIER_NAMES,
    TIER_POINTS,
    TIER_REWARDS_INR,
    ambassador,
    gift_card,
    student,
    teacher,
)
from .fakes import FakeGifting, FakeHubble, FakeReferrers, FakeUsers


class ScriptedHandleRegistry:
    """``exists`` reports taken for the first N calls, then free.

    Used to pin collision-retry without talking to Firestore.
    """

    def __init__(self, taken_first_n: int = 0) -> None:
        self.taken_first_n = taken_first_n
        self.calls: list[str] = []

    async def exists(self, handle: str) -> bool:
        self.calls.append(handle)
        return len(self.calls) <= self.taken_first_n


# ---------------------------------------------------------------------------
# _tier_reached / _next_tier
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_tier_reached_below_first_rung_is_none() -> None:
    assert _tier_reached(0) is None
    assert _tier_reached(TIER_POINTS[0] - 1) is None


@pytest.mark.boundary
def test_next_tier_below_first_rung_is_campus_ambassador() -> None:
    """Bound to the real named ladder (AMBASSADOR_TIERS), not a second
    hand-copied tier name/points/reward triple."""
    nxt = _next_tier(TIER_POINTS[0] - 1)
    assert nxt is not None
    assert nxt.name == TIER_NAMES[0]
    assert nxt.points == TIER_POINTS[0]
    assert nxt.rewardInr == TIER_REWARDS_INR[0]


@pytest.mark.boundary
def test_tier_reached_exactly_at_each_rung() -> None:
    for points, name in zip(TIER_POINTS, TIER_NAMES):
        assert _tier_reached(points) == name


@pytest.mark.boundary
def test_next_tier_at_top_rung_is_none() -> None:
    assert _next_tier(TIER_POINTS[-1]) is None
    assert _next_tier(10_000) is None


@pytest.mark.boundary
def test_next_tier_between_rungs() -> None:
    """Standing exactly at one rung, the next tier is the immediately
    following one -- bound to the real ladder, not hand-copied numbers."""
    nxt = _next_tier(TIER_POINTS[1])
    assert nxt is not None
    assert nxt.name == TIER_NAMES[2]
    assert nxt.points == TIER_POINTS[2]
    assert nxt.rewardInr == TIER_REWARDS_INR[2]


@pytest.mark.boundary
def test_negative_points_have_not_reached_a_tier() -> None:
    assert _tier_reached(-1) is None
    nxt = _next_tier(-1)
    assert nxt is not None
    assert nxt.name == TIER_NAMES[0]


@pytest.mark.property
@given(points=st.integers(min_value=-50, max_value=500))
def test_tier_reached_and_next_tier_are_always_consistent(points: int) -> None:
    """You can never be 'at' a tier you have not reached, and next-tier is
    always the immediately following uncrossed rung (or None at the top).
    """
    reached = _tier_reached(points)
    nxt = _next_tier(points)
    if reached is None:
        assert nxt is not None
        assert nxt.name == TIER_NAMES[0]
        assert nxt.points == TIER_POINTS[0]
        assert points < TIER_POINTS[0]
        return
    assert reached in TIER_NAMES
    idx = TIER_NAMES.index(reached)
    assert points >= TIER_POINTS[idx]
    if idx > 0:
        assert points >= TIER_POINTS[idx - 1]
    if idx + 1 < len(TIER_NAMES):
        assert nxt is not None
        assert nxt.name == TIER_NAMES[idx + 1]
        assert nxt.points == TIER_POINTS[idx + 1]
        assert points < TIER_POINTS[idx + 1]
        # The next rung has not been reached.
        assert reached != nxt.name
    else:
        assert nxt is None
        assert points >= TIER_POINTS[-1]


# ---------------------------------------------------------------------------
# mint_handle
# ---------------------------------------------------------------------------


def _split_handle(handle: str) -> tuple[str, str]:
    stem, suffix = handle.rsplit("-", 1)
    return stem, suffix


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_mint_handle_name_with_no_latin_letters_raises() -> None:
    """A Han-script name cannot produce the documented ``arjun-x4k9`` stem."""
    with pytest.raises(ValueError):
        await mint_handle("张伟", ScriptedHandleRegistry())


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_mint_handle_punctuation_only_name_raises() -> None:
    with pytest.raises(ValueError):
        await mint_handle("!!!", ScriptedHandleRegistry())


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_mint_handle_empty_name_raises() -> None:
    with pytest.raises(ValueError):
        await mint_handle("", ScriptedHandleRegistry())


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_mint_handle_strips_leading_and_trailing_whitespace() -> None:
    handle = await mint_handle("  Arjun  ", ScriptedHandleRegistry())
    stem, suffix = _split_handle(handle)
    assert stem == "arjun"
    assert len(suffix) == HANDLE_SUFFIX_LENGTH
    assert all(ch in HANDLE_SUFFIX_ALPHABET for ch in suffix)


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_mint_handle_single_character_first_name() -> None:
    handle = await mint_handle("A", ScriptedHandleRegistry())
    stem, suffix = _split_handle(handle)
    assert stem == "a"
    assert len(suffix) == HANDLE_SUFFIX_LENGTH
    assert all(ch in HANDLE_SUFFIX_ALPHABET for ch in suffix)


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_mint_handle_matches_documented_arjun_form() -> None:
    handle = await mint_handle("Arjun", ScriptedHandleRegistry())
    stem, suffix = _split_handle(handle)
    assert stem == "arjun"
    assert len(suffix) == HANDLE_SUFFIX_LENGTH
    assert all(ch in HANDLE_SUFFIX_ALPHABET for ch in suffix)


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_mint_handle_retries_until_the_registry_reports_a_free_handle() -> None:
    registry = ScriptedHandleRegistry(taken_first_n=3)
    handle = await mint_handle("Arjun", registry)
    assert len(registry.calls) == 4
    assert registry.calls[-1] == handle
    assert handle not in registry.calls[:-1]
    stem, suffix = _split_handle(handle)
    assert stem == "arjun"
    assert all(candidate.startswith("arjun-") for candidate in registry.calls)


@pytest.mark.property
@given(st.sampled_from(["Arjun", "Bina", "Chetna", "Diya", "Esha"]))
@pytest.mark.asyncio
async def test_minted_handle_always_has_a_four_char_alphabet_suffix(name: str) -> None:
    handle = await mint_handle(name, ScriptedHandleRegistry())
    stem, suffix = _split_handle(handle)
    assert stem == name.casefold()
    assert len(suffix) == 4
    assert all(ch in HANDLE_SUFFIX_ALPHABET for ch in suffix)


# ---------------------------------------------------------------------------
# Roster / status / detail (I/O wrappers mutmut found untested)
# README: started = onboarded referrals + abandoned starts; points = onboarded
# count; studentsReferred / teachersReferred split by persona; spendable
# balance is earned ₹ minus non-failed gifting after lazy settlement.
# ---------------------------------------------------------------------------


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_enrolled_raises_when_a_registry_entry_has_no_profile() -> None:
    """Docstring: user deletion cascades the registry; a missing profile is a bug."""
    entry = ambassador(handle="ghost-abcd", user_id="missing-user")
    living = ambassador(handle="arjun-x4k9", user_id="user-arjun")
    users = FakeUsers()
    users.add(student(user_id="user-arjun", name="Arjun"))
    with pytest.raises(ValueError):
        await _enrolled(FakeReferrers(ambassadors=[living, entry]), users)


@pytest.mark.boundary
def test_row_tier_at_first_rung_is_the_first_named_tier() -> None:
    profile = student(user_id="user-arjun", name="Arjun")
    row = _row(ambassador(), profile, points=TIER_POINTS[0], started=TIER_POINTS[0])
    assert row.tier == TIER_NAMES[0]
    assert row.points == TIER_POINTS[0]
    assert row.started == TIER_POINTS[0]
    assert row.handle == "arjun-x4k9"
    assert row.name == "Arjun"


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_roster_started_is_points_plus_abandoned_starts() -> None:
    """README: started counts people who began onboarding with this handle,
    finished or not. Two onboarded + one pending start = started 3, points 2.
    """
    entry = ambassador(handle="arjun-x4k9", user_id="user-arjun")
    users = FakeUsers()
    users.add(student(user_id="user-arjun", name="Arjun"))
    users.counts_by_handle["arjun-x4k9"] = 2
    rows = await derive_roster(
        FakeReferrers(ambassadors=[entry]),
        users,
        starts={"arjun-x4k9": [1_500]},
    )
    assert len(rows) == 1
    assert rows[0].points == 2
    assert rows[0].started == 3
    assert rows[0].tier is None


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_roster_with_no_starts_and_no_onboards_is_zero() -> None:
    entry = ambassador(handle="arjun-x4k9", user_id="user-arjun")
    users = FakeUsers()
    users.add(student(user_id="user-arjun", name="Arjun"))
    users.counts_by_handle["arjun-x4k9"] = 0
    rows = await derive_roster(FakeReferrers(ambassadors=[entry]), users, starts={})
    assert rows[0].points == 0
    assert rows[0].started == 0
    assert rows[0].tier is None


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_status_splits_student_and_teacher_referrals_and_computes_points_to_next() -> None:
    """Referrals up to the first tier's threshold (4 students + 1 teacher)
    unlock the first named tier. Next rung is the second; pointsToNextTier is
    its threshold minus the first's. Link is origin + /go/{handle}. One
    succeeded card leaves (earned - spend) spendable. Bound to the real
    ladder, not hand-copied numbers.
    """
    entry = ambassador(handle="arjun-x4k9", user_id="user-arjun")
    first_tier_points = TIER_POINTS[0]
    spend = 50
    users = FakeUsers()
    users.referred_by_handle["arjun-x4k9"] = [
        student(
            user_id=f"s{i}",
            name=f"S{i}",
            phone=f"91980000000{i}",
            referrer_handle="arjun-x4k9",
        )
        for i in range(first_tier_points - 1)
    ] + [
        teacher(
            user_id="t1",
            name="T1",
            phone="919800000999",
            referrer_handle="arjun-x4k9",
        )
    ]
    gifting = FakeGifting()
    gifting.seed("user-arjun", gift_card(amount_inr=spend, status="succeeded"))
    status = await derive_status(
        entry, users, gifting, FakeHubble(), "https://sujho.example"
    )
    assert users.by_referrer_calls == ["arjun-x4k9"]
    assert gifting.list_calls == ["user-arjun"]
    assert status.handle == "arjun-x4k9"
    assert status.link == "https://sujho.example/go/arjun-x4k9"
    assert status.points == first_tier_points
    assert status.studentsReferred == first_tier_points - 1
    assert status.teachersReferred == 1
    assert status.tier == TIER_NAMES[0]
    assert status.nextTier is not None
    assert status.nextTier.name == TIER_NAMES[1]
    assert status.nextTier.points == TIER_POINTS[1]
    assert status.pointsToNextTier == TIER_POINTS[1] - first_tier_points
    assert status.earnedInr == EARNED_AT_TIER_INR[0]
    assert status.balanceInr == EARNED_AT_TIER_INR[0] - spend


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_status_below_first_rung_has_no_tier_and_points_to_ambassador() -> None:
    """Zero referrals: tier is None, next is the first named tier, that many
    points away."""
    entry = ambassador(handle="arjun-x4k9", user_id="user-arjun")
    users = FakeUsers()
    users.referred_by_handle["arjun-x4k9"] = []
    status = await derive_status(
        entry, users, FakeGifting(), FakeHubble(), "https://sujho.example"
    )
    assert status.points == 0
    assert status.studentsReferred == 0
    assert status.teachersReferred == 0
    assert status.tier is None
    assert status.nextTier is not None
    assert status.nextTier.name == TIER_NAMES[0]
    assert status.nextTier.points == TIER_POINTS[0]
    assert status.pointsToNextTier == TIER_POINTS[0]
    assert status.earnedInr == 0
    assert status.balanceInr == 0


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_status_settles_a_pending_mint_before_reporting_balance() -> None:
    """Docstring: reading gift cards settles any pending mint, so the balance
    is always live. Enough referrals to cross the first tier; a pending card
    whose Hubble order 404s must restore the debit -> spendable == earned,
    not earned-minus-pending. Bound to the real ladder.
    """
    entry = ambassador(handle="arjun-x4k9", user_id="user-arjun")
    first_tier_points = TIER_POINTS[0]
    users = FakeUsers()
    users.referred_by_handle["arjun-x4k9"] = [
        student(
            user_id=f"s{i}",
            name=f"S{i}",
            phone=f"91980000000{i}",
            referrer_handle="arjun-x4k9",
        )
        for i in range(first_tier_points)
    ]
    gifting = FakeGifting()
    gifting.seed("user-arjun", gift_card(amount_inr=50, status="pending", gift_id="gc-stale"))
    hubble = FakeHubble()
    status = await derive_status(
        entry, users, gifting, hubble, "https://sujho.example"
    )
    assert status.earnedInr == EARNED_AT_TIER_INR[0]
    assert status.balanceInr == EARNED_AT_TIER_INR[0]
    assert gifting.fail_calls == [("user-arjun", "gc-stale")]
    assert hubble.get_order_calls == ["gc-stale"]


@pytest.mark.boundary
def test_detail_started_is_referred_plus_pending_starts() -> None:
    entry = ambassador()
    profile = student(user_id="user-arjun", name="Arjun")
    referred = [
        student(user_id="s1", name="S1", phone="919800000001", referrer_handle="arjun-x4k9"),
        student(user_id="s2", name="S2", phone="919800000002", referrer_handle="arjun-x4k9"),
    ]
    cards = [gift_card(amount_inr=50, status="succeeded")]
    detail = derive_detail(entry, profile, referred, cards, pending_starts=[1_111])
    assert detail.row.points == 2
    assert detail.row.started == 3
    assert detail.row.tier is None
    assert detail.earnedInr == 0
    assert detail.balanceInr == -50
    assert detail.giftCards == cards
    assert [row.userId for row in detail.referrals] == ["s1", "s2"]
