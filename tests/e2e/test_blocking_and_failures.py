"""Journeys 4, 12, 13, 14 — blocked senders, ignored types, loud parse failures."""

from __future__ import annotations

import pytest

from . import constants as K
from . import payloads
from .conftest import (
    all_transcript_row_count,
    derive_user_id,
    pending_action,
    transcript_rows,
)
from .scripting import block_user, create_user, student_profile_input
from .servers import settle, wait_until

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Journey 4
# --------------------------------------------------------------------------


async def test_blocked_phone_gets_only_the_canned_error(
    adapter, whatsapp, openai, db, users_api
):
    """A blocked phone receives the canned error and nothing else runs."""
    phone = "919300000004"
    await block_user(users_api, derive_user_id(phone))

    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j4",
            sender_id="bsuid-j4",
            sender_phone=phone,
            body="let me in",
            profile_name="Blocked User",
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()

    assert len(whatsapp.calls) == 1
    assert whatsapp.calls[0].kind == "text"
    assert whatsapp.calls[0].to == phone
    assert whatsapp.calls[0].data["body"] == K.CANNED_BLOCKED

    # no transcript, no agent work
    assert await all_transcript_row_count(db) == 0
    assert openai.calls == []
    assert await pending_action(db, "bsuid-j4") is None


# --------------------------------------------------------------------------
# Journey 12
# --------------------------------------------------------------------------


async def test_reaction_message_is_dropped(adapter, whatsapp, openai, db, users_api):
    """A reaction webhook returns 200 and changes nothing anywhere.

    `"reaction"` is a real Meta type `_normalize_message` deliberately drops
    (returns `None`) -- it never becomes an `UnsupportedMessage` and is not
    what the README's "Unsupported message type" Test Matrix row is naming.
    See `test_unrecognized_message_type_is_ignored` below for that claim.
    """
    phone = "919300000012"
    await create_user(users_api, student_profile_input(phone=phone, name="Nita"))
    user_id = derive_user_id(phone)

    response = await adapter.post_webhook(
        payloads.reaction_webhook(
            message_id="wamid.j12",
            sender_id="bsuid-j12",
            sender_phone=phone,
            profile_name="Nita",
        )
    )
    assert response.status_code == 200
    await settle()

    assert whatsapp.calls == []
    assert openai.calls == []
    claims = [doc.id async for doc in db.collection(K.MESSAGE_CLAIMS_COLLECTION).stream()]
    assert claims == []
    onboarding = [doc.id async for doc in db.collection(K.ONBOARDING_COLLECTION).stream()]
    assert onboarding == []
    assert await transcript_rows(db, user_id) == []
    assert await all_transcript_row_count(db) == 0


async def test_unrecognized_message_type_is_ignored(adapter, whatsapp, openai, db, users_api):
    """README Test Matrix: "Unsupported message type -> Ignore and return 200."

    A genuinely unrecognized type (`"order"`) is what this row actually
    describes, not `"reaction"` (a different, already fully-dropped branch --
    see the test above). Per tests/outcomes/UNCERTAINTY.md Journey 12,
    `_normalize_message`'s wildcard arm converts an unrecognized type into an
    `UnsupportedMessage`, which the coordinator claims and runs through one
    full agent turn via `AgentInputBuilder.unsupported()` rather than
    ignoring. Expected to fail against current code: that failure is the
    correct oracle for the README's literal "ignore" claim.
    """
    phone = "919300000112"
    await create_user(users_api, student_profile_input(phone=phone, name="Rohan"))
    user_id = derive_user_id(phone)

    response = await adapter.post_webhook(
        payloads.unrecognized_type_webhook(
            message_id="wamid.j12b",
            sender_id="bsuid-j12b",
            sender_phone=phone,
            profile_name="Rohan",
        )
    )
    assert response.status_code == 200
    await settle()

    assert whatsapp.calls == [], "an ignored message must not produce any outbound reply"
    assert openai.calls == [], "an ignored message must not run an agent turn"
    claims = [doc.id async for doc in db.collection(K.MESSAGE_CLAIMS_COLLECTION).stream()]
    assert claims == [], "an ignored message must not be claimed"
    assert await transcript_rows(db, user_id) == []
    assert await all_transcript_row_count(db) == 0


# --------------------------------------------------------------------------
# Journey 13
# --------------------------------------------------------------------------


async def test_malformed_supported_payload_fails_loudly(adapter, whatsapp, openai, db):
    """README Test Matrix: "Malformed supported payload -> Fail loudly during
    parsing." A text message with no 'text' block must not succeed and must
    produce no side effects -- the README documents "fail loudly," not a
    specific exception type or status, so this asserts the qualitative claim
    (non-2xx, no outbound, no agent turn, no claim) rather than pinning
    today's `KeyError` -> 500 as the contract.
    """
    payload = payloads.malformed_text_webhook(
        message_id="wamid.j13",
        sender_id="bsuid-j13",
        sender_phone="919300000013",
        profile_name="Broken",
    )

    response = await adapter.post_webhook(payload)
    assert not (200 <= response.status_code < 300), "a malformed payload must not succeed"
    await settle()

    assert whatsapp.calls == []
    assert openai.calls == []
    claims = [doc.id async for doc in db.collection(K.MESSAGE_CLAIMS_COLLECTION).stream()]
    assert claims == []


# --------------------------------------------------------------------------
# Journey 14
# --------------------------------------------------------------------------


async def test_generation_failure_sends_canned_error_and_closes_the_turn(
    adapter, whatsapp, openai, db, users_api
):
    """A model failure delivers the canned error and still records the turn."""
    phone = "919300000014"
    user_id = derive_user_id(phone)
    await create_user(users_api, student_profile_input(phone=phone, name="Farah"))
    openai.push(RuntimeError("simulated OpenAI failure"))

    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j14",
            sender_id="bsuid-j14",
            sender_phone=phone,
            body="explain photosynthesis",
            profile_name="Farah",
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()

    assert len(whatsapp.calls) == 1
    assert whatsapp.calls[0].kind == "text"
    assert whatsapp.calls[0].to == phone
    assert whatsapp.calls[0].data["body"] == K.CANNED_ERROR

    rows = await transcript_rows(db, user_id)
    turn_rows = [row for row in rows if row["turnId"] == "wamid.j14"]
    # the user turn was appended before generation; the error reply closes the turn
    assert [row["role"] for row in turn_rows] == ["user", "user", "assistant"]
    assert turn_rows[1]["content"]["text"] == "explain photosynthesis"
    assert turn_rows[2]["content"] == {"type": "text", "text": K.CANNED_ERROR}
