"""Journey 15 — the two-hour session boundary.

The adapter stamps transcript rows with wall-clock `now_ms()`, not the webhook
timestamp (`whatsapp_adapter/app/src/transcripts.py::_stamp`), and user_service
resolves the session from `messages[0].createdAtMs`. Millisecond boundary
precision is therefore unreachable through webhook posts, so this journey drives
the boundary through user_service's real transcript-append route with explicit
`createdAtMs` values — the same code path the adapter calls.
"""

from __future__ import annotations

import pytest

from . import constants as K
from .conftest import derive_user_id, session_ids
from .scripting import append_transcript, create_user, student_profile_input, user_row

pytestmark = pytest.mark.asyncio

BASE_MS = 1_750_000_000_000


async def test_session_gap_boundary(db, users_api):
    """Under 2h stays in one session; exactly 2h and beyond open a new one.

    README (user_service/README.md): "a gap of two hours between user
    messages opens a new session" -- read plainly, a gap that has reached two
    hours has opened a new session (>= 2h), not "more than two hours"
    (> 2h). The code implements the exclusive `>` reading
    (`infra/firestore/repos/threads.py::_resolve`), so the exactly-2h case
    below is expected to fail against current code. This intentionally
    matches `tests/integration/test_session_boundary.py::
    test_gap_exactly_two_hours_opens_a_new_session` (also red) instead of the
    old reading here, which happened to match the code and silently
    disagreed with that sibling test -- see tests/outcomes/FINDINGS.md
    integration #5 and tests/outcomes/MIRRORED_AND_WRONG.md ("guessed the
    operator, stayed green").
    """
    phone = "919500000015"
    user_id = derive_user_id(phone)
    await create_user(users_api, student_profile_input(phone=phone, name="Tara"))

    # A opens the first session.
    a = await append_transcript(
        users_api, user_id, [user_row("message A", BASE_MS, turn_id="turn-a")]
    )
    assert a["startedAtMs"] == BASE_MS
    assert await session_ids(db, user_id) == [str(BASE_MS)]

    # B lands 1h59m after A — inside the window.
    b_ms = BASE_MS + K.SESSION_GAP_MS - 60_000
    b = await append_transcript(
        users_api, user_id, [user_row("message B", b_ms, turn_id="turn-b")]
    )
    assert b["startedAtMs"] == BASE_MS
    assert await session_ids(db, user_id) == [str(BASE_MS)]

    # C lands exactly 2h after B — the gap has reached two hours, so this
    # opens a new session under the README's plain-English reading.
    c_ms = b_ms + K.SESSION_GAP_MS
    c = await append_transcript(
        users_api, user_id, [user_row("message C", c_ms, turn_id="turn-c")]
    )
    assert c["startedAtMs"] == c_ms
    assert await session_ids(db, user_id) == sorted([str(BASE_MS), str(c_ms)])

    # D lands 2h + 1ms after C — also a new session.
    d_ms = c_ms + K.SESSION_GAP_MS + 1
    d = await append_transcript(
        users_api, user_id, [user_row("message D", d_ms, turn_id="turn-d")]
    )
    assert d["startedAtMs"] == d_ms
    assert await session_ids(db, user_id) == sorted([str(BASE_MS), str(c_ms), str(d_ms)])
