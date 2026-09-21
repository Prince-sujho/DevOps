"""nextTranscriptSequence is owned by user_service; callers cannot assign order.

Spec: Firestore Layout — "Transactional counter owned by user_service; callers
cannot assign transcript order." A fresh session starts the counter at 0.
"""

from __future__ import annotations

import asyncio

import pytest

from .helpers import session_ids, student_profile, transcript_rows, user_message

pytestmark = pytest.mark.asyncio

BASE_MS = 1_750_000_000_000
# Concurrent writers on the one session document; see the xfail reason below.
N = 2


@pytest.mark.xfail(
    reason=(
        "Environment gap, not a spec-vs-code mismatch: the Firestore emulator "
        "cannot reliably commit concurrent transactions against one session "
        "document. N=2 writers flake (3 passed / 2 failed in 5 runs) and N>=3 "
        "exhausts the 5-attempt retry budget outright, wedging the locks for "
        "later tests. Real Firestore handles this contention -- see "
        "tests/outcomes/HANDOVER.md part 3."
    ),
    strict=False,
)
async def test_concurrent_appends_to_one_session_assign_contiguous_sequences(api, db):
    """A seed append opens the session, then N concurrent pinned appends: 0..N."""
    profile = await api.create_user(student_profile("910000010001", name="Seq"))
    user_id = profile["userId"]

    seed = await api.append(
        user_id, [user_message("seed", BASE_MS, turn_id="turn-seed")]
    )
    assert seed.status_code == 200
    assert seed.json()["startedAtMs"] == BASE_MS

    async def one_append(index: int):
        return await api.append(
            user_id,
            [user_message(f"concurrent {index}", BASE_MS + index, turn_id=f"turn-{index}")],
            started_at_ms=BASE_MS,
        )

    responses = await asyncio.gather(*[one_append(i) for i in range(N)])
    assert [r.status_code for r in responses] == [200] * N
    assert [r.json()["startedAtMs"] for r in responses] == [BASE_MS] * N

    assert await session_ids(db, user_id) == [str(BASE_MS)]
    rows = await transcript_rows(db, user_id)
    # Equality with range() is the whole claim: N+1 rows, 0-based, no dupes, no gaps.
    assert sorted(row["sequence"] for row in rows) == list(range(N + 1))


async def test_caller_supplied_sequence_is_ignored(api, db):
    """Callers cannot assign transcript order — a payload sequence is not stored as-is."""
    profile = await api.create_user(student_profile("910000010002", name="IgnoreSeq"))
    user_id = profile["userId"]
    response = await api.append(
        user_id,
        [user_message("hello", BASE_MS, turn_id="turn-a", sequence=99)],
    )
    assert response.status_code == 200
    rows = await transcript_rows(db, user_id)
    assert [row["sequence"] for row in rows] == [0]


async def test_append_empty_messages_is_422(api):
    """AppendTranscriptRequest.messages has min_length=1; empty list is invalid input."""
    profile = await api.create_user(student_profile("910000010003"))
    user_id = profile["userId"]
    response = await api.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript",
        json={
            "messages": [],
            "readIds": [],
            "previousResponseId": None,
        },
    )
    assert response.status_code == 422
