"""Derive-on-read: counts must never disagree with the rows they describe.

README Stored derivations: anything summarizing a *different* document —
referral counts, points, reward balances — stays derived on read. Directory
activity, ambassador points, and influencer funnel are computed from the
underlying rows. Mutate the rows, re-read the surface, assert they move
together. Inverse: nothing writes a stored counter for those metrics.
"""

from __future__ import annotations

import pytest

from infra.conversation import ContentMessage, PendingAction
from infra.firestore.repos.onboarding import OnboardingRepository

from . import constants as K
from .helpers import (
    campaign_docs,
    click_count,
    forbidden_counters_present,
    referrer_doc,
    session_ids,
    student_profile,
    teacher_profile,
    transcript_rows,
    user_doc,
    user_message,
)

pytestmark = pytest.mark.asyncio

BASE_MS = 1_780_000_000_000


async def test_directory_activity_moves_with_session_and_transcript_rows(api, db):
    """sessionCount / lastMessageAtMs on the directory equal the session documents."""
    profile = await api.create_user(student_profile("910000040001", name="Dir"))
    user_id = profile["userId"]

    before = await api.get(f"/internal/directory/{user_id}")
    assert before.status_code == 200
    assert before.json()["activity"] == {"sessionCount": 0, "lastMessageAtMs": None}

    first = await api.append(user_id, [user_message("hello", BASE_MS, turn_id="t1")])
    assert first.status_code == 200

    mid = await api.get(f"/internal/directory/{user_id}")
    assert mid.status_code == 200
    assert mid.json()["activity"] == {"sessionCount": 1, "lastMessageAtMs": BASE_MS}
    assert await session_ids(db, user_id) == [str(BASE_MS)]
    assert len(await transcript_rows(db, user_id)) == 1

    later_ms = BASE_MS + K.SESSION_GAP_MS + 1
    second = await api.append(user_id, [user_message("later", later_ms, turn_id="t2")])
    assert second.status_code == 200

    after = await api.get(f"/internal/directory/{user_id}")
    assert after.status_code == 200
    assert after.json()["activity"] == {"sessionCount": 2, "lastMessageAtMs": later_ms}
    assert await session_ids(db, user_id) == sorted([str(BASE_MS), str(later_ms)])
    assert len(await transcript_rows(db, user_id)) == 2


async def test_directory_unknown_user_is_404(api):
    response = await api.get("/internal/directory/no-such-user")
    assert response.status_code == 404


async def test_ambassador_points_move_with_attributed_user_rows(api, db):
    """points == number of users keyed by referrerHandle; adding a referral increments."""
    holder = await api.create_user(
        student_profile("910000040002", name="Arjun", institution_id="school-1")
    )
    holder_id = holder["userId"]
    enroll = await api.post(f"/internal/users/{holder_id}/ambassador")
    assert enroll.status_code == 200
    handle = enroll.json()["handle"]
    assert enroll.json()["points"] == 0

    await api.create_user(
        student_profile("910000040102", name="Referred1"),
        texts=[f"hi @{handle}"],
    )
    after_one = await api.get(f"/internal/users/{holder_id}/ambassador")
    assert after_one.status_code == 200
    assert after_one.json()["points"] == 1
    assert after_one.json()["studentsReferred"] == 1
    assert after_one.json()["teachersReferred"] == 0

    await api.create_user(
        teacher_profile("910000040103", name="ReferredTeacher"),
        texts=[f"hello @{handle}"],
    )
    after_two = await api.get(f"/internal/users/{holder_id}/ambassador")
    assert after_two.status_code == 200
    assert after_two.json()["points"] == 2
    assert after_two.json()["studentsReferred"] == 1
    assert after_two.json()["teachersReferred"] == 1

    stored = await referrer_doc(db, handle)
    assert stored is not None
    assert forbidden_counters_present(stored) == set()
    assert stored["kind"] == "ambassador"
    assert stored["userId"] == holder_id


async def test_ambassador_status_null_when_not_enrolled(api):
    profile = await api.create_user(student_profile("910000040003"))
    response = await api.get(f"/internal/users/{profile['userId']}/ambassador")
    assert response.status_code == 200
    assert response.json() is None


async def test_influencer_funnel_moves_with_clicks_and_onboards(api, db):
    """Clicks and onboards on the report equal the click rows and attributed users."""
    created = await api.post(
        "/internal/influencers", json={"handle": "funnelkid", "platform": "instagram"}
    )
    assert created.status_code == 200
    handle = created.json()["handle"]
    assert handle == "funnelkid"

    empty = await api.get(f"/internal/influencers/{handle}")
    assert empty.status_code == 200
    assert empty.json()["miscellaneous"] == {
        "clicks": 0,
        "started": 0,
        "onboards": 0,
        "retained": 0,
    }
    assert empty.json()["campaigns"] == []

    window = {
        "startMs": 1,
        "endMs": 9_999_999_999_999,
        "payout": {
            "baseInr": 0,
            "perBlockInr": 0,
            "blockSize": 1,
            "incentiveCapInr": 0,
        },
    }
    campaign = await api.post(f"/internal/influencers/{handle}/campaigns", json=window)
    assert campaign.status_code == 200

    click_one = await api.post(f"/internal/referrers/{handle}/click")
    click_two = await api.post(f"/internal/referrers/{handle}/click")
    assert click_one.status_code == 204
    assert click_two.status_code == 204
    assert await click_count(db, handle) == 2

    referred = await api.create_user(
        student_profile("910000040201", name="Onboarded"),
        texts=[f"hi @{handle}"],
    )
    join_ms = referred["createdAtMs"]

    mid = await api.get(f"/internal/influencers/{handle}")
    assert mid.status_code == 200
    stats = mid.json()["campaigns"][0]["stats"]
    assert stats["clicks"] == 2
    assert stats["onboards"] == 1
    assert stats["retained"] == 0

    # Mutate: one more click. Funnel clicks must move with the new row.
    click_three = await api.post(f"/internal/referrers/{handle}/click")
    assert click_three.status_code == 204
    after_click = await api.get(f"/internal/influencers/{handle}")
    assert after_click.json()["campaigns"][0]["stats"]["clicks"] == 3
    assert after_click.json()["campaigns"][0]["stats"]["onboards"] == 1

    # Mutate: a message >= 7 days after join makes the onboard retained.
    retained_at = join_ms + K.RETENTION_WINDOW_MS
    append = await api.append(
        referred["userId"],
        [user_message("still here", retained_at, turn_id="retain")],
    )
    # Pin may create/address a session at join_ms; if the service instead
    # opens a session at retained_at that is still a successful append.
    assert append.status_code == 200
    after_retain = await api.get(f"/internal/influencers/{handle}")
    assert after_retain.json()["campaigns"][0]["stats"]["retained"] == 1
    assert after_retain.json()["campaigns"][0]["stats"]["onboards"] == 1


async def test_influencer_started_moves_with_buffered_onboarding_rows(api, db):
    """Abandoned starts (onboarding buffer mentions the handle, never onboarded)."""
    created = await api.post(
        "/internal/influencers", json={"handle": "startkid", "platform": "youtube"}
    )
    handle = created.json()["handle"]
    window = {
        "startMs": 1,
        "endMs": 9_999_999_999_999,
        "payout": {"baseInr": 0, "perBlockInr": 0, "blockSize": 1, "incentiveCapInr": 0},
    }
    await api.post(f"/internal/influencers/{handle}/campaigns", json=window)

    pending = PendingAction(
        action="select_persona",
        messages=[
            ContentMessage(
                type="text",
                content={"body": f"hey @{handle} told me to try this"},
                phone_number_id="111",
                sender_phone="910000040301",
                sender_id="bsuid-start-1",
                profile_name="Waiter",
                message_id="wamid.start.1",
                timestamp="1750000000",
            )
        ],
    )
    onboarding = OnboardingRepository(db)
    await onboarding.set("bsuid-start-1", pending)

    report = await api.get(f"/internal/influencers/{handle}")
    assert report.status_code == 200
    stats = report.json()["campaigns"][0]["stats"]
    assert stats["started"] == 1
    assert stats["onboards"] == 0


async def test_influencer_unknown_handle_is_404(api):
    response = await api.get("/internal/influencers/no-such-handle")
    assert response.status_code == 404


async def test_nothing_writes_stored_counters_for_points_or_balances(api, db):
    """Inverse of derive-on-read: referrer/campaign/user docs have no stored counters."""
    holder = await api.create_user(
        student_profile("910000040004", name="Maya", institution_id="school-1")
    )
    holder_id = holder["userId"]
    enroll = await api.post(f"/internal/users/{holder_id}/ambassador")
    handle = enroll.json()["handle"]
    await api.create_user(
        student_profile("910000040104", name="Kid"), texts=[f"hi @{handle}"]
    )

    stored_referrer = await referrer_doc(db, handle)
    stored_user = await user_doc(db, holder_id)
    assert forbidden_counters_present(stored_referrer) == set()
    assert forbidden_counters_present(stored_user) == set()

    created = await api.post(
        "/internal/influencers", json={"handle": "nocounters", "platform": "instagram"}
    )
    inf_handle = created.json()["handle"]
    await api.post(
        f"/internal/influencers/{inf_handle}/campaigns",
        json={
            "startMs": 10,
            "endMs": 20,
            "payout": {"baseInr": 1, "perBlockInr": 1, "blockSize": 1, "incentiveCapInr": 1},
        },
    )
    inf_doc = await referrer_doc(db, inf_handle)
    campaigns = await campaign_docs(db, inf_handle)
    assert forbidden_counters_present(inf_doc) == set()
    for campaign in campaigns:
        assert forbidden_counters_present(campaign) == set()
        # payout terms are identity, not a running counter
        assert "stats" not in campaign
        assert "spendInr" not in campaign
