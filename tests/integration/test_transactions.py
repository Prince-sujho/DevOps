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
    """Happy path: after one user+assistant append, cursors match the rows."""
    profile = await api.create_user(student_profile("910000020001", name="Commit"))
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


async def test_failed_append_leaves_all_cursors_and_rows_unchanged(api, db, monkeypatch):
    """A failing write inside the append transaction rolls every cursor back.

    The activity-tip write shares the commit with the rows. An exception from
    that write must abort the Firestore transaction so lastMessageAtMs,
    nextTranscriptSequence, the activity tip and the transcript rows all stay
    at the pre-append snapshot. Firestore itself is not mocked.
    """
    profile = await api.create_user(student_profile("910000020002", name="Rollback"))
    user_id = profile["userId"]
    first = await api.append(user_id, [user_message("seed", BASE_MS, turn_id="seed")])
    assert first.status_code == 200

    before_session = dict(await session_doc(db, user_id, BASE_MS))
    before_activity = dict((await user_doc(db, user_id))["activity"][K.WHATSAPP_THREAD_KEY])
    before_row_ids = sorted(row["_rowId"] for row in await transcript_rows(db, user_id))

    def explode(*args, **kwargs):
        raise RuntimeError("injected failure of the activity-tip write")

    monkeypatch.setattr(ThreadsRepository, "_save_activity", explode)

    failed = await api.append(
        user_id,
        [user_message("should not land", BASE_MS + 10, turn_id="fail")],
        started_at_ms=BASE_MS,
    )
    assert failed.status_code >= 500

    after_session = await session_doc(db, user_id, BASE_MS)
    after_activity = (await user_doc(db, user_id))["activity"][K.WHATSAPP_THREAD_KEY]
    after_row_ids = sorted(row["_rowId"] for row in await transcript_rows(db, user_id))
    assert after_session["lastMessageAtMs"] == before_session["lastMessageAtMs"]
    assert after_session["nextTranscriptSequence"] == before_session["nextTranscriptSequence"]
    assert after_activity == before_activity
    assert after_row_ids == before_row_ids


async def test_join_append_does_not_open_a_new_session(api, db):
    """A follow-up append in the same gap joins the session: openedSessionNumber is None."""
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
    """The route has no 404 gate, so it fails in the transaction — but writes nothing."""
    unknown_id = "no-such-user"
    response = await api.append(
        unknown_id, [user_message("hello", BASE_MS, turn_id="t-unknown")]
    )
    assert response.status_code >= 400
    assert await session_ids(db, unknown_id) == []
    assert await user_doc(db, unknown_id) is None
