"""nextTranscriptSequence is owned by user_service; callers cannot assign order.

Spec: Firestore Layout — "Transactional counter owned by user_service; callers
cannot assign transcript order." A fresh session starts the counter at 0.
"""

from __future__ import annotations

import pytest

from .helpers import student_profile, transcript_rows, user_message

pytestmark = pytest.mark.asyncio

BASE_MS = 1_750_000_000_000


async def test_caller_supplied_sequence_is_ignored(api, db):
    """Callers cannot assign transcript order — a payload sequence is not stored
    as-is.

    Args:
        api: HTTP client for user_service's internal surface.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    profile = await api.create_user(
        student_profile("910000010002", name="IgnoreSeq")
    )
    user_id = profile["userId"]
    response = await api.append(
        user_id, [user_message("hello", BASE_MS, turn_id="turn-a", sequence=99)]
    )
    assert response.status_code == 200
    rows = await transcript_rows(db, user_id)
    assert [row["sequence"] for row in rows] == [0]
