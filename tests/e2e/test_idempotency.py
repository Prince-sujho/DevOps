"""Journey 7 — duplicate webhook delivery is claimed once and processed once."""

from __future__ import annotations

import pytest

from infra.conversation import TextMessage

from . import payloads
from .conftest import derive_user_id, transcript_rows
from .scripting import create_user, student_profile_input, turn
from .servers import settle, wait_until

pytestmark = pytest.mark.asyncio


async def test_duplicate_delivery_is_processed_once(
    adapter, whatsapp, openai, db, users_api
):
    """The same Meta message id delivered twice runs exactly one agent turn."""
    phone = "919400000007"
    user_id = derive_user_id(phone)
    await create_user(users_api, student_profile_input(phone=phone, name="Anil"))
    openai.push(
        turn(response_id="resp-j7", messages=[TextMessage(type="text", text="Only once")])
    )

    payload = payloads.text_webhook(
        message_id="wamid.j7.duplicate",
        sender_id="bsuid-j7",
        sender_phone=phone,
        body="are you there",
        profile_name="Anil",
    )

    first = await adapter.post_webhook(payload)
    assert first.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()

    rows_after_first = await transcript_rows(db, user_id)
    assert len(rows_after_first) == 3
    assert len(openai.calls) == 1
    assert whatsapp.kinds() == ["text"]

    second = await adapter.post_webhook(payload)
    assert second.status_code == 200
    await settle()

    # the duplicate is a no-op: no second turn, no extra rows, no extra delivery
    assert len(openai.calls) == 1
    assert whatsapp.kinds() == ["text"]
    rows_after_second = await transcript_rows(db, user_id)
    assert len(rows_after_second) == len(rows_after_first)
    assert [row["sequence"] for row in rows_after_second] == [
        row["sequence"] for row in rows_after_first
    ]
