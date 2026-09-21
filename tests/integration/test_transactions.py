"""Transactional commit of session cursors with the rows they summarize.

Spec: Stored derivations "legal only when written in the same commit as the
rows they summarize — session cursors (lastMessageAtMs, nextTranscriptSequence,
readNodeIds) and the user-level channel activity tip."

A failed append must leave ALL of them unchanged.
readNodeIds is a deduplicated union across appends in a session.
"""

from __future__ import annotations

import pytest

from infra.firestore.repos.threads import ThreadsRepository

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
    response = await api.append(
        user_id,
        [
            user_message("hello", BASE_MS, turn_id="t1"),
            assistant_message("hi", BASE_MS + 1, turn_id="t1"),
        ],
        read_ids=["node-a"],
        previous_response_id="resp-good",
    )
    assert response.status_code == 200
    assert response.json() == {"startedAtMs": BASE_MS, "openedSessionNumber": 1}

    session = await session_doc(db, user_id, BASE_MS)
    user = await user_doc(db, user_id)
    rows = await transcript_rows(db, user_id)
    assert session is not None
    assert user is not None
    assert [row["sequence"] for row in rows] == [0, 1]
    assert session["lastMessageAtMs"] == BASE_MS
    assert session["nextTranscriptSequence"] == 2
    assert sorted(session["readNodeIds"]) == ["node-a"]
    assert user["activity"]["whatsapp"]["sessionCount"] == 1
    assert user["activity"]["whatsapp"]["lastMessageAtMs"] == BASE_MS


async def test_failed_append_leaves_all_cursors_and_rows_unchanged(api, db, monkeypatch):
    """Failing dependency inside the append transaction rolls every cursor back.

    The activity-tip write is specified to share the commit with the rows. An
    exception raised from that write must abort the Firestore transaction so
    lastMessageAtMs, nextTranscriptSequence, readNodeIds,
    the activity tip, and the transcript rows all stay at the pre-append
    snapshot. Firestore itself is not mocked — the emulator still runs the
    transaction.
    """
    profile = await api.create_user(student_profile("910000020002", name="Rollback"))
    user_id = profile["userId"]
    first = await api.append(
        user_id,
        [user_message("seed", BASE_MS, turn_id="seed")],
        read_ids=["seed-node"],
        previous_response_id="resp-seed",
    )
    assert first.status_code == 200

    before_session = dict(await session_doc(db, user_id, BASE_MS))
    before_user = dict(await user_doc(db, user_id))
    before_rows = await transcript_rows(db, user_id)
    before_row_ids = sorted(row["_rowId"] for row in before_rows)

    def explode(*args, **kwargs):
        raise RuntimeError("injected failure of the activity-tip write")

    monkeypatch.setattr(ThreadsRepository, "_save_activity", explode)

    failed = await api.append(
        user_id,
        [user_message("should not land", BASE_MS + 10, turn_id="fail")],
        read_ids=["new-node"],
        previous_response_id="resp-must-not-stick",
        started_at_ms=BASE_MS,
    )
    assert failed.status_code == 500

    after_session = await session_doc(db, user_id, BASE_MS)
    after_user = await user_doc(db, user_id)
    after_rows = await transcript_rows(db, user_id)
    assert after_session["lastMessageAtMs"] == before_session["lastMessageAtMs"]
    assert after_session["nextTranscriptSequence"] == before_session["nextTranscriptSequence"]
    assert sorted(after_session["readNodeIds"]) == sorted(before_session["readNodeIds"])
    assert after_user["activity"]["whatsapp"]["sessionCount"] == before_user["activity"]["whatsapp"]["sessionCount"]
    assert after_user["activity"]["whatsapp"]["lastMessageAtMs"] == before_user["activity"]["whatsapp"]["lastMessageAtMs"]
    assert sorted(row["_rowId"] for row in after_rows) == before_row_ids
    assert [row["sequence"] for row in after_rows] == [0]


async def test_join_append_does_not_open_a_new_session(api, db):
    """A follow-up append in the same gap returns openedSessionNumber None."""
    profile = await api.create_user(student_profile("910000020003", name="Tip"))
    user_id = profile["userId"]
    good = await api.append(
        user_id,
        [
            user_message("q", BASE_MS, turn_id="t-good"),
            assistant_message("a", BASE_MS + 1, turn_id="t-good"),
        ],
    )
    assert good.status_code == 200
    assert good.json() == {"startedAtMs": BASE_MS, "openedSessionNumber": 1}

    failure = await api.append(
        user_id,
        [assistant_message("Sorry, something went wrong", BASE_MS + 2, turn_id="t-fail")],
        started_at_ms=BASE_MS,
    )
    assert failure.status_code == 200
    assert failure.json() == {"startedAtMs": BASE_MS, "openedSessionNumber": None}

    nxt = await api.append(
        user_id,
        [user_message("retry", BASE_MS + 3, turn_id="t-retry")],
        started_at_ms=BASE_MS,
    )
    assert nxt.status_code == 200
    assert nxt.json() == {"startedAtMs": BASE_MS, "openedSessionNumber": None}


async def test_read_node_ids_are_a_deduplicated_union_across_appends(api, db):
    """README: every graph node id the agent read this session, deduplicated."""
    profile = await api.create_user(student_profile("910000020004", name="Union"))
    user_id = profile["userId"]
    first = await api.append(
        user_id,
        [user_message("one", BASE_MS, turn_id="t1")],
        read_ids=["n1", "n1", "n2"],
    )
    assert first.status_code == 200
    session = await session_doc(db, user_id, BASE_MS)
    assert sorted(session["readNodeIds"]) == ["n1", "n2"]

    second = await api.append(
        user_id,
        [user_message("two", BASE_MS + 1, turn_id="t2")],
        read_ids=["n2", "n3"],
        started_at_ms=BASE_MS,
    )
    assert second.status_code == 200
    session = await session_doc(db, user_id, BASE_MS)
    assert sorted(session["readNodeIds"]) == ["n1", "n2", "n3"]


async def test_append_for_an_unknown_user_writes_nothing(api, db):
    """The route has no 404 gate, so it fails in the transaction — but writes nothing."""
    unknown_id = "no-such-user"
    response = await api.append(
        unknown_id, [user_message("hello", BASE_MS, turn_id="t-unknown")]
    )
    assert response.status_code >= 400
    assert await session_ids(db, unknown_id) == []
    assert await user_doc(db, unknown_id) is None


async def test_append_with_non_list_read_ids_is_422(api):
    """Invalid input: readIds must be a list of strings."""
    profile = await api.create_user(student_profile("910000020005"))
    user_id = profile["userId"]
    response = await api.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript",
        json={
            "messages": [user_message("x", BASE_MS)],
            "readIds": "node-a",
            "previousResponseId": None,
        },
    )
    assert response.status_code == 422
