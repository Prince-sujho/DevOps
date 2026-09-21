"""The pending-action state machine: advance a valid action, re-present the required one.

Oracle is the adapter README. Line 114: "the identity gate owns `resolve_phone`;
`OnboardingCoordinator` owns `select_persona`, `student_flow`, and
`teacher_flow`. Unexpected conversational messages are buffered on the pending
action and re-present the current interactive, valid actions advance it, and
completion clears it after replaying the buffered conversation as one agent
turn. Every bubble sent while an action is pending is kept on the action
(`said`)". Plus the Test Matrix rows for unknown-phone, hidden-number, contact
share, stray-message-during-onboarding, and onboarding completion, and the
design note that "abandoned setup does not depend on stale buttons or timers;
the next inbound message re-presents the exact pending interactive".
"""

from __future__ import annotations

from typing import get_args

import pytest

from infra.attribution import AdAttribution
from infra.canned import CANNED_RESPONSES
from infra.conversation import PendingActionName, TextMessage
from whatsapp_adapter.app.src.constants import ONBOARDING_FLOW_TOKEN
from whatsapp_adapter.app.src.flows.constants import (
    PERSONA_STUDENT_BUTTON_ID,
    PERSONA_TEACHER_BUTTON_ID,
)
from whatsapp_adapter.app.src.flows.copy import (
    onboarding_fork_body,
    onboarding_fork_buttons,
    persona_resume_body,
    phone_request_body,
)
from whatsapp_adapter.app.src.input import PendingAction
from whatsapp_adapter.app.src.service.onboarding import OnboardingCoordinator

from .fakes import FakeFlows, FakeInputs, FakePending, FakeUsers, FakeWhatsApp, tag_of
from .factories import (
    MESSAGE_ID,
    PROFILE_NAME,
    SENDER_ID,
    SENDER_PHONE,
    STUDENT_ONBOARDING_RESPONSE,
    TEACHER_ONBOARDING_RESPONSE,
    inbound_contact,
    inbound_flow,
    inbound_tap,
    inbound_text,
    student,
)

pytestmark = pytest.mark.asyncio

ONBOARDING = CANNED_RESPONSES.onboarding
LAUNCH_BODY = "Let's set up your profile."


class Wiring:
    """An OnboardingCoordinator plus the fakes behind it."""

    def __init__(self, pending: PendingAction | None = None) -> None:
        self.users = FakeUsers(created=student())
        self.whatsapp = FakeWhatsApp()
        self.flows = FakeFlows(body=LAUNCH_BODY)
        self.inputs = FakeInputs()
        self.store = FakePending(pending=pending)
        self.coordinator = OnboardingCoordinator(
            self.users, self.whatsapp, self.flows, self.inputs, self.store
        )

    @property
    def bubble_count(self) -> int:
        """How many interactives the sender would actually see."""
        return (
            len(self.whatsapp.buttons)
            + len(self.whatsapp.contact_requests)
            + len(self.whatsapp.texts)
            + len(self.flows.launched)
        )


# --------------------------------------------------------------------------
# the phone ask, which the identity gate owns
# --------------------------------------------------------------------------


async def test_a_first_hidden_number_is_greeted_by_name_and_its_message_buffered():
    """README: hidden-number inbound -> message buffered in pending, prompt sent."""
    wiring = Wiring()
    inbound = inbound_text("solve this for me")

    await wiring.coordinator.request_phone(inbound)

    body = phone_request_body(PROFILE_NAME)
    assert wiring.whatsapp.contact_requests == [(SENDER_ID, body)]
    action = wiring.store.latest
    assert action.action == "resolve_phone"
    assert action.messages == [inbound]
    # Every bubble sent while the action is pending is kept on it.
    assert action.said == [TextMessage(type="text", text=body)]


async def test_the_phone_prompt_is_addressed_by_sender_id_because_the_phone_is_unknown():
    """The whole point of this prompt is that there is no number to send to."""
    wiring = Wiring()

    await wiring.coordinator.request_phone(inbound_text(sender_phone=None))

    to, _ = wiring.whatsapp.contact_requests[0]
    assert to == SENDER_ID
    assert to != SENDER_PHONE


async def test_re_presenting_the_phone_ask_does_not_greet_them_a_second_time():
    already = PendingAction(
        action="resolve_phone",
        messages=[inbound_text("first")],
        said=[TextMessage(type="text", text=phone_request_body(PROFILE_NAME))],
    )
    wiring = Wiring(pending=already)
    again = inbound_text("hello?")

    await wiring.coordinator.request_phone(again)

    _, body = wiring.whatsapp.contact_requests[0]
    assert body == ONBOARDING.phone_request
    assert PROFILE_NAME not in body
    action = wiring.store.latest
    # The earlier message is still buffered and the new one joins it.
    assert action.messages == [*already.messages, again]
    assert len(action.said) == 2


# --------------------------------------------------------------------------
# first contact: open persona selection
# --------------------------------------------------------------------------


async def test_a_sender_with_no_pending_action_gets_the_persona_fork():
    """README: unknown phone inbound -> the sender queue sends the persona fork."""
    wiring = Wiring()
    inbound = inbound_text("hi")

    assert await wiring.coordinator.handle(inbound, None) is None

    to, body, buttons = wiring.whatsapp.buttons[0]
    assert to == SENDER_PHONE
    assert body == onboarding_fork_body(PROFILE_NAME)
    assert buttons == onboarding_fork_buttons()
    action = wiring.store.latest
    assert action.action == "select_persona"
    assert action.messages == [inbound]


# --------------------------------------------------------------------------
# the phone arrived: advance to persona selection
# --------------------------------------------------------------------------


async def test_a_requested_contact_share_thanks_them_then_asks_for_the_persona():
    """README: contact share -> the persona fork or buffered conversation resumes."""
    wiring = Wiring()
    pending = PendingAction(action="resolve_phone", messages=[inbound_text("earlier")])

    await wiring.coordinator.handle(inbound_contact("contact_request"), pending)

    _, body, _ = wiring.whatsapp.buttons[0]
    assert body == persona_resume_body()
    assert wiring.store.latest.action == "select_persona"


async def test_a_forwarded_contact_card_does_not_get_the_thank_you_reserved_for_a_share():
    """README: only `origin: contact_request` is a share we asked for; a forwarded
    card (`origin: other`) is just conversation, so it gets the plain question.
    """
    wiring = Wiring()
    pending = PendingAction(action="resolve_phone")

    await wiring.coordinator.handle(inbound_contact("other"), pending)

    _, body, _ = wiring.whatsapp.buttons[0]
    assert body == ONBOARDING.persona_question
    assert body != persona_resume_body()


async def test_a_phone_that_arrived_without_a_contact_card_just_asks_for_the_persona():
    """No card means no share to thank them for, so only the question is sent."""
    wiring = Wiring()
    pending = PendingAction(action="resolve_phone")

    await wiring.coordinator.handle(inbound_text("hi again"), pending)

    _, body, _ = wiring.whatsapp.buttons[0]
    assert body == ONBOARDING.persona_question
    assert body != persona_resume_body()
    assert wiring.store.latest.action == "select_persona"


async def test_the_contact_card_itself_is_not_buffered_as_something_the_user_said():
    """A shared card is identity, not conversation; the replay must not carry it."""
    earlier = [inbound_text("earlier")]
    wiring = Wiring()
    pending = PendingAction(action="resolve_phone", messages=earlier)

    await wiring.coordinator.handle(inbound_contact("contact_request"), pending)

    assert wiring.store.latest.messages == earlier


# --------------------------------------------------------------------------
# persona chosen: launch that persona's Flow
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply_id", "persona", "action"),
    [
        (PERSONA_STUDENT_BUTTON_ID, "student", "student_flow"),
        (PERSONA_TEACHER_BUTTON_ID, "teacher", "teacher_flow"),
    ],
)
async def test_tapping_a_persona_launches_that_personas_flow(reply_id, persona, action):
    """README: the persona fork, then the onboarding Flow."""
    wiring = Wiring()
    pending = PendingAction(action="select_persona")

    result = await wiring.coordinator.handle(inbound_tap(reply_id, "Student"), pending)

    assert result is None
    assert wiring.flows.launched == [(persona, SENDER_PHONE, PROFILE_NAME)]
    assert wiring.store.latest.action == action
    # The launch bubble joins the record, so the model later reads its own words.
    assert wiring.store.last_said.body == LAUNCH_BODY


async def test_the_flow_launch_bubble_is_kept_on_record_as_the_form_that_was_sent():
    wiring = Wiring()
    pending = PendingAction(action="select_persona")

    await wiring.coordinator.handle(
        inbound_tap(PERSONA_STUDENT_BUTTON_ID, "Student"), pending
    )

    form = wiring.store.last_said
    assert form.type == "form"
    assert form.form == "profile"
    assert form.body == LAUNCH_BODY
    assert form.requestText == ONBOARDING_FLOW_TOKEN


async def test_a_tap_that_is_not_a_persona_re_presents_the_persona_buttons():
    """An old button from elsewhere in the conversation must not advance setup."""
    wiring = Wiring()
    pending = PendingAction(action="select_persona")

    await wiring.coordinator.handle(inbound_tap("difficulty:easy", "Easy"), pending)

    _, body, buttons = wiring.whatsapp.buttons[0]
    assert body == ONBOARDING.persona_question
    assert buttons == onboarding_fork_buttons()
    assert wiring.store.latest.action == "select_persona"
    assert wiring.flows.launched == []


# --------------------------------------------------------------------------
# stray conversation: buffer it, re-present the exact pending interactive
# --------------------------------------------------------------------------


async def test_a_stray_message_awaiting_a_persona_re_asks_without_the_greeting():
    """README: stray message during onboarding -> buffered, current interactive re-presented."""
    wiring = Wiring()
    pending = PendingAction(action="select_persona", messages=[inbound_text("first")])
    stray = inbound_text("are you there?")

    await wiring.coordinator.handle(stray, pending)

    _, body, _ = wiring.whatsapp.buttons[0]
    assert body == ONBOARDING.persona_question
    # The named fork body is first contact only; this sender has already seen it.
    assert body != onboarding_fork_body(PROFILE_NAME)
    assert wiring.store.latest.messages == [*pending.messages, stray]


@pytest.mark.parametrize(
    ("action", "persona"), [("student_flow", "student"), ("teacher_flow", "teacher")]
)
async def test_a_stray_message_awaiting_a_flow_re_offers_that_same_flow(action, persona):
    wiring = Wiring()
    pending = PendingAction(action=action)
    stray = inbound_text("what do I do?")

    await wiring.coordinator.handle(stray, pending)

    assert wiring.flows.launched == [(persona, SENDER_PHONE, PROFILE_NAME)]
    assert wiring.store.latest.action == action
    assert wiring.store.latest.messages == [stray]


@pytest.mark.parametrize("action", get_args(PendingActionName))
async def test_no_pending_action_ever_answers_a_stray_message_with_silence(action):
    """Every action must re-present something; none may drop the sender.

    `_represent` matches on the action name with no fallback arm, so an action
    it does not recognise buffers the message into a copy that is then thrown
    away: nothing sent, nothing persisted, no error. Today the ordered arms in
    `handle` keep that unreachable, and nothing checks it -- the function
    returns None, so mypy cannot flag the missing arm, and mypy's gate does not
    cover this service anyway. Driving this off `PendingActionName` means a
    fifth action fails here instead of silently swallowing conversations.
    """
    wiring = Wiring()

    await wiring.coordinator.handle(inbound_text("hello?"), PendingAction(action=action))

    assert wiring.bubble_count == 1, f"a stray message during {action} got silence"
    # The buffered copy must be persisted, or the message is lost even though
    # the sender saw a reply.
    assert len(wiring.store.saved) == 1


async def test_re_offering_a_flow_sends_no_buttons_because_the_flow_is_the_interactive():
    wiring = Wiring()

    await wiring.coordinator.handle(inbound_text("?"), PendingAction(action="student_flow"))

    assert wiring.whatsapp.buttons == []
    assert wiring.whatsapp.contact_requests == []


# --------------------------------------------------------------------------
# completion: create the user, clear the action, replay the conversation
# --------------------------------------------------------------------------


def completed_pending(action: str = "student_flow") -> PendingAction:
    """A finished setup with two buffered texts and one bubble on record."""
    return PendingAction(
        action=action,
        messages=[inbound_text("thanks @arjun"), inbound_text("solve 2x=4")],
        said=[TextMessage(type="text", text=ONBOARDING.persona_question)],
        ad=AdAttribution(
            sourceId="ad-1",
            headline="Learn maths on WhatsApp",
            sourceUrl="https://fb.me/ad-1",
            ctwaClid="clid-1",
        ),
    )


async def test_completion_creates_the_user_from_what_the_flow_collected():
    wiring = Wiring()
    inbound = inbound_flow(STUDENT_ONBOARDING_RESPONSE)

    turn = await wiring.coordinator.handle(inbound, completed_pending())

    profile = wiring.users.created[0].profile
    assert profile.persona == "student"
    assert profile.phone == SENDER_PHONE
    assert profile.name == PROFILE_NAME
    assert profile.institution.id == "school-1"
    assert profile.scope.grade == 8
    assert turn is not None


async def test_the_persona_comes_from_the_flow_response_not_the_pending_action_name():
    """The Flow is the record of what the user chose; the action name only routed them."""
    wiring = Wiring()

    await wiring.coordinator.handle(
        inbound_flow(TEACHER_ONBOARDING_RESPONSE), completed_pending("teacher_flow")
    )

    profile = wiring.users.created[0].profile
    assert profile.persona == "teacher"
    assert profile.scope.grades == [9, 10]


async def test_completion_hands_over_the_buffered_texts_and_the_ad_for_attribution():
    """README: attribute from the first buffered text; the ad travels with the profile."""
    wiring = Wiring()
    pending = completed_pending()

    await wiring.coordinator.handle(inbound_flow(STUDENT_ONBOARDING_RESPONSE), pending)

    request = wiring.users.created[0]
    assert request.preOnboardingTexts == ["thanks @arjun", "solve 2x=4"]
    assert request.ad == pending.ad


async def test_completion_replays_the_buffered_conversation_as_one_turn():
    wiring = Wiring()
    pending = completed_pending()

    turn = await wiring.coordinator.handle(
        inbound_flow(STUDENT_ONBOARDING_RESPONSE), pending
    )

    assert tag_of(turn.message) == "<replay>"
    assert wiring.inputs.replayed == pending.messages
    assert turn.inbound_id == MESSAGE_ID
    # The onboarding bubbles become assistant rows once the session opens.
    assert turn.said == pending.said


async def test_completion_closes_the_pending_action():
    wiring = Wiring()

    await wiring.coordinator.handle(
        inbound_flow(STUDENT_ONBOARDING_RESPONSE), completed_pending()
    )

    assert wiring.store.cleared == [SENDER_ID]


async def test_a_failed_user_creation_leaves_the_action_pending_so_setup_can_be_retried():
    """Clearing before the user exists would strand the sender with no way back."""
    wiring = Wiring()
    wiring.users = FakeUsers(create_error=RuntimeError("user service down"))
    coordinator = OnboardingCoordinator(
        wiring.users, wiring.whatsapp, wiring.flows, wiring.inputs, wiring.store
    )

    with pytest.raises(RuntimeError):
        await coordinator.handle(
            inbound_flow(STUDENT_ONBOARDING_RESPONSE), completed_pending()
        )

    assert wiring.store.cleared == []
    assert wiring.inputs.calls == []


async def test_a_flow_completion_before_a_persona_is_chosen_does_not_create_a_user():
    """Only the persona Flows finish setup; anything else re-presents the fork."""
    wiring = Wiring()

    result = await wiring.coordinator.handle(
        inbound_flow(STUDENT_ONBOARDING_RESPONSE), PendingAction(action="select_persona")
    )

    assert result is None
    assert wiring.users.created == []
    assert wiring.store.latest.action == "select_persona"
