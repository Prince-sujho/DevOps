"""First-touch @-mention attribution.

Oracle: user_service README (first registered @-mention across pre-onboarding
texts; handles stored normalized lowercase) and function docstrings (first
registered mention in reading order; first registered mention across the
ordered texts).
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from user_service.app.src.attribution import (
    derive_starts,
    first_registered_mention,
    resolve_attribution,
)
from infra.attribution import AdAttribution, ReferrerAttribution

from .fakes import BufferedOnboarding, FakeOnboarding, TextMessage


class FakeReferrers:
    def __init__(self, handles: set[str]) -> None:
        self._handles = set(handles)

    async def list_handles(self) -> set[str]:
        return set(self._handles)


# ---------------------------------------------------------------------------
# first_registered_mention
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_first_registered_mention_wins_even_when_an_unregistered_mention_appears_earlier() -> None:
    """``@ghost`` is first in the text but not in the registry; ``@alice`` wins."""
    assert (
        first_registered_mention("hi @ghost then @alice please", {"alice"}) == "alice"
    )


@pytest.mark.boundary
def test_first_of_two_registered_mentions_wins() -> None:
    assert (
        first_registered_mention("ping @alice and @bob", {"alice", "bob"}) == "alice"
    )


@pytest.mark.boundary
def test_no_mentions_returns_none() -> None:
    assert first_registered_mention("hello there, no handles", {"alice"}) is None


@pytest.mark.boundary
def test_mentions_none_of_which_are_registered_returns_none() -> None:
    assert first_registered_mention("hi @ghost @stranger", {"alice"}) is None


@pytest.mark.boundary
def test_empty_string_returns_none() -> None:
    assert first_registered_mention("", {"alice"}) is None


@pytest.mark.boundary
def test_empty_registry_returns_none_even_with_mentions() -> None:
    assert first_registered_mention("hi @alice", set()) is None


@pytest.mark.boundary
def test_uppercase_mention_matches_normalized_lowercase_handle() -> None:
    """README: referrers/{handle} doc id is the normalized handle (lowercase, no @)."""
    assert first_registered_mention("join via @ALICE please", {"alice"}) == "alice"


@pytest.mark.boundary
def test_leading_at_in_the_registry_is_not_required() -> None:
    """Handles are stored without @; the mention's @ is the scan key."""
    assert first_registered_mention("hi @alice", {"alice"}) == "alice"


@pytest.mark.property
@given(
    prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=20),
    suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=20),
)
def test_a_lone_registered_mention_is_found_regardless_of_surrounding_prose(
    prefix: str, suffix: str
) -> None:
    text = f"{prefix} @bob {suffix}"
    assert first_registered_mention(text, {"bob"}) == "bob"


# ---------------------------------------------------------------------------
# resolve_attribution
# ---------------------------------------------------------------------------


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_referrer_first_text_with_a_registered_mention_wins() -> None:
    """CreateUserRequest texts are oldest-first; the earliest registered mention sticks."""
    referrers = FakeReferrers({"alice", "bob"})
    assert await resolve_attribution(
        ["talk to @alice", "later @bob"], None, referrers
    ) == ReferrerAttribution(handle="alice")


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_referrer_skips_earlier_texts_that_only_mention_unregistered_handles() -> None:
    referrers = FakeReferrers({"bob"})
    assert await resolve_attribution(
        ["hi @ghost", "then @bob"], None, referrers
    ) == ReferrerAttribution(handle="bob")


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_referrer_no_registered_mention_in_any_text() -> None:
    referrers = FakeReferrers({"alice"})
    assert (
        await resolve_attribution(["hello", "still nothing", "hi @ghost"], None, referrers)
        is None
    )


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_referrer_empty_texts() -> None:
    referrers = FakeReferrers({"alice"})
    assert await resolve_attribution([], None, referrers) is None


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_referrer_uppercase_mention_across_texts() -> None:
    referrers = FakeReferrers({"alice"})
    assert await resolve_attribution(
        ["please @ALICE"], None, referrers
    ) == ReferrerAttribution(handle="alice")


def _ad() -> AdAttribution:
    return AdAttribution(
        sourceId="ad-1",
        headline="Learn with Sujho",
        sourceUrl="https://fb.me/ad-1",
        ctwaClid="clid-1",
    )


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_attribution_mention_beats_an_ad() -> None:
    """README: a registered @-mention beats a Click-to-WhatsApp ad."""
    referrers = FakeReferrers({"alice"})
    assert await resolve_attribution(
        ["talk to @alice"], _ad(), referrers
    ) == ReferrerAttribution(handle="alice")


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_attribution_ad_when_no_registered_mention() -> None:
    referrers = FakeReferrers({"alice"})
    ad = _ad()
    assert await resolve_attribution(["hello there"], ad, referrers) == ad


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_resolve_attribution_unregistered_mention_does_not_beat_an_ad() -> None:
    referrers = FakeReferrers({"alice"})
    ad = _ad()
    assert await resolve_attribution(["hi @ghost"], ad, referrers) == ad


# ---------------------------------------------------------------------------
# derive_starts — unfinished onboardings with a registered mention
# Docstring: handle → start times; first registered mention in reading order;
# break after the first hit in one buffering (later buffered users still count).
# ---------------------------------------------------------------------------


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_derive_starts_records_the_first_registered_mention_timestamp() -> None:
    onboarding = FakeOnboarding(
        [
            BufferedOnboarding(
                [
                    TextMessage("hi @ghost then @alice", 1_000),
                    TextMessage("later @alice again", 2_000),
                ]
            )
        ]
    )
    starts = await derive_starts(onboarding, FakeReferrers({"alice"}))
    assert starts == {"alice": [1_000]}


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_derive_starts_two_in_flight_users_both_count() -> None:
    """``break`` after the first hit must not ``return`` from the whole function."""
    onboarding = FakeOnboarding(
        [
            BufferedOnboarding([TextMessage("join via @alice", 1_000)]),
            BufferedOnboarding([TextMessage("also @alice please", 2_000)]),
        ]
    )
    starts = await derive_starts(onboarding, FakeReferrers({"alice"}))
    assert starts == {"alice": [1_000, 2_000]}


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_derive_starts_unregistered_mention_is_omitted() -> None:
    onboarding = FakeOnboarding(
        [BufferedOnboarding([TextMessage("hi @ghost", 1_000)])]
    )
    starts = await derive_starts(onboarding, FakeReferrers({"alice"}))
    assert starts == {}


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_derive_starts_no_mention_is_omitted() -> None:
    onboarding = FakeOnboarding(
        [BufferedOnboarding([TextMessage("hello there", 1_000)])]
    )
    starts = await derive_starts(onboarding, FakeReferrers({"alice"}))
    assert starts == {}


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_derive_starts_empty_buffer_is_empty() -> None:
    starts = await derive_starts(FakeOnboarding([]), FakeReferrers({"alice"}))
    assert starts == {}
