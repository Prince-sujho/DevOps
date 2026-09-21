"""Journeys 1, 2, 5, 6, 8 — the onboarding pending-action state machine."""

from __future__ import annotations

import pytest

from . import constants as K
from . import payloads
from .conftest import derive_user_id, pending_action, transcript_rows
from .servers import settle, wait_until

pytestmark = pytest.mark.asyncio

FORK_BUTTONS = [
    {"id": K.PERSONA_STUDENT_BUTTON_ID, "title": K.PERSONA_STUDENT_BUTTON_TITLE},
    {"id": K.PERSONA_TEACHER_BUTTON_ID, "title": K.PERSONA_TEACHER_BUTTON_TITLE},
]
INSTITUTION_SEED = {"query": "", "results": [], "hasResults": False}


async def _claim_exists(db, message_id: str) -> bool:
    doc = await db.collection(K.MESSAGE_CLAIMS_COLLECTION).document(message_id).get()
    return doc.exists


async def _register_handle(users_api, handle: str) -> None:
    """Register one referrer handle through the real public registration
    route (POST /internal/influencers), not a direct Firestore write.

    Per tests/outcomes/UNCERTAINTY.md's harness-fake rule: seeding
    `referrers/{handle}` directly would bypass influencer registration for a
    journey that is specifically about attribution *after* a public
    register -- a registration bug (FINDINGS API #5-6: collision returns 200
    or crashes 500 instead of 409) would then be invisible to this journey.
    Going through the real route means those bugs, if triggered, can fail
    this test.
    """
    response = await users_api.post(
        "/internal/influencers", json={"handle": handle, "platform": "instagram"}
    )
    assert response.status_code == 200, (
        f"expected influencer registration to succeed for {handle!r}; "
        f"got {response.status_code}: {response.text}"
    )


# --------------------------------------------------------------------------
# Journey 1
# --------------------------------------------------------------------------


async def test_unknown_phone_sends_text_then_picks_student(adapter, whatsapp, openai, db):
    """Unknown phone: claim, persona fork, buffered text, then the student Flow."""
    sender_id = "bsuid-j1"
    phone = "919100000001"
    name = "Anika"

    first = payloads.text_webhook(
        message_id="wamid.j1.a",
        sender_id=sender_id,
        sender_phone=phone,
        body="hi",
        profile_name=name,
    )
    response = await adapter.post_webhook(first)
    assert response.status_code == 200

    await wait_until(lambda: len(whatsapp.calls) >= 1, message="persona fork not delivered")

    # (a) the Meta message id is claimed exactly once
    assert await _claim_exists(db, "wamid.j1.a") is True

    # (b) the persona fork is the only delivery, with both persona options
    assert len(whatsapp.calls) == 1
    fork = whatsapp.calls[0]
    assert fork.kind == "buttons"
    assert fork.to == phone
    # Bound to the real canned-copy constants (infra.canned.CANNED_RESPONSES),
    # not a second hand-copied literal.
    assert fork.data["body"] == (
        f"{K.INTRO_TEMPLATE.format(name=name)}\n{K.PERSONA_QUESTION}"
    )
    assert fork.data["buttons"] == FORK_BUTTONS

    # (c) the pending action is persona selection
    pending = await pending_action(db, sender_id)
    assert pending is not None
    assert pending["action"] == "select_persona"

    # (e) the original text is buffered verbatim
    assert len(pending["messages"]) == 1
    assert pending["messages"][0]["type"] == "text"
    assert pending["messages"][0]["content"]["body"] == "hi"

    # (d) no transcript exists anywhere yet
    assert await transcript_rows(db, derive_user_id(phone)) == []
    assert openai.calls == []

    # --- tap the student persona option ---
    tap = payloads.button_reply_webhook(
        message_id="wamid.j1.b",
        sender_id=sender_id,
        sender_phone=phone,
        reply_id=K.PERSONA_STUDENT_BUTTON_ID,
        title=K.PERSONA_STUDENT_BUTTON_TITLE,
        profile_name=name,
    )
    response = await adapter.post_webhook(tap)
    assert response.status_code == 200

    await wait_until(lambda: len(whatsapp.calls) >= 2, message="student Flow not launched")
    assert len(whatsapp.calls) == 2
    launch = whatsapp.calls[1]
    assert launch.kind == "flow"
    assert launch.to == phone
    assert launch.data["flow_id"] == K.STUDENT_ONBOARDING_FLOW_ID
    assert launch.data["flow_token"] == K.ONBOARDING_FLOW_TOKEN
    assert launch.data["cta"] == K.ONBOARDING_FLOW_CTA
    assert launch.data["screen"] == K.INSTITUTION_SCREEN
    assert launch.data["data"] == INSTITUTION_SEED
    assert launch.data["body"] == K.STUDENT_LAUNCH_TEMPLATE.format(name=name)

    pending = await pending_action(db, sender_id)
    assert pending is not None
    assert pending["action"] == "student_flow"
    assert len(pending["messages"]) == 1
    assert pending["messages"][0]["content"]["body"] == "hi"
    assert openai.calls == []


# --------------------------------------------------------------------------
# Journey 2
# --------------------------------------------------------------------------


async def test_onboarding_flow_completion_attributes_first_mention(
    adapter, whatsapp, openai, db, users_api
):
    """Flow completion creates one user, attributes the first mention, replays once."""
    from .scripting import turn

    sender_id = "bsuid-j2"
    phone = "919100000002"
    name = "Rahul"
    await _register_handle(users_api, "alpha-1111")
    await _register_handle(users_api, "beta-2222")

    buffered = [
        ("wamid.j2.t1", "hey is anyone there"),
        ("wamid.j2.t2", "thanks @alpha-1111 for pointing me here"),
        ("wamid.j2.t3", "also @beta-2222 said good things"),
    ]
    for index, (message_id, body) in enumerate(buffered, start=1):
        response = await adapter.post_webhook(
            payloads.text_webhook(
                message_id=message_id,
                sender_id=sender_id,
                sender_phone=phone,
                body=body,
                profile_name=name,
            )
        )
        assert response.status_code == 200
        await wait_until(lambda i=index: len(whatsapp.calls) >= i)

    response = await adapter.post_webhook(
        payloads.button_reply_webhook(
            message_id="wamid.j2.tap",
            sender_id=sender_id,
            sender_phone=phone,
            reply_id=K.PERSONA_STUDENT_BUTTON_ID,
            title=K.PERSONA_STUDENT_BUTTON_TITLE,
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 4)

    pending = await pending_action(db, sender_id)
    assert pending is not None
    assert pending["action"] == "student_flow"
    assert len(pending["messages"]) == 3

    openai.push(turn(response_id="resp-j2-1"))
    response = await adapter.post_webhook(
        payloads.flow_completion_webhook(
            message_id="wamid.j2.done",
            sender_id=sender_id,
            sender_phone=phone,
            response_json=payloads.student_onboarding_completion(),
            profile_name=name,
        )
    )
    assert response.status_code == 200

    user_id = derive_user_id(phone)
    await wait_until(
        lambda: len(openai.calls) >= 1, message="buffered conversation was never replayed"
    )
    await settle()

    # (a) exactly one user document was created
    user_ids = [doc.id async for doc in db.collection(K.USERS_COLLECTION).stream()]
    assert user_ids == [user_id]
    doc = await db.collection(K.USERS_COLLECTION).document(user_id).get()
    profile = doc.to_dict()
    assert profile["persona"] == "student"
    assert profile["name"] == name
    assert profile["scope"] == {"grade": 9, "subjects": ["mathematics", "science"]}
    assert profile["institution"] == {"id": "school-dps-001", "name": "Delhi Public School"}

    # (b) the FIRST registered mention wins, not the later one
    assert profile["attribution"] == {"kind": "referrer", "handle": "alpha-1111"}

    # (c) the whole buffered conversation is exactly one agent turn
    assert len(openai.calls) == 1

    # (d) the pending action is cleared on completion
    assert await pending_action(db, sender_id) is None


# --------------------------------------------------------------------------
# Journey 5
# --------------------------------------------------------------------------


async def test_hidden_number_requests_contact_then_resumes(adapter, whatsapp, openai, db):
    """A webhook with no 'from' buffers the message and asks for the phone."""
    sender_id = "bsuid-j5"
    name = "Priya"
    phone = "919100000005"

    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j5.a",
            sender_id=sender_id,
            sender_phone=None,
            body="help me with algebra",
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)

    assert len(whatsapp.calls) == 1
    prompt = whatsapp.calls[0]
    assert prompt.kind == "contact_request"
    assert prompt.to == sender_id
    assert prompt.data["body"] == (
        f"{K.INTRO_TEMPLATE.format(name=name)}\n{K.PHONE_REQUEST}"
    )

    pending = await pending_action(db, sender_id)
    assert pending is not None
    assert pending["action"] == "resolve_phone"
    assert len(pending["messages"]) == 1
    assert pending["messages"][0]["content"]["body"] == "help me with algebra"

    # --- the user shares their number ---
    response = await adapter.post_webhook(
        payloads.contacts_webhook(
            message_id="wamid.j5.b",
            sender_id=sender_id,
            sender_phone=None,
            origin="contact_request",
            shared_phone=phone,
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 2)

    assert len(whatsapp.calls) == 2
    fork = whatsapp.calls[1]
    assert fork.kind == "buttons"
    assert fork.to == phone
    assert fork.data["body"] == f"{K.PHONE_ACK} {K.PERSONA_QUESTION}"
    assert fork.data["buttons"] == FORK_BUTTONS

    pending = await pending_action(db, sender_id)
    assert pending is not None
    assert pending["action"] == "select_persona"
    assert len(pending["messages"]) == 1
    assert pending["messages"][0]["content"]["body"] == "help me with algebra"
    assert openai.calls == []


# --------------------------------------------------------------------------
# Journey 6
# --------------------------------------------------------------------------


async def test_forwarded_contact_represents_phone_request(adapter, whatsapp, openai, db):
    """A forwarded card re-presents the phone request; the intro is not repeated."""
    sender_id = "bsuid-j6"
    name = "Priya"

    await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j6.a",
            sender_id=sender_id,
            sender_phone=None,
            body="hello",
            profile_name=name,
        )
    )
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    first = whatsapp.calls[0]
    intro_body = f"{K.INTRO_TEMPLATE.format(name=name)}\n{K.PHONE_REQUEST}"
    assert first.data["body"] == intro_body

    response = await adapter.post_webhook(
        payloads.contacts_webhook(
            message_id="wamid.j6.b",
            sender_id=sender_id,
            sender_phone=None,
            origin="other",
            shared_phone="919100000099",
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 2)
    await settle()

    assert len(whatsapp.calls) == 2
    represented = whatsapp.calls[1]
    assert represented.kind == "contact_request"
    assert represented.to == sender_id
    assert represented.data["body"] == K.PHONE_REQUEST

    pending_after = await pending_action(db, sender_id)
    assert pending_after is not None
    assert pending_after["action"] == "resolve_phone"
    assert pending_after["said"][-1]["text"] == K.PHONE_REQUEST
    assert openai.calls == []


# --------------------------------------------------------------------------
# Journey 8
# --------------------------------------------------------------------------


async def test_stray_message_during_onboarding_buffers_and_represents(
    adapter, whatsapp, openai, db
):
    """A stray text while awaiting persona selection buffers and re-presents the fork."""
    sender_id = "bsuid-j8"
    phone = "919100000008"
    name = "Kabir"

    await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j8.a",
            sender_id=sender_id,
            sender_phone=phone,
            body="first message",
            profile_name=name,
        )
    )
    await wait_until(lambda: len(whatsapp.calls) >= 1)

    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j8.b",
            sender_id=sender_id,
            sender_phone=phone,
            body="second message",
            profile_name=name,
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 2)
    await settle()

    assert len(whatsapp.calls) == 2
    represented = whatsapp.calls[1]
    assert represented.kind == "buttons"
    assert represented.to == phone
    assert represented.data["buttons"] == FORK_BUTTONS
    assert represented.data["body"] == K.PERSONA_QUESTION

    pending = await pending_action(db, sender_id)
    assert pending is not None
    assert pending["action"] == "select_persona"
    assert [message["content"]["body"] for message in pending["messages"]] == [
        "first message",
        "second message",
    ]
    assert openai.calls == []
