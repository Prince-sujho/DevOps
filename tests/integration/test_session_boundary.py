"""Session-gap boundary: two hours between user messages.

Spec (user_service README, Firestore Layout):
"a gap of two hours between user messages opens a new session."
"Optional startedAtMs pins the append to that session (no re-gap)."

Task:
- Gap strictly under 2 hours -> same session
- Gap strictly over 2 hours -> new session
- Gap EXACTLY 2 hours -> documented behaviour (see comment in the exact-boundary test)
- An append pinned with an explicit startedAtMs must NOT re-gap
"""

from __future__ import annotations

import pytest

from . import constants as K
from .helpers import session_ids, student_profile, user_message

pytestmark = pytest.mark.asyncio

BASE_MS = 1_770_000_000_000


async def test_gap_strictly_under_two_hours_stays_in_the_same_session(api, db):
    profile = await api.create_user(student_profile("910000030001", name="Under"))
    user_id = profile["userId"]
    first = await api.append(user_id, [user_message("A", BASE_MS, turn_id="a")])
    assert first.status_code == 200
    assert first.json()["startedAtMs"] == BASE_MS

    later_ms = BASE_MS + K.SESSION_GAP_MS - 1
    second = await api.append(user_id, [user_message("B", later_ms, turn_id="b")])
    assert second.status_code == 200
    assert second.json()["startedAtMs"] == BASE_MS
    assert await session_ids(db, user_id) == [str(BASE_MS)]


async def test_gap_strictly_over_two_hours_opens_a_new_session(api, db):
    profile = await api.create_user(student_profile("910000030002", name="Over"))
    user_id = profile["userId"]
    first = await api.append(user_id, [user_message("A", BASE_MS, turn_id="a")])
    assert first.status_code == 200

    later_ms = BASE_MS + K.SESSION_GAP_MS + 1
    second = await api.append(user_id, [user_message("B", later_ms, turn_id="b")])
    assert second.status_code == 200
    assert second.json()["startedAtMs"] == later_ms
    assert await session_ids(db, user_id) == sorted([str(BASE_MS), str(later_ms)])


async def test_gap_exactly_two_hours_opens_a_new_session(api, db):
    """README: "a gap of two hours between user messages opens a new session."

    That sentence names the two-hour duration itself as the thing that opens a
    new session, so a gap of exactly SESSION_GAP_MS is committed here as a new
    session. The competing reading ("more than two hours") is recorded in
    UNCERTAINTY.md; this assertion is the user_service README's wording, which
    is the spec source for this layer.
    """
    profile = await api.create_user(student_profile("910000030003", name="Exact"))
    user_id = profile["userId"]
    first = await api.append(user_id, [user_message("A", BASE_MS, turn_id="a")])
    assert first.status_code == 200

    later_ms = BASE_MS + K.SESSION_GAP_MS
    second = await api.append(user_id, [user_message("B", later_ms, turn_id="b")])
    assert second.status_code == 200
    assert second.json()["startedAtMs"] == later_ms
    assert await session_ids(db, user_id) == sorted([str(BASE_MS), str(later_ms)])


async def test_pinned_started_at_ms_does_not_re_gap(api, db):
    """A 3-hour wall-clock gap still lands in the pinned session."""
    profile = await api.create_user(student_profile("910000030004", name="Pin"))
    user_id = profile["userId"]
    first = await api.append(user_id, [user_message("A", BASE_MS, turn_id="a")])
    assert first.status_code == 200
    assert first.json()["startedAtMs"] == BASE_MS

    later_ms = BASE_MS + 3 * K.SESSION_GAP_MS
    pinned = await api.append(
        user_id,
        [user_message("B", later_ms, turn_id="b")],
        started_at_ms=BASE_MS,
    )
    assert pinned.status_code == 200
    assert pinned.json()["startedAtMs"] == BASE_MS
    assert await session_ids(db, user_id) == [str(BASE_MS)]


async def test_started_at_ms_of_wrong_type_is_422(api):
    """Invalid input: startedAtMs must be an optional int, not a string."""
    profile = await api.create_user(student_profile("910000030005"))
    user_id = profile["userId"]
    response = await api.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript",
        json={
            "messages": [user_message("A", BASE_MS)],
            "readIds": [],
            "previousResponseId": None,
            "startedAtMs": "not-a-number",
        },
    )
    assert response.status_code == 422
