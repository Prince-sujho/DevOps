"""Derive-on-read: counts must never disagree with the rows they describe.

README Stored derivations: anything summarizing a *different* document —
referral counts, points, reward balances — stays derived on read. Mutate the
rows, re-read the surface, assert they move together. Inverse: nothing writes
a stored counter for those metrics.

Channels come from ``infra.attribution.CHANNELS`` and mention texts from
``referral_prefill``, so a channel added or renamed needs no edit here.
"""

from __future__ import annotations

import pytest

from infra.attribution import CHANNELS, referral_prefill
from infra.conversation import ContentMessage, PendingAction
from infra.firestore.repos.onboarding import OnboardingRepository

from . import constants as K
from .helpers import (
    campaign_docs,
    click_count,
    forbidden_counters_present,
    referrer_doc,
    student_profile,
    teacher_profile,
    user_doc,
    user_message,
)

pytestmark = pytest.mark.asyncio

BASE_MS = 1_780_000_000_000
CAMPAIGN_PLATFORM, OTHER_PLATFORM = list(CHANNELS)[:2]
OPEN_WINDOW = {"startMs": 1, "endMs": 9_999_999_999_999}
NO_PAYOUT = {
    "baseInr": 0,
    "perBlockInr": 0,
    "blockSize": 1,
    "incentiveCapInr": 0,
}


async def _influencer_with_campaign(api, handle: str) -> str:
    """Seed an influencer with an active reward campaign.

    Args:
        api: the UsersApi test client.
    Returns:
        The influencer handle.
    Raises:
        None.
    """
    created = await api.post("/internal/influencers", json={"handle": handle})
    assert created.status_code == 200
    handle = created.json()["handle"]
    campaign = await api.post(
        f"/internal/influencers/{handle}/campaigns",
        json={
            "platform": CAMPAIGN_PLATFORM,
            **OPEN_WINDOW,
            "payout": NO_PAYOUT,
        },
    )
    assert campaign.status_code == 200
    return handle


async def _click(api, handle: str, platform) -> None:
    """Record one referral click.

    Args:
        api: the UsersApi test client.
        handle: the referrer handle the click is attributed to.
        platform: the click's originating platform.
    Returns:
        None.
    Raises:
        None.
    """
    response = await api.post(
        f"/internal/referrers/{handle}/click", json={"platform": platform}
    )
    assert response.status_code == 204


async def test_directory_activity_moves_with_session_rows(api):
    """The directory's derived activity state moves with real session rows, not
    a stored counter.

    Args:
        api: the UsersApi test client.
    Returns:
        None.
    Raises:
        None.
    """
    profile = await api.create_user(student_profile("910000040001", name="Dir"))
    user_id = profile["userId"]

    async def activity():
        """Re-fetch this user's directory activity block.

        Args:
            None.
        Returns:
            The activity object from the directory response JSON.
        Raises:
            AssertionError: the directory response status is not 200.
        """
        response = await api.get(f"/internal/directory/{user_id}")
        assert response.status_code == 200
        return response.json()["activity"]

    before = await activity()
    assert before["sessionCount"] == 0
    assert before["lastMessageAtMs"] is None

    for count, at_ms in enumerate(
        (BASE_MS, BASE_MS + K.SESSION_GAP_MS + 1), start=1
    ):
        appended = await api.append(
            user_id, [user_message("hi", at_ms, turn_id=f"t{count}")]
        )
        assert appended.status_code == 200
        now = await activity()
        assert now["sessionCount"] == count
        assert now["lastMessageAtMs"] == at_ms


async def test_ambassador_points_move_with_attributed_user_rows(api, db):
    """Ambassador points are derived from real attributed-user rows, not a
    stored counter.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    holder = await api.create_user(
        student_profile("910000040002", name="Arjun", institution_id="school-1")
    )
    holder_id = holder["userId"]
    enroll = await api.post(f"/internal/users/{holder_id}/ambassador")
    assert enroll.status_code == 200
    handle = enroll.json()["handle"]
    assert enroll.json()["points"] == 0

    referrals = [
        student_profile("910000040102", name="Referred1"),
        teacher_profile("910000040103", name="ReferredTeacher"),
    ]
    for points, referred in enumerate(referrals, start=1):
        await api.create_user(referred, texts=[referral_prefill(handle, None)])
        status = await api.get(f"/internal/users/{holder_id}/ambassador")
        assert status.status_code == 200
        assert status.json()["points"] == points
    assert status.json()["studentsReferred"] + status.json()[
        "teachersReferred"
    ] == len(referrals)

    stored = await referrer_doc(db, handle)
    assert forbidden_counters_present(stored) == set()
    assert stored["userId"] == holder_id


async def _influencer_report(api, handle: str):
    """Re-fetch this influencer's report.

    Args:
        api: the UsersApi test client.
        handle: the influencer handle.
    Returns:
        The JSON value parsed from that text.
    Raises:
        AssertionError: the influencer report response status is not 200.
    """
    response = await api.get(f"/internal/influencers/{handle}")
    assert response.status_code == 200
    return response.json()


async def test_influencer_funnel_moves_with_clicks_onboards_and_retention(
    api, db
):
    """The influencer funnel is derived from real clicks/onboards/retention
    rows.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    handle = await _influencer_with_campaign(api, "funnelkid")

    await _click(api, handle, CAMPAIGN_PLATFORM)
    await _click(api, handle, CAMPAIGN_PLATFORM)
    await _click(api, handle, OTHER_PLATFORM)
    assert await click_count(db, handle) == 3

    referred = await api.create_user(
        student_profile("910000040201", name="Onboarded"),
        texts=[referral_prefill(handle, CAMPAIGN_PLATFORM)],
    )
    mid = await _influencer_report(api, handle)
    stats = mid["campaigns"][0]["stats"]
    assert stats["clicks"] == 2
    assert mid["miscellaneous"]["clicks"] == 1
    assert stats["onboards"] == 1
    assert stats["retained"] == 0

    retained_at = referred["createdAtMs"] + K.RETENTION_WINDOW_MS
    append = await api.append(
        referred["userId"],
        [user_message("still here", retained_at, turn_id="r")],
    )
    assert append.status_code == 200
    after = (await _influencer_report(api, handle))["campaigns"][0]["stats"]
    assert after["retained"] == 1
    assert after["onboards"] == 1


async def test_influencer_started_moves_with_buffered_onboarding_rows(api, db):
    """The influencer "started" count is derived from real buffered onboarding
    rows.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    handle = await _influencer_with_campaign(api, "startkid")
    pending = PendingAction(
        action="select_persona",
        messages=[
            ContentMessage(
                type="text",
                content={"body": referral_prefill(handle, CAMPAIGN_PLATFORM)},
                sender_phone="910000040301",
                sender_id="bsuid-start-1",
                profile_name="Waiter",
                message_id="wamid.start.1",
                timestamp="1750000000",
            )
        ],
    )
    await OnboardingRepository(db).set("bsuid-start-1", pending)

    report = await api.get(f"/internal/influencers/{handle}")
    assert report.status_code == 200
    stats = report.json()["campaigns"][0]["stats"]
    assert stats["started"] == 1
    assert stats["onboards"] == 0


async def test_nothing_writes_stored_counters_for_points_or_balances(api, db):
    """No route writes a stored points/balance counter; everything is derived on
    read.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    holder = await api.create_user(
        student_profile("910000040004", name="Maya", institution_id="school-1")
    )
    holder_id = holder["userId"]
    handle = (await api.post(f"/internal/users/{holder_id}/ambassador")).json()[
        "handle"
    ]
    await api.create_user(
        student_profile("910000040104", name="Kid"),
        texts=[referral_prefill(handle, None)],
    )
    inf_handle = await _influencer_with_campaign(api, "nocounters")
    await _click(api, inf_handle, CAMPAIGN_PLATFORM)

    campaigns = await campaign_docs(db, inf_handle)
    assert campaigns
    for stored in [
        await referrer_doc(db, handle),
        await user_doc(db, holder_id),
        await referrer_doc(db, inf_handle),
        *campaigns,
    ]:
        assert forbidden_counters_present(stored) == set()
