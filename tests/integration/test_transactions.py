"""Transactional commit of session cursors with the rows they summarize.

Spec: Stored derivations "legal only when written in the same commit as the
rows they summarize — session cursors (lastMessageAtMs, nextTranscriptSequence)
and the user-level channel activity tip."

A failed append must leave ALL of them unchanged.
"""

from __future__ import annotations

import pytest

from infra.firestore.repos.threads import ThreadsRepository

from . import constants as K
from .helpers import (
    assistant_message,
    session_doc,
    session_ids,
    student_profile,
    transcript_rows,
    user_doc,
    user_message,
)

pytestmark = pytest.mark.asyncio

BASE_MS = 1_760_000_000_000


async def test_successful_append_moves_cursors_with_the_rows(api, db):
    """A successful append moves the session cursors together with its rows.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    profile = await api.create_user(
        student_profile("910000020001", name="Commit")
    )
    user_id = profile["userId"]
    messages = [
        user_message("hello", BASE_MS, turn_id="t1"),
        assistant_message("hi", BASE_MS + 1, turn_id="t1"),
    ]
    response = await api.append(user_id, messages)
    assert response.status_code == 200
    assert response.json()["startedAtMs"] == BASE_MS
    assert response.json()["openedSessionNumber"] == 1

    session = await session_doc(db, user_id, BASE_MS)
    user = await user_doc(db, user_id)
    rows = await transcript_rows(db, user_id)
    activity = user["activity"][K.WHATSAPP_THREAD_KEY]
    assert [row["sequence"] for row in rows] == list(range(len(messages)))
    assert session["nextTranscriptSequence"] == len(rows)
    assert session["lastMessageAtMs"] == BASE_MS
    assert activity["sessionCount"] == 1
    assert activity["lastMessageAtMs"] == session["lastMessageAtMs"]


def _explode_activity_tip(*args, **kwargs):
    """Stand in for the activity-tip write and fail it on purpose.

    Args:
        args: positional args from the call site (ignored).
        kwargs: keyword args from the call site (ignored).
    Returns:
        None.
    Raises:
        RuntimeError: always, to simulate a mid-transaction failure.
    """
    raise RuntimeError("injected failure of the activity-tip write")


async def _cursor_snapshot(db, user_id: str) -> tuple[dict, dict, list]:
    """Session doc, activity tip, and sorted transcript row ids for user_id.

    Args:
        db: the emulator-bound Firestore client.
        user_id: the user whose cursors/rows to read.
    Returns:
        (session, activity, row_ids) as of the moment this is called.
    Raises:
        None.
    """
    session = dict(await session_doc(db, user_id, BASE_MS))
    activity = dict(
        (await user_doc(db, user_id))["activity"][K.WHATSAPP_THREAD_KEY]
    )
    row_ids = sorted(
        row["_rowId"] for row in await transcript_rows(db, user_id)
    )
    return session, activity, row_ids


async def _seeded_user(api, phone: str, name: str) -> str:
    """Create a student and append one transcript row.

    Args:
        api: the UsersApi test client.
        phone: the student's phone number.
        name: the student's display name.
    Returns:
        The new user's id.
    Raises:
        AssertionError: the seed append did not succeed.
    """
    profile = await api.create_user(student_profile(phone, name=name))
    user_id = profile["userId"]
    first = await api.append(
        user_id, [user_message("seed", BASE_MS, turn_id="seed")]
    )
    assert first.status_code == 200
    return user_id


def _assert_cursors_unchanged(before: tuple, after: tuple) -> None:
    """Compare two cursor snapshots field by field.

    Args:
        before: (session, activity, row ids) taken before the failing append.
        after: the same triple taken after the failing append.
    Returns:
        None.
    Raises:
        AssertionError: any cursor or row id changed.
    """
    before_session, before_activity, before_row_ids = before
    after_session, after_activity, after_row_ids = after
    assert after_session["lastMessageAtMs"] == before_session["lastMessageAtMs"]
    assert (
        after_session["nextTranscriptSequence"]
        == before_session["nextTranscriptSequence"]
    )
    assert after_activity == before_activity
    assert after_row_ids == before_row_ids


async def test_failed_append_leaves_all_cursors_and_rows_unchanged(
    api, db, monkeypatch
):
    """A failed append (mid-transaction) leaves every cursor and row exactly as
    before.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
        monkeypatch: pytest's monkeypatch fixture, used to inject the failure.
    Returns:
        None.
    Raises:
        None.
    """
    user_id = await _seeded_user(api, "910000020002", "Rollback")
    before = await _cursor_snapshot(db, user_id)
    monkeypatch.setattr(
        ThreadsRepository, "_save_activity", _explode_activity_tip
    )
    failed = await api.append(
        user_id,
        [user_message("should not land", BASE_MS + 10, turn_id="fail")],
        started_at_ms=BASE_MS,
    )
    assert failed.status_code >= 500
    after = await _cursor_snapshot(db, user_id)
    _assert_cursors_unchanged(before, after)


async def test_join_append_does_not_open_a_new_session(api, db):
    """Appending within the session gap joins the existing session, opening
    none.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    profile = await api.create_user(student_profile("910000020003", name="Tip"))
    user_id = profile["userId"]
    first = await api.append(
        user_id,
        [
            user_message("q", BASE_MS, turn_id="t-good"),
            assistant_message("a", BASE_MS + 1, turn_id="t-good"),
        ],
    )
    assert first.status_code == 200
    assert first.json()["openedSessionNumber"] == 1

    for offset, turn_id in ((2, "t-fail"), (3, "t-retry")):
        joined = await api.append(
            user_id,
            [user_message("again", BASE_MS + offset, turn_id=turn_id)],
            started_at_ms=BASE_MS,
        )
        assert joined.status_code == 200
        assert joined.json()["startedAtMs"] == BASE_MS
        assert joined.json()["openedSessionNumber"] is None

    assert await session_ids(db, user_id) == [str(BASE_MS)]


async def test_append_for_an_unknown_user_writes_nothing(api, db):
    """Appending for a user id that doesn't exist writes nothing.

    Args:
        api: the UsersApi test client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    unknown_id = "no-such-user"
    response = await api.append(
        unknown_id, [user_message("hello", BASE_MS, turn_id="t-unknown")]
    )
    assert response.status_code >= 400
    assert await session_ids(db, unknown_id) == []
    assert await user_doc(db, unknown_id) is None
