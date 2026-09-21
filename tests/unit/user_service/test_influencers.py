"""Pure influencer campaign windowing, spend, and report bucketing.

Oracle: user_service README (inclusive campaign windows; events in no window
land in miscellaneous; onboards are referred users and also count as started;
abandoned starts bucket at the mentioning timestamp; spend is derived from
payout terms) and function docstrings (base fee plus a capped, stepwise
per-block incentive on completed onboard blocks).
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, strategies as st

from infra.clients.users import FunnelStats, Payout
from user_service.app.src.influencers import (
    _assemble_report,
    _campaign_for,
    _campaign_spend,
    derive_influencer_report,
)

from .factories import (
    RETENTION_WINDOW_MS,
    campaign,
    influencer,
    payout,
    student,
)
from .fakes import FakeCampaigns, FakeClicks


def _terms(
    *,
    base: int = 1000,
    per_block: int = 50,
    block_size: int = 5,
    cap: int = 200,
) -> Payout:
    return payout(
        base_inr=base,
        per_block_inr=per_block,
        block_size=block_size,
        incentive_cap_inr=cap,
    )


# ---------------------------------------------------------------------------
# _campaign_for
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_campaign_for_start_ms_is_inclusive() -> None:
    window = campaign("c1", 1_000, 2_000)
    assert _campaign_for([window], 1_000) is window


@pytest.mark.boundary
def test_campaign_for_end_ms_is_inclusive() -> None:
    window = campaign("c1", 1_000, 2_000)
    assert _campaign_for([window], 2_000) is window


@pytest.mark.boundary
def test_campaign_for_one_ms_before_start_is_none() -> None:
    window = campaign("c1", 1_000, 2_000)
    assert _campaign_for([window], 999) is None


@pytest.mark.boundary
def test_campaign_for_one_ms_after_end_is_none() -> None:
    window = campaign("c1", 1_000, 2_000)
    assert _campaign_for([window], 2_001) is None


@pytest.mark.boundary
def test_campaign_for_gap_between_two_campaigns_is_none() -> None:
    """README: events whose timestamp falls in no campaign window land in misc."""
    first = campaign("a", 1_000, 2_000)
    second = campaign("b", 3_000, 4_000)
    assert _campaign_for([first, second], 2_500) is None
    assert _campaign_for([first, second], 2_001) is None
    assert _campaign_for([first, second], 2_999) is None


@pytest.mark.boundary
def test_campaign_for_empty_campaign_list_is_none() -> None:
    assert _campaign_for([], 1_500) is None


@pytest.mark.property
@given(
    start=st.integers(min_value=0, max_value=10_000_000),
    width=st.integers(min_value=0, max_value=10_000_000),
)
def test_campaign_window_contains_exactly_its_closed_interval(start: int, width: int) -> None:
    end = start + width
    window = campaign("w", start, end)
    assert _campaign_for([window], start) is window
    assert _campaign_for([window], end) is window
    if start > 0:
        assert _campaign_for([window], start - 1) is None
    assert _campaign_for([window], end + 1) is None


# ---------------------------------------------------------------------------
# _campaign_spend
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_campaign_spend_zero_onboards_is_the_base_fee() -> None:
    assert _campaign_spend(_terms(), 0) == 1000


@pytest.mark.boundary
def test_campaign_spend_partial_block_earns_nothing_beyond_base() -> None:
    """blockSize=5, onboards=4: zero completed blocks."""
    assert _campaign_spend(_terms(block_size=5), 4) == 1000


@pytest.mark.boundary
def test_campaign_spend_exactly_one_block() -> None:
    """Five onboards complete one ₹50 block: 1000 + 50."""
    assert _campaign_spend(_terms(block_size=5, per_block=50), 5) == 1050


@pytest.mark.boundary
def test_campaign_spend_incentive_is_capped() -> None:
    """40 onboards / blockSize 5 = 8 blocks × ₹50 = ₹400, capped at ₹200.
    Spend is base 1000 + cap 200 = 1200, not 1400.
    """
    assert _campaign_spend(_terms(per_block=50, block_size=5, cap=200), 40) == 1200


@pytest.mark.boundary
def test_campaign_spend_block_size_of_one() -> None:
    """Every onboard is a completed block. 3 onboards × ₹10 = ₹30 + base ₹100."""
    assert _campaign_spend(_terms(base=100, per_block=10, block_size=1, cap=1000), 3) == 130


@pytest.mark.boundary
def test_campaign_spend_block_size_one_still_respects_the_cap() -> None:
    assert _campaign_spend(_terms(base=5, per_block=10, block_size=1, cap=50), 20) == 55


@pytest.mark.boundary
def test_campaign_spend_negative_onboards_does_not_pay_below_base() -> None:
    """Spec does not allow negative onboards. No completed block has been
    earned, so spend is the base fee — never a deduction from it.
    """
    assert _campaign_spend(_terms(base=1000, per_block=50, block_size=5, cap=200), -1) == 1000


@pytest.mark.property
@given(
    base=st.integers(min_value=0, max_value=10_000),
    per_block=st.integers(min_value=0, max_value=5_000),
    block_size=st.integers(min_value=1, max_value=50),
    cap=st.integers(min_value=0, max_value=10_000),
    onboards=st.integers(min_value=0, max_value=500),
)
def test_spend_never_below_base_and_never_above_base_plus_cap(
    base: int, per_block: int, block_size: int, cap: int, onboards: int
) -> None:
    """Invariants only -- deliberately NOT a second reimplementation of
    `_campaign_spend`'s block-counting arithmetic compared for exact equality
    (that failure mode turns a property test into "the function equals a
    copy of itself"; see tests/MIRRORED_AND_WRONG.md). The README describes
    the inputs (base fee, per-block incentive, block size, cap) but never a
    formula, so the only independently-statable properties are the bounds:
    spend never drops below the base fee and never exceeds base + cap.
    """
    terms = _terms(base=base, per_block=per_block, block_size=block_size, cap=cap)
    spend = _campaign_spend(terms, onboards)
    assert spend >= base
    assert spend <= base + cap


# ---------------------------------------------------------------------------
# _assemble_report bucketing
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_clicks_with_no_matching_campaign_land_in_miscellaneous() -> None:
    """10 total clicks, 4 + 3 assigned to two windows: 3 leftover → misc."""
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    report = _assemble_report(
        influencer(),
        windows,
        total_clicks=10,
        campaign_clicks=[4, 3],
        referred=[],
        pending_starts=[],
    )
    assert report.campaigns[0].stats.clicks == 4
    assert report.campaigns[1].stats.clicks == 3
    assert report.miscellaneous.clicks == 3
    assert report.miscellaneous == FunnelStats(clicks=3, started=0, onboards=0, retained=0)


@pytest.mark.boundary
def test_referred_user_in_no_window_counts_as_started_and_onboarded_in_misc() -> None:
    """Join time 2500 sits in the gap between [1000, 2000] and [3000, 4000].
    README: onboards are referred users; their start buckets at join time too.
    """
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    referred = [
        student(user_id="gap-user", created_at_ms=2_500, referrer_handle="coolkid")
    ]
    report = _assemble_report(
        influencer(),
        windows,
        total_clicks=0,
        campaign_clicks=[0, 0],
        referred=referred,
        pending_starts=[],
    )
    assert report.miscellaneous.started == 1
    assert report.miscellaneous.onboards == 1
    assert report.campaigns[0].stats.started == 0
    assert report.campaigns[0].stats.onboards == 0
    assert report.campaigns[1].stats.started == 0
    assert report.campaigns[1].stats.onboards == 0


@pytest.mark.boundary
def test_referred_user_inside_a_window_buckets_there_not_misc() -> None:
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    referred = [
        student(user_id="in-a", created_at_ms=1_500, referrer_handle="coolkid")
    ]
    report = _assemble_report(
        influencer(),
        windows,
        total_clicks=0,
        campaign_clicks=[0, 0],
        referred=referred,
        pending_starts=[],
    )
    assert report.campaigns[0].stats.started == 1
    assert report.campaigns[0].stats.onboards == 1
    assert report.miscellaneous.started == 0
    assert report.miscellaneous.onboards == 0


@pytest.mark.boundary
def test_pending_start_in_a_gap_increments_misc_started_only() -> None:
    """Abandoned starts are started-but-not-onboarded."""
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    report = _assemble_report(
        influencer(),
        windows,
        total_clicks=0,
        campaign_clicks=[0, 0],
        referred=[],
        pending_starts=[2_500],
    )
    assert report.miscellaneous.started == 1
    assert report.miscellaneous.onboards == 0


@pytest.mark.boundary
def test_empty_campaigns_put_every_click_and_referral_in_misc() -> None:
    referred = [student(user_id="u", created_at_ms=9_999, referrer_handle="coolkid")]
    report = _assemble_report(
        influencer(),
        [],
        total_clicks=7,
        campaign_clicks=[],
        referred=referred,
        pending_starts=[1],
    )
    assert report.campaigns == []
    assert report.miscellaneous.clicks == 7
    assert report.miscellaneous.started == 2
    assert report.miscellaneous.onboards == 1


@pytest.mark.property
@given(
    total=st.integers(min_value=0, max_value=10_000),
    c0=st.integers(min_value=0, max_value=5_000),
    c1=st.integers(min_value=0, max_value=5_000),
)
def test_per_campaign_clicks_plus_misc_clicks_equal_total_clicks(
    total: int, c0: int, c1: int
) -> None:
    assume(c0 + c1 <= total)
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    report = _assemble_report(
        influencer(),
        windows,
        total_clicks=total,
        campaign_clicks=[c0, c1],
        referred=[],
        pending_starts=[],
    )
    campaign_sum = sum(row.stats.clicks for row in report.campaigns)
    assert campaign_sum + report.miscellaneous.clicks == total
    assert report.campaigns[0].stats.clicks == c0
    assert report.campaigns[1].stats.clicks == c1
    assert report.miscellaneous.clicks == total - c0 - c1


@pytest.mark.boundary
def test_retained_requires_last_message_at_least_seven_days_after_join() -> None:
    """README: retained = referred users still messaging >= 7 days after joining."""
    join = 1_500
    windows = [campaign("a", 1_000, 10_000_000_000_000)]
    retained_user = student(
        user_id="kept",
        created_at_ms=join,
        last_message_at_ms=join + RETENTION_WINDOW_MS,
        session_count=2,
        referrer_handle="coolkid",
    )
    not_yet = student(
        user_id="new",
        created_at_ms=join,
        last_message_at_ms=join + RETENTION_WINDOW_MS - 1,
        session_count=2,
        referrer_handle="coolkid",
        name="Not Yet",
    )
    kept_report = _assemble_report(
        influencer(), windows, 0, [0], [retained_user], []
    )
    early_report = _assemble_report(influencer(), windows, 0, [0], [not_yet], [])
    assert kept_report.campaigns[0].stats.retained == 1
    assert early_report.campaigns[0].stats.retained == 0


@pytest.mark.boundary
def test_two_pending_starts_inside_one_window_both_count() -> None:
    """A single-item fixture cannot see ``+= 1`` mutated to ``= 1``."""
    windows = [campaign("a", 1_000, 2_000)]
    report = _assemble_report(
        influencer(), windows, 0, [0], [], pending_starts=[1_200, 1_800]
    )
    assert report.campaigns[0].stats.started == 2
    assert report.campaigns[0].stats.onboards == 0
    assert report.miscellaneous.started == 0


@pytest.mark.boundary
def test_two_onboards_inside_one_window_both_count() -> None:
    windows = [campaign("a", 1_000, 2_000)]
    referred = [
        student(user_id="u1", created_at_ms=1_200, referrer_handle="coolkid", name="One"),
        student(user_id="u2", created_at_ms=1_800, referrer_handle="coolkid", name="Two"),
    ]
    report = _assemble_report(influencer(), windows, 0, [0], referred, [])
    assert report.campaigns[0].stats.started == 2
    assert report.campaigns[0].stats.onboards == 2
    assert report.miscellaneous.onboards == 0


@pytest.mark.boundary
def test_two_retained_users_inside_one_window_both_count() -> None:
    join = 1_500
    windows = [campaign("a", 1_000, 10_000_000_000_000)]
    referred = [
        student(
            user_id="kept-1",
            created_at_ms=join,
            last_message_at_ms=join + RETENTION_WINDOW_MS,
            name="Kept One",
            referrer_handle="coolkid",
        ),
        student(
            user_id="kept-2",
            phone="919811111112",
            created_at_ms=join,
            last_message_at_ms=join + RETENTION_WINDOW_MS,
            name="Kept Two",
            referrer_handle="coolkid",
        ),
    ]
    report = _assemble_report(influencer(), windows, 0, [0], referred, [])
    assert report.campaigns[0].stats.retained == 2


@pytest.mark.boundary
def test_pending_start_inside_a_window_increments_that_campaign_not_misc() -> None:
    """README: abandoned starts bucket at the mentioning timestamp."""
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    report = _assemble_report(
        influencer(), windows, 0, [0, 0], [], pending_starts=[1_500]
    )
    assert report.campaigns[0].stats.started == 1
    assert report.campaigns[1].stats.started == 0
    assert report.miscellaneous.started == 0
    assert report.miscellaneous.onboards == 0


@pytest.mark.boundary
def test_referral_inside_a_window_is_tagged_with_that_campaign_id() -> None:
    windows = [campaign("a", 1_000, 2_000)]
    referred = [
        student(user_id="in-a", created_at_ms=1_500, referrer_handle="coolkid")
    ]
    report = _assemble_report(influencer(), windows, 0, [0], referred, [])
    assert len(report.referrals) == 1
    assert report.referrals[0].campaignId == "a"
    assert report.referrals[0].userId == "in-a"


@pytest.mark.boundary
def test_referral_in_a_gap_has_no_campaign_id() -> None:
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    referred = [
        student(user_id="gap", created_at_ms=2_500, referrer_handle="coolkid")
    ]
    report = _assemble_report(influencer(), windows, 0, [0, 0], referred, [])
    assert report.referrals[0].campaignId is None


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_derive_influencer_report_fetches_clicks_and_windows_for_this_handle() -> None:
    """Click counts and campaign list are keyed by the influencer's handle;
    count_between uses each window's inclusive startMs/endMs.
    """
    person = influencer(handle="coolkid")
    windows = [campaign("a", 1_000, 2_000), campaign("b", 3_000, 4_000)]
    campaigns = FakeCampaigns({"coolkid": windows})
    clicks = FakeClicks(
        all_by_handle={"coolkid": 10},
        between={("coolkid", 1_000, 2_000): 4, ("coolkid", 3_000, 4_000): 3},
    )
    report = await derive_influencer_report(person, clicks, campaigns, [], [])
    assert campaigns.list_calls == ["coolkid"]
    assert clicks.count_all_calls == ["coolkid"]
    assert clicks.count_between_calls == [
        ("coolkid", 1_000, 2_000),
        ("coolkid", 3_000, 4_000),
    ]
    assert report.handle == "coolkid"
    assert report.campaigns[0].stats.clicks == 4
    assert report.campaigns[1].stats.clicks == 3
    assert report.miscellaneous.clicks == 3


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_derive_influencer_report_unknown_handle_has_zero_clicks_and_no_windows() -> None:
    """A handle with no campaigns and no clicks is an empty report, not a crash."""
    person = influencer(handle="nobody")
    report = await derive_influencer_report(
        person, FakeClicks(), FakeCampaigns(), [], []
    )
    assert report.campaigns == []
    assert report.miscellaneous.clicks == 0
    assert report.miscellaneous.started == 0
