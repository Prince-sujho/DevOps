"""Journey 7 — duplicate webhook delivery is claimed once and processed once."""

from __future__ import annotations

import pytest

from infra.conversation import TextMessage

from . import payloads
from .conftest import derive_user_id, transcript_rows
from .scripting import create_user, student_profile_input, turn
from .servers import settle, wait_until

pytestmark = pytest.mark.asyncio

PHONE = "919400000007"


async def _deliver(adapter, payload: dict):
    """POST one webhook payload; assert Meta's synchronous ack, nothing more.

    Args:
        adapter: HTTP client for the running whatsapp_adapter.
        payload: the webhook body to deliver.
    Returns:
        None.
    Raises:
        None.
    """
    response = await adapter.post_webhook(payload)
    assert response.status_code == 200


def _assert_processed_exactly_once(openai, whatsapp) -> None:
    """One agent turn ran and exactly one reply was sent — never more,
    regardless of retries.

    Args:
        openai: the fake OpenAI Responses client.
        whatsapp: the fake Meta Graph API client.
    Returns:
        None.
    Raises:
        None.
    """
    assert len(openai.calls) == 1
    assert whatsapp.kinds() == ["text"]


def _assert_same_sequences(after, before) -> None:
    """Assert two transcripts share the same sequence numbers.

    Args:
        after: transcript rows after the duplicate delivery.
        before: transcript rows after the first delivery.
    Returns:
        None.
    Raises:
        AssertionError: the sequences differ.
    """
    assert [row["sequence"] for row in after] == [
        row["sequence"] for row in before
    ]


async def test_duplicate_delivery_is_processed_once(
    adapter, whatsapp, openai, db, users_api
):
    """The same Meta message id delivered twice runs exactly one agent turn.

    Args:
        adapter: HTTP client for the running whatsapp_adapter.
        whatsapp: the fake Meta Graph API client.
        openai: the fake OpenAI Responses client.
        db: the emulator-bound Firestore client.
        users_api: HTTP client for user_service's internal surface.
    Returns:
        None.
    Raises:
        None.
    """
    user_id = derive_user_id(PHONE)
    await create_user(
        users_api, student_profile_input(phone=PHONE, name="Anil")
    )
    openai.push(
        turn(
            response_id="resp-j7",
            messages=[TextMessage(type="text", text="Only once")],
        )
    )
    payload = payloads.text_webhook(
        message_id="wamid.j7.duplicate",
        sender_id="bsuid-j7",
        sender_phone=PHONE,
        body="are you there",
        profile_name="Anil",
    )

    await _deliver(adapter, payload)
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()
    rows_after_first = await transcript_rows(db, user_id)
    assert rows_after_first
    _assert_processed_exactly_once(openai, whatsapp)

    await _deliver(adapter, payload)
    await settle()

    # the duplicate is a no-op: no second turn, no extra rows, no extra delivery
    _assert_processed_exactly_once(openai, whatsapp)
    rows_after_second = await transcript_rows(db, user_id)
    _assert_same_sequences(rows_after_second, rows_after_first)
