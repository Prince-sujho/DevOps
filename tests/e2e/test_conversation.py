"""Journeys 3, 9, 10, 11 — the generated-reply path for onboarded users."""

from __future__ import annotations

import pytest

from infra.conversation import DocumentFormMessage, TextMessage
from infra.utils.time import now_ms

from . import constants as K
from . import payloads
from .conftest import derive_user_id, session_ids, transcript_rows, user_doc
from .scripting import (
    append_transcript,
    create_user,
    student_profile_input,
    teacher_profile_input,
    turn,
    user_row,
)
from .servers import settle, wait_until

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Journey 3
# --------------------------------------------------------------------------


async def test_known_phone_generates_and_delivers_in_model_order(
    adapter, whatsapp, openai, db, users_api
):
    """Reaction, then messages in model order.

    No tool call runs in this scripted turn, so `state.read_ids` is genuinely
    empty and no Sources footer should be delivered -- `citations_responder`
    (tests/e2e/scripting.py) only returns rows when asked about at least one
    real id. Per tests/outcomes/UNCERTAINTY.md, no journey in this suite
    drives a real tool-based graph read, so citations-footer rendering
    itself is not covered here; asserting a fabricated footer against an
    empty read-id query would prove wiring, not retrieval.
    """
    phone = "919200000003"
    sender_id = "bsuid-j3"
    user_id = derive_user_id(phone)
    await create_user(users_api, student_profile_input(phone=phone, name="Meera"))

    seeded = await append_transcript(
        users_api,
        user_id,
        [user_row("earlier turn", now_ms() - 1000, turn_id="seed-turn")],
        previous_response_id="resp-seed-1",
    )
    assert seeded["startedAtMs"] is not None
    assert seeded["openedSessionNumber"] == 1
    seed_session = str(seeded["startedAtMs"])

    openai.push(
        turn(
            response_id="resp-new-2",
            reaction="👍",
            messages=[
                TextMessage(type="text", text="first bubble"),
                TextMessage(type="text", text="second bubble"),
            ],
        )
    )

    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j3",
            sender_id=sender_id,
            sender_phone=phone,
            body="explain states of matter",
            profile_name="Meera",
        )
    )
    assert response.status_code == 200

    await wait_until(lambda: len(whatsapp.calls) >= 3, message="reply was not fully delivered")
    await settle()

    # (c) exact delivery order: reaction, then model messages -- no citations
    # footer, since this turn read no graph nodes.
    assert whatsapp.kinds() == ["reaction", "text", "text"]
    assert whatsapp.calls[0].data == {"message_id": "wamid.j3", "emoji": "👍"}
    assert whatsapp.calls[0].to == phone
    assert whatsapp.calls[1].data["body"] == "first bubble"
    assert whatsapp.calls[2].data["body"] == "second bubble"

    # (b) the model ran one turn over the seeded session
    assert len(openai.calls) == 1

    # (d) the reply landed in the seeded session
    assert await session_ids(db, user_id) == [seed_session]

    rows = await transcript_rows(db, user_id)
    turn_rows = [row for row in rows if row["turnId"] == "wamid.j3"]
    # (a) the user turn is recorded: one stamp part plus the typed text
    user_texts = [r["content"]["text"] for r in turn_rows if r["role"] == "user"]
    assert len(user_texts) == 2
    assert user_texts[1] == "explain states of matter"
    # (d) the reply rows match what was delivered, in order
    assistant_rows = [r for r in turn_rows if r["role"] == "assistant"]
    assert [r["content"]["type"] for r in assistant_rows] == [
        "reaction",
        "text",
        "text",
    ]
    assert assistant_rows[0]["content"]["emoji"] == "👍"
    assert assistant_rows[1]["content"]["text"] == "first bubble"
    assert assistant_rows[2]["content"]["text"] == "second bubble"
    # (e) every row of this cycle carries the inbound Meta message id
    assert len(turn_rows) == 5
    assert {row["turnId"] for row in turn_rows} == {"wamid.j3"}
    # the user row precedes the assistant rows in canonical sequence
    assert max(r["sequence"] for r in turn_rows if r["role"] == "user") < min(
        r["sequence"] for r in assistant_rows
    )


# --------------------------------------------------------------------------
# Journey 9
# --------------------------------------------------------------------------


async def test_form_message_resolves_persona_specific_flow_id(
    adapter, whatsapp, openai, db, users_api
):
    """The same document form launches distinct student and teacher Flow ids."""
    student_phone = "919200000009"
    teacher_phone = "919200000109"
    await create_user(users_api, student_profile_input(phone=student_phone, name="Ravi"))
    await create_user(users_api, teacher_profile_input(phone=teacher_phone, name="Sunita"))

    form = DocumentFormMessage(
        type="form",
        form="document",
        body="Let's set up your practice sheet.",
        requestText="practice on states of matter",
        detailsPrompt="Which chapter should it cover?",
        kind="practice",
        difficulty="medium",
    )

    openai.push(turn(response_id="resp-j9-student", messages=[form]))
    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j9.student",
            sender_id="bsuid-j9-student",
            sender_phone=student_phone,
            body="make me a practice sheet",
            profile_name="Ravi",
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()

    assert len(whatsapp.calls) == 1
    student_launch = whatsapp.calls[0]
    assert student_launch.kind == "flow"
    assert student_launch.to == student_phone
    assert student_launch.data["flow_id"] == K.STUDENT_DOC_FLOW_ID
    assert student_launch.data["flow_token"] == "practice on states of matter"
    assert student_launch.data["body"] == "Let's set up your practice sheet."
    assert student_launch.data["cta"] == K.DOCUMENT_FLOW_CTA
    assert student_launch.data["screen"] == K.DOCUMENT_FORM_SCREEN
    assert student_launch.data["data"] == {
        "requestText": "practice on states of matter",
        "detailsPrompt": "Which chapter should it cover?",
        "kind": "practice",
        "difficulty": "medium",
    }

    openai.push(turn(response_id="resp-j9-teacher", messages=[form]))
    response = await adapter.post_webhook(
        payloads.text_webhook(
            message_id="wamid.j9.teacher",
            sender_id="bsuid-j9-teacher",
            sender_phone=teacher_phone,
            body="make me a practice sheet",
            profile_name="Sunita",
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 2)
    await settle()

    assert len(whatsapp.calls) == 2
    teacher_launch = whatsapp.calls[1]
    assert teacher_launch.kind == "flow"
    assert teacher_launch.to == teacher_phone
    assert teacher_launch.data["flow_id"] == K.TEACHER_DOC_FLOW_ID

    # persona resolution, not a hardcoded id
    assert student_launch.data["flow_id"] != teacher_launch.data["flow_id"]
    assert (student_launch.data["flow_id"], teacher_launch.data["flow_id"]) == (
        "flow-student-doc",
        "flow-teacher-doc",
    )


# --------------------------------------------------------------------------
# Journey 10
# --------------------------------------------------------------------------


async def test_location_share_saves_profile_and_runs_one_turn(
    adapter, whatsapp, openai, db, users_api
):
    """A shared location lands on the profile and triggers exactly one agent turn."""
    phone = "919200000010"
    user_id = derive_user_id(phone)
    await create_user(users_api, student_profile_input(phone=phone, name="Devi"))
    openai.push(turn(response_id="resp-j10", messages=[TextMessage(type="text", text="Got it")]))

    response = await adapter.post_webhook(
        payloads.location_webhook(
            message_id="wamid.j10",
            sender_id="bsuid-j10",
            sender_phone=phone,
            latitude=12.9716,
            longitude=77.5946,
            address="MG Road, Bengaluru",
            profile_name="Devi",
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()

    profile = await user_doc(db, user_id)
    assert profile is not None
    assert profile["location"] == {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "address": "MG Road, Bengaluru",
    }

    assert len(openai.calls) == 1
    assert whatsapp.kinds() == ["text"]
    assert whatsapp.calls[0].data["body"] == "Got it"


# --------------------------------------------------------------------------
# Journey 11
# --------------------------------------------------------------------------


async def test_button_tap_runs_one_stateless_turn(adapter, whatsapp, openai, users_api):
    """A tap becomes one '[tapped] {id} — {title}' user turn."""
    phone = "919200000011"
    await create_user(users_api, student_profile_input(phone=phone, name="Ishan"))
    openai.push(
        turn(response_id="resp-j11", messages=[TextMessage(type="text", text="Option 42 it is")])
    )

    response = await adapter.post_webhook(
        payloads.button_reply_webhook(
            message_id="wamid.j11",
            sender_id="bsuid-j11",
            sender_phone=phone,
            reply_id="opt:42",
            title="Option 42",
            profile_name="Ishan",
        )
    )
    assert response.status_code == 200
    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()

    assert len(openai.calls) == 1
    history = openai.calls[0].input_message
    texts = [
        part.text
        for item in history
        if getattr(item, "parts", None)
        for part in item.parts
        if getattr(part, "text", None)
    ]
    assert "[tapped] opt:42 — Option 42" in texts
    assert whatsapp.kinds() == ["text"]
    assert whatsapp.calls[0].data["body"] == "Option 42 it is"
