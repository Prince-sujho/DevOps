"""Rendering WhatsApp inputs as turns the model can read.

Two oracles. First, the stamp invariant from the builder's own reasoning:
"Conversation history carries no timestamps the model can see, so each turn
opens with one context line; long gaps read as session breaks." Second, the
synthetic-event wire format, `[label] detail`, which is what the model actually
sees for anything the user did rather than typed. The expected strings below are
hand-written rather than built by calling `synthetic_event`, so a change to
either the labels or the format fails here instead of agreeing with itself.
"""

from __future__ import annotations

import pytest

from infra.llm.content import TextContent, UriMediaContent
from whatsapp_adapter.app.src.service.inputs import AgentInputBuilder
from whatsapp_adapter.app.src.types import GradeFlowPayload

from .fakes import FakeBucket, FakeFetcher, FakeUploads
from .factories import (
    MESSAGE_ID,
    flow_media_ref,
    inbound_flow,
    inbound_location,
    inbound_media,
    inbound_tap,
    inbound_text,
    student,
)

# Pure rendering, like the package's other boundary modules; the async tests
# carry their own mark since this module mixes both.
pytestmark = pytest.mark.boundary

STAMP_PREFIX = "[date-time] "
USER = student()


class Wiring:
    """An AgentInputBuilder plus the fakes behind it."""

    def __init__(
        self,
        *,
        fetched: list[object] | None = None,
        uploaded: list[object] | None = None,
    ) -> None:
        self.bucket = FakeBucket()
        self.fetcher = FakeFetcher(parts=fetched)
        self.uploads = FakeUploads(parts=uploaded)
        self.builder = AgentInputBuilder(self.bucket, self.fetcher, self.uploads)


def texts_after_stamp(message) -> list[str]:
    """Every rendered part after the leading context line."""
    return [part.text for part in message.parts[1:]]


def builder() -> AgentInputBuilder:
    """A builder for the cases that touch no media."""
    return Wiring().builder


# --------------------------------------------------------------------------
# the context line every turn opens with
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "render",
    [
        lambda b: b.text("hi"),
        lambda b: b.tapped(inbound_tap()),
        lambda b: b.location(inbound_location()),
        lambda b: b.contact(),
        lambda b: b.profile_updated(),
    ],
)
def test_every_turn_opens_with_a_date_time_context_line(render):
    """Without it the model cannot tell a follow-up from a message days later."""
    stamp = render(builder()).parts[0]

    assert stamp.text.startswith(STAMP_PREFIX)
    # The label alone would carry no information; the reading must be there.
    assert stamp.text != STAMP_PREFIX.strip()
    assert len(stamp.text) > len(STAMP_PREFIX)


def test_a_text_turn_is_the_context_line_and_the_text_and_nothing_else():
    message = builder().text("solve 2x = 4")

    assert len(message.parts) == 2
    assert message.parts[1] == TextContent(text="solve 2x = 4")


# --------------------------------------------------------------------------
# things the user did rather than typed
# --------------------------------------------------------------------------


def test_a_tap_shows_the_model_both_the_tapped_id_and_the_visible_title():
    """README: the adapter records the visible title and the tapped id."""
    tap = inbound_tap("difficulty:easy", "Easy")

    assert texts_after_stamp(builder().tapped(tap)) == [
        "[tapped] difficulty:easy \u2014 Easy"
    ]


def test_a_shared_location_shows_the_model_the_place_it_resolved_to():
    shared = inbound_location(address="MG Road, Bengaluru")

    assert texts_after_stamp(builder().location(shared)) == [
        "[shared location] MG Road, Bengaluru"
    ]


def test_a_location_with_no_address_shows_the_coordinates_instead():
    """The detail is whatever identifies the place; coordinates are the fallback."""
    shared = inbound_location(12.97, 77.59, address=None)

    assert texts_after_stamp(builder().location(shared)) == [
        "[shared location] 12.97, 77.59"
    ]


def test_a_shared_contact_card_is_an_event_with_nothing_to_quote():
    assert texts_after_stamp(builder().contact()) == ["[shared a contact]"]


def test_a_completed_profile_update_is_an_event_the_model_can_acknowledge():
    assert texts_after_stamp(builder().profile_updated()) == [
        "[user updated their profile]"
    ]


# --------------------------------------------------------------------------
# content messages
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_typed_message_is_rendered_verbatim_and_fetches_no_media():
    wiring = Wiring()

    message = await wiring.builder.content(inbound_text("what is a prime?"), USER, [])

    assert texts_after_stamp(message) == ["what is a prime?"]
    assert wiring.fetcher.fetched == []


@pytest.mark.asyncio
async def test_media_is_handed_to_the_fetcher_and_its_parts_become_the_turn():
    part = UriMediaContent(type="image", uri="https://media/x.jpg", filename="x.jpg")
    wiring = Wiring(fetched=[part])
    image = inbound_media("image")

    message = await wiring.builder.content(image, USER, [])

    assert wiring.fetcher.fetched == [image]
    assert message.parts[1:] == [part]


@pytest.mark.asyncio
async def test_fetched_media_lands_in_this_users_own_whatsapp_thread_folder():
    """Scope is what keeps one user's attachments out of another's folder."""
    wiring = Wiring()

    await wiring.builder.content(inbound_media("image"), USER, [])

    scope = wiring.fetcher.scopes[0]
    assert scope.user_id == USER.userId
    assert scope.thread_key == "whatsapp"


@pytest.mark.asyncio
async def test_the_callers_own_usage_list_is_threaded_through_so_it_sees_the_cost():
    """A copied list would silently lose voice-note transcription billing."""
    wiring = Wiring()
    usage: list[object] = []

    await wiring.builder.content(inbound_media("audio", mime_type="audio/ogg"), USER, usage)

    assert wiring.fetcher.usage_lists[0] is usage


# --------------------------------------------------------------------------
# replaying what was buffered during onboarding
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_buffer_still_gives_the_model_something_to_open_on():
    """Someone who onboarded without typing a word still gets a first turn."""
    wiring = Wiring()

    message = await wiring.builder.replay([], USER, [])

    assert texts_after_stamp(message) == ["[user just completed onboarding]"]


@pytest.mark.asyncio
async def test_the_whole_buffered_conversation_replays_as_one_turn_in_order():
    wiring = Wiring()
    buffered = [inbound_text("hi"), inbound_text("are you there?"), inbound_text("help")]

    message = await wiring.builder.replay(buffered, USER, [])

    assert texts_after_stamp(message) == ["hi", "are you there?", "help"]
    # One turn, so exactly one context line at the front.
    assert message.parts[0].text.startswith(STAMP_PREFIX)


@pytest.mark.asyncio
async def test_a_location_buffered_before_onboarding_replays_as_a_location_event():
    """The location sits mid-buffer so the replay must carry on past it."""
    wiring = Wiring()
    buffered = [
        inbound_text("here I am"),
        inbound_location(address="Sector 12"),
        inbound_text("is that near you?"),
    ]

    message = await wiring.builder.replay(buffered, USER, [])

    assert texts_after_stamp(message) == [
        "here I am",
        "[shared location] Sector 12",
        "is that near you?",
    ]


# --------------------------------------------------------------------------
# Flow completions that feed the agent
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_document_flow_shows_the_model_the_fields_the_user_filled_in():
    wiring = Wiring()
    completion = inbound_flow({"route": "documents", "topic": "Photosynthesis", "grade": "8"})

    message = await wiring.builder.from_flow_completion(completion, USER, "documents")

    assert texts_after_stamp(message) == ["topic: Photosynthesis\ngrade: 8"]


@pytest.mark.asyncio
async def test_the_route_is_plumbing_and_never_reaches_the_model():
    wiring = Wiring()
    completion = inbound_flow({"route": "documents", "topic": "Algebra"})

    message = await wiring.builder.from_flow_completion(completion, USER, "documents")

    assert "documents" not in texts_after_stamp(message)[0]
    assert "route" not in texts_after_stamp(message)[0]


@pytest.mark.asyncio
async def test_a_blank_flow_field_is_left_out_rather_than_shown_as_empty():
    wiring = Wiring()
    completion = inbound_flow({"route": "documents", "topic": "Algebra", "notes": "   "})

    message = await wiring.builder.from_flow_completion(completion, USER, "documents")

    assert texts_after_stamp(message) == ["topic: Algebra"]


@pytest.mark.asyncio
async def test_a_grade_flow_opens_with_a_manifest_then_the_uploaded_files():
    page = UriMediaContent(type="image", uri="https://media/a.jpg", filename="a.jpg")
    wiring = Wiring(uploaded=[page])
    completion = inbound_flow(
        {
            "route": "grade",
            "question_paper": [flow_media_ref("qp")],
            "rubric": [flow_media_ref("rb")],
            "answer_sheets": [flow_media_ref("a1"), flow_media_ref("a2")],
        }
    )

    message = await wiring.builder.from_flow_completion(completion, USER, "grade")

    assert message.parts[1].text == (
        "question_paper: 1 PDF attached\n"
        "rubric: 1 PDF attached\n"
        "answer_sheets: 2 images attached"
    )
    assert message.parts[2:] == [page]


@pytest.mark.asyncio
async def test_a_grade_submission_is_persisted_under_its_own_inbound_message_id():
    """The message id is what keeps two submissions from overwriting each other."""
    wiring = Wiring()
    completion = inbound_flow(
        {
            "route": "grade",
            "question_paper": [],
            "rubric": [],
            "answer_sheets": [flow_media_ref("a1")],
        }
    )

    await wiring.builder.from_flow_completion(completion, USER, "grade")

    payload, scope, message_id = wiring.uploads.submissions[0]
    assert message_id == MESSAGE_ID
    assert scope.user_id == USER.userId
    assert isinstance(payload, GradeFlowPayload)
    assert len(payload.answer_sheets) == 1
