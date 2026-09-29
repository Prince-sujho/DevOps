"""Session-gap boundary between user messages.

Rule (infra ThreadsRepository._resolve): a message joins the latest session
while ``at_ms - lastMessageAtMs <= SESSION_GAP_MS``; anything later opens a
new one. A pinned ``startedAtMs`` addresses that session and never re-gaps.
Every offset is expressed in SESSION_GAP_MS so the window can move freely.
"""

from __future__ import annotations

import pytest

from . import constants as K
from .helpers import session_ids, student_profile, user_message

pytestmark = pytest.mark.asyncio

BASE_MS = 1_770_000_000_000


async def _two_appends(api, phone: str, later_ms: int, **pin):
    """Append at BASE_MS, then again at later_ms; return (user_id, second's
    startedAtMs).

    Args:
        api: the UsersApi test client.
        phone: the test user's phone number.
        later_ms: the second append's timestamp.
        pin: extra kwargs passed through to the second append (e.g.
            started_at_ms).
    Returns:
        (user_id, the second append's startedAtMs).
    Raises:
        None.
    """
    profile = await api.create_user(student_profile(phone))
    user_id = profile["userId"]
    first = await api.append(user_id, [user_message("A", BASE_MS, turn_id="a")])
    assert first.status_code == 200
    second = await api.append(
        user_id, [user_message("B", later_ms, turn_id="b")], **pin
    )
    assert second.status_code == 200
    return user_id, second.json()["startedAtMs"]


async def test_gap_under_the_window_stays_in_the_same_session(api, db):
    """A gap smaller than SESSION_GAP_MS joins the existing session.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, started = await _two_appends(
        api, "910000030001", BASE_MS + K.SESSION_GAP_MS - 1
    )
    assert started == BASE_MS
    assert await session_ids(db, user_id) == [str(BASE_MS)]


async def test_gap_over_the_window_opens_a_new_session(api, db):
    """A gap larger than SESSION_GAP_MS opens a new session.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    later_ms = BASE_MS + K.SESSION_GAP_MS + 1
    user_id, started = await _two_appends(api, "910000030002", later_ms)
    assert started == later_ms
    assert await session_ids(db, user_id) == sorted(
        [str(BASE_MS), str(later_ms)]
    )


async def test_gap_of_exactly_one_window_stays_in_the_same_session(api, db):
    """The boundary is inclusive: exactly SESSION_GAP_MS later still joins.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, started = await _two_appends(
        api, "910000030003", BASE_MS + K.SESSION_GAP_MS
    )
    assert started == BASE_MS
    assert await session_ids(db, user_id) == [str(BASE_MS)]


async def test_pinned_started_at_ms_does_not_re_gap(api, db):
    """A wall-clock gap of several windows still lands in the pinned session.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, started = await _two_appends(
        api,
        "910000030004",
        BASE_MS + 3 * K.SESSION_GAP_MS,
        started_at_ms=BASE_MS,
    )
    assert started == BASE_MS
    assert await session_ids(db, user_id) == [str(BASE_MS)]
